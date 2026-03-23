from __future__ import annotations

from types import SimpleNamespace

import pytest

from handlers.weixin_bind_handlers import weixin_bind_command


class _DummyAdapter:
    def __init__(self) -> None:
        self.start_calls: list[str] = []
        self.render_calls: list[str] = []

    async def start_additional_binding(
        self, *, requester_user_id: str
    ) -> dict[str, str]:
        self.start_calls.append(str(requester_user_id))
        return {
            "qrcode_token": "qr-token-1",
            "qr_url": "https://wx.example/qr/abc",
        }

    def render_qr_png(self, data: str) -> bytes:
        self.render_calls.append(str(data))
        return f"png::{data}".encode("utf-8")


class _DummyContext:
    def __init__(self) -> None:
        self.message = SimpleNamespace(
            user=SimpleNamespace(id="admin-user"),
            platform="weixin",
            text="/wxbind qr",
        )
        self._adapter = _DummyAdapter()
        self.reply_calls: list[dict[str, object]] = []
        self.reply_photo_calls: list[dict[str, object]] = []

    async def reply(self, text: str, **kwargs) -> None:
        self.reply_calls.append({"text": text, "kwargs": dict(kwargs)})

    async def reply_photo(self, photo, caption=None, **kwargs) -> None:
        self.reply_photo_calls.append(
            {
                "photo": photo,
                "caption": caption,
                "kwargs": dict(kwargs),
            }
        )


@pytest.mark.asyncio
async def test_wxbind_qr_replies_with_rendered_png(monkeypatch):
    monkeypatch.setattr(
        "handlers.weixin_bind_handlers.is_user_admin",
        lambda user_id: True,
    )
    ctx = _DummyContext()

    await weixin_bind_command(ctx)

    assert ctx._adapter.start_calls == ["admin-user"]
    assert ctx._adapter.render_calls == ["https://wx.example/qr/abc"]
    assert len(ctx.reply_photo_calls) == 1
    assert ctx.reply_photo_calls[0]["photo"] == b"png::https://wx.example/qr/abc"
    assert ctx.reply_photo_calls[0]["kwargs"]["filename"] == "weixin-bind-qr.png"
    assert ctx.reply_calls == []
