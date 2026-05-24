from __future__ import annotations

from datetime import datetime
from typing import Any


def _safe_text(value: Any, limit: int = 0) -> str:
    rendered = str(value or "").strip()
    return rendered[:limit] if limit > 0 else rendered


def _parse_deadline(value: Any) -> datetime | None:
    raw = _safe_text(value, 80)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def is_confirmation_expired(
    active_task: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    if not isinstance(active_task, dict):
        return False
    deadline = _parse_deadline(active_task.get("confirmation_deadline"))
    if deadline is None:
        return (
            _safe_text(active_task.get("status"), 40) == "waiting_user"
            and bool(active_task.get("needs_confirmation"))
        )
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    return current >= deadline.astimezone()


async def clear_expired_waiting_confirmation(
    *,
    user_id: str,
    platform: str = "",
    active_task: dict[str, Any] | None = None,
) -> None:
    safe_user_id = _safe_text(user_id, 128)
    if not safe_user_id:
        return
    task_id = _safe_text((active_task or {}).get("id"), 80) or "waiting_task"
    task_inbox_id = _safe_text(
        (active_task or {}).get("task_inbox_id")
        or (active_task or {}).get("session_task_id"),
        80,
    )
    result_summary = "Waiting confirmation expired."

    from core.channel_runtime_store import channel_runtime_store
    from core.heartbeat_store import heartbeat_store

    if _safe_text(platform, 64) or safe_user_id:
        channel_runtime_store.update_active_task(
            platform=_safe_text(platform, 64),
            platform_user_id=safe_user_id,
            status="cancelled",
            needs_confirmation=False,
            confirmation_deadline="",
            clear_active=True,
            result_summary=result_summary,
        )
    await heartbeat_store.update_session_active_task(
        safe_user_id,
        status="cancelled",
        needs_confirmation=False,
        confirmation_deadline="",
        clear_active=True,
        result_summary=result_summary,
    )
    await heartbeat_store.release_lock(safe_user_id)
    await heartbeat_store.append_session_event(
        safe_user_id,
        f"confirmation_expired:{task_id}",
    )
    if task_inbox_id:
        from core.task_inbox import task_inbox

        await task_inbox.update_status(
            task_inbox_id,
            "cancelled",
            event="confirmation_expired",
            detail=result_summary,
            result={"summary": result_summary},
            output={"text": result_summary},
        )
