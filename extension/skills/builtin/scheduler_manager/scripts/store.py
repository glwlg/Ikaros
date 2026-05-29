from __future__ import annotations

import re
from typing import Any

from core.runtime_v2 import runtime_v2
from core.state_paths import SINGLE_USER_SCOPE
from core.storage_service import now_iso


def scheduler_task_session_id(task_id: int | str) -> str:
    raw = str(task_id or "").strip()
    safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", raw).strip("-")
    return f"scheduler-task-{safe or 'unknown'}"


def _owner_user_id(user_id: int | str | None = None) -> str:
    return str(user_id or "").strip()


def _default_owner_user_id(user_id: int | str | None = None) -> str:
    return _owner_user_id(user_id) or str(SINGLE_USER_SCOPE)


def _session_owner_user_id(session_id: str, user_id: int | str | None = None) -> str:
    owner = _owner_user_id(user_id)
    if owner:
        return owner
    existing = runtime_v2.get_session(session_id)
    return str(existing.get("platform_user_id") or "").strip() or str(SINGLE_USER_SCOPE)


def _to_int_id(value: Any) -> int:
    try:
        return int(str(value or "0").strip())
    except Exception:
        return 0


def _normalize_scheduled_task(raw: dict[str, Any]) -> dict[str, Any]:
    task_id = _to_int_id(raw.get("id"))
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    session_id = str(raw.get("session_id") or "").strip() or scheduler_task_session_id(
        task_id
    )
    return {
        "id": task_id,
        "crontab": str(raw.get("crontab") or "").strip(),
        "instruction": str(raw.get("instruction") or "").strip(),
        "platform": str(raw.get("platform") or "telegram").strip() or "telegram",
        "chat_id": str(raw.get("chat_id") or "").strip(),
        "session_id": session_id,
        "user_id": str(
            raw.get("platform_user_id")
            or metadata.get("created_by_user_id")
            or SINGLE_USER_SCOPE
        ).strip(),
        "need_push": bool(metadata.get("need_push", True)),
        "is_active": bool(raw.get("enabled", 1)),
        "created_at": str(raw.get("created_at") or now_iso()),
        "updated_at": str(raw.get("updated_at") or now_iso()),
    }


def _ensure_scheduler_session(
    task_id: int | str,
    *,
    instruction: str = "",
    user_id: int | str | None = None,
    platform: str = "scheduler",
    chat_id: str = "",
) -> str:
    session_id = scheduler_task_session_id(task_id)
    runtime_v2.ensure_session(
        session_id=session_id,
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id=_session_owner_user_id(session_id, user_id),
        title=str(instruction or "")[:80],
        metadata={
            "scheduled_task_id": str(task_id or "").strip(),
            "delivery_platform": str(platform or "").strip(),
            "delivery_chat_id": str(chat_id or "").strip(),
        },
    )
    return session_id


def _get_scheduler_job_for_user(
    task_id: int | str,
    user_id: int | str | None = None,
) -> dict[str, Any]:
    existing = runtime_v2.get_scheduler_job(str(int(task_id)))
    if not existing:
        return {}
    owner = _owner_user_id(user_id)
    if not owner:
        return existing
    session = runtime_v2.get_session(str(existing.get("session_id") or ""))
    if str(session.get("platform_user_id") or "").strip() != owner:
        return {}
    return existing


async def add_scheduled_task(
    crontab: str,
    instruction: str,
    user_id: int | str = 0,
    platform: str = "telegram",
    chat_id: str = "",
    session_id: str = "",
    need_push: bool = True,
) -> int:
    _ = session_id
    job = runtime_v2.create_scheduler_job(
        crontab=str(crontab or "").strip(),
        instruction=str(instruction or "").strip(),
        owner_user_id=_default_owner_user_id(user_id),
        platform=str(platform or "telegram").strip() or "telegram",
        chat_id=str(chat_id or "").strip(),
        enabled=True,
        metadata={
            "need_push": bool(need_push),
            "created_by_user_id": str(user_id or "").strip(),
        },
    )
    return int(job.get("id") or 0)


