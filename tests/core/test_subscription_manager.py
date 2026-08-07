from datetime import date

import aiosqlite
import pytest

from core import subscription_reminders, subscription_store


def test_add_months_clamps_to_target_month_end():
    assert subscription_store.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert subscription_store.add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert subscription_store.add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_advance_expiry_date_uses_first_current_or_future_cycle():
    assert subscription_store.advance_expiry_date(
        date(2026, 8, 5),
        1,
        today=date(2026, 8, 7),
    ) == date(2026, 9, 5)
    assert subscription_store.advance_expiry_date(
        date(2026, 8, 7),
        1,
        today=date(2026, 8, 7),
    ) == date(2026, 8, 7)
    assert subscription_store.advance_expiry_date(
        date(2025, 11, 30),
        3,
        today=date(2026, 8, 7),
    ) == date(2026, 8, 30)
    assert subscription_store.advance_expiry_date(
        date(2026, 2, 28),
        1,
        today=date(2026, 3, 1),
        start_date=date(2026, 1, 31),
    ) == date(2026, 3, 31)


@pytest.mark.asyncio
async def test_existing_subscription_database_adds_cost_column(mock_db):
    path = subscription_store.subscription_database_path()
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(
            """
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
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
            """
        )
        await conn.commit()

    await subscription_store.init_subscription_store()

    async with aiosqlite.connect(path) as conn:
        cursor = await conn.execute("PRAGMA table_info(subscriptions)")
        columns = {str(row[1]) for row in await cursor.fetchall()}
    assert "cost" in columns


@pytest.mark.asyncio
async def test_subscription_crud_is_owner_scoped_and_allows_manual_expiry(mock_db):
    created = await subscription_store.create_subscription(
        "web-1",
        {
            "name": "ChatGPT Plus",
            "category": "AI 会员",
            "provider": "OpenAI",
            "cost": "20 USD / 月",
            "start_date": "2026-01-31",
            "cycle_months": 1,
            "reminder_days_before": 3,
            "reminder_enabled": True,
            "delivery_platform": "telegram",
            "delivery_user_id": "tg-1",
        },
    )

    assert created["expiry_date"] == "2026-02-28"
    assert created["cost"] == "20 USD / 月"
    assert await subscription_store.get_subscription("web-2", created["id"]) is None

    updated = await subscription_store.update_subscription(
        "web-1",
        created["id"],
        {"expiry_date": "2026-02-27"},
    )
    assert updated is not None
    assert updated["expiry_date"] == "2026-02-27"

    assert await subscription_store.delete_subscription("web-2", created["id"]) is False
    assert await subscription_store.delete_subscription("web-1", created["id"]) is True


@pytest.mark.asyncio
async def test_cycle_change_recalculates_expiry_unless_explicitly_overridden(mock_db):
    created = await subscription_store.create_subscription(
        "web-1",
        {
            "name": "VPS",
            "start_date": "2026-08-31",
            "cycle_months": 1,
        },
    )

    recalculated = await subscription_store.update_subscription(
        "web-1",
        created["id"],
        {"cycle_months": 6},
    )
    assert recalculated is not None
    assert recalculated["expiry_date"] == "2027-02-28"

    overridden = await subscription_store.update_subscription(
        "web-1",
        created["id"],
        {"cycle_months": 12, "expiry_date": "2027-08-30"},
    )
    assert overridden is not None
    assert overridden["expiry_date"] == "2027-08-30"


@pytest.mark.asyncio
async def test_due_subscription_is_not_selected_twice_after_success(mock_db):
    created = await subscription_store.create_subscription(
        "web-1",
        {
            "name": "视频会员",
            "start_date": "2026-07-06",
            "cycle_months": 1,
            "expiry_date": "2026-08-06",
            "reminder_days_before": 3,
            "delivery_platform": "telegram",
            "delivery_user_id": "tg-1",
        },
    )

    due = await subscription_store.list_due_subscriptions(today=date(2026, 8, 3))
    assert [item["id"] for item in due] == [created["id"]]

    assert await subscription_store.mark_subscription_reminded(
        created["id"],
        created["expiry_date"],
        reminded_at="2026-08-03T09:00:00+08:00",
    )
    assert await subscription_store.list_due_subscriptions(today=date(2026, 8, 3)) == []


