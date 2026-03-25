from __future__ import annotations

from typing import Any

from core.state_paths import SINGLE_USER_SCOPE
from core.storage_service import (
    dedupe_rows,
    now_iso,
    read_row_list,
    storage_service,
    user_state_path,
)
from core.subscription_types import normalize_platform


def _watchlist_path(user_id: int | str):
    return user_state_path(user_id, "stock_watch", "watchlist.md")


def _delivery_target_path(user_id: int | str):
    return user_state_path(user_id, "stock_watch", "delivery_target.md")


def _normalize_delivery_target(raw: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(raw or {})
    return {
        "platform": normalize_platform(payload.get("platform")),
        "chat_id": str(payload.get("chat_id") or "").strip(),
        "updated_at": str(payload.get("updated_at") or now_iso()),
    }


async def get_stock_delivery_target(user_id: int | str) -> dict[str, str]:
    data = await storage_service.read(_delivery_target_path(user_id), {})
    if not isinstance(data, dict):
        return {}
    target = _normalize_delivery_target(data)
    if not target["platform"] or not target["chat_id"]:
        return {}
    return target


async def set_stock_delivery_target(
    user_id: int | str,
    platform: str,
    chat_id: str,
) -> dict[str, str]:
    normalized = _normalize_delivery_target(
        {
            "platform": platform,
            "chat_id": chat_id,
            "updated_at": now_iso(),
        }
    )
    if not normalized["platform"] or not normalized["chat_id"]:
        raise ValueError("platform and chat_id are required")
    await storage_service.write(_delivery_target_path(user_id), normalized)
    return normalized


def _normalize_watchlist_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "stock_code": str(raw.get("stock_code") or "").strip(),
        "stock_name": str(raw.get("stock_name") or "").strip(),
        "platform": str(raw.get("platform") or "telegram").strip() or "telegram",
    }


def _to_watchlist_runtime_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        code = str(item.get("stock_code") or "").strip()
        if not code:
            continue
        runtime.append(
            {
                "id": index,
                "stock_code": code,
                "stock_name": str(item.get("stock_name") or code),
                "platform": str(item.get("platform") or "telegram"),
            }
        )
    return runtime


async def _read_watchlist(user_id: int | str) -> list[dict[str, Any]]:
    current_rows = read_row_list(await storage_service.read(_watchlist_path(user_id), []))
    normalized_current: list[dict[str, Any]] = []
    for raw in current_rows:
        normalized = _normalize_watchlist_row(raw)
        if normalized.get("stock_code"):
            normalized_current.append(normalized)
    return dedupe_rows(
        normalized_current,
        key_fn=lambda row: (
            str(row.get("stock_code") or "").strip().lower(),
            str(row.get("platform") or "telegram").strip().lower(),
        ),
    )


async def _write_watchlist(user_id: int | str, rows: list[dict[str, Any]]) -> None:
    payload: list[dict[str, Any]] = []
    for row in dedupe_rows(
        rows,
        key_fn=lambda item: (
            str(item.get("stock_code") or "").strip().lower(),
            str(item.get("platform") or "telegram").strip().lower(),
        ),
    ):
        code = str(row.get("stock_code") or "").strip()
        if not code:
            continue
        payload.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("stock_name") or code).strip(),
                "platform": str(row.get("platform") or "telegram").strip() or "telegram",
            }
        )
    await storage_service.write(_watchlist_path(user_id), payload)


async def add_watchlist_stock(
    user_id: int | str,
    stock_code: str,
    stock_name: str,
    platform: str = "telegram",
) -> bool:
    rows = await _read_watchlist(user_id)
    code = str(stock_code or "").strip()
    if not code:
        return False
    if any(str(item.get("stock_code") or "").strip() == code for item in rows):
        return False
    rows.append(
        {
            "stock_code": code,
            "stock_name": str(stock_name or code).strip(),
            "platform": str(platform or "telegram"),
        }
    )
    await _write_watchlist(user_id, rows)
    return True


async def remove_watchlist_stock(user_id: int | str, stock_code: str) -> bool:
    rows = await _read_watchlist(user_id)
    code = str(stock_code or "").strip()
    kept = [item for item in rows if str(item.get("stock_code") or "").strip() != code]
    changed = len(kept) != len(rows)
    if changed:
        await _write_watchlist(user_id, kept)
    return changed


async def get_user_watchlist(
    user_id: int | str,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    rows = await _read_watchlist(user_id)
    if platform:
        target = str(platform).strip().lower()
        rows = [
            item
            for item in rows
            if str(item.get("platform") or "telegram").strip().lower() == target
        ]
    else:
        rows = dedupe_rows(
            rows,
            key_fn=lambda row: str(row.get("stock_code") or "").strip().lower(),
        )
    return _to_watchlist_runtime_rows(rows)


async def get_all_watchlist_users() -> list[tuple[int | str, str]]:
    rows = await _read_watchlist("")
    if not rows:
        return []
    target = await get_stock_delivery_target("")
    platform = str(target.get("platform") or rows[0].get("platform") or "telegram")
    return [(SINGLE_USER_SCOPE, platform)]


__all__ = [
    "add_watchlist_stock",
    "get_all_watchlist_users",
    "get_stock_delivery_target",
    "get_user_watchlist",
    "remove_watchlist_stock",
    "set_stock_delivery_target",
]
