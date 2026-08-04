from __future__ import annotations

import math
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


def _last_push_prices_path(user_id: int | str):
    return user_state_path(user_id, "stock_watch", "last_push_prices.md")


def _last_push_message_path(user_id: int | str):
    return user_state_path(user_id, "stock_watch", "last_push_message.md")


def _normalize_delivery_target(raw: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(raw or {})
    return {
        "platform": normalize_platform(payload.get("platform")),
        "chat_id": str(payload.get("chat_id") or "").strip(),
        "updated_at": str(payload.get("updated_at") or now_iso()),
    }


def _normalize_last_push_message(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(raw or {})
    platform = normalize_platform(payload.get("platform"))
    chat_id = str(payload.get("chat_id") or "").strip()
    message_id = str(payload.get("message_id") or "").strip()
    if not platform or not chat_id or not message_id:
        return {}
    return {
        "platform": platform,
        "chat_id": chat_id,
        "message_id": message_id,
        "text": str(payload.get("text") or ""),
        "updated_at": str(payload.get("updated_at") or now_iso()),
        "is_latest": bool(payload.get("is_latest", True)),
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


async def get_last_stock_push_prices(user_id: int | str) -> dict[str, float]:
    data = await storage_service.read(_last_push_prices_path(user_id), {})
    if not isinstance(data, dict):
        return {}
    raw_prices = data.get("prices")
    if not isinstance(raw_prices, dict):
        return {}

    prices: dict[str, float] = {}
    for raw_code, raw_price in raw_prices.items():
        code = str(raw_code or "").strip()
        if not code:
            continue
        try:
            prices[code] = float(raw_price)
        except (TypeError, ValueError):
            continue
    return prices


async def save_last_stock_push_prices(
    user_id: int | str,
    quotes: list[dict[str, Any]],
) -> None:
    prices: dict[str, float] = {}
    for quote in quotes:
        code = str(quote.get("code") or "").strip()
        if not code:
            continue
        try:
            prices[code] = float(quote.get("price") or 0)
        except (TypeError, ValueError):
            continue

    await storage_service.write(
        _last_push_prices_path(user_id),
        {
            "updated_at": now_iso(),
            "prices": prices,
        },
    )


async def get_last_stock_push_message(user_id: int | str) -> dict[str, Any]:
    data = await storage_service.read(_last_push_message_path(user_id), {})
    if not isinstance(data, dict):
        return {}
    return _normalize_last_push_message(data)


async def save_last_stock_push_message(
    user_id: int | str,
    *,
    platform: str,
    chat_id: str,
    message_id: str,
    text: str = "",
) -> dict[str, Any]:
    normalized = _normalize_last_push_message(
        {
            "platform": platform,
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "updated_at": now_iso(),
            "is_latest": True,
        }
    )
    if not normalized:
        raise ValueError("platform, chat_id and message_id are required")
    await storage_service.write(_last_push_message_path(user_id), normalized)
    return normalized


async def clear_last_stock_push_message(user_id: int | str) -> None:
    await storage_service.write(_last_push_message_path(user_id), {})


async def mark_stock_push_chat_activity(
    platform: str,
    chat_id: str,
    *,
    user_id: int | str = "",
) -> None:
    """Mark that the delivery chat has newer activity than the last stock push."""
    target_platform = normalize_platform(platform)
    target_chat_id = str(chat_id or "").strip()
    if not target_platform or not target_chat_id:
        return

    scope = str(user_id or "").strip() or ""
    current = await get_last_stock_push_message(scope)
    if not current:
        return
    if (
        str(current.get("platform") or "") != target_platform
        or str(current.get("chat_id") or "") != target_chat_id
    ):
        return
    if not bool(current.get("is_latest")):
        return

    current["is_latest"] = False
    current["updated_at"] = now_iso()
    await storage_service.write(_last_push_message_path(scope), current)


async def get_editable_stock_push_message_id(
    user_id: int | str,
    *,
    platform: str,
    chat_id: str,
) -> str:
    current = await get_last_stock_push_message(user_id)
    if not current or not bool(current.get("is_latest")):
        return ""
    if normalize_platform(platform) != str(current.get("platform") or ""):
        return ""
    if str(chat_id or "").strip() != str(current.get("chat_id") or "").strip():
        return ""
    return str(current.get("message_id") or "").strip()


def _normalize_watchlist_row(raw: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stock_code": str(raw.get("stock_code") or "").strip(),
        "stock_name": str(raw.get("stock_name") or "").strip(),
        "platform": str(raw.get("platform") or "telegram").strip() or "telegram",
    }
    position_quantity = _positive_float(raw.get("position_quantity"))
    cost_price = _positive_float(raw.get("cost_price"))
    if position_quantity and cost_price:
        row["position_quantity"] = position_quantity
        row["cost_price"] = cost_price
    return row


def _positive_float(value: Any) -> float:
    try:
        normalized = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(normalized) or normalized <= 0:
        return 0.0
    return normalized


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
                "position_quantity": _positive_float(item.get("position_quantity")),
                "cost_price": _positive_float(item.get("cost_price")),
            }
        )
    return runtime


async def _read_watchlist(user_id: int | str) -> list[dict[str, Any]]:
    current_rows = read_row_list(
        await storage_service.read(_watchlist_path(user_id), [])
    )
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
        normalized: dict[str, Any] = {
            "stock_code": code,
            "stock_name": str(row.get("stock_name") or code).strip(),
            "platform": str(row.get("platform") or "telegram").strip() or "telegram",
        }
        position_quantity = _positive_float(row.get("position_quantity"))
        cost_price = _positive_float(row.get("cost_price"))
        if position_quantity and cost_price:
            normalized["position_quantity"] = position_quantity
            normalized["cost_price"] = cost_price
        payload.append(normalized)
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


async def set_watchlist_position(
    user_id: int | str,
    stock_code: str,
    quantity: float,
    cost_price: float,
) -> bool:
    normalized_quantity = _positive_float(quantity)
    normalized_cost = _positive_float(cost_price)
    if not normalized_quantity or not normalized_cost:
        raise ValueError("quantity and cost_price must be positive numbers")

    rows = await _read_watchlist(user_id)
    code = str(stock_code or "").strip().lower()
    found = False
    for row in rows:
        if str(row.get("stock_code") or "").strip().lower() != code:
            continue
        row["position_quantity"] = normalized_quantity
        row["cost_price"] = normalized_cost
        found = True
    if found:
        await _write_watchlist(user_id, rows)
    return found


async def clear_watchlist_position(
    user_id: int | str,
    stock_code: str,
) -> bool:
    rows = await _read_watchlist(user_id)
    code = str(stock_code or "").strip().lower()
    found = False
    for row in rows:
        if str(row.get("stock_code") or "").strip().lower() != code:
            continue
        row.pop("position_quantity", None)
        row.pop("cost_price", None)
        found = True
    if found:
        await _write_watchlist(user_id, rows)
    return found


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
    "clear_watchlist_position",
    "clear_last_stock_push_message",
    "get_all_watchlist_users",
    "get_editable_stock_push_message_id",
    "get_last_stock_push_message",
    "get_last_stock_push_prices",
    "get_stock_delivery_target",
    "get_user_watchlist",
    "mark_stock_push_chat_activity",
    "remove_watchlist_stock",
    "save_last_stock_push_message",
    "save_last_stock_push_prices",
    "set_watchlist_position",
    "set_stock_delivery_target",
]
