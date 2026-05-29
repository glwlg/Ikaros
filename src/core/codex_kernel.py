from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict

from core.app_paths import data_dir, project_root
from core.channel_runtime_store import channel_runtime_store
from core.config import (
    IKAROS_CODEX_APPROVAL_POLICY,
    IKAROS_CODEX_EFFORT,
    IKAROS_CODEX_MODEL,
    IKAROS_CODEX_REQUEST_TIMEOUT_SEC,
    IKAROS_CODEX_SANDBOX,
    IKAROS_CODEX_SKILL_ALLOWLIST,
    IKAROS_CODEX_SKILL_DENYLIST,
    IKAROS_CODEX_TIMEOUT_SEC,
    ikaros_codex_command,
    ikaros_codex_writable_roots,
)
from core.file_artifacts import (
    extract_file_rows_from_text,
    merge_file_rows,
    normalize_file_rows,
)
from core.heartbeat_store import heartbeat_store
from core.kernel_provider import KernelProvider, KernelSessionRef, KernelTurnInput
from core.codex_kernel_sessions import codex_kernel_sessions
from core.prompt_composer import prompt_composer
from core.runtime_v2 import TERMINAL_STATUSES, runtime_event_bus, runtime_v2
from core.task_inbox import task_inbox
from core.task_manager import task_manager
from ikaros.dev.codex_app_server_client import (
    CodexAppServerClient,
    JsonRpcError,
    _append_app_server_log,
    _command_to_text,
    _extract_generated_image_files,
    _extract_local_media_files,
    _tail,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any] | None]]
CODEX_KERNEL_INTERFACE: type[KernelProvider] = KernelProvider

DEFAULT_CODEX_SKILL_DENYLIST = {
    "coding_session",
    "deep_research",
    "deployment_manager",
    "docker_ops",
    "generate_image",
    "gh-cli",
    "git_ops",
    "opencli",
    "playwright-cli",
    "repo_workspace",
    "skill_manager",
    "video_to_text",
    "web_extractor",
    "web_search",
}


@dataclass
class ActiveCodexTurn:
    user_id: str
    task_id: str
    task_inbox_id: str
    thread_id: str
    turn_id: str
    client: CodexAppServerClient
    runtime_session_id: str = ""
    runtime_turn_id: str = ""


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
    for key in {
        turn.user_id,
        turn.task_id,
        turn.task_inbox_id,
        turn.runtime_turn_id,
    }:
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


