from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

from core.runtime_v2 import TERMINAL_STATUSES, runtime_v2


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
    close_runtime_v2_waiting_task(
        active_task=active_task,
        status="expired",
        reason=result_summary,
        event_type="task.confirmation_expired",
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


def _runtime_task_from_active(active_task: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(active_task, dict):
        return {}
    candidates = (
        active_task.get("runtime_v2_task_id"),
        active_task.get("task_id"),
        active_task.get("id"),
        active_task.get("session_task_id"),
    )
    for candidate in candidates:
        task_id = _safe_text(candidate, 180)
        if not task_id:
            continue
        with contextlib.suppress(Exception):
            task = runtime_v2.get_task(task_id)
            if task:
                return task
    return {}


def _runtime_turn_from_active(
    active_task: dict[str, Any] | None,
    runtime_task: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(active_task, dict):
        active_task = {}
    candidates = (
        active_task.get("runtime_v2_turn_id"),
        active_task.get("turn_id"),
        (runtime_task or {}).get("turn_id"),
    )
    for candidate in candidates:
        turn_id = _safe_text(candidate, 180)
        if not turn_id:
            continue
        with contextlib.suppress(Exception):
            turn = runtime_v2.get_turn(turn_id)
            if turn:
                return turn
    return {}


def close_runtime_v2_waiting_task(
    *,
    active_task: dict[str, Any] | None,
    status: str,
    reason: str,
    event_type: str,
) -> bool:
    target = _safe_text(status, 40).lower()
    if target not in {"expired", "cancelled", "failed"}:
        target = "cancelled"
    summary = _safe_text(reason, 1000)
    runtime_task = _runtime_task_from_active(active_task)
    runtime_turn = _runtime_turn_from_active(active_task, runtime_task)
    changed = False

    if runtime_turn and _safe_text(runtime_turn.get("status"), 40) not in TERMINAL_STATUSES:
        with contextlib.suppress(Exception):
            if _safe_text(runtime_turn.get("status"), 40) == "queued":
                runtime_v2.update_turn_status(
                    _safe_text(runtime_turn.get("id"), 180),
                    "running",
                    metadata={"waiting_confirmation_close": True},
                )
            runtime_v2.update_turn_status(
                _safe_text(runtime_turn.get("id"), 180),
                target,
                error=summary if target == "failed" else "",
                metadata={
                    "waiting_confirmation_closed": True,
                    "waiting_confirmation_close_reason": summary,
                },
            )
            changed = True

    if runtime_task and _safe_text(runtime_task.get("status"), 40) not in TERMINAL_STATUSES:
        with contextlib.suppress(Exception):
            if _safe_text(runtime_task.get("status"), 40) == "queued":
                runtime_v2.update_task_status(
                    _safe_text(runtime_task.get("id"), 180),
                    "running",
                    metadata={"waiting_confirmation_close": True},
                )
            runtime_v2.update_task_status(
                _safe_text(runtime_task.get("id"), 180),
                target,
                metadata={
                    "waiting_confirmation_closed": True,
                    "waiting_confirmation_close_reason": summary,
                },
            )
            changed = True

    session_id = _safe_text(
        (active_task or {}).get("runtime_v2_session_id")
        or runtime_task.get("session_id")
        or runtime_turn.get("session_id"),
        180,
    )
    if session_id:
        with contextlib.suppress(Exception):
            runtime_v2.append_event(
                session_id=session_id,
                turn_id=_safe_text(runtime_turn.get("id"), 180),
                event_type=_safe_text(event_type, 120) or "task.waiting_closed",
                payload={
                    "status": target,
                    "reason": summary,
                    "runtime_v2_task_id": _safe_text(runtime_task.get("id"), 180),
                },
            )
            changed = True
    return changed
