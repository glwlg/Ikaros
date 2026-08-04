from __future__ import annotations

import asyncio
import calendar
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from core.app_paths import data_dir

_INITIALIZED_PATHS: set[str] = set()
_INIT_LOCKS: dict[str, asyncio.Lock] = {}


def subscription_database_path() -> Path:
    return (data_dir() / "subscriptions.db").resolve()


def add_months(value: date, months: int) -> date:
    month_count = int(months)
    if month_count <= 0:
        raise ValueError("cycle_months must be greater than 0")
    month_index = value.year * 12 + value.month - 1 + month_count
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _date_value(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def init_subscription_store() -> None:
    path = subscription_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    lock = _INIT_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        if key in _INITIALIZED_PATHS:
            return
        async with aiosqlite.connect(path) as conn:
            await conn.execute("PRAGMA busy_timeout = 5000")
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    cost TEXT NOT NULL DEFAULT '',
                    start_date TEXT NOT NULL,
                    cycle_months INTEGER NOT NULL,
                    expiry_date TEXT NOT NULL,
                    reminder_enabled INTEGER NOT NULL DEFAULT 1,
                    reminder_days_before INTEGER NOT NULL DEFAULT 3,
                    delivery_platform TEXT NOT NULL DEFAULT '',
                    delivery_user_id TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    last_reminded_for_expiry TEXT NOT NULL DEFAULT '',
                    last_reminded_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_owner_expiry
                    ON subscriptions(owner_user_id, expiry_date);
                CREATE INDEX IF NOT EXISTS idx_subscriptions_reminder_scan
                    ON subscriptions(reminder_enabled, expiry_date);
                """
            )
            columns_cursor = await conn.execute("PRAGMA table_info(subscriptions)")
            columns = {str(row[1]) for row in await columns_cursor.fetchall()}
            if "cost" not in columns:
                await conn.execute(
                    "ALTER TABLE subscriptions ADD COLUMN cost TEXT NOT NULL DEFAULT ''"
                )
            await conn.commit()
        _INITIALIZED_PATHS.add(key)


@asynccontextmanager
async def _connection() -> AsyncIterator[aiosqlite.Connection]:
    await init_subscription_store()
    conn = await aiosqlite.connect(subscription_database_path())
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
    finally:
        await conn.close()


def _normalize_record(row: aiosqlite.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": int(data.get("id") or 0),
        "owner_user_id": str(data.get("owner_user_id") or ""),
        "name": str(data.get("name") or ""),
        "category": str(data.get("category") or ""),
        "provider": str(data.get("provider") or ""),
        "cost": str(data.get("cost") or ""),
        "start_date": str(data.get("start_date") or ""),
        "cycle_months": int(data.get("cycle_months") or 0),
        "expiry_date": str(data.get("expiry_date") or ""),
        "reminder_enabled": bool(data.get("reminder_enabled")),
        "reminder_days_before": int(data.get("reminder_days_before") or 0),
        "delivery_platform": str(data.get("delivery_platform") or ""),
        "delivery_user_id": str(data.get("delivery_user_id") or ""),
        "notes": str(data.get("notes") or ""),
        "last_reminded_for_expiry": str(data.get("last_reminded_for_expiry") or ""),
        "last_reminded_at": str(data.get("last_reminded_at") or ""),
        "created_at": str(data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }


def _normalized_payload(
    payload: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(current or {})
    source.update(payload)

    name = str(source.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    cycle_months = int(source.get("cycle_months") or 0)
    if cycle_months <= 0 or cycle_months > 1200:
        raise ValueError("cycle_months must be between 1 and 1200")

    start_date = _date_value(source.get("start_date"), field="start_date")
    expiry_input = source.get("expiry_date")
    if expiry_input in {None, ""}:
        expiry_date = add_months(start_date, cycle_months)
    else:
        expiry_date = _date_value(expiry_input, field="expiry_date")
    if expiry_date < start_date:
        raise ValueError("expiry_date cannot be earlier than start_date")

    reminder_days = int(source.get("reminder_days_before", 3))
    if reminder_days < 0 or reminder_days > 3650:
        raise ValueError("reminder_days_before must be between 0 and 3650")

    delivery_platform = str(source.get("delivery_platform") or "").strip().lower()
    delivery_user_id = str(source.get("delivery_user_id") or "").strip()
    if bool(delivery_platform) != bool(delivery_user_id):
        raise ValueError("delivery_platform and delivery_user_id must be set together")

    return {
        "name": name,
        "category": str(source.get("category") or "其他").strip() or "其他",
        "provider": str(source.get("provider") or "").strip(),
        "cost": str(source.get("cost") or "").strip(),
        "start_date": start_date.isoformat(),
        "cycle_months": cycle_months,
        "expiry_date": expiry_date.isoformat(),
        "reminder_enabled": bool(source.get("reminder_enabled", True)),
        "reminder_days_before": reminder_days,
        "delivery_platform": delivery_platform,
        "delivery_user_id": delivery_user_id,
        "notes": str(source.get("notes") or "").strip(),
    }


async def create_subscription(
    owner_user_id: int | str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    owner = str(owner_user_id or "").strip()
    if not owner:
        raise ValueError("owner_user_id is required")
    normalized = _normalized_payload(payload)
    now = _now_iso()
    async with _connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO subscriptions(
                owner_user_id, name, category, provider, cost, start_date,
                cycle_months, expiry_date, reminder_enabled,
                reminder_days_before, delivery_platform, delivery_user_id,
                notes, last_reminded_for_expiry, last_reminded_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?)
            """,
            (
                owner,
                normalized["name"],
                normalized["category"],
                normalized["provider"],
                normalized["cost"],
                normalized["start_date"],
                normalized["cycle_months"],
                normalized["expiry_date"],
                int(normalized["reminder_enabled"]),
                normalized["reminder_days_before"],
                normalized["delivery_platform"],
                normalized["delivery_user_id"],
                normalized["notes"],
                now,
                now,
            ),
        )
        await conn.commit()
        created = await get_subscription(owner, int(cursor.lastrowid or 0), conn=conn)
    if created is None:
        raise RuntimeError("subscription was not created")
    return created


