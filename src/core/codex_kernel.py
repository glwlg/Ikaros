from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from core.app_paths import data_dir, project_root
from core.channel_runtime_store import channel_runtime_store
from core.config import (
    IKAROS_CODEX_APPROVAL_POLICY,
    IKAROS_CODEX_EFFORT,
    IKAROS_CODEX_MODEL,
    IKAROS_CODEX_SANDBOX,
    IKAROS_CODEX_TIMEOUT_SEC,
    ikaros_codex_command,
    ikaros_codex_writable_roots,
)
from core.heartbeat_store import heartbeat_store
from core.codex_kernel_sessions import codex_kernel_sessions
from core.prompt_composer import prompt_composer
from core.task_inbox import task_inbox
from core.task_manager import task_manager
from ikaros.dev.codex_app_server_client import (
    CodexAppServerClient,
    JsonRpcError,
    _append_app_server_log,
    _command_to_text,
    _tail,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any] | None]]


@dataclass
class ActiveCodexTurn:
    user_id: str
    task_id: str
    task_inbox_id: str
    thread_id: str
    turn_id: str
    client: CodexAppServerClient


_ACTIVE_TURNS: Dict[str, ActiveCodexTurn] = {}
_PERSISTENT_CLIENT: CodexAppServerClient | None = None
_PERSISTENT_CLIENT_KEY: tuple[Any, ...] | None = None
_PERSISTENT_CLIENT_LOCK = asyncio.Lock()
_PERSISTENT_TURN_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _deadline_iso() -> str:
    return (datetime.now().astimezone() + timedelta(seconds=180)).isoformat(
        timespec="seconds"
    )


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    return env


async def close_persistent_codex_kernel_client() -> None:
    global _PERSISTENT_CLIENT, _PERSISTENT_CLIENT_KEY
    async with _PERSISTENT_CLIENT_LOCK:
        client = _PERSISTENT_CLIENT
        _PERSISTENT_CLIENT = None
        _PERSISTENT_CLIENT_KEY = None
    if client is not None:
        with contextlib.suppress(Exception):
            await client.close()


def _register_active_turn(turn: ActiveCodexTurn) -> None:
    for key in {turn.user_id, turn.task_id, turn.task_inbox_id}:
        safe_key = str(key or "").strip()
        if safe_key:
            _ACTIVE_TURNS[safe_key] = turn


def _unregister_active_turn(turn: ActiveCodexTurn) -> None:
    for key, value in list(_ACTIVE_TURNS.items()):
        if value is turn:
            _ACTIVE_TURNS.pop(key, None)


def _safe_text(value: Any, limit: int = 0) -> str:
    rendered = str(value or "").strip()
    return rendered[:limit] if limit > 0 else rendered


def _safe_list(values: Any, *, limit: int = 0) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    output: list[str] = []
    for item in values:
        token = str(item or "").strip()
        if token and token not in output:
            output.append(token)
        if limit > 0 and len(output) >= limit:
            break
    return output