def _one_line(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").strip().split())
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _client_stdout(client: Any) -> str:
    if client is None:
        return ""
    getter = getattr(client, "_assistant_stdout", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            return _safe_text(getter())
    return ""


def _split_skill_names(raw: str) -> set[str]:
    names: set[str] = set()
    for item in str(raw or "").replace(";", ",").split(","):
        name = str(item or "").strip()
        if name:
            names.add(name)
    return names


def _codex_skill_visible(name: str) -> bool:
    safe_name = str(name or "").strip()
    if not safe_name:
        return False
    allowlist = _split_skill_names(
        os.getenv("IKAROS_CODEX_SKILL_ALLOWLIST", IKAROS_CODEX_SKILL_ALLOWLIST)
    )
    denylist = set(DEFAULT_CODEX_SKILL_DENYLIST)
    denylist.update(
        _split_skill_names(
            os.getenv("IKAROS_CODEX_SKILL_DENYLIST", IKAROS_CODEX_SKILL_DENYLIST)
        )
    )
    if allowlist:
        return safe_name in allowlist
    return safe_name not in denylist


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
        explicit_allowlist = _split_skill_names(
            os.getenv("IKAROS_CODEX_SKILL_ALLOWLIST", IKAROS_CODEX_SKILL_ALLOWLIST)
        )
        skills = sorted(
            list(skill_loader.get_enabled_skill_index().values()),
            key=lambda item: str(item.get("name") or "").strip(),
        )
        lines: list[str] = []
        for info in skills:
            name = str(info.get("name") or "").strip()
            if not name:
                continue
            if not _codex_skill_visible(name):
                continue
            if not explicit_allowlist:
                if not candidate_names or name not in candidate_names:
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

            desc = _one_line(info.get("description"), limit=180)
            lines.append(f"- `{name}`: {desc}" if desc else f"- `{name}`")

        if not lines:
            return ""

        header = [
            "【Ikaros-only local skills】",
            "Only use these when they add Ikaros-specific user data, platform actions, or local system integrations. For generic search, webpage reading, coding, shell, git, browser, deployment, or research work, prefer native Codex capabilities. If using one, find it under `extension/skills/**`, read its `SKILL.md`, then run its documented script/CLI directly.",
        ]
        return "\n".join(header + [""] + lines).strip()
    except Exception:
        logger.debug("Failed to build Codex skill catalog.", exc_info=True)
        return ""


def _message_history_text(
    message_history: list[Any],
    *,
    limit: int = 8000,
    current_user_request: str = "",
) -> str:
    rows: list[str] = []
    recent_items = list(message_history or [])[-12:]
    current_request = str(current_user_request or "").strip()
    for idx, item in enumerate(recent_items):
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
                    texts.append("[inline media attached separately]")
            else:
                text = str(getattr(part, "text", "") or "").strip()
                if text:
                    texts.append(text)
        if texts:
            if (
                current_request
                and idx == len(recent_items) - 1
                and role == "user"
                and "\n".join(texts).strip() == current_request
            ):
                continue
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


def _runtime_status_for_codex_result(
    result: dict[str, Any],
    *,
    needs_user: bool = False,
) -> str:
    stop_reason = _safe_text(result.get("stop_reason"), 80).lower()
    error_code = _safe_text(result.get("error_code"), 80).lower()
    if stop_reason in {"interrupted", "interrupt", "cancelled", "canceled"}:
        return "cancelled"
    if error_code in {"interrupted", "cancelled", "canceled"}:
        return "cancelled"
    if needs_user:
        return "waiting_user"
    return "succeeded" if bool(result.get("ok")) else "failed"


def _runtime_v2_session_kind(*, platform: str, session_id: str) -> str:
    safe_platform = _safe_text(platform, 64).lower()
    safe_session_id = _safe_text(session_id, 160)
    if safe_platform == "scheduler" or safe_session_id.startswith("scheduler-task-"):
        return "scheduled_task"
    if safe_platform == "web":
        return "web_workspace"
    return "channel_chat"


def _default_runtime_session_id(*, platform: str, user_id: str) -> str:
    safe_platform = _safe_text(platform, 64).lower() or "channel"
    safe_user_id = _safe_text(user_id, 128) or "user"
    return f"{safe_platform}:{safe_user_id}:main"


def _inline_data_suffix(mime_type: str) -> str:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
    }
    return mapping.get(normalized, ".bin")


def _materialize_codex_inline_file(
    inline_data: dict[str, Any],
    *,
    thread_key: str = "",
) -> tuple[str, str]:
    mime_type = _safe_text(
        inline_data.get("mime_type") or inline_data.get("mimeType"), 80
    )
    encoded = _safe_text(inline_data.get("data"), 0)
    if not encoded:
        return "", mime_type
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return "", mime_type
    if not payload:
        return "", mime_type
    digest = hashlib.sha256(payload).hexdigest()[:24]
    safe_thread = _safe_text(thread_key, 80).replace("/", "_") or "session"
    suffix = _inline_data_suffix(mime_type)
    directory = data_dir() / "codex" / "input_files" / safe_thread
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path_obj = (directory / f"input_{digest}{suffix}").resolve()
        if not path_obj.exists() or path_obj.read_bytes() != payload:
            path_obj.write_bytes(payload)
        return str(path_obj), mime_type
    except Exception:
        logger.debug("Failed to materialize Codex inline input file.", exc_info=True)
        return "", mime_type


def _codex_turn_input_items(
    *,
    instruction: str,
    message_history: list[Any],
    thread_key: str = "",
) -> list[dict[str, str]]:
    """Build Codex app-server user input items for current-turn inline media."""
    current_parts: list[Any] = []
    for item in reversed(list(message_history or [])):
        role = (
            str(item.get("role") or "").strip().lower()
            if isinstance(item, dict)
            else str(getattr(item, "role", "") or "").strip().lower()
        )
        if role != "user":
            continue
        current_parts = (
            list(item.get("parts") or [])
            if isinstance(item, dict)
            else list(getattr(item, "parts", []) or [])
        )
        break
    if not current_parts:
        return []

    input_items: list[dict[str, str]] = []
    attachment_notes: list[str] = []
    for idx, part in enumerate(current_parts):
        inline_data = (
            part.get("inline_data")
            if isinstance(part, dict)
            else getattr(part, "inline_data", None)
        )
        if not isinstance(inline_data, dict):
            continue
        path_text, mime_type = _materialize_codex_inline_file(
            inline_data,
            thread_key=thread_key,
        )
        if not path_text:
            continue
        normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
        attachment_notes.append(
            f"- attachment {idx + 1}: {path_text}"
            + (f" ({normalized_mime})" if normalized_mime else "")
        )
        if normalized_mime.startswith("image/"):
            input_items.append({"type": "localImage", "path": path_text})

    if not attachment_notes:
        return []
    text = _safe_text(instruction)
    text += "\n\nAttached local files for this user turn:\n" + "\n".join(
        attachment_notes
    )
    return [{"type": "text", "text": text.strip()}] + input_items


def _codex_generated_image_rows(
    *,
    thread_id: str,
    since_ts: float,
    include_recent_global: bool = False,
) -> list[dict[str, str]]:
    safe_thread_id = _safe_text(thread_id, 160)
    if not safe_thread_id and not include_recent_global:
        return []
    candidates: list[Path] = []
    if safe_thread_id:
        candidates.append(
            (data_dir() / "codex" / "generated_images" / safe_thread_id).resolve()
        )
        with contextlib.suppress(Exception):
            candidates.append(
                (Path.home() / ".codex" / "generated_images" / safe_thread_id).resolve()
            )
    if include_recent_global:
        candidates.append((data_dir() / "codex" / "generated_images").resolve())
        with contextlib.suppress(Exception):
            candidates.append((Path.home() / ".codex" / "generated_images").resolve())

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for directory in candidates:
        if not directory.exists() or not directory.is_dir():
            continue
        for path_obj in sorted(
            directory.rglob("*"),
            key=lambda item: item.stat().st_mtime,
        ):
            if not path_obj.is_file():
                continue
            if path_obj.suffix.lower() not in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
                ".bmp",
            }:
                continue
            with contextlib.suppress(Exception):
                if path_obj.stat().st_mtime + 1.0 < since_ts:
                    continue
            resolved = str(path_obj.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            rows.append(
                {
                    "kind": "photo",
                    "path": resolved,
                    "filename": path_obj.name,
                    "caption": "",
                }
            )
    return normalize_file_rows(rows)


def _codex_session_files_for_thread(thread_id: str) -> list[Path]:
    safe_thread_id = _safe_text(thread_id, 160)
    if not safe_thread_id:
        return []
    root = Path.home() / ".codex" / "sessions"
    if not root.exists() or not root.is_dir():
        return []
    with contextlib.suppress(Exception):
        return sorted(
            root.rglob(f"*{safe_thread_id}.jsonl"),
            key=lambda item: item.stat().st_mtime,
        )
    return []


def _iso_timestamp_to_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    with contextlib.suppress(Exception):
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    return 0.0


def _codex_session_image_rows_from_record(
    record: dict[str, Any],
    *,
    thread_id: str,
    since_ts: float,
) -> list[dict[str, str]]:
    if _iso_timestamp_to_epoch(record.get("timestamp")) + 1.0 < since_ts:
        return []
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    record_type = str(record.get("type") or "").strip()
    payload_type = str(payload.get("type") or "").strip()
    if record_type not in {"event_msg", "response_item"}:
        return []
    if payload_type not in {"image_generation_end", "image_generation_call"}:
        return []
    rows = _extract_local_media_files(payload)
    rows.extend(_extract_generated_image_files(payload, thread_id=thread_id))
    return normalize_file_rows(rows)


def _codex_session_completion_from_record(
    record: dict[str, Any],
    *,
    since_ts: float,
) -> dict[str, Any] | None:
    if _iso_timestamp_to_epoch(record.get("timestamp")) + 1.0 < since_ts:
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    if str(record.get("type") or "").strip() != "event_msg":
        return None
    if str(payload.get("type") or "").strip() != "task_complete":
        return None
    return dict(payload)


def _codex_session_started_turn_from_record(
    record: dict[str, Any],
    *,
    since_ts: float,
) -> str:
    if _iso_timestamp_to_epoch(record.get("timestamp")) + 1.0 < since_ts:
        return ""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""
    if str(record.get("type") or "").strip() != "event_msg":
        return ""
    if str(payload.get("type") or "").strip() != "task_started":
        return ""
    return _safe_text(payload.get("turn_id") or payload.get("turnId"), 160)


async def _wait_for_codex_session_started_turn(
    *,
    thread_id: str,
    since_ts: float,
    timeout_sec: float = 5.0,
) -> str:
    deadline = time.monotonic() + max(0.1, float(timeout_sec or 0))
    while time.monotonic() < deadline:
        try:
            for session_file in reversed(_codex_session_files_for_thread(thread_id)):
                if not session_file.exists():
                    continue
                latest_turn_id = ""
                with session_file.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        with contextlib.suppress(Exception):
                            record = json.loads(line)
                            if isinstance(record, dict):
                                turn_id = _codex_session_started_turn_from_record(
                                    record,
                                    since_ts=since_ts,
                                )
                                if turn_id:
                                    latest_turn_id = turn_id
                if latest_turn_id:
                    return latest_turn_id
        except Exception:
            logger.debug("Failed to inspect Codex session task_started.", exc_info=True)
        await asyncio.sleep(0.25)
    return ""


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
    history = _message_history_text(
        message_history,
        current_user_request=user_request,
    )
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
            "【Ikaros runtime】",
            (
                f"cwd: {repo_root}. Ikaros skills live under {skill_root}. "
                "You are the Codex kernel for this Ikaros session; "
                "use native Codex tools by default. Use listed Ikaros-only skills only "
                "when they provide user/account/platform/local-system data or actions "
                "that Codex cannot infer directly."
            ),
        ]
    )
    if task_inbox_id:
        sections.append(f"Ikaros task id: {task_inbox_id}")
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
        if turn.runtime_session_id:
            runtime_event_bus.publish(
                session_id=turn.runtime_session_id,
                turn_id=turn.runtime_turn_id,
                event_type="kernel_interrupt_requested",
                payload={
                    "kernel_provider": "codex",
                    "codex_thread_id": turn.thread_id,
                    "codex_turn_id": turn.turn_id,
                    "matched_key": str(key or "").strip(),
                },
            )
            if turn.runtime_turn_id:
                current = runtime_v2.get_turn(turn.runtime_turn_id)
                if current:
                    with contextlib.suppress(Exception):
                        runtime_v2.update_turn_status(
                            turn.runtime_turn_id,
                            _safe_text(current.get("status"), 40) or "running",
                            external_turn_id=turn.turn_id,
                            metadata={
                                "cancel_requested_at": _now_iso(),
                                "cancel_requested_by": str(key or "").strip(),
                            },
                        )
        try:
            await turn.client.interrupt_turn(
                thread_id=turn.thread_id,
                turn_id=turn.turn_id,
            )
            if turn.runtime_session_id:
                runtime_event_bus.publish(
                    session_id=turn.runtime_session_id,
                    turn_id=turn.runtime_turn_id,
                    event_type="kernel_interrupted",
                    payload={
                        "kernel_provider": "codex",
                        "codex_thread_id": turn.thread_id,
                        "codex_turn_id": turn.turn_id,
                    },
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

    async def ensure_session(self, session: dict[str, Any]) -> KernelSessionRef:
        session_obj = dict(session or {})
        session_id = _safe_text(session_obj.get("id") or session_obj.get("session_id"), 180)
        if not session_id:
            raise ValueError("session id is required")
        platform = _safe_text(session_obj.get("platform"), 64)
        user_id = _safe_text(session_obj.get("platform_user_id"), 128)
        runtime_v2.ensure_session(
            session_id=session_id,
            kind=_runtime_v2_session_kind(platform=platform, session_id=session_id),
            platform=platform,
            platform_user_id=user_id,
            title=_safe_text(session_obj.get("title"), 240),
            metadata={"kernel_provider": "codex"},
        )
        thread_id = self._existing_thread_for_session(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        if thread_id:
            runtime_v2.upsert_kernel_session(
                session_id=session_id,
                provider="codex",
                external_thread_id=thread_id,
                status="active",
                metadata={"ensured_by": "kernel_provider"},
            )
        return KernelSessionRef(
            provider="codex",
            session_id=session_id,
            external_thread_id=thread_id,
            metadata={"platform": platform, "platform_user_id": user_id},
        )

    async def start_turn(
        self,
        session: dict[str, Any],
        turn: dict[str, Any],
        input: KernelTurnInput,
    ) -> AsyncIterator[dict[str, Any]]:
        session_ref = await self.ensure_session(session)
        session_id = session_ref.session_id
        platform = _safe_text(session_ref.metadata.get("platform"), 64)
        user_id = _safe_text(session_ref.metadata.get("platform_user_id"), 128)
        turn_obj = dict(turn or {})
        turn_id = _safe_text(turn_obj.get("id") or turn_obj.get("turn_id"), 180)
        if not turn_id:
            created_turn = runtime_v2.create_turn(
                session_id=session_id,
                source=_safe_text(turn_obj.get("source"), 80) or "user",
                input_text=input.text,
                kernel_provider="codex",
            )
            turn_id = _safe_text(created_turn.get("id"), 180)
        elif not runtime_v2.get_turn(turn_id):
            created_turn = runtime_v2.create_turn(
                session_id=session_id,
                source=_safe_text(turn_obj.get("source"), 80) or "user",
                input_text=input.text,
                kernel_provider="codex",
            )
            turn_id = _safe_text(created_turn.get("id"), 180)
        current_turn = runtime_v2.get_turn(turn_id)
        if current_turn and str(current_turn.get("status") or "") == "queued":
            runtime_v2.update_turn_status(turn_id, "running")

        metadata = dict(input.metadata or {})
        request_mode = _safe_text(metadata.get("request_mode"), 40) or "chat"
        task_id = _safe_text(metadata.get("task_id"), 80)
        task_inbox_id = _safe_text(metadata.get("task_inbox_id"), 80)
        message_history = list(metadata.get("message_history") or [])
        existing_thread_id = session_ref.external_thread_id
        if existing_thread_id:
            instruction = _thread_user_instruction(user_request=input.text)
        else:
            instruction = _kernel_prompt(
                user_request=input.text,
                message_history=message_history,
                request_mode=request_mode,
                task_inbox_id=task_inbox_id,
                runtime_user_id=user_id,
                platform=platform,
                include_base_context=True,
                candidate_skill_names=metadata.get("candidate_skill_names"),
            )
        new_thread_instruction = _kernel_prompt(
            user_request=input.text,
            message_history=message_history,
            request_mode=request_mode,
            task_inbox_id=task_inbox_id,
            runtime_user_id=user_id,
            platform=platform,
            include_base_context=True,
            candidate_skill_names=metadata.get("candidate_skill_names"),
        )
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def _event_callback(event: str, payload: Dict[str, Any]) -> None:
            await queue.put({"type": event, "payload": dict(payload or {})})

        async def _runner() -> None:
            try:
                result = await self._run_turn(
                    user_id=user_id,
                    task_id=task_id,
                    task_inbox_id=task_inbox_id,
                    instruction=instruction,
                    platform=platform,
                    existing_thread_id=existing_thread_id,
                    new_thread_instruction=new_thread_instruction,
                    message_history=message_history,
                    thread_key=f"{platform}:{user_id}:{session_id}",
                    event_callback=_event_callback,
                    runtime_session_id=session_id,
                    runtime_turn_id=turn_id,
                )
                self._persist_session_thread(
                    user_id=user_id,
                    platform=platform,
                    session_id=session_id,
                    result=result,
                )
                needs_user = self._needs_user(result)
                runtime_status = _runtime_status_for_codex_result(
                    result,
                    needs_user=needs_user,
                )
                runtime_v2.update_turn_status(
                    turn_id,
                    runtime_status,
                    error="" if bool(result.get("ok")) else self._output_text(result),
                    external_turn_id=_safe_text(result.get("turn_id"), 160),
                    metadata={
                        "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                        "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                        "stop_reason": _safe_text(result.get("stop_reason"), 80),
                    },
                )
                output_text = self._output_text(result)
                if output_text:
                    runtime_event_bus.publish(
                        session_id=session_id,
                        turn_id=turn_id,
                        event_type="assistant_message_final",
                        payload={
                            "text": output_text,
                            "ok": bool(result.get("ok")),
                            "kernel_provider": "codex",
                            "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                            "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                        },
                    )
                await queue.put({"type": "turn_completed", "payload": result})
            except Exception as exc:
                with contextlib.suppress(Exception):
                    runtime_v2.update_turn_status(turn_id, "failed", error=str(exc))
                await queue.put(
                    {
                        "type": "turn_failed",
                        "payload": {"error": str(exc), "kernel_provider": "codex"},
                    }
                )
            finally:
                await queue.put(None)

        runner_task = asyncio.create_task(_runner(), name="codex-kernel-provider-turn")
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        await runner_task

    async def interrupt(self, turn_id: str) -> None:
        await interrupt_codex_kernel_task(task_id=_safe_text(turn_id, 180))

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
        session_platform = self._resolve_session_store_platform(
            runtime_ctx=runtime_ctx,
            platform=platform,
        )
        session_user_id = self._resolve_session_store_user_id(
            runtime_ctx=runtime_ctx,
            user_id=user_id,
        )
        if not session_id:
            session_id = _default_runtime_session_id(
                platform=session_platform or platform,
                user_id=session_user_id or user_id,
            )
        runtime_session_kind = _runtime_v2_session_kind(
            platform=session_platform or platform,
            session_id=session_id,
        )
        runtime_v2.ensure_session(
            session_id=session_id,
            kind=runtime_session_kind,
            platform=session_platform or platform,
            platform_user_id=session_user_id or user_id,
            title=task_goal[:80],
            metadata={
                "request_mode": request_mode,
                "kernel_provider": "codex",
            },
        )
        user_data = getattr(ctx, "user_data", None)
        runtime_turn_id = ""
        if isinstance(user_data, dict):
            existing_runtime_session_id = _safe_text(
                user_data.get("runtime_v2_session_id"),
                180,
            )
            if existing_runtime_session_id == session_id:
                candidate_turn_id = _safe_text(user_data.get("runtime_v2_turn_id"), 180)
                if candidate_turn_id:
                    with contextlib.suppress(Exception):
                        candidate_turn = runtime_v2.get_turn(candidate_turn_id)
                        if (
                            candidate_turn
                            and str(candidate_turn.get("session_id") or "").strip()
                            == session_id
                            and str(candidate_turn.get("status") or "").strip()
                            not in TERMINAL_STATUSES
                        ):
                            runtime_turn_id = candidate_turn_id
        if not runtime_turn_id:
            runtime_turn = runtime_v2.create_turn(
                session_id=session_id,
                source=(
                    "scheduler" if runtime_session_kind == "scheduled_task" else "user"
                ),
                input_text=task_goal,
                kernel_provider="codex",
                metadata={
                    "task_id": _safe_text(getattr(runtime_ctx, "task_id", ""), 80),
                    "task_inbox_id": task_inbox_id,
                    "platform": platform,
                    "runtime_user_id": runtime_user_id,
                },
            )
            runtime_turn_id = _safe_text(runtime_turn.get("id"), 180)
        if isinstance(user_data, dict):
            user_data["runtime_v2_session_id"] = session_id
            user_data["runtime_v2_turn_id"] = runtime_turn_id
        existing_thread_id = self._existing_thread_for_session(
            user_id=session_user_id,
            platform=session_platform,
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
            message_history=message_history,
            thread_key=(
                f"{session_platform}:{session_user_id}:{session_id}"
                if session_id
                else user_id
            ),
            event_callback=event_callback,
            runtime_session_id=session_id,
            runtime_turn_id=runtime_turn_id,
        )
        self._persist_session_thread(
            user_id=session_user_id,
            platform=session_platform,
            session_id=session_id,
            result=result,
        )
        result_files = normalize_file_rows(result.get("files"))
        if result_files:
            await event_callback(
                "codex_result_files",
                {
                    "source": "codex_kernel",
                    "kernel_provider": "codex",
                    "turn": 1,
                    "task_id": _safe_text(getattr(runtime_ctx, "task_id", ""), 80),
                    "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                    "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                    "files": result_files,
                    "terminal_payload": {"files": result_files},
                },
            )
        needs_user = self._needs_user(result)
        runtime_v2.update_turn_status(
            runtime_turn_id,
            "running",
            external_turn_id=_safe_text(result.get("turn_id"), 160),
            metadata={
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
            },
        )
        runtime_status = _runtime_status_for_codex_result(
            result,
            needs_user=needs_user,
        )
        runtime_v2.update_turn_status(
            runtime_turn_id,
            runtime_status,
            error="" if bool(result.get("ok")) else self._output_text(result),
            external_turn_id=_safe_text(result.get("turn_id"), 160),
            metadata={
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                "stop_reason": _safe_text(result.get("stop_reason"), 80),
            },
        )
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
        if output_text:
            runtime_event_bus.publish(
                session_id=session_id,
                turn_id=runtime_turn_id,
                event_type="assistant_message_final",
                payload={
                    "text": output_text,
                    "ok": bool(result.get("ok")),
                    "kernel_provider": "codex",
                    "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                    "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                },
            )
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
                runtime_session_id=session_id,
                runtime_turn_id=runtime_turn_id,
                runtime_v2_task_id=_safe_text(
                    getattr(runtime_ctx, "runtime_v2_task_id", ""), 180
                ),
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
        if not session_id:
            session_id = _default_runtime_session_id(
                platform=platform,
                user_id=safe_user_id,
            )
        runtime_v2.ensure_session(
            session_id=session_id,
            kind=_runtime_v2_session_kind(platform=platform, session_id=session_id),
            platform=platform,
            platform_user_id=safe_user_id,
            title=task_goal[:80],
            metadata={"kernel_provider": "codex", "resume": True},
        )
        runtime_turn = runtime_v2.create_turn(
            session_id=session_id,
            source="user_resume",
            input_text=reply or "继续",
            kernel_provider="codex",
            metadata={
                "task_inbox_id": task_inbox_id,
                "previous_codex_thread_id": thread_id,
                "source": source,
            },
        )
        runtime_turn_id = _safe_text(runtime_turn.get("id"), 180)
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
            runtime_session_id=session_id,
            runtime_turn_id=runtime_turn_id,
        )
        self._persist_session_thread(
            user_id=safe_user_id,
            platform=platform,
            session_id=session_id,
            result=result,
        )
        needs_user = self._needs_user(result)
        output_text = self._output_text(result)
        runtime_v2.update_turn_status(
            runtime_turn_id,
            "running",
            external_turn_id=_safe_text(result.get("turn_id"), 160),
            metadata={
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
            },
        )
        runtime_v2.update_turn_status(
            runtime_turn_id,
            _runtime_status_for_codex_result(result, needs_user=needs_user),
            error="" if bool(result.get("ok")) else output_text,
            external_turn_id=_safe_text(result.get("turn_id"), 160),
            metadata={
                "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                "stop_reason": _safe_text(result.get("stop_reason"), 80),
            },
        )
        if output_text:
            runtime_event_bus.publish(
                session_id=session_id,
                turn_id=runtime_turn_id,
                event_type="assistant_message_final",
                payload={
                    "text": output_text,
                    "ok": bool(result.get("ok")),
                    "kernel_provider": "codex",
                    "codex_thread_id": _safe_text(result.get("thread_id"), 160),
                    "codex_turn_id": _safe_text(result.get("turn_id"), 160),
                },
            )
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
                runtime_session_id=session_id,
                runtime_turn_id=_safe_text(active_task.get("runtime_v2_turn_id"), 180),
                runtime_v2_task_id=_safe_text(
                    active_task.get("runtime_v2_task_id"), 180
                ),
            )
            return {
                "handled": True,
                "ok": True,
                "message": final_text,
                "files": normalize_file_rows(result.get("files")),
            }

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
            return {
                "handled": True,
                "ok": True,
                "message": output_text,
                "files": normalize_file_rows(result.get("files")),
            }

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
        return {
            "handled": True,
            "ok": False,
            "message": output_text,
            "files": normalize_file_rows(result.get("files")),
        }

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
    def _resolve_session_store_platform(*, runtime_ctx: Any, platform: str) -> str:
        user_data = getattr(runtime_ctx, "user_data", None)
        if isinstance(user_data, dict):
            override = _safe_text(user_data.get("codex_kernel_session_platform"), 64)
            if override:
                return override.lower()
        return _safe_text(platform, 64).lower()

    @staticmethod
    def _resolve_session_store_user_id(*, runtime_ctx: Any, user_id: str) -> str:
        user_data = getattr(runtime_ctx, "user_data", None)
        if isinstance(user_data, dict):
            override = _safe_text(user_data.get("codex_kernel_session_user_id"), 128)
            if override:
                return override
        return _safe_text(user_id, 128)

    @staticmethod
    def _existing_thread_for_session(
        *,
        user_id: str,
        platform: str,
        session_id: str,
    ) -> str:
        if not session_id:
            return ""
        runtime_row = runtime_v2.get_kernel_session(
            session_id=session_id,
            provider="codex",
        )
        runtime_thread_id = _safe_text(
            runtime_row.get("external_thread_id")
            or runtime_row.get("codex_thread_id"),
            160,
        )
        if runtime_thread_id:
            return runtime_thread_id
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
        runtime_v2.ensure_session(
            session_id=session_id,
            kind=_runtime_v2_session_kind(platform=platform, session_id=session_id),
            platform=platform,
            platform_user_id=user_id,
            metadata={"kernel_provider": "codex"},
        )
        runtime_v2.upsert_kernel_session(
            session_id=session_id,
            provider="codex",
            external_thread_id=thread_id,
            external_turn_id=_safe_text(result.get("turn_id"), 160),
            status="active" if bool(result.get("ok", True)) else "error",
            metadata={
                "legacy_platform": platform,
                "legacy_user_id": user_id,
            },
        )
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
        message_history: list[Any] | None = None,
        thread_key: str = "",
        event_callback: EventCallback | None = None,
        runtime_session_id: str = "",
        runtime_turn_id: str = "",
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
        last_activity_emit_at = 0.0
        last_activity_text = ""
        turn_started_ts = 0.0
        emitted_file_paths: set[str] = set()
        session_completion: asyncio.Future[dict[str, Any]] | None = None
        completed_from_session = False
        timeout_stage = "turn"

        def _publish_runtime_event(
            event_type: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            if not runtime_session_id:
                return
            runtime_event_bus.publish(
                session_id=runtime_session_id,
                turn_id=runtime_turn_id,
                event_type=event_type,
                payload=dict(payload or {}),
            )

        async def _emit_result_files(rows: list[dict[str, str]]) -> None:
            result_files = normalize_file_rows(rows)
            if not result_files:
                return
            new_rows = [
                row
                for row in result_files
                if str(row.get("path") or "").strip() not in emitted_file_paths
            ]
            if not new_rows:
                return
            artifact_rows = runtime_v2.record_artifacts(
                session_id=runtime_session_id,
                turn_id=runtime_turn_id,
                rows=new_rows,
                source="codex_kernel",
            )
            if artifact_rows:
                _publish_runtime_event(
                    "artifact_created",
                    {
                        "source": "codex_kernel",
                        "artifacts": artifact_rows,
                        "files": new_rows,
                    },
                )
            emitted_file_paths.update(
                str(row.get("path") or "").strip()
                for row in new_rows
                if str(row.get("path") or "").strip()
            )
            if event_callback is None:
                return
            await event_callback(
                "codex_result_files",
                {
                    "source": "codex_kernel",
                    "kernel_provider": "codex",
                    "turn": 1,
                    "task_id": task_id,
                    "codex_thread_id": thread_id,
                    "codex_turn_id": turn_id,
                    "files": new_rows,
                    "terminal_payload": {"files": new_rows},
                },
            )

        async def _monitor_codex_session_images(done: asyncio.Event) -> None:
            nonlocal session_completion
            session_file: Path | None = None
            offset = 0
            while not done.is_set():
                try:
                    if session_file is None:
                        candidates = _codex_session_files_for_thread(thread_id)
                        if candidates:
                            session_file = candidates[-1]
                            offset = 0
                    if session_file is not None and session_file.exists():
                        with session_file.open("r", encoding="utf-8") as handle:
                            handle.seek(offset)
                            lines = handle.readlines()
                            offset = handle.tell()
                        for line in lines:
                            with contextlib.suppress(Exception):
                                record = json.loads(line)
                                if isinstance(record, dict):
                                    await _emit_result_files(
                                        _codex_session_image_rows_from_record(
                                            record,
                                            thread_id=thread_id,
                                            since_ts=turn_started_ts,
                                        )
                                    )
                                    completion = _codex_session_completion_from_record(
                                        record,
                                        since_ts=turn_started_ts,
                                    )
                                    completion_turn_id = _safe_text(
                                        (completion or {}).get("turn_id")
                                        or (completion or {}).get("turnId"),
                                        160,
                                    )
                                    if (
                                        completion
                                        and session_completion is not None
                                        and not session_completion.done()
                                        and (
                                            not completion_turn_id
                                            or not turn_id
                                            or completion_turn_id == turn_id
                                        )
                                    ):
                                        session_completion.set_result(completion)
                except Exception:
                    logger.debug(
                        "Failed to monitor Codex session images.", exc_info=True
                    )
                await asyncio.sleep(1)

        async def _codex_event_callback(event: str, payload: Dict[str, Any]) -> None:
            nonlocal last_agent_emit_at, last_agent_emit_len
            nonlocal last_activity_emit_at, last_activity_text
            payload_turn_id = _safe_text(
                payload.get("turn_id") or payload.get("turnId"), 160
            )
            if payload_turn_id and turn_id and payload_turn_id != turn_id:
                return
            _publish_runtime_event(
                f"kernel.{event}",
                {
                    **dict(payload or {}),
                    "codex_thread_id": thread_id,
                    "codex_turn_id": turn_id or payload_turn_id,
                },
            )
            now = time.monotonic()
            if event in {"agent_message_delta", "agent_message_completed"}:
                text = _safe_text(payload.get("text"), 6000)
                if not text:
                    return
                runtime_event_bus.publish(
                    session_id=runtime_session_id,
                    turn_id=runtime_turn_id,
                    event_type=(
                        "text_delta"
                        if event == "agent_message_delta"
                        else "message_update"
                    ),
                    payload={
                        "text": text,
                        "delta": _safe_text(payload.get("delta"), 2000),
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id or payload_turn_id,
                    },
                )
                if event_callback is None:
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
            if event == "command_output_delta":
                await _emit_result_files(
                    extract_file_rows_from_text(
                        str(payload.get("text") or ""),
                        base_dir=project_root(),
                    )
                )
                return
            if event == "item_activity":
                text = _safe_text(payload.get("text"), 800)
                if not text:
                    return
                runtime_event_bus.publish(
                    session_id=runtime_session_id,
                    turn_id=runtime_turn_id,
                    event_type="kernel_activity",
                    payload={
                        "text": text,
                        "item_type": _safe_text(payload.get("item_type"), 80),
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id or payload_turn_id,
                    },
                )
                if event_callback is None:
                    return
                if now - last_activity_emit_at < 0.8 and text == last_activity_text:
                    return
                last_activity_emit_at = now
                last_activity_text = text
                await event_callback(
                    "codex_activity",
                    {
                        "source": "codex_kernel",
                        "kernel_provider": "codex",
                        "turn": 1,
                        "task_id": task_id,
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id,
                        "item_type": _safe_text(payload.get("item_type"), 80),
                        "text_preview": text,
                    },
                )
                return
            if event == "request_user_input":
                params = payload.get("params")
                params = dict(params) if isinstance(params, dict) else {}
                prompt = _safe_text(
                    params.get("prompt")
                    or params.get("message")
                    or params.get("label")
                    or "",
                    2000,
                )
                if runtime_turn_id:
                    with contextlib.suppress(Exception):
                        runtime_v2.update_turn_status(
                            runtime_turn_id,
                            "waiting_user",
                            external_turn_id=turn_id or payload_turn_id,
                            metadata={
                                "codex_thread_id": thread_id,
                                "codex_turn_id": turn_id or payload_turn_id,
                                "waiting_user_prompt": prompt,
                            },
                        )
                _publish_runtime_event(
                    "request_user_input",
                    {
                        "prompt": prompt,
                        "params": params,
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id or payload_turn_id,
                    },
                )
                return
            if event == "generated_files":
                await _emit_result_files(
                    normalize_file_rows(
                        payload.get("files")
                        or (
                            payload.get("terminal_payload", {}).get("files")
                            if isinstance(payload.get("terminal_payload"), dict)
                            else []
                        )
                    )
                )
                return
            return

        try:
            async with _PERSISTENT_TURN_LOCK:
                loaded_existing = False
                turn_instruction = instruction
                open_existing_thread_id = existing_thread_id
                resume_setup_timeouts = 0
                fresh_setup_timeouts = 0
                replaced_stale_thread_id = ""
                while True:
                    client = await self._persistent_client(
                        command=command,
                        cwd=cwd,
                        log_path=log_path,
                    )
                    client.reset_turn_state()
                    client.set_event_callback(_codex_event_callback)
                    try:
                        timeout_stage = (
                            "thread_resume" if open_existing_thread_id else "thread_start"
                        )
                        thread_id, loaded_existing = await client.open_thread(
                            existing_thread_id=open_existing_thread_id
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Codex app-server thread open timed out; recycling client "
                            "before retry. attempt=%s thread_id=%s",
                            resume_setup_timeouts + fresh_setup_timeouts + 1,
                            open_existing_thread_id or thread_id,
                        )
                        await close_persistent_codex_kernel_client()
                        if open_existing_thread_id:
                            resume_setup_timeouts += 1
                            replaced_stale_thread_id = open_existing_thread_id
                            logger.warning(
                                "Codex existing thread resume timed out; starting "
                                "a fresh thread for the same Ikaros session. thread_id=%s",
                                open_existing_thread_id,
                            )
                            open_existing_thread_id = ""
                            continue
                        fresh_setup_timeouts += 1
                        if fresh_setup_timeouts >= 2:
                            raise
                        continue
                    except JsonRpcError:
                        await close_persistent_codex_kernel_client()
                        raise

                    if open_existing_thread_id and loaded_existing:
                        turn_instruction = instruction
                    else:
                        turn_instruction = new_thread_instruction or instruction
                    if (
                        open_existing_thread_id
                        and not loaded_existing
                        and new_thread_instruction
                    ):
                        turn_instruction = new_thread_instruction
                    turn_started_ts = time.time()
                    turn_input_items = _codex_turn_input_items(
                        instruction=turn_instruction,
                        message_history=list(message_history or []),
                        thread_key=thread_key or thread_id or user_id,
                    )
                    try:
                        timeout_stage = "turn_start"
                        start_kwargs: dict[str, Any] = {
                            "thread_id": thread_id,
                            "instruction": turn_instruction,
                        }
                        if turn_input_items:
                            start_kwargs["input_items"] = turn_input_items
                        turn_id = await client.start_turn(**start_kwargs)
                        break
                    except asyncio.TimeoutError:
                        recovered_turn_id = await _wait_for_codex_session_started_turn(
                            thread_id=thread_id,
                            since_ts=turn_started_ts,
                        )
                        if recovered_turn_id:
                            turn_id = recovered_turn_id
                            logger.warning(
                                "Codex turn/start response timed out, but task_started "
                                "was observed; continuing without retry. thread_id=%s "
                                "turn_id=%s",
                                thread_id,
                                turn_id,
                            )
                            break
                        logger.warning(
                            "Codex app-server turn/start timed out before task_started; "
                            "recycling client before retry. attempt=%s thread_id=%s",
                            resume_setup_timeouts + fresh_setup_timeouts + 1,
                            open_existing_thread_id or thread_id,
                        )
                        await close_persistent_codex_kernel_client()
                        if open_existing_thread_id:
                            resume_setup_timeouts += 1
                            logger.warning(
                                "Codex existing thread did not start a new turn; retrying "
                                "same thread before failing. thread_id=%s",
                                open_existing_thread_id,
                            )
                            if resume_setup_timeouts >= 2:
                                raise
                            continue
                        fresh_setup_timeouts += 1
                        if fresh_setup_timeouts >= 2:
                            raise
                    except JsonRpcError:
                        await close_persistent_codex_kernel_client()
                        raise
                if runtime_turn_id:
                    runtime_v2.update_turn_status(
                        runtime_turn_id,
                        "running",
                        external_turn_id=turn_id,
                        metadata={
                            "codex_thread_id": thread_id,
                            "codex_turn_id": turn_id,
                            "loaded_existing_thread": loaded_existing,
                        },
                    )
                _publish_runtime_event(
                    "kernel_turn_started",
                    {
                        "kernel_provider": "codex",
                        "codex_thread_id": thread_id,
                        "codex_turn_id": turn_id,
                        "loaded_existing_thread": loaded_existing,
                    },
                )
                session_completion = asyncio.get_running_loop().create_future()
                session_monitor_done = asyncio.Event()
                session_monitor_task = asyncio.create_task(
                    _monitor_codex_session_images(session_monitor_done)
                )
                active = ActiveCodexTurn(
                    user_id=user_id,
                    task_id=task_id,
                    task_inbox_id=task_inbox_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    client=client,
                    runtime_session_id=runtime_session_id,
                    runtime_turn_id=runtime_turn_id,
                )
                _register_active_turn(active)
                timeout_stage = "turn"
                await self._persist_kernel_metadata(
                    user_id=user_id,
                    platform=platform,
                    task_id=task_id,
                    task_inbox_id=task_inbox_id,
                    result={"thread_id": thread_id, "turn_id": turn_id},
                    kernel_status="running",
                )
                wait_task = asyncio.create_task(
                    client.wait_for_turn_completed(turn_id=turn_id)
                )
                try:
                    completed_from_session = False
                    done_tasks, pending_tasks = await asyncio.wait(
                        {wait_task, session_completion},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if session_completion in done_tasks and session_completion.done():
                        completed_from_session = True
                        completion = session_completion.result()
                        turn = {
                            "id": _safe_text(
                                completion.get("turn_id")
                                or completion.get("turnId")
                                or turn_id,
                                160,
                            ),
                            "status": "completed",
                            "source": "codex_session_task_complete",
                            "last_agent_message": completion.get("last_agent_message"),
                        }
                        if not wait_task.done():
                            wait_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await wait_task
                    else:
                        turn = await wait_task
                    for pending_task in pending_tasks:
                        pending_task.cancel()
                finally:
                    session_monitor_done.set()
                    with contextlib.suppress(Exception):
                        await session_monitor_task
                result = client.build_result(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    turn=turn,
                    loaded_existing_thread=loaded_existing,
                )
                if replaced_stale_thread_id:
                    result["codex_thread_replaced_from"] = replaced_stale_thread_id
                result["files"] = merge_file_rows(
                    normalize_file_rows(result.get("files")),
                    _codex_generated_image_rows(
                        thread_id=thread_id,
                        since_ts=turn_started_ts,
                    ),
                )
                await _emit_result_files(result["files"])
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
            timeout_messages = {
                "thread_resume": "Codex kernel thread resume timed out.",
                "thread_start": "Codex kernel thread start timed out.",
                "turn_start": "Codex kernel turn start timed out.",
            }
            return {
                "ok": False,
                "error_code": "timeout",
                "message": timeout_messages.get(
                    timeout_stage,
                    "Codex kernel turn timed out.",
                ),
                "command": _command_to_text(command),
                "cwd": cwd,
                "stdout": _client_stdout(client),
                "stderr": _tail(client.stderr_text) if client is not None else "",
                "summary": _tail(
                    (_client_stdout(client) or client.stderr_text)
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
                "stdout": _client_stdout(client),
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
                "stdout": _client_stdout(client),
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
            max(5, int(IKAROS_CODEX_REQUEST_TIMEOUT_SEC or 300)),
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
                request_timeout_sec=max(
                    5,
                    int(IKAROS_CODEX_REQUEST_TIMEOUT_SEC or 300),
                ),
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
        if normalize_file_rows(result.get("files")) and not (
            _safe_text(result.get("stdout"))
            or _safe_text(result.get("message"))
            or _safe_text(result.get("summary"))
        ):
            return ""
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
            task_status = (
                "waiting_user" if kernel_status == "waiting_user" else "running"
            )
            with contextlib.suppress(Exception):
                await task_inbox.update_status(
                    task_inbox_id,
                    task_status,
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
                        task_status,
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
        runtime_session_id: str = "",
        runtime_turn_id: str = "",
        runtime_v2_task_id: str = "",
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
        if runtime_session_id:
            fields["runtime_v2_session_id"] = runtime_session_id
        if runtime_turn_id:
            fields["runtime_v2_turn_id"] = runtime_turn_id
        if runtime_v2_task_id:
            fields["runtime_v2_task_id"] = runtime_v2_task_id
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
                "waiting_user",
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
        if runtime_v2_task_id:
            with contextlib.suppress(Exception):
                task = runtime_v2.get_task(runtime_v2_task_id)
                if task and _safe_text(task.get("status"), 40) != "waiting_user":
                    runtime_v2.update_task_status(runtime_v2_task_id, "waiting_user")

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