async def get_subscription(
    owner_user_id: int | str,
    subscription_id: int,
    *,
    conn: aiosqlite.Connection | None = None,
) -> dict[str, Any] | None:
    owner = str(owner_user_id or "").strip()

    async def _read(active_conn: aiosqlite.Connection) -> dict[str, Any] | None:
        cursor = await active_conn.execute(
            "SELECT * FROM subscriptions WHERE id = ? AND owner_user_id = ?",
            (int(subscription_id), owner),
        )
        row = await cursor.fetchone()
        return _normalize_record(row) if row is not None else None

    if conn is not None:
        return await _read(conn)
    async with _connection() as active_conn:
        return await _read(active_conn)


async def list_subscriptions(owner_user_id: int | str) -> list[dict[str, Any]]:
    owner = str(owner_user_id or "").strip()
    async with _connection() as conn:
        cursor = await conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE owner_user_id = ?
            ORDER BY expiry_date ASC, id ASC
            """,
            (owner,),
        )
        return [_normalize_record(row) for row in await cursor.fetchall()]


async def update_subscription(
    owner_user_id: int | str,
    subscription_id: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    owner = str(owner_user_id or "").strip()
    async with _connection() as conn:
        current = await get_subscription(owner, subscription_id, conn=conn)
        if current is None:
            return None

        update_payload = dict(payload)
        if "expiry_date" not in update_payload and (
            {"start_date", "cycle_months"} & update_payload.keys()
        ):
            update_payload["expiry_date"] = None
        normalized = _normalized_payload(update_payload, current=current)
        expiry_changed = normalized["expiry_date"] != current["expiry_date"]
        now = _now_iso()
        await conn.execute(
            """
            UPDATE subscriptions SET
                name = ?, category = ?, provider = ?, cost = ?, start_date = ?,
                cycle_months = ?, expiry_date = ?, reminder_enabled = ?,
                reminder_days_before = ?, delivery_platform = ?,
                delivery_user_id = ?, notes = ?,
                last_reminded_for_expiry = ?, last_reminded_at = ?, updated_at = ?
            WHERE id = ? AND owner_user_id = ?
            """,
            (
                normalized["name"],
                normalized["category"],
                normalized["provider"],
                normalized["cost"],
                normalized["start_date"],
                normalized["cycle_months"],
                normalized["expiry_date"],
                int(normalized["reminder_enabled"]),
                normalized["reminder_days_before"],
                normalized["delivery_platform"],
                normalized["delivery_user_id"],
                normalized["notes"],
                "" if expiry_changed else current["last_reminded_for_expiry"],
                "" if expiry_changed else current["last_reminded_at"],
                now,
                int(subscription_id),
                owner,
            ),
        )
        await conn.commit()
        return await get_subscription(owner, subscription_id, conn=conn)


async def delete_subscription(owner_user_id: int | str, subscription_id: int) -> bool:
    owner = str(owner_user_id or "").strip()
    async with _connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM subscriptions WHERE id = ? AND owner_user_id = ?",
            (int(subscription_id), owner),
        )
        await conn.commit()
        return bool(cursor.rowcount)


async def list_due_subscriptions(
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    current_date = today or date.today()
    async with _connection() as conn:
        cursor = await conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE reminder_enabled = 1 AND expiry_date >= ?
            ORDER BY expiry_date ASC, id ASC
            """,
            (current_date.isoformat(),),
        )
        rows = [_normalize_record(row) for row in await cursor.fetchall()]

    due: list[dict[str, Any]] = []
    for row in rows:
        expiry = _date_value(row["expiry_date"], field="expiry_date")
        reminder_date = expiry - timedelta(days=row["reminder_days_before"])
        if reminder_date > current_date:
            continue
        if row["last_reminded_for_expiry"] == row["expiry_date"]:
            continue
        due.append(row)
    return due


async def mark_subscription_reminded(
    subscription_id: int,
    expiry_date: str,
    *,
    reminded_at: str | None = None,
) -> bool:
    timestamp = reminded_at or _now_iso()
    async with _connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE subscriptions
            SET last_reminded_for_expiry = ?, last_reminded_at = ?, updated_at = ?
            WHERE id = ? AND expiry_date = ?
            """,
            (
                str(expiry_date),
                timestamp,
                timestamp,
                int(subscription_id),
                str(expiry_date),
            ),
        )
        await conn.commit()
        return bool(cursor.rowcount)


__all__ = [
    "add_months",
    "create_subscription",
    "delete_subscription",
    "get_subscription",
    "init_subscription_store",
    "list_due_subscriptions",
    "list_subscriptions",
    "mark_subscription_reminded",
    "subscription_database_path",
    "update_subscription",
]
