from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.channel_runtime_store import channel_runtime_store
from core.context_budget import (
    ContextBudgetReport,
    default_dialog_message_limit,
    estimate_tokens,
    select_recent_by_budget,
)
from core.state_store import get_session_entries

logger = logging.getLogger(__name__)

SESSION_MEMORY_PREFIX = "【会话记忆种子】"
SESSION_CORE_PREFIX = "【核心记忆】"
SESSION_SUMMARY_PREFIX = "【会话压缩摘要】"
SESSION_WORKING_PREFIX = "【工作状态】"
SESSION_RETRIEVED_PREFIX = "【相关记忆】"


@dataclass
class ContextPacket:
    """Assembled per-turn context for the model."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    budget: ContextBudgetReport = field(default_factory=ContextBudgetReport)
    session_id: str = ""
    user_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "message_count": len(self.messages),
            "budget": self.budget.as_dict(),
        }


class ContextAssembler:
    """
    Build a layered context packet from session rows + ephemeral memory layers.

    Layer order (system first, then dialog):
      L1 core memory → L2 working → L3 summary → L5 retrieved → L4 recent dialog
    """

    async def assemble(
        self,
        *,
        user_id: str,
        session_id: str,
        platform: str = "",
        include_hidden_system: bool = True,
        dialog_limit: int | None = None,
        recent_token_budget: int = 128_000,
        compact_triggered: bool = False,
        core_memory_text: str = "",
        retrieved_memory_text: str = "",
        query_text: str = "",
    ) -> ContextPacket:
        safe_user_id = str(user_id or "").strip()
        safe_session_id = str(session_id or "").strip()
        rows = await get_session_entries(safe_user_id, safe_session_id)
        budget = ContextBudgetReport(compact_triggered=bool(compact_triggered))
        if query_text:
            budget.notes.append(f"query_chars={len(str(query_text))}")

        # L1: prefer fresh core snapshot; fall back to legacy session seed once.
        memory_text = str(core_memory_text or "").strip()
        if include_hidden_system and not memory_text:
            legacy_seed = self._latest_system_with_prefix(rows, SESSION_MEMORY_PREFIX)
            if legacy_seed:
                memory_text = legacy_seed
        if memory_text and not memory_text.startswith(SESSION_MEMORY_PREFIX):
            if memory_text.startswith(SESSION_CORE_PREFIX):
                memory_text = (
                    f"{SESSION_MEMORY_PREFIX}\n"
                    "以下为核心长期事实（每轮刷新）。"
                    "与当前用户表达冲突时以当前输入为准。\n\n"
                    f"{memory_text}"
                )
            else:
                memory_text = f"{SESSION_MEMORY_PREFIX}\n{memory_text}"

        summary_text = ""
        if include_hidden_system:
            summary_text = self._latest_system_with_prefix(rows, SESSION_SUMMARY_PREFIX)

        working_text = self.build_working_snapshot(
            platform=platform,
            platform_user_id=safe_user_id,
        )
        retrieved_text = str(retrieved_memory_text or "").strip()
        if retrieved_text and not retrieved_text.startswith(SESSION_RETRIEVED_PREFIX):
            retrieved_text = f"{SESSION_RETRIEVED_PREFIX}\n{retrieved_text}"

        dialog_rows = [
            row
            for row in rows
            if str(row.get("role") or "").strip().lower() in {"user", "model"}
            and str(row.get("content") or "").strip()
        ]
        budget.dialog_count = len(dialog_rows)

        limit = (
            max(1, int(dialog_limit))
            if dialog_limit is not None
            else default_dialog_message_limit()
        )
        capped = dialog_rows[-limit:]
        recent_rows = select_recent_by_budget(
            capped,
            token_budget=max(200, int(recent_token_budget)),
            max_messages=limit,
            min_messages=min(2, len(capped) or 1) if capped else 1,
        )

        system_layers: list[tuple[str, str]] = []
        if include_hidden_system and memory_text:
            system_layers.append(("memory_seed", memory_text))
        if working_text:
            system_layers.append(("working", working_text))
        if include_hidden_system and summary_text:
            system_layers.append(("summary", summary_text))
        if include_hidden_system and retrieved_text:
            system_layers.append(("retrieved", retrieved_text))

        messages: list[dict[str, Any]] = []
        for layer_name, text in system_layers:
            budget.set_layer(layer_name, text)
            messages.append(self._to_model_message("system", text))

        dialog_blob_parts: list[str] = []
        for row in recent_rows:
            role = str(row.get("role") or "user").strip().lower() or "user"
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            messages.append(self._to_model_message(role, content))
            dialog_blob_parts.append(content)
        budget.set_layer("recent_dialog", "\n".join(dialog_blob_parts))
        budget.finalize()

        if budget.total_tokens > 0:
            logger.info(
                "context_budget user=%s session=%s %s",
                safe_user_id,
                safe_session_id,
                budget.log_line(),
            )

        return ContextPacket(
            messages=messages,
            budget=budget,
            session_id=safe_session_id,
            user_id=safe_user_id,
        )

    @staticmethod
    def _to_model_message(role: str, content: str) -> dict[str, Any]:
        safe_role = str(role or "user").strip().lower() or "user"
        if safe_role not in {"user", "model", "system"}:
            safe_role = "user"
        return {
            "role": safe_role,
            "parts": [{"text": str(content or "")}],
        }

    @staticmethod
    def _latest_system_with_prefix(rows: list[dict[str, str]], prefix: str) -> str:
        latest = ""
        for row in rows:
            if str(row.get("role") or "").strip().lower() != "system":
                continue
            content = str(row.get("content") or "").strip()
            if content.startswith(prefix):
                latest = content
        return latest

    def build_working_snapshot(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> str:
        safe_platform = str(platform or "").strip().lower()
        safe_user_id = str(platform_user_id or "").strip()
        if not safe_user_id:
            return ""

        task: dict[str, Any] | None = None
        if safe_platform:
            try:
                task = channel_runtime_store.get_active_task(
                    platform=safe_platform,
                    platform_user_id=safe_user_id,
                )
            except Exception:
                logger.debug(
                    "Failed to read active task for working snapshot user=%s",
                    safe_user_id,
                    exc_info=True,
                )
                task = None

        if not task:
            return ""

        status = str(task.get("status") or "").strip().lower() or "running"
        if status in {"completed", "succeeded", "failed", "cancelled", "expired"}:
            return ""

        lines = [SESSION_WORKING_PREFIX]
        task_id = str(task.get("id") or task.get("session_task_id") or "").strip()
        goal = " ".join(str(task.get("goal") or "").split())
        goal_short = goal[:180] + ("..." if len(goal) > 180 else "")
        head = f"- task: {status}"
        if task_id:
            head += f" id={task_id}"
        if goal_short:
            head += f" | {goal_short}"
        lines.append(head)

        stage_title = str(task.get("stage_title") or "").strip()
        stage_index = int(task.get("stage_index") or 0)
        stage_total = int(task.get("stage_total") or 0)
        if stage_title or stage_total > 0:
            if stage_total > 0:
                lines.append(
                    f"- stage: {stage_index}/{stage_total}"
                    + (f" {stage_title}" if stage_title else "")
                )
            elif stage_title:
                lines.append(f"- stage: {stage_title}")

        if status == "waiting_user" or bool(task.get("needs_confirmation")):
            waiting_bits: list[str] = []
            reason = str(task.get("last_blocking_reason") or "").strip()
            preview = str(task.get("resume_instruction_preview") or "").strip()
            if reason:
                waiting_bits.append(reason[:200])
            if preview and preview not in waiting_bits:
                waiting_bits.append(preview[:200])
            if waiting_bits:
                lines.append("- waiting_user: " + " | ".join(waiting_bits))
            else:
                lines.append("- waiting_user: 等待用户确认或补充信息")

        last_error = str(task.get("last_blocking_reason") or "").strip()
        if last_error and status not in {"waiting_user"}:
            lines.append(f"- last_block: {last_error[:200]}")

        summary = str(
            task.get("last_user_visible_summary") or task.get("result_summary") or ""
        ).strip()
        if summary:
            lines.append(f"- last_summary: {summary[:220]}")

        kernel = str(task.get("kernel_provider") or "").strip()
        kernel_status = str(task.get("kernel_status") or "").strip()
        if kernel:
            lines.append(
                f"- kernel: {kernel}"
                + (f" ({kernel_status})" if kernel_status else "")
            )

        rendered = "\n".join(lines).strip()
        if estimate_tokens(rendered) > 400:
            rendered = rendered[:1200].rstrip() + "…"
        return rendered


context_assembler = ContextAssembler()
