from types import SimpleNamespace

import pytest

from extension.skills.learned.stock_watch.scripts import execute as stock_execute
from extension.skills.learned.stock_watch.scripts import store as stock_store


class _EditableAdapter:
    can_update_message = True

    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, **kwargs):
        self.sent.append(dict(kwargs))
        return SimpleNamespace(message_id=f"msg-{len(self.sent)}")

    async def edit_text(self, context, message_id, text, **kwargs):
        self.edited.append(
            {
                "message_id": str(message_id),
                "text": text,
                "chat_id": str(context.message.chat.id),
                "kwargs": dict(kwargs),
            }
        )
        return SimpleNamespace(message_id=message_id)


class _NonEditableAdapter:
    can_update_message = False

    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, **kwargs):
        self.sent.append(dict(kwargs))
        return SimpleNamespace(message_id=f"msg-{len(self.sent)}")

    async def edit_text(self, context, message_id, text, **kwargs):
        self.edited.append((message_id, text))
        raise AssertionError("edit should not be used")


@pytest.mark.asyncio
async def test_stock_push_edits_latest_message_when_supported(monkeypatch):
    adapter = _EditableAdapter()
    monkeypatch.setattr(
        "core.platform.registry.adapter_manager.get_adapter",
        lambda platform: adapter,
    )

    await stock_store.clear_last_stock_push_message("user")
    ok, message_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="telegram",
        chat_id="chat-1",
        text="first",
    )
    assert ok is True
    assert message_id == "msg-1"
    assert edited is False
    assert len(adapter.sent) == 1
    assert adapter.edited == []

    ok, message_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="telegram",
        chat_id="chat-1",
        text="second",
    )
    assert ok is True
    assert message_id == "msg-1"
    assert edited is True
    assert len(adapter.sent) == 1
    assert len(adapter.edited) == 1
    assert adapter.edited[0]["text"] == "second"


@pytest.mark.asyncio
async def test_stock_push_sends_new_message_after_chat_activity(monkeypatch):
    adapter = _EditableAdapter()
    monkeypatch.setattr(
        "core.platform.registry.adapter_manager.get_adapter",
        lambda platform: adapter,
    )

    await stock_store.clear_last_stock_push_message("user")
    ok, first_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="telegram",
        chat_id="chat-1",
        text="first",
    )
    assert ok is True
    assert first_id == "msg-1"
    assert edited is False

    await stock_store.mark_stock_push_chat_activity("telegram", "chat-1")
    ok, second_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="telegram",
        chat_id="chat-1",
        text="second",
    )
    assert ok is True
    assert second_id == "msg-2"
    assert edited is False
    assert len(adapter.sent) == 2
    assert adapter.edited == []


@pytest.mark.asyncio
async def test_stock_push_skips_edit_on_unsupported_platform(monkeypatch):
    adapter = _NonEditableAdapter()
    monkeypatch.setattr(
        "core.platform.registry.adapter_manager.get_adapter",
        lambda platform: adapter,
    )

    await stock_store.clear_last_stock_push_message("user")
    ok, first_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="weixin",
        chat_id="chat-1",
        text="first",
    )
    assert ok is True
    assert first_id == "msg-1"
    assert edited is False

    ok, second_id, edited = await stock_execute._deliver_stock_push(
        user_id="user",
        platform="weixin",
        chat_id="chat-1",
        text="second",
    )
    assert ok is True
    assert second_id == "msg-2"
    assert edited is False
    assert len(adapter.sent) == 2
    assert adapter.edited == []


@pytest.mark.asyncio
async def test_manual_stock_check_passes_positions_to_formatter(monkeypatch):
    watchlist = [
        {
            "stock_code": "sh601006",
            "stock_name": "大秦铁路",
            "position_quantity": 100,
            "cost_price": 7.5,
        }
    ]
    quotes = [
        {
            "code": "sh601006",
            "name": "大秦铁路",
            "price": 8.0,
            "change": 0.2,
            "percent": 2.56,
        }
    ]
    captured = {}

    async def fake_get_watchlist(_user_id):
        return watchlist

    async def fake_fetch(_codes):
        return quotes

    def fake_format(stocks, previous_prices=None, positions=None):
        captured["stocks"] = stocks
        captured["previous_prices"] = previous_prices
        captured["positions"] = positions
        return "formatted"

    monkeypatch.setattr(stock_execute, "get_user_watchlist", fake_get_watchlist)
    monkeypatch.setattr(stock_execute, "fetch_stock_quotes", fake_fetch)
    monkeypatch.setattr(stock_execute, "format_stock_message", fake_format)

    result = await stock_execute.trigger_manual_stock_check("user")

    assert result == "formatted"
    assert captured == {
        "stocks": quotes,
        "previous_prices": None,
        "positions": watchlist,
    }


@pytest.mark.asyncio
async def test_scheduled_stock_push_includes_position_profit(monkeypatch):
    watchlist = [
        {
            "stock_code": "sh601006",
            "stock_name": "大秦铁路",
            "position_quantity": 100,
            "cost_price": 7.5,
        }
    ]
    quotes = [
        {
            "code": "sh601006",
            "name": "大秦铁路",
            "price": 8.0,
            "change": 0.2,
            "percent": 2.56,
        }
    ]
    captured = {}

    async def fake_get_users():
        return [("user", "telegram")]

    async def fake_get_watchlist(_user_id):
        return watchlist

    async def fake_fetch(_codes):
        return quotes

    async def fake_previous(_user_id):
        return {"sh601006": 7.9}

    async def fake_delivery_target(_user_id):
        return {"platform": "telegram", "chat_id": "chat-1"}

    def fake_format(stocks, previous_prices=None, positions=None):
        captured["stocks"] = stocks
        captured["previous_prices"] = previous_prices
        captured["positions"] = positions
        return "profit-message"

    async def fake_delivery(**kwargs):
        captured["delivery_text"] = kwargs["text"]
        return True, "msg-1", False

    async def fake_target(*_args, **_kwargs):
        return "telegram", "chat-1"

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(stock_execute, "is_trading_time", lambda: True)
    monkeypatch.setattr(stock_execute, "get_all_watchlist_users", fake_get_users)
    monkeypatch.setattr(stock_execute, "get_user_watchlist", fake_get_watchlist)
    monkeypatch.setattr(stock_execute, "fetch_stock_quotes", fake_fetch)
    monkeypatch.setattr(stock_execute, "get_last_stock_push_prices", fake_previous)
    monkeypatch.setattr(stock_execute, "format_stock_message", fake_format)
    monkeypatch.setattr(
        stock_execute,
        "get_stock_delivery_target",
        fake_delivery_target,
    )
    monkeypatch.setattr(stock_execute, "_deliver_stock_push", fake_delivery)
    monkeypatch.setattr(stock_execute, "save_last_stock_push_prices", noop)
    monkeypatch.setattr("core.scheduler._resolve_proactive_delivery_target", fake_target)
    monkeypatch.setattr("core.scheduler._remember_proactive_delivery_target", noop)
    monkeypatch.setattr("core.background_delivery._record_background_history", noop)

    await stock_execute.stock_push_job()

    assert captured == {
        "stocks": quotes,
        "previous_prices": {"sh601006": 7.9},
        "positions": watchlist,
        "delivery_text": "profit-message",
    }