def _one_line(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").strip().split())
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _codex_skill_catalog(
    *,
    runtime_user_id: str,
    platform: str,
    candidate_skill_names: list[str] | None = None,
) -> str:
    """Build a Codex-native catalog of all enabled Ikaros skills."""
    try:
        from core.tool_access_store import tool_access_store
        from extension.skills.registry import skill_registry as skill_loader

        candidate_names = {
            str(item or "").strip()
            for item in list(candidate_skill_names or [])
            if str(item or "").strip()
        }
        skills = sorted(
            list(skill_loader.get_enabled_skill_index().values()),
            key=lambda item: str(item.get("name") or "").strip(),
        )
        lines: list[str] = []
        for info in skills:
            name = str(info.get("name") or "").strip()
            if not name:
                continue
            allowed_roles = {
                str(item or "").strip().lower()
                for item in list(info.get("allowed_roles") or [])
                if str(item or "").strip()
            }
            if allowed_roles and "ikaros" not in allowed_roles:
                continue

            tool_names = [f"ext_{name.replace('-', '_')}"]
            for exported in list(info.get("tool_exports") or []):
                exported_name = str((exported or {}).get("name") or "").strip()
                if exported_name:
                    tool_names.append(exported_name)
            if tool_names:
                if not any(
                    bool(
                        tool_access_store.is_tool_allowed(
                            runtime_user_id=runtime_user_id,
                            platform=platform,
                            tool_name=tool_name,
                            kind="tool",
                        )[0]
                    )
                    for tool_name in tool_names
                ):
                    continue

            marker = " (本轮路由提示可能相关)" if name in candidate_names else ""
            lines.append(f"- `{name}`{marker}")
            desc = _one_line(info.get("description"), limit=180)
            if desc:
                lines.append(f"  desc: {desc}")
            triggers = _safe_list(info.get("triggers"), limit=10)
            if triggers:
                lines.append(f"  triggers: {', '.join(triggers)}")
            skill_md_path = str(info.get("skill_md_path") or "").strip()
            if skill_md_path:
                lines.append(f"  SKILL.md: `{skill_md_path}`")
            skill_dir = str(info.get("skill_dir") or "").strip()
            entrypoint = str(info.get("entrypoint") or "").strip()
            if not entrypoint and skill_dir:
                default_entrypoint = Path(skill_dir) / "scripts" / "execute.py"
                if default_entrypoint.exists():
                    entrypoint = "scripts/execute.py"
            if skill_dir and entrypoint:
                lines.append(f"  entrypoint: `{Path(skill_dir) / entrypoint}`")
            exports: list[str] = []
            for exported in list(info.get("tool_exports") or [])[:4]:
                if not isinstance(exported, dict):
                    continue
                export_name = str(exported.get("name") or "").strip()
                hint = _one_line(
                    exported.get("prompt_hint") or exported.get("description"),
                    limit=180,
                )
                if export_name and hint:
                    exports.append(f"{export_name}: {hint}")
                elif export_name:
                    exports.append(export_name)
            if exports:
                lines.append(f"  exports: {'; '.join(exports)}")

        if not lines:
            return ""

        header = [
            "【Codex skill catalog】",
            "下面是当前已启用且可供 Ikaros 使用的本地 skills。Codex 首轮应看到全量目录；后续用户没有说出 skill 名时，也要根据问题含义主动匹配。",
            "匹配到 skill 后，先读取对应 `SKILL.md`，再按 entrypoint 或 SOP 调用脚本；不要调用原生 Ikaros 的 `load_skill`，也不要假设存在远程适配器。",
            "当用户询问个人状态、车辆/行程、提醒、订阅、账务、部署、仓库或其他本地系统数据，而会话记忆没有答案时，优先检查这个目录里的只读或管理型 skill。",
        ]
        if candidate_names:
            header.append(
                "本轮路由提示可能相关 skills: "
                + ", ".join(f"`{name}`" for name in sorted(candidate_names))
            )
        return "\n".join(header + [""] + lines).strip()
    except Exception:
        logger.debug("Failed to build Codex skill catalog.", exc_info=True)
        return ""


def _message_history_text(message_history: list[Any], *, limit: int = 8000) -> str:
    rows: list[str] = []
    for item in list(message_history or [])[-12:]:
        role = "unknown"
        parts: list[Any] = []
        if isinstance(item, dict):
            role = str(item.get("role") or "unknown").strip()
            parts = list(item.get("parts") or [])
        else:
            role = str(getattr(item, "role", "") or "unknown").strip()
            parts = list(getattr(item, "parts", []) or [])
        texts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = str(part.get("text") or "").strip()
                if text:
                    texts.append(text)
                elif part.get("inline_data"):
                    texts.append("[inline media omitted by codex kernel v1]")
            else:
                text = str(getattr(part, "text", "") or "").strip()
                if text:
                    texts.append(text)
        if texts:
            rows.append(f"{role}: " + "\n".join(texts))
    rendered = "\n\n".join(rows).strip()
    return rendered[-limit:] if len(rendered) > limit else rendered


def _thread_user_instruction(
    *,
    user_request: str,
    resume_user_message: str = "",
) -> str:
    reply = _safe_text(resume_user_message)
    if reply:
        return reply
    return _safe_text(user_request)


def _kernel_prompt(
    *,
    user_request: str,
    message_history: list[Any],
    request_mode: str,
    task_inbox_id: str,
    runtime_user_id: str,
    platform: str,
    resume_user_message: str = "",
    include_base_context: bool = True,
    candidate_skill_names: list[str] | None = None,
) -> str:
    repo_root = str(project_root().resolve())
    skill_root = str((project_root() / "extension" / "skills").resolve())
    roots = "\n".join([f"- {root}" for root in ikaros_codex_writable_roots()])
    history = _message_history_text(message_history)
    sections: list[str] = []
    if include_base_context:
        # Codex has its own shell/filesystem execution contract. Use chat mode here
        # to inherit AGENTS/SOUL/USER identity context without Ikaros tool-loop hints.
        sections.append(
            prompt_composer.compose_base(
                runtime_user_id=_safe_text(runtime_user_id, 128),
                platform=_safe_text(platform, 64),
                mode="chat",
                allowed_skill_names=[],
            )
        )
        skill_catalog = _codex_skill_catalog(
            runtime_user_id=_safe_text(runtime_user_id, 128),
            platform=_safe_text(platform, 64),
            candidate_skill_names=candidate_skill_names,
        )
        if skill_catalog:
            sections.append(skill_catalog)
    sections.extend(
        [
            "【Codex kernel execution context】",
            (
                (
                    "The Ikaros base prompt above governs identity, personality, memory, "
                    "and user relationship context. The Codex kernel notes below govern "
                    "local execution mechanics for this turn."
                )
                if include_base_context
                else (
                    "Continue the existing Codex thread for this Ikaros session. "
                    "Do not reload SOUL/AGENTS unless the user asks or context is missing."
                )
            ),
            "You are executing through the Codex kernel provider for Ikaros.",
            (
                "Current working directory is the Ikaros repository root. Treat local "
                "files and skills exactly as a human operator in this repo would."
            ),
            f"Repo root: {repo_root}",
            f"Skill root: {skill_root}",
            "Writable/readable roots configured for this kernel:\n" + roots,
            (
                "Ikaros skills are local directory capabilities, not remote tools. "
                "When a skill may help, use the Codex skill catalog path if present; "
                "otherwise search under `extension/skills/builtin` and "
                "`extension/skills/learned`. First read `SKILL.md`, then invoke the "
                "documented CLI/script entrypoint."
            ),
            (
                "Do not expect Ikaros to provide per-skill adapters or Codex tool schemas. "
                "Use shell, filesystem, repo scripts, and tests directly."
            ),
            (
                "Before modifying code, inspect the surrounding context. Do not reset, "
                "checkout, or overwrite user changes. Keep edits scoped, verify what you "
                "changed, and report any failed verification plainly."
            ),
            (
                "Final output must clearly state the result, a failure reason, or the "
                "specific question needed from the user."
            ),
            f"Ikaros task inbox id: {task_inbox_id or 'none'}",
            f"Request mode: {request_mode or 'chat'}",
        ]
    )
    if resume_user_message:
        sections.append(
            "User reply for the previous waiting state:\n" + resume_user_message
        )
    sections.append("Current user request:\n" + (user_request or ""))
    if history:
        sections.append("Recent Ikaros conversation context:\n" + history)
    return "\n\n".join([item for item in sections if str(item).strip()]).strip()


async def interrupt_codex_kernel_task(
    *,
    user_id: str = "",
    task_id: str = "",
    task_inbox_id: str = "",
) -> bool:
    for key in (task_inbox_id, task_id, user_id):
        turn = _ACTIVE_TURNS.get(str(key or "").strip())
        if turn is None:
            continue
        if not turn.thread_id or not turn.turn_id:
            return False
        try:
            await turn.client.interrupt_turn(
                thread_id=turn.thread_id,
                turn_id=turn.turn_id,
            )
            return True
        except Exception:
            logger.warning("Failed to interrupt Codex kernel turn.", exc_info=True)
            return False
    return False


class CodexKernelProvider:
    provider = "codex"

    def should_handle(self, runtime_ctx: Any) -> bool:
        if bool(getattr(runtime_ctx, "subagent_runtime_user", False)):
            return False
        if bool(getattr(runtime_ctx, "heartbeat_runtime_user", False)):
            return False
        return True

    async def run_for_orchestrator(
        self,
        *,
        ctx: Any,
        runtime_ctx: Any,
        message_history: list[Any],
        task_goal: str,
        request_mode: str,
        event_callback: EventCallback,
        candidate_skill_names: list[str] | None = None,
    ) -> str:
        task_inbox_id = _safe_text(getattr(runtime_ctx, "task_inbox_id", ""), 80)
        user_id = _safe_text(getattr(runtime_ctx, "user_id", ""), 128)
        platform = _safe_text(getattr(runtime_ctx, "platform_name", ""), 64)
        runtime_user_id = _safe_text(
            getattr(runtime_ctx, "runtime_user_id", "")
            or getattr(runtime_ctx, "user_id", ""),
            128,
        )
        session_id = self._resolve_ikaros_session_id(
            runtime_ctx=runtime_ctx,
            user_id=user_id,
            platform=platform,
        )
        existing_thread_id = self._existing_thread_for_session(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        if existing_thread_id:
            instruction = _thread_user_instruction(user_request=task_goal)
        else:
            instruction = _kernel_prompt(
                user_request=task_goal,
                message_history=message_history,
                request_mode=request_mode,
                task_inbox_id=task_inbox_id,
                runtime_user_id=runtime_user_id,
                platform=platform,
                include_base_context=True,
                candidate_skill_names=candidate_skill_names,
            )
        new_thread_instruction = _kernel_prompt(
            user_request=task_goal,
            message_history=message_history,
            request_mode=request_mode,
            task_inbox_id=task_inbox_id,
            runtime_user_id=runtime_user_id,
            platform=platform,
            include_base_context=True,
            candidate_skill_names=candidate_skill_names,
        )
        result = await self._run_turn(
            user_id=user_id,
            task_id=_safe_text(getattr(runtime_ctx, "task_id", ""), 80),
            task_inbox_id=task_inbox_id,
            instruction=instruction,
            platform=platform,
            existing_thread_id=existing_thread_id,
            new_thread_instruction=new_thread_instruction,
            event_callback=event_callback,
        )
        self._persist_session_thread(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
            result=result,
        )
        needs_user = self._needs_user(result)
        await self._persist_kernel_metadata(
            user_id=user_id,
            platform=platform,
            task_id=_safe_text(getattr(runtime_ctx, "task_id", ""), 80),
            task_inbox_id=task_inbox_id,
            result=result,
            kernel_status="waiting_user" if needs_user else "finished",
            session_id=session_id,
        )
        output_text = self._output_text(result)
        if needs_user:
            await self._set_active_waiting(
                user_id=user_id,
                platform=platform,
                task_id=_safe_text(getattr(runtime_ctx, "task_id", ""), 80),
                task_inbox_id=task_inbox_id,
                goal=task_goal,
                result_summary=output_text,
                thread_id=_safe_text(result.get("thread_id"), 160),
                turn_id=_safe_text(result.get("turn_id"), 160),
            )
        completion_status = "waiting_user" if needs_user else "done"
        if not bool(result.get("ok")):
            completion_status = "failed"
        directive = await event_callback(
            "final_response",
            {
                "source": "codex_kernel",
                "text": output_text,
                "full_text": output_text,
                "text_preview": output_text[:500],
                "completion_signal": {
                    "explicit": True,
                    "status": completion_status,
                },
                "kernel_provider": "codex",
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
            },
        )
        if isinstance(directive, dict) and directive.get("final_text"):
            return str(directive.get("final_text") or "")
        return output_text

    async def resume_waiting_task(
        self,
        *,
        user_id: str,
        platform: str,
        user_message: str,
        source: str = "text",
    ) -> Dict[str, Any]:
        safe_user_id = _safe_text(user_id, 128)
        active_task = channel_runtime_store.get_active_task(
            platform=platform,
            platform_user_id=safe_user_id,
        )
        if not active_task:
            active_task = await heartbeat_store.get_session_active_task(safe_user_id)
        if (
            not active_task
            or _safe_text(active_task.get("status"), 40) != "waiting_user"
        ):
            return {
                "handled": False,
                "ok": False,
                "message": "当前没有等待继续的任务。",
            }

        task_inbox_id = _safe_text(
            active_task.get("task_inbox_id") or active_task.get("session_task_id"),
            80,
        )
        session_task = await task_inbox.get(task_inbox_id) if task_inbox_id else None
        metadata = dict(session_task.metadata or {}) if session_task else {}
        payload = dict(session_task.payload or {}) if session_task else {}
        session_id = _safe_text(
            metadata.get("session_id") or payload.get("session_id"),
            160,
        )
        if (
            _safe_text(active_task.get("kernel_provider"), 40) != "codex"
            and _safe_text(metadata.get("kernel_provider"), 40) != "codex"
        ):
            return {"handled": False, "ok": False, "message": ""}

        thread_id = _safe_text(
            active_task.get("codex_thread_id") or metadata.get("codex_thread_id"),
            160,
        )
        if not thread_id:
            return {
                "handled": True,
                "ok": False,
                "message": "找不到 Codex thread，上下文无法继续。请重新发送请求。",
            }

        task_goal = (
            _safe_text(metadata.get("task_goal"), 6000)
            or _safe_text((session_task or {}).goal if session_task else "", 6000)
            or _safe_text(active_task.get("goal"), 6000)
        )
        reply = _safe_text(user_message, 4000)
        instruction = _thread_user_instruction(
            user_request=task_goal,
            resume_user_message=reply or "继续",
        )
        new_thread_instruction = _kernel_prompt(
            user_request=task_goal,
            message_history=[],
            request_mode="task",
            task_inbox_id=task_inbox_id,
            runtime_user_id=(
                _safe_text(payload.get("runtime_user_id"), 128) or safe_user_id
            ),
            platform=_safe_text(payload.get("platform"), 64) or platform,
            resume_user_message=reply or "继续",
            include_base_context=True,
        )
        await self._set_active_running(
            user_id=safe_user_id,
            platform=platform,
            task_inbox_id=task_inbox_id,
            result_summary=f"Codex kernel resumed by {source}.",
        )
        result = await self._run_turn(
            user_id=safe_user_id,
            task_id=_safe_text(active_task.get("id"), 80),
            task_inbox_id=task_inbox_id,
            instruction=instruction,
            existing_thread_id=thread_id,
            new_thread_instruction=new_thread_instruction,
            platform=platform,
            event_callback=None,
        )
        self._persist_session_thread(
            user_id=safe_user_id,
            platform=platform,
            session_id=session_id,
            result=result,
        )
        needs_user = self._needs_user(result)
        output_text = self._output_text(result)
        await self._persist_kernel_metadata(
            user_id=safe_user_id,
            platform=platform,
            task_id=_safe_text(active_task.get("id"), 80),
            task_inbox_id=task_inbox_id,
            result=result,
            kernel_status="waiting_user" if needs_user else "finished",
            session_id=session_id,
        )
        if needs_user:
            final_text = (
                f"{output_text}\n\n"
                "请确认下一步：点击按钮，或直接回复“继续”/“停止”（3分钟内有效）。"
            )
            await self._set_active_waiting(
                user_id=safe_user_id,
                platform=platform,
                task_id=_safe_text(active_task.get("id"), 80),
                task_inbox_id=task_inbox_id,
                goal=task_goal,
                result_summary=output_text,
                thread_id=_safe_text(result.get("thread_id"), 160),
                turn_id=_safe_text(result.get("turn_id"), 160),
            )
            return {"handled": True, "ok": True, "message": final_text}

        if bool(result.get("ok")):
            await task_inbox.complete(
                task_inbox_id,
                result={
                    "kernel_provider": "codex",
                    "summary": output_text[:500],
                    "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                    "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                },
                final_output=output_text,
            )
            await self._clear_active_done(
                user_id=safe_user_id,
                platform=platform,
                result_summary=output_text,
            )
            return {"handled": True, "ok": True, "message": output_text}

        await task_inbox.fail(
            task_inbox_id,
            error=output_text,
            result={
                "kernel_provider": "codex",
                "summary": output_text[:500],
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
            },
        )
        await self._clear_active_failed(
            user_id=safe_user_id,
            platform=platform,
            result_summary=output_text,
        )
        return {"handled": True, "ok": False, "message": output_text}

    def _resolve_ikaros_session_id(
        self,
        *,
        runtime_ctx: Any,
        user_id: str,
        platform: str,
    ) -> str:
        session_id = _safe_text(getattr(runtime_ctx, "session_id", ""), 160)
        if session_id:
            return session_id
        user_data = getattr(runtime_ctx, "user_data", None)
        if isinstance(user_data, dict):
            session_id = _safe_text(user_data.get("current_session_id"), 160)
            if session_id:
                return session_id
        with contextlib.suppress(Exception):
            session_id = channel_runtime_store.get_session_id(
                platform=platform,
                platform_user_id=user_id,
            )
            if session_id:
                return _safe_text(session_id, 160)
        return ""

    @staticmethod
    def _existing_thread_for_session(
        *,
        user_id: str,
        platform: str,
        session_id: str,
    ) -> str:
        if not session_id:
            return ""
        row = codex_kernel_sessions.get(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        return _safe_text(row.get("codex_thread_id"), 160)

    @staticmethod
    def _persist_session_thread(
        *,
        user_id: str,
        platform: str,
        session_id: str,
        result: Dict[str, Any],
    ) -> None:
        thread_id = _safe_text(result.get("thread_id"), 160)
        if not session_id or not thread_id:
            return
        codex_kernel_sessions.upsert(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
            codex_thread_id=thread_id,
            codex_turn_id=_safe_text(result.get("turn_id"), 160),
        )

    async def _run_turn(
        self,
        *,
        user_id: str,
        task_id: str,
        task_inbox_id: str,
        instruction: str,
        platform: str,
        existing_thread_id: str = "",
        new_thread_instruction: str = "",
        event_callback: EventCallback | None = None,
    ) -> Dict[str, Any]:
        command = ikaros_codex_command()
        cwd = str(project_root().resolve())
        log_path = str((data_dir() / "logs" / "codex_kernel_app_server.log").resolve())
        thread_id = ""
        turn_id = ""
        active: ActiveCodexTurn | None = None
        client: CodexAppServerClient | None = None
        last_agent_emit_at = 0.0
        last_agent_emit_len = 0

        async def _codex_event_callback(event: str, payload: Dict[str, Any]) -> None:
            nonlocal last_agent_emit_at, last_agent_emit_len
            if event_callback is None:
                return
            payload_turn_id = _safe_text(payload.get("turn_id") or payload.get("turnId"), 160)
            if payload_turn_id and turn_id and payload_turn_id != turn_id:
                return
            now = time.monotonic()
            if event in {"agent_message_delta", "agent_message_completed"}:
                text = _safe_text(payload.get("text"), 6000)
                if not text:
                    return
                if event == "agent_message_delta":
                    text_len = len(text)
                    if (
                        now - last_agent_emit_at < 0.8
                        and text_len - last_agent_emit_len < 80
                    ):
                        return
                    last_agent_emit_at = now
                    last_agent_emit_len = text_len
                else:
                    last_agent_emit_at = now
                    last_agent_emit_len = len(text)
                await event_callback(
                    "codex_agent_message",
                    {
                        "source": "codex_kernel",
                        "kernel_provider": "codex",
                        "turn": 1,
                        "task_id": task_id,
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id,
                        "text_preview": text[-500:],
                    },
                )
                return
            return

        try:
            async with _PERSISTENT_TURN_LOCK:
                client = await self._persistent_client(
                    command=command,
                    cwd=cwd,
                    log_path=log_path,
                )
                client.reset_turn_state()
                client.set_event_callback(_codex_event_callback)
                thread_id, loaded_existing = await client.open_thread(
                    existing_thread_id=existing_thread_id
                )
                turn_instruction = instruction
                if existing_thread_id and not loaded_existing and new_thread_instruction:
                    turn_instruction = new_thread_instruction
                turn_id = await client.start_turn(
                    thread_id=thread_id,
                    instruction=turn_instruction,
                )
                active = ActiveCodexTurn(
                    user_id=user_id,
                    task_id=task_id,
                    task_inbox_id=task_inbox_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    client=client,
                )
                _register_active_turn(active)
                await self._persist_kernel_metadata(
                    user_id=user_id,
                    platform=platform,
                    task_id=task_id,
                    task_inbox_id=task_inbox_id,
                    result={"thread_id": thread_id, "turn_id": turn_id},
                    kernel_status="running",
                )
                turn = await client.wait_for_turn_completed(turn_id=turn_id)
                result = client.build_result(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    turn=turn,
                    loaded_existing_thread=loaded_existing,
                )
            _append_app_server_log(
                log_path=log_path,
                command=command,
                cwd=cwd,
                thread_id=thread_id,
                turn_id=turn_id,
                status=str(result.get("stop_reason") or ""),
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
                timed_out=False,
            )
            return result
        except FileNotFoundError:
            return {
                "ok": False,
                "error_code": "command_not_found",
                "message": f"command not found: {command[0] if command else 'codex'}",
                "command": _command_to_text(command),
                "cwd": cwd,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "transport": "app-server",
            }
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                if client is not None and thread_id and turn_id:
                    await client.interrupt_turn(thread_id=thread_id, turn_id=turn_id)
            return {
                "ok": False,
                "error_code": "timeout",
                "message": "Codex kernel turn timed out.",
                "command": _command_to_text(command),
                "cwd": cwd,
                "stdout": client._assistant_stdout() if client is not None else "",
                "stderr": _tail(client.stderr_text) if client is not None else "",
                "summary": _tail(
                    (
                        client._assistant_stdout() or client.stderr_text
                    )
                    if client is not None
                    else ""
                ),
                "thread_id": thread_id,
                "turn_id": turn_id,
                "transport": "app-server",
            }
        except JsonRpcError as exc:
            return {
                "ok": False,
                "error_code": "command_failed",
                "message": exc.message,
                "command": _command_to_text(command),
                "cwd": cwd,
                "stdout": client._assistant_stdout() if client is not None else "",
                "stderr": _tail(client.stderr_text) if client is not None else "",
                "summary": _tail(exc.message),
                "thread_id": thread_id,
                "turn_id": turn_id,
                "transport": "app-server",
            }
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "exec_prepare_failed",
                "message": str(exc),
                "command": _command_to_text(command),
                "cwd": cwd,
                "stdout": client._assistant_stdout() if client is not None else "",
                "stderr": _tail(client.stderr_text) if client is not None else "",
                "summary": _tail(str(exc)),
                "thread_id": thread_id,
                "turn_id": turn_id,
                "transport": "app-server",
            }
        finally:
            if active is not None:
                _unregister_active_turn(active)
            if client is not None:
                client.set_event_callback(None)

    async def _persistent_client(
        self,
        *,
        command: list[str],
        cwd: str,
        log_path: str,
    ) -> CodexAppServerClient:
        global _PERSISTENT_CLIENT, _PERSISTENT_CLIENT_KEY
        key = (
            tuple(command),
            cwd,
            max(30, int(IKAROS_CODEX_TIMEOUT_SEC or 1800)),
            log_path,
            IKAROS_CODEX_MODEL,
            IKAROS_CODEX_EFFORT,
            IKAROS_CODEX_APPROVAL_POLICY,
            IKAROS_CODEX_SANDBOX,
        )
        async with _PERSISTENT_CLIENT_LOCK:
            if (
                _PERSISTENT_CLIENT is not None
                and _PERSISTENT_CLIENT_KEY == key
                and _PERSISTENT_CLIENT.is_running()
            ):
                return _PERSISTENT_CLIENT
            if _PERSISTENT_CLIENT is not None:
                with contextlib.suppress(Exception):
                    await _PERSISTENT_CLIENT.close()
            client = CodexAppServerClient(
                command=command,
                cwd=cwd,
                env=_subprocess_env(),
                timeout_sec=max(30, int(IKAROS_CODEX_TIMEOUT_SEC or 1800)),
                log_path=log_path,
                model=IKAROS_CODEX_MODEL,
                effort=IKAROS_CODEX_EFFORT,
                approval_policy=IKAROS_CODEX_APPROVAL_POLICY,
                sandbox=IKAROS_CODEX_SANDBOX,
                approval_decision="accept",
            )
            await client.start()
            await client.initialize()
            _PERSISTENT_CLIENT = client
            _PERSISTENT_CLIENT_KEY = key
            return client

    @staticmethod
    def _needs_user(result: Dict[str, Any]) -> bool:
        requests = result.get("user_input_requests")
        return isinstance(requests, list) and bool(requests)

    @staticmethod
    def _output_text(result: Dict[str, Any]) -> str:
        text = (
            _safe_text(result.get("stdout"))
            or _safe_text(result.get("summary"))
            or _safe_text(result.get("message"))
            or "Codex kernel finished without visible output."
        )
        return text

    async def _persist_kernel_metadata(
        self,
        *,
        user_id: str,
        platform: str,
        task_id: str,
        task_inbox_id: str,
        result: Dict[str, Any],
        kernel_status: str,
        session_id: str = "",
    ) -> None:
        metadata = {
            "kernel_provider": "codex",
            "kernel_status": kernel_status,
            "session_id": _safe_text(session_id, 160),
            "codex_thread_id": _safe_text(result.get("thread_id"), 160),
            "codex_turn_id": _safe_text(result.get("turn_id"), 160),
            "codex_stop_reason": _safe_text(result.get("stop_reason"), 80),
            "codex_transport": _safe_text(result.get("transport"), 80) or "app-server",
            "codex_diff_count": len(list(result.get("diffs") or [])),
            "codex_command_output_count": len(dict(result.get("command_output") or {})),
            "kernel_updated_at": _now_iso(),
        }
        if task_inbox_id:
            with contextlib.suppress(Exception):
                await task_inbox.update_status(
                    task_inbox_id,
                    "running",
                    event="codex_kernel_metadata",
                    detail=kernel_status,
                    metadata=metadata,
                    result={
                        "kernel_provider": "codex",
                        "session_id": _safe_text(session_id, 160),
                        "summary": _safe_text(
                            result.get("stdout")
                            or result.get("summary")
                            or result.get("message"),
                            500,
                        ),
                        "diff_count": metadata["codex_diff_count"],
                        "command_output_count": metadata["codex_command_output_count"],
                    },
                )
            command_output = dict(result.get("command_output") or {})
            for item_id, text in list(command_output.items())[-3:]:
                with contextlib.suppress(Exception):
                    await task_inbox.update_status(
                        task_inbox_id,
                        "running",
                        event="codex_kernel_command_output",
                        detail=f"{_safe_text(item_id, 40)}: {_safe_text(text, 160)}",
                    )
        active_fields = {
            "kernel_provider": "codex",
            "kernel_status": kernel_status,
            "codex_session_id": _safe_text(session_id, 160),
            "codex_thread_id": metadata["codex_thread_id"],
            "codex_turn_id": metadata["codex_turn_id"],
        }
        with contextlib.suppress(Exception):
            channel_runtime_store.update_active_task(
                platform=platform,
                platform_user_id=user_id,
                **active_fields,
            )
        with contextlib.suppress(Exception):
            await heartbeat_store.update_session_active_task(user_id, **active_fields)
        task_manager.heartbeat(user_id, f"codex_kernel:{kernel_status}:{task_id}")

    async def _set_active_running(
        self,
        *,
        user_id: str,
        platform: str,
        task_inbox_id: str,
        result_summary: str,
    ) -> None:
        fields = {
            "status": "running",
            "needs_confirmation": False,
            "confirmation_deadline": "",
            "result_summary": result_summary[:500],
            "kernel_provider": "codex",
            "kernel_status": "running",
        }
        channel_runtime_store.update_active_task(
            platform=platform,
            platform_user_id=user_id,
            **fields,
        )
        await heartbeat_store.update_session_active_task(user_id, **fields)
        if task_inbox_id:
            await task_inbox.update_status(
                task_inbox_id,
                "running",
                event="codex_kernel_resumed",
                detail=result_summary[:180],
            )

    async def _set_active_waiting(
        self,
        *,
        user_id: str,
        platform: str,
        task_id: str = "",
        task_inbox_id: str,
        goal: str = "",
        result_summary: str,
        thread_id: str,
        turn_id: str,
    ) -> None:
        fields = {
            "status": "waiting_user",
            "id": task_id or task_inbox_id or f"codex:{thread_id}",
            "goal": goal[:500],
            "source": "message",
            "needs_confirmation": True,
            "confirmation_deadline": _deadline_iso(),
            "result_summary": result_summary[:500],
            "kernel_provider": "codex",
            "kernel_status": "waiting_user",
            "codex_thread_id": thread_id,
            "codex_turn_id": turn_id,
        }
        updated = channel_runtime_store.update_active_task(
            platform=platform,
            platform_user_id=user_id,
            **fields,
        )
        if updated is None:
            channel_runtime_store.set_active_task(
                fields,
                platform=platform,
                platform_user_id=user_id,
            )
        heartbeat_updated = await heartbeat_store.update_session_active_task(
            user_id,
            **fields,
        )
        if heartbeat_updated is None:
            await heartbeat_store.set_session_active_task(user_id, fields)
        if task_inbox_id:
            await task_inbox.update_status(
                task_inbox_id,
                "running",
                event="codex_kernel_waiting_user",
                detail=result_summary[:180],
                metadata={
                    "kernel_provider": "codex",
                    "kernel_status": "waiting_user",
                    "codex_thread_id": thread_id,
                    "codex_turn_id": turn_id,
                },
                result={"summary": result_summary[:500]},
                output={"text": result_summary},
            )

    async def _clear_active_done(
        self,
        *,
        user_id: str,
        platform: str,
        result_summary: str,
    ) -> None:
        fields = {
            "status": "done",
            "needs_confirmation": False,
            "confirmation_deadline": "",
            "result_summary": result_summary[:500],
            "kernel_provider": "codex",
            "kernel_status": "done",
            "clear_active": True,
        }
        channel_runtime_store.update_active_task(
            platform=platform,
            platform_user_id=user_id,
            **fields,
        )
        await heartbeat_store.update_session_active_task(user_id, **fields)

    async def _clear_active_failed(
        self,
        *,
        user_id: str,
        platform: str,
        result_summary: str,
    ) -> None:
        fields = {
            "status": "failed",
            "needs_confirmation": False,
            "confirmation_deadline": "",
            "result_summary": result_summary[:500],
            "kernel_provider": "codex",
            "kernel_status": "failed",
            "clear_active": True,
        }
        channel_runtime_store.update_active_task(
            platform=platform,
            platform_user_id=user_id,
            **fields,
        )
        await heartbeat_store.update_session_active_task(user_id, **fields)


codex_kernel_provider = CodexKernelProvider()
