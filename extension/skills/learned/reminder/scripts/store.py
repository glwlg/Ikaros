from __future__ import annotations

from typing import Any

from core.storage_service import (
    dedupe_rows,
    now_iso,
    read_row_list,
    storage_service,
    user_state_path,
)


def _reminders_path(user_id: int | str):
    return user_state_path(user_id, "reminder", "reminders.md")


def _normalize_reminder(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(raw.get("id") or 0),
        "chat_id": str(raw.get("chat_id") or ""),
        "message": str(raw.get("message") or ""),
        "trigger_time": str(raw.get("trigger_time") or ""),
        "created_at": str(raw.get("created_at") or now_iso()),
        "platform": str(raw.get("platform") or "telegram"),
    }


async def _read_user_reminders(user_id: int | str) -> list[dict[str, Any]]:
    current_rows = read_row_list(
        await storage_service.read(_reminders_path(user_id), []),
        "reminders",
    )
    return dedupe_rows(
        [
            _normalize_reminder(item)
            for item in current_rows
            if isinstance(item, dict)
        ],
        key_fn=lambda row: int(row.get("id") or 0),
    )


async def _write_user_reminders(user_id: int | str, rows: list[dict[str, Any]]) -> None:
    payload: list[dict[str, Any]] = []
    for row in dedupe_rows(rows, key_fn=lambda item: int(item.get("id") or 0)):
        payload.append(
            {
                "id": int(row.get("id") or 0),
                "chat_id": str(row.get("chat_id") or ""),
                "message": str(row.get("message") or ""),
                "trigger_time": str(row.get("trigger_time") or ""),
                "created_at": str(row.get("created_at") or now_iso()),
                "platform": str(row.get("platform") or "telegram"),
            }
        )
    await storage_service.write(_reminders_path(user_id), payload)


async def add_reminder(
    user_id: int | str,
    chat_id: int | str,
    message: str,
    trigger_time: str,
    platform: str = "telegram",
) -> int:
    rows = await _read_user_reminders(user_id)
    reminder_id = await storage_service.next_id_after_store_rows(
        "reminder",
        _reminders_path(""),
        list_keys=("reminders",),
    )
    rows.append(
        {
            "id": int(reminder_id),
            "chat_id": str(chat_id),
            "message": str(message or ""),
            "trigger_time": str(trigger_time or ""),
            "created_at": now_iso(),
            "platform": str(platform or "telegram"),
        }
    )
    await _write_user_reminders(user_id, rows)
    return int(reminder_id)


async def delete_reminder(reminder_id: int, user_id: int | str | None = None) -> None:
    rid = int(reminder_id)
    rows = await _read_user_reminders(user_id or "")
    kept = [item for item in rows if int(item.get("id") or 0) != rid]
    if len(kept) != len(rows):
        await _write_user_reminders(user_id or "", kept)


async def get_pending_reminders(
    user_id: int | str | None = None,
) -> list[dict[str, Any]]:
    return sorted(
        await _read_user_reminders(user_id or ""),
        key=lambda item: str(item.get("trigger_time") or ""),
    )


__all__ = ["add_reminder", "delete_reminder", "get_pending_reminders"]
