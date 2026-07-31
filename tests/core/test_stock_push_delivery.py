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
