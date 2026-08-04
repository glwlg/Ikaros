from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import get_client_for_model
from core.context_budget import (
    default_compact_message_threshold,
    default_compact_token_threshold,
    default_keep_recent_max_messages,
    default_keep_recent_tokens,
    estimate_messages_tokens,
    select_recent_by_budget,
)
from core.llm_usage_store import llm_usage_session
from core.model_config import select_model_for_role
from core.state_store import get_session_entries, replace_session_entries
from services.openai_adapter import generate_text

logger = logging.getLogger(__name__)

SESSION_SUMMARY_PREFIX = "【会话压缩摘要】"
SESSION_MEMORY_PREFIX = "【会话记忆种子】"
VISIBLE_DIALOG_ROLES = {"user", "model"}


def _dialog_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        item
        for item in list(rows or [])
        if str(item.get("role") or "").strip().lower() in VISIBLE_DIALOG_ROLES
        and str(item.get("content") or "").strip()
    ]


def _system_rows_with_prefix(
    rows: list[dict[str, str]],
    prefix: str,
) -> list[dict[str, str]]:
    return [
        item
        for item in list(rows or [])
        if str(item.get("role") or "").strip().lower() == "system"
        and str(item.get("content") or "").startswith(prefix)
    ]


def _render_dialog_lines(rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for item in rows:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {content}")
    return "\n".join(lines).strip()


def _fallback_summary(
    *,
    previous_summary: str,
    older_rows: list[dict[str, str]],
) -> str:
    snippets: list[str] = []
    if previous_summary:
        snippets.append(previous_summary.strip())
    for item in older_rows[-12:]:
        content = " ".join(str(item.get("content") or "").split())
        if not content:
            continue
        label = "用户" if str(item.get("role") or "") == "user" else "助手"
        snippets.append(f"- {label}: {content[:180]}")
    if not snippets:
        return ""
    return "本会话较早内容摘要：\n" + "\n".join(snippets[:16])


class SessionCompactionService:
    async def compact_session(
        self,
        *,
        user_id: str,
        session_id: str,
        keep_recent: int | None = None,
        keep_recent_tokens: int | None = None,
        threshold: int | None = None,
        token_threshold: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        rows = await get_session_entries(user_id, session_id)
        if not rows:
            return {
                "ok": True,
                "compacted": False,
                "reason": "empty_session",
                "dialog_count": 0,
                "dialog_tokens": 0,
                "compressed_count": 0,
                "kept_recent": 0,
                "archived": False,
            }

        dialog_rows = _dialog_rows(rows)
        dialog_count = len(dialog_rows)
        dialog_tokens = estimate_messages_tokens(dialog_rows)

        message_threshold = (
            max(1, int(threshold))
            if threshold is not None
            else default_compact_message_threshold()
        )
        tok_threshold = (
            max(1, int(token_threshold))
            if token_threshold is not None
            else default_compact_token_threshold()
        )
        recent_token_budget = (
            max(1, int(keep_recent_tokens))
            if keep_recent_tokens is not None
            else default_keep_recent_tokens()
        )
        recent_max_messages = (
            max(1, int(keep_recent))
            if keep_recent is not None
            else default_keep_recent_max_messages()
        )

        over_message = dialog_count > message_threshold
        over_tokens = dialog_tokens > tok_threshold
        if not force and not over_message and not over_tokens:
            return {
                "ok": True,
                "compacted": False,
                "reason": "below_threshold",
                "dialog_count": dialog_count,
                "dialog_tokens": dialog_tokens,
                "message_threshold": message_threshold,
                "token_threshold": tok_threshold,
                "compressed_count": 0,
                "kept_recent": min(dialog_count, recent_max_messages),
                "archived": False,
            }

        preserved_recent = select_recent_by_budget(
            dialog_rows,
            token_budget=recent_token_budget,
            max_messages=recent_max_messages,
            min_messages=min(2, dialog_count) if dialog_count else 1,
        )
        # When force-compact on a small session, still leave a short tail.
        if force and not preserved_recent and dialog_rows:
            preserved_recent = dialog_rows[-min(2, len(dialog_rows)) :]

        # select_recent_by_budget always keeps a contiguous suffix.
        keep_n = len(preserved_recent)
        if keep_n <= 0:
            older_rows = list(dialog_rows)
            preserved_recent = []
        else:
            older_rows = dialog_rows[:-keep_n]
            preserved_recent = dialog_rows[-keep_n:]

        summary_rows = _system_rows_with_prefix(rows, SESSION_SUMMARY_PREFIX)
        previous_summary = ""
        if summary_rows:
            previous_summary = str(summary_rows[-1].get("content") or "").strip()

        if not older_rows and not previous_summary:
            return {
                "ok": True,
                "compacted": False,
                "reason": "nothing_to_compact",
                "dialog_count": dialog_count,
                "dialog_tokens": dialog_tokens,
                "compressed_count": 0,
                "kept_recent": len(preserved_recent),
                "archived": False,
            }

        archived_path = ""
        if older_rows:
            archived_path = self._archive_older_rows(
                user_id=user_id,
                session_id=session_id,
                older_rows=older_rows,
                previous_summary=previous_summary,
            )

        summary_text = await self._summarize_history(
            user_id=user_id,
            session_id=session_id,
            previous_summary=previous_summary,
            older_rows=older_rows,
        )
        if not summary_text:
            summary_text = _fallback_summary(
                previous_summary=previous_summary,
                older_rows=older_rows,
            )
        if summary_text and not summary_text.startswith(SESSION_SUMMARY_PREFIX):
            summary_text = f"{SESSION_SUMMARY_PREFIX}\n{summary_text.strip()}"

        memory_rows = _system_rows_with_prefix(rows, SESSION_MEMORY_PREFIX)
        rebuilt_rows: list[dict[str, str]] = []
        if memory_rows:
            rebuilt_rows.append(memory_rows[-1])
        if summary_text:
            rebuilt_rows.append({"role": "system", "content": summary_text.strip()})
        rebuilt_rows.extend(preserved_recent)

        ok = await replace_session_entries(user_id, session_id, rebuilt_rows)
        result = {
            "ok": bool(ok),
            "compacted": bool(ok),
            "reason": "compacted" if ok else "write_failed",
            "dialog_count": dialog_count,
            "dialog_tokens": dialog_tokens,
            "compressed_count": len(older_rows),
            "kept_recent": len(preserved_recent),
            "kept_recent_tokens": estimate_messages_tokens(preserved_recent),
            "archived": bool(archived_path),
            "archive_path": archived_path,
            "trigger": (
                "force"
                if force
                else (
                    "tokens"
                    if over_tokens and not over_message
                    else ("messages" if over_message and not over_tokens else "both")
                )
            ),
        }
        if ok:
            logger.info(
                "session_compacted user=%s session=%s compressed=%s kept=%s "
                "dialog_tokens=%s archive=%s trigger=%s",
                user_id,
                session_id,
                len(older_rows),
                len(preserved_recent),
                dialog_tokens,
                archived_path or "none",
                result["trigger"],
            )
        return result

    def _archive_older_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        older_rows: list[dict[str, str]],
        previous_summary: str = "",
    ) -> str:
        if not older_rows:
            return ""
        try:
            import json

            from core.state_store import _chat_root, _safe_session_id

            root = _chat_root(user_id)
            sid = _safe_session_id(session_id)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            archive_dir = (root / "archive" / sid).resolve()
            archive_dir.mkdir(parents=True, exist_ok=True)
            path = (archive_dir / f"{stamp}.jsonl").resolve()
            archived_at = datetime.now().astimezone().isoformat(timespec="seconds")

            def _line(payload: dict[str, Any]) -> str:
                return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

            chunks = [
                _line(
                    {
                        "type": "archive_meta",
                        "ts": archived_at,
                        "session_id": sid,
                        "compressed_count": len(older_rows),
                        "compressed_tokens": estimate_messages_tokens(older_rows),
                    }
                )
            ]
            if previous_summary:
                chunks.append(
                    _line(
                        {
                            "type": "previous_summary",
                            "ts": archived_at,
                            "content": previous_summary.strip(),
                        }
                    )
                )
            for item in older_rows:
                role = str(item.get("role") or "user").strip().lower() or "user"
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                chunks.append(
                    _line(
                        {
                            "type": "message",
                            "ts": archived_at,
                            "role": role,
                            "content": content,
                        }
                    )
                )
            path.write_text("".join(chunks), encoding="utf-8")
            return str(path)
        except Exception as exc:
            logger.warning(
                "Failed to archive compacted session rows user=%s session=%s: %s",
                user_id,
                session_id,
                exc,
            )
            return ""

    async def _summarize_history(
        self,
        *,
        user_id: str,
        session_id: str,
        previous_summary: str,
        older_rows: list[dict[str, str]],
    ) -> str:
        source_blocks: list[str] = []
        if previous_summary:
            source_blocks.append(previous_summary.strip())
        rendered_dialog = _render_dialog_lines(older_rows)
        if rendered_dialog:
            source_blocks.append(rendered_dialog)
        source_text = "\n\n".join(block for block in source_blocks if block).strip()
        if not source_text:
            return ""
        if len(source_text) > 18000:
            source_text = source_text[-18000:]

        prompt = (
            "请把下面这段更早的会话内容压缩成一段后续对话可复用的中文摘要。\n"
            "要求：\n"
            "1. 保留用户稳定偏好、身份信息、约束条件、重要事实。\n"
            "2. 保留未完成事项、待跟进项、最近决策与结论。\n"
            "3. 保留关键任务 id、产物路径或等待用户的点（如有）。\n"
            "4. 不要出现“以上/下面/本段”之类元话术，不要写分析过程。\n"
            "5. 输出简洁的要点列表，控制在 12 条以内。\n"
            "6. 如果存在旧摘要，要把旧摘要与新内容融合成一份更新后的滚动摘要。\n\n"
            f"会话内容：\n{source_text}"
        )

        try:
            model_name = select_model_for_role("primary")
            client = get_client_for_model(model_name, is_async=True)
            if client is None:
                raise RuntimeError("OpenAI async client is not initialized")
            with llm_usage_session(session_id or user_id):
                summary = await generate_text(
                    async_client=client,
                    model=model_name,
                    contents=prompt,
                    config={
                        "system_instruction": (
                            "你是会话压缩助手。"
                            "只输出可直接作为后续对话上下文的摘要，不要附加说明。"
                        ),
                    },
                )
            return str(summary or "").strip()
        except Exception as exc:
            logger.warning("Session compaction summarization failed: %s", exc)
            return ""


session_compaction_service = SessionCompactionService()