async def get_all_active_tasks(
    user_id: int | str | None = None,
) -> list[dict[str, Any]]:
    rows = await get_all_scheduled_tasks(user_id)
    return [item for item in rows if bool(item.get("is_active", True))]


async def get_all_scheduled_tasks(
    user_id: int | str | None = None,
) -> list[dict[str, Any]]:
    rows = runtime_v2.list_scheduler_jobs(
        platform_user_id=_owner_user_id(user_id),
        limit=1000,
    )
    normalized = [_normalize_scheduled_task(item) for item in rows]
    return sorted(normalized, key=lambda item: int(item.get("id") or 0))


async def update_task_status(
    task_id: int,
    is_active: bool,
    user_id: int | str | None = None,
) -> bool:
    existing = _get_scheduler_job_for_user(task_id, user_id)
    if not existing:
        return False
    task = _normalize_scheduled_task(existing)
    session_id = _ensure_scheduler_session(
        task_id,
        instruction=task["instruction"],
        user_id=user_id,
        platform=task["platform"],
        chat_id=task["chat_id"],
    )
    runtime_v2.upsert_scheduler_job(
        job_id=str(int(task_id)),
        session_id=session_id,
        crontab=task["crontab"],
        instruction=task["instruction"],
        platform=task["platform"],
        chat_id=task["chat_id"],
        enabled=bool(is_active),
        metadata={"need_push": task["need_push"]},
    )
    return True


async def update_task_delivery_target(
    task_id: int,
    user_id: int | str | None = None,
    *,
    platform: str,
    chat_id: str,
    session_id: str = "",
) -> bool:
    _ = session_id
    existing = _get_scheduler_job_for_user(task_id, user_id)
    if not existing:
        return False
    task = _normalize_scheduled_task(existing)
    target_platform = str(platform or "telegram").strip() or "telegram"
    target_chat_id = str(chat_id or "").strip()
    scheduler_session_id = _ensure_scheduler_session(
        task_id,
        instruction=task["instruction"],
        user_id=user_id,
        platform=target_platform,
        chat_id=target_chat_id,
    )
    runtime_v2.upsert_scheduler_job(
        job_id=str(int(task_id)),
        session_id=scheduler_session_id,
        crontab=task["crontab"],
        instruction=task["instruction"],
        platform=target_platform,
        chat_id=target_chat_id,
        enabled=task["is_active"],
        metadata={"need_push": task["need_push"]},
    )
    return True


async def delete_task(task_id: int, user_id: int | str | None = None) -> None:
    if not _get_scheduler_job_for_user(task_id, user_id):
        return
    runtime_v2.delete_scheduler_job(str(int(task_id)))


async def update_scheduled_task(
    task_id: int,
    user_id: int | str | None = None,
    crontab: str | None = None,
    instruction: str | None = None,
) -> bool:
    existing = _get_scheduler_job_for_user(task_id, user_id)
    if not existing:
        return False
    task = _normalize_scheduled_task(existing)
    next_crontab = task["crontab"] if crontab is None else str(crontab).strip()
    next_instruction = (
        task["instruction"] if instruction is None else str(instruction).strip()
    )
    session_id = _ensure_scheduler_session(
        task_id,
        instruction=next_instruction,
        user_id=user_id,
        platform=task["platform"],
        chat_id=task["chat_id"],
    )
    runtime_v2.upsert_scheduler_job(
        job_id=str(int(task_id)),
        session_id=session_id,
        crontab=next_crontab,
        instruction=next_instruction,
        platform=task["platform"],
        chat_id=task["chat_id"],
        enabled=task["is_active"],
        metadata={"need_push": task["need_push"]},
    )
    return True


__all__ = [
    "add_scheduled_task",
    "delete_task",
    "get_all_active_tasks",
    "get_all_scheduled_tasks",
    "scheduler_task_session_id",
    "update_scheduled_task",
    "update_task_delivery_target",
    "update_task_status",
]
