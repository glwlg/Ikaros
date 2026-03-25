from __future__ import annotations

from typing import Any

from core.storage_service import (
    dedupe_rows,
    now_iso,
    read_row_list,
    storage_service,
    user_state_path,
)
from core.subscription_types import default_title, normalize_platform, normalize_provider


def _subscriptions_path(user_id: int | str):
    return user_state_path(user_id, "rss_subscribe", "subscriptions.md")


def _delivery_target_path(user_id: int | str):
    return user_state_path(user_id, "rss_subscribe", "delivery_target.md")


def _normalize_delivery_target(raw: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(raw or {})
    return {
        "platform": normalize_platform(payload.get("platform")),
        "chat_id": str(payload.get("chat_id") or "").strip(),
        "updated_at": str(payload.get("updated_at") or now_iso()),
    }


async def get_rss_delivery_target(user_id: int | str) -> dict[str, str]:
    data = await storage_service.read(_delivery_target_path(user_id), {})
    if not isinstance(data, dict):
        return {}
    target = _normalize_delivery_target(data)
    if not target["platform"] or not target["chat_id"]:
        return {}
    return target


async def set_rss_delivery_target(
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


def _normalize_subscription(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        sub_id = int(raw.get("id") or 0)
    except Exception:
        return None
    if sub_id <= 0:
        return None

    feed_url = str(raw.get("feed_url") or "").strip()
    if not feed_url:
        return None

    provider_value = raw.get("provider")
    if str(provider_value or "").strip().lower() == "rss":
        provider_value = "native_rss"

    try:
        provider = normalize_provider(provider_value, feed_url=feed_url)
    except ValueError:
        return None

    title = str(raw.get("title") or "").strip()
    if not title:
        title = default_title(feed_url=feed_url)

    return {
        "id": sub_id,
        "provider": provider,
        "title": title,
        "platform": normalize_platform(raw.get("platform")),
        "feed_url": feed_url,
        "last_etag": str(raw.get("last_etag") or "").strip(),
        "last_modified": str(raw.get("last_modified") or "").strip(),
        "last_entry_hash": str(raw.get("last_entry_hash") or "").strip(),
    }


def _serialize_subscription(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_subscription(row)
    if normalized is None:
        raise ValueError("invalid subscription row")
    return normalized


async def _read_subscription_rows(user_id: int | str) -> list[dict[str, Any]]:
    data = await storage_service.read(_subscriptions_path(user_id), [])
    rows: list[dict[str, Any]] = []
    for item in read_row_list(data):
        normalized = _normalize_subscription(item)
        if normalized is not None:
            rows.append(normalized)
    return dedupe_rows(rows, key_fn=lambda row: int(row.get("id") or 0))


async def _write_subscription_rows(user_id: int | str, rows: list[dict[str, Any]]) -> None:
    payload: list[dict[str, Any]] = []
    for row in dedupe_rows(rows, key_fn=lambda item: int(item.get("id") or 0)):
        payload.append(_serialize_subscription(row))
    payload.sort(key=lambda item: int(item["id"]))
    await storage_service.write(_subscriptions_path(user_id), payload)


def _find_subscription_index(rows: list[dict[str, Any]], sub_id: int) -> int:
    for index, row in enumerate(rows):
        if int(row.get("id") or 0) == int(sub_id):
            return index
    return -1


def _assert_unique_subscription(
    rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    ignore_id: int | None = None,
) -> None:
    for row in rows:
        if ignore_id is not None and int(row.get("id") or 0) == int(ignore_id):
            continue
        if (
            str(row.get("feed_url") or "").strip()
            == str(candidate.get("feed_url") or "").strip()
        ):
            raise ValueError("feed subscription already exists")


def _validate_subscription_payload(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    subscription_id: int | None = None,
) -> dict[str, Any]:
    source = dict(existing or {})
    source.update(dict(payload or {}))
    platform = normalize_platform(source.get("platform"))
    feed_url = str(source.get("feed_url") or "").strip()
    if not feed_url:
        raise ValueError("feed_url is required for RSS subscriptions")
    for removed_field in ("kind", "query", "scope"):
        if str(source.get(removed_field) or "").strip():
            raise ValueError("关键词监控已下线，仅支持 RSS 订阅")

    provider = normalize_provider(source.get("provider"), feed_url=feed_url)
    title = str(source.get("title") or "").strip()
    if not title:
        title = default_title(feed_url=feed_url)

    return {
        "id": int(subscription_id or source.get("id") or 0),
        "provider": provider,
        "title": title,
        "platform": platform,
        "feed_url": feed_url,
        "last_etag": str(source.get("last_etag") or "").strip(),
        "last_modified": str(source.get("last_modified") or "").strip(),
        "last_entry_hash": str(source.get("last_entry_hash") or "").strip(),
    }


async def create_subscription(user_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
    rows = await _read_subscription_rows(user_id)
    sub_id = await storage_service.next_id_after_store_rows(
        "subscriptions",
        _subscriptions_path(""),
    )
    record = _validate_subscription_payload(payload, subscription_id=sub_id)
    _assert_unique_subscription(rows, record)
    rows.append(record)
    await _write_subscription_rows(user_id, rows)
    return record


async def list_subscriptions(user_id: int | str) -> list[dict[str, Any]]:
    return await _read_subscription_rows(user_id)


async def get_subscription(user_id: int | str, sub_id: int) -> dict[str, Any] | None:
    rows = await _read_subscription_rows(user_id)
    index = _find_subscription_index(rows, sub_id)
    if index < 0:
        return None
    return rows[index]


async def update_subscription(
    sub_id: int,
    user_id: int | str,
    payload: dict[str, Any],
) -> bool:
    rows = await _read_subscription_rows(user_id)
    index = _find_subscription_index(rows, sub_id)
    if index < 0:
        return False
    updated = _validate_subscription_payload(
        payload,
        existing=rows[index],
        subscription_id=sub_id,
    )
    _assert_unique_subscription(rows, updated, ignore_id=sub_id)
    rows[index] = updated
    await _write_subscription_rows(user_id, rows)
    return True


async def delete_subscription(user_id: int | str, sub_id: int) -> bool:
    rows = await _read_subscription_rows(user_id)
    index = _find_subscription_index(rows, sub_id)
    if index < 0:
        return False
    rows.pop(index)
    await _write_subscription_rows(user_id, rows)
    return True


async def list_all_subscriptions() -> list[dict[str, Any]]:
    return await _read_subscription_rows("")


async def list_feed_subscriptions() -> list[dict[str, Any]]:
    return await list_all_subscriptions()


async def update_feed_subscription_state(
    user_id: int | str,
    sub_id: int,
    *,
    last_entry_hash: str,
    last_etag: str | None = None,
    last_modified: str | None = None,
) -> bool:
    rows = await _read_subscription_rows(user_id)
    index = _find_subscription_index(rows, sub_id)
    if index < 0:
        return False
    target = rows[index]
    target["last_entry_hash"] = str(last_entry_hash or "").strip()
    target["last_etag"] = str(last_etag or "").strip()
    target["last_modified"] = str(last_modified or "").strip()
    rows[index] = target
    await _write_subscription_rows(user_id, rows)
    return True


async def get_user_subscriptions(user_id: int | str) -> list[dict[str, Any]]:
    return await list_subscriptions(user_id)


async def get_all_subscriptions() -> list[dict[str, Any]]:
    return await list_all_subscriptions()


__all__ = [
    "create_subscription",
    "delete_subscription",
    "get_all_subscriptions",
    "get_rss_delivery_target",
    "get_subscription",
    "get_user_subscriptions",
    "list_all_subscriptions",
    "list_feed_subscriptions",
    "list_subscriptions",
    "set_rss_delivery_target",
    "update_feed_subscription_state",
    "update_subscription",
]
