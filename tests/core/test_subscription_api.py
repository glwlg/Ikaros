from types import SimpleNamespace

import pytest

from api.api.endpoints import subscriptions as endpoint


@pytest.mark.asyncio
async def test_create_subscription_uses_current_users_default_binding(monkeypatch):
    captured = {}

    async def fake_user_bindings(user_id, session):
        assert user_id == 42
        assert session == "session"
        return {"weixin": "wx-42", "telegram": "tg-42"}

    async def fake_create_subscription(owner_user_id, payload):
        captured.update(payload)
        return {
            "id": 1,
            "owner_user_id": str(owner_user_id),
            **payload,
            "last_reminded_for_expiry": "",
            "last_reminded_at": "",
            "created_at": "2026-08-03T09:00:00+08:00",
            "updated_at": "2026-08-03T09:00:00+08:00",
        }

    monkeypatch.setattr(endpoint, "_user_bindings", fake_user_bindings)
    monkeypatch.setattr(
        endpoint.subscription_store,
        "create_subscription",
        fake_create_subscription,
    )

    result = await endpoint.create_subscription(
        endpoint.SubscriptionCreate(
            name="ChatGPT Plus",
            category="AI 会员",
            cost="20 USD / 月",
            start_date="2026-08-03",
            cycle_months=1,
            expiry_date="2026-09-03",
        ),
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert captured["delivery_platform"] == "telegram"
    assert captured["delivery_user_id"] == "tg-42"
    assert captured["cost"] == "20 USD / 月"
    assert result["delivery_configured"] is True
    assert "owner_user_id" not in result
    assert "delivery_user_id" not in result


@pytest.mark.asyncio
async def test_list_subscriptions_uses_authenticated_owner(monkeypatch):
    async def fake_list_subscriptions(owner_user_id):
        assert owner_user_id == 7
        return []

    monkeypatch.setattr(
        endpoint.subscription_store,
        "list_subscriptions",
        fake_list_subscriptions,
    )

    result = await endpoint.get_subscriptions(current_user=SimpleNamespace(id=7))

    assert result == []