@pytest.mark.asyncio
async def test_expired_subscription_rolls_forward_and_resets_reminder(mock_db):
    created = await subscription_store.create_subscription(
        "web-1",
        {
            "name": "ChatGPT Plus",
            "start_date": "2026-07-05",
            "cycle_months": 1,
            "expiry_date": "2026-08-05",
            "reminder_days_before": 3,
            "delivery_platform": "telegram",
            "delivery_user_id": "tg-1",
        },
    )
    assert await subscription_store.mark_subscription_reminded(
        created["id"],
        created["expiry_date"],
        reminded_at="2026-08-02T09:00:00+08:00",
    )

    rows = await subscription_store.list_subscriptions(
        "web-1",
        today=date(2026, 8, 7),
    )

    assert rows[0]["expiry_date"] == "2026-09-05"
    assert rows[0]["last_reminded_for_expiry"] == ""
    assert rows[0]["last_reminded_at"] == ""
    stored = await subscription_store.get_subscription("web-1", created["id"])
    assert stored is not None
    assert stored["expiry_date"] == "2026-09-05"


@pytest.mark.asyncio
async def test_reminder_scan_rolls_forward_before_selecting_due_rows(mock_db):
    created = await subscription_store.create_subscription(
        "web-1",
        {
            "name": "月付会员",
            "start_date": "2026-06-05",
            "cycle_months": 1,
            "expiry_date": "2026-07-05",
            "reminder_days_before": 3,
            "delivery_platform": "telegram",
            "delivery_user_id": "tg-1",
        },
    )

    assert await subscription_store.list_due_subscriptions(
        today=date(2026, 8, 1)
    ) == []
    stored = await subscription_store.get_subscription("web-1", created["id"])
    assert stored is not None
    assert stored["expiry_date"] == "2026-08-05"

    due = await subscription_store.list_due_subscriptions(today=date(2026, 8, 2))
    assert [row["id"] for row in due] == [created["id"]]


@pytest.mark.asyncio
async def test_reminder_scan_uses_bound_user_as_delivery_fallback(monkeypatch):
    subscription = {
        "id": 9,
        "name": "AI 会员",
        "category": "AI 会员",
        "provider": "Example",
        "cycle_months": 3,
        "expiry_date": "2026-08-06",
        "delivery_platform": "telegram",
        "delivery_user_id": "12345",
    }
    sent: list[dict] = []
    marked: list[tuple[int, str]] = []

    async def fake_list_due_subscriptions(*, today):
        assert today == date(2026, 8, 3)
        return [subscription]

    async def fake_resolve_proactive_target(**_kwargs):
        return "", ""

    async def fake_push_background_text(**kwargs):
        sent.append(kwargs)
        return True

    async def fake_mark_subscription_reminded(subscription_id, expiry_date):
        marked.append((subscription_id, expiry_date))
        return True

    monkeypatch.setattr(
        subscription_reminders,
        "list_due_subscriptions",
        fake_list_due_subscriptions,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "resolve_proactive_target",
        fake_resolve_proactive_target,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "push_background_text",
        fake_push_background_text,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "mark_subscription_reminded",
        fake_mark_subscription_reminded,
    )

    result = await subscription_reminders.check_subscription_reminders(
        today=date(2026, 8, 3)
    )

    assert result == {"due": 1, "sent": 1, "skipped": 0, "failed": 0}
    assert sent[0]["platform"] == "telegram"
    assert sent[0]["chat_id"] == "12345"
    assert "还有 3 天到期" in sent[0]["text"]
    assert marked == [(9, "2026-08-06")]


@pytest.mark.asyncio
async def test_failed_delivery_is_left_pending_for_retry(monkeypatch):
    subscription = {
        "id": 10,
        "name": "VPS",
        "category": "VPS / 云服务",
        "provider": "",
        "cycle_months": 12,
        "expiry_date": "2026-08-03",
        "delivery_platform": "telegram",
        "delivery_user_id": "12345",
    }
    marked = False

    async def fake_list_due_subscriptions(*, today):
        return [subscription]

    async def fake_resolve_proactive_target(**_kwargs):
        return "telegram", "12345"

    async def fake_push_background_text(**_kwargs):
        return False

    async def fake_mark_subscription_reminded(*_args, **_kwargs):
        nonlocal marked
        marked = True
        return True

    monkeypatch.setattr(
        subscription_reminders,
        "list_due_subscriptions",
        fake_list_due_subscriptions,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "resolve_proactive_target",
        fake_resolve_proactive_target,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "push_background_text",
        fake_push_background_text,
    )
    monkeypatch.setattr(
        subscription_reminders,
        "mark_subscription_reminded",
        fake_mark_subscription_reminded,
    )

    result = await subscription_reminders.check_subscription_reminders(
        today=date(2026, 8, 3)
    )

    assert result == {"due": 1, "sent": 0, "skipped": 0, "failed": 1}
    assert marked is False
