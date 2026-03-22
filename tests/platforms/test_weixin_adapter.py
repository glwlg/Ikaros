from __future__ import annotations

from datetime import datetime

import pytest

from core.platform.models import Chat, UnifiedContext, UnifiedMessage, User
from core.platform.models import MessageType
from platforms.weixin.adapter import (
    WEIXIN_TYPING_STATUS_CANCEL,
    WEIXIN_TYPING_STATUS_TYPING,
    WeixinAdapter,
)


def _build_context(
    *,
    user_id: str = "wx-user-1",
    context_token: str = "ctx-1",
) -> UnifiedContext:
    message = UnifiedMessage(
        id="msg-1",
        platform="weixin",
        user=User(id=user_id, username=user_id, first_name=user_id),
        chat=Chat(id=user_id, type="private"),
        date=datetime.now(),
        type=MessageType.TEXT,
        text="hello",
        raw_data={"from_user_id": user_id, "context_token": context_token},
    )
    return UnifiedContext(
        message=message,
        platform_ctx=None,
        platform_event=message.raw_data,
        user=message.user,
    )


@pytest.mark.asyncio
async def test_send_chat_action_typing_fetches_ticket_and_sends_indicator():
    adapter = WeixinAdapter()
    calls: list[tuple[str, dict]] = []

    async def _fake_api_post(endpoint, payload, *, timeout, token=None):
        _ = timeout
        _ = token
        calls.append((endpoint, dict(payload)))
        if endpoint == "ilink/bot/getconfig":
            return {"ret": 0, "typing_ticket": "ticket-1"}
        if endpoint == "ilink/bot/sendtyping":
            return {"ret": 0}
        raise AssertionError(endpoint)

    adapter._api_post = _fake_api_post  # type: ignore[method-assign]

    await adapter.send_chat_action(_build_context(), "typing")
    await adapter.stop()

    assert calls[0][0] == "ilink/bot/getconfig"
    assert calls[0][1]["ilink_user_id"] == "wx-user-1"
    assert calls[1][0] == "ilink/bot/sendtyping"
    assert calls[1][1]["typing_ticket"] == "ticket-1"
    assert calls[1][1]["status"] == WEIXIN_TYPING_STATUS_TYPING


@pytest.mark.asyncio
async def test_send_chat_action_reuses_cached_typing_ticket_and_can_cancel():
    adapter = WeixinAdapter()
    getconfig_calls = 0
    sendtyping_statuses: list[int] = []

    async def _fake_api_post(endpoint, payload, *, timeout, token=None):
        nonlocal getconfig_calls
        _ = timeout
        _ = token
        if endpoint == "ilink/bot/getconfig":
            getconfig_calls += 1
            return {"ret": 0, "typing_ticket": "ticket-1"}
        if endpoint == "ilink/bot/sendtyping":
            sendtyping_statuses.append(int(payload["status"]))
            return {"ret": 0}
        raise AssertionError(endpoint)

    adapter._api_post = _fake_api_post  # type: ignore[method-assign]
    ctx = _build_context()

    await adapter.send_chat_action(ctx, "typing")
    await adapter.send_chat_action(ctx, "cancel_typing")
    await adapter.stop()

    assert getconfig_calls == 1
    assert sendtyping_statuses == [
        WEIXIN_TYPING_STATUS_TYPING,
        WEIXIN_TYPING_STATUS_CANCEL,
    ]
