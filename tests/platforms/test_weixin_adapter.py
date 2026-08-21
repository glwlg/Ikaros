from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import json
import logging
from types import SimpleNamespace

import pytest

from core.state_file import parse_state_payload
from core.platform.models import Chat, UnifiedContext, UnifiedMessage, User
from core.platform.models import MessageType
from extension.channels.weixin.adapter import (
    DEFAULT_INBOUND_MERGE_WINDOW_SEC,
    WEIXIN_TYPING_STATUS_CANCEL,
    WEIXIN_TYPING_STATUS_TYPING,
    WeixinAdapter,
)
from extension.channels.weixin.media import UploadedWeixinMedia


def _build_context(
    *,
    user_id: str = "wx-user-1",
    context_token: str = "ctx-1",
    account_id: str = "bot-1",
) -> UnifiedContext:
    message = UnifiedMessage(
        id="msg-1",
        platform="weixin",
        user=User(id=user_id, username=user_id, first_name=user_id),
        chat=Chat(id=user_id, type="private"),
        date=datetime.now(),
        type=MessageType.TEXT,
        text="hello",
        raw_data={
            "from_user_id": user_id,
            "to_user_id": account_id,
            "bot_account_id": account_id,
            "context_token": context_token,
        },
    )
    return UnifiedContext(
        message=message,
        platform_ctx=None,
        platform_event=message.raw_data,
        user=message.user,
    )


def _session(account_id: str) -> dict[str, str]:
    return {
        "token": f"token-{account_id}",
        "baseUrl": "https://ilinkai.weixin.qq.com/",
        "cdnBaseUrl": "https://novac2c.cdn.weixin.qq.com/c2c",
        "accountId": account_id,
    }


@pytest.mark.asyncio
async def test_send_chat_action_typing_fetches_ticket_and_sends_indicator():
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    calls: list[tuple[str, dict]] = []

    async def _fake_api_post(
        endpoint, payload, *, timeout, token=None, session_account_id=""
    ):
        _ = timeout
        _ = token
        assert session_account_id == "bot-1"
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
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    getconfig_calls = 0
    sendtyping_statuses: list[int] = []

    async def _fake_api_post(
        endpoint, payload, *, timeout, token=None, session_account_id=""
    ):
        nonlocal getconfig_calls
        _ = timeout
        _ = token
        assert session_account_id == "bot-1"
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


@pytest.mark.asyncio
async def test_persist_binding_writes_bindings_and_allow_list(tmp_path, monkeypatch):
    monkeypatch.setattr("extension.channels.weixin.adapter.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.ADMIN_USER_IDS", set())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    promoted: list[tuple[str, str, str]] = []

    def _promote_admin(user_id, *, actor="system", reason="ensure_admin_user_id"):
        promoted.append((str(user_id), str(actor), str(reason)))
        current = set(getattr(__import__("core.config", fromlist=["ADMIN_USER_IDS"]), "ADMIN_USER_IDS"))
        current.add(str(user_id))
        monkeypatch.setattr("core.config.ADMIN_USER_IDS", current)
        return sorted(current)

    monkeypatch.setattr(
        "extension.channels.weixin.adapter.ensure_admin_user_id_present",
        _promote_admin,
    )

    adapter = WeixinAdapter()
    result = await adapter._persist_binding(
        {
            "bot_token": "token-1",
            "baseurl": "https://ilinkai.weixin.qq.com/",
            "cdn_baseurl": "https://novac2c.cdn.weixin.qq.com/c2c",
            "ilink_bot_id": "bot-1",
            "ilink_user_id": "wx-user-9",
        },
        source="wxbind_qr",
        bound_by="admin-user",
    )

    bindings = json.loads((tmp_path / "weixin" / "bindings.json").read_text(encoding="utf-8"))
    allow_ok, allow_list = parse_state_payload(
        (tmp_path / "system" / "allowed_users.md").read_text(encoding="utf-8")
    )

    assert result["user_id"] == "wx-user-9"
    assert bindings["sessions"]["bot-1"]["token"] == "token-1"
    assert bindings["bound_users"]["wx-user-9"]["source"] == "wxbind_qr"
    assert bindings["bound_users"]["wx-user-9"]["account_id"] == "bot-1"
    assert allow_ok is True
    assert allow_list[0]["user_id"] == "wx-user-9"
    assert promoted == [("wx-user-9", "admin-user", "weixin_first_bound_user")]


@pytest.mark.asyncio
async def test_persist_binding_keeps_existing_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr("extension.channels.weixin.adapter.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.ADMIN_USER_IDS", set())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    promoted: list[str] = []

    def _promote_admin(user_id, *, actor="system", reason="ensure_admin_user_id"):
        _ = actor
        _ = reason
        promoted.append(str(user_id))
        current = set(getattr(__import__("core.config", fromlist=["ADMIN_USER_IDS"]), "ADMIN_USER_IDS"))
        current.add(str(user_id))
        monkeypatch.setattr("core.config.ADMIN_USER_IDS", current)
        return sorted(current)

    monkeypatch.setattr(
        "extension.channels.weixin.adapter.ensure_admin_user_id_present",
        _promote_admin,
    )

    adapter = WeixinAdapter()
    await adapter._persist_binding(
        {
            "bot_token": "token-1",
            "baseurl": "https://ilinkai.weixin.qq.com/",
            "cdn_baseurl": "https://novac2c.cdn.weixin.qq.com/c2c",
            "ilink_bot_id": "bot-1",
            "ilink_user_id": "wx-user-1",
        },
        source="bootstrap_qr",
        bound_by="wx-user-1",
    )
    await adapter._persist_binding(
        {
            "bot_token": "token-2",
            "baseurl": "https://ilinkai.weixin.qq.com/",
            "cdn_baseurl": "https://novac2c.cdn.weixin.qq.com/c2c",
            "ilink_bot_id": "bot-2",
            "ilink_user_id": "wx-user-2",
        },
        source="wxbind_qr",
        bound_by="admin-user",
    )

    bindings = json.loads(
        (tmp_path / "weixin" / "bindings.json").read_text(encoding="utf-8")
    )

    assert bindings["version"] == 2
    assert bindings["sessions"]["bot-1"]["token"] == "token-1"
    assert bindings["sessions"]["bot-2"]["token"] == "token-2"
    assert bindings["bound_users"]["wx-user-1"]["account_id"] == "bot-1"
    assert bindings["bound_users"]["wx-user-2"]["account_id"] == "bot-2"
    assert promoted == ["wx-user-1"]


def test_render_qr_png_returns_png_bytes():
    payload = WeixinAdapter.render_qr_png("https://example.com/wxbind")

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 100


@pytest.mark.asyncio
async def test_handle_incoming_message_accepts_nonstandard_user_link_message():
    adapter = WeixinAdapter()
    adapter._inbound_merge_window_sec = 0.05
    captured: dict[str, str] = {}

    async def _handler(ctx: UnifiedContext):
        captured["text"] = str(ctx.message.text or "")
        captured["type"] = ctx.message.type.value
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(
        {
            "from_user_id": "wx-user-10",
            "from_user_name": "Alice",
            "to_user_id": "bot-1",
            "message_type": 2,
            "client_id": "msg-link-1",
            "context_token": "ctx-link-1",
            "item_list": [
                {
                    "type": 6,
                    "link_item": {
                        "title": "GitHub",
                        "description": "A collective list of free APIs",
                        "url": "https://github.com/public-apis/public-apis",
                    },
                }
            ],
        }
    )
    await asyncio.sleep(0.12)
    await adapter.stop()

    assert captured["type"] == "text"
    assert "GitHub" in captured["text"]
    assert "https://github.com/public-apis/public-apis" in captured["text"]


@pytest.mark.asyncio
async def test_handle_incoming_message_skips_nonstandard_outbound_echo():
    adapter = WeixinAdapter()
    called = False

    async def _handler(ctx: UnifiedContext):
        nonlocal called
        called = True
        _ = ctx
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(
        {
            "from_user_id": "",
            "to_user_id": "wx-user-10",
            "message_type": 2,
            "client_id": "msg-out-1",
            "item_list": [
                {"type": 1, "text_item": {"text": "bot echo"}}
            ],
        }
    )

    assert called is False


@pytest.mark.asyncio
async def test_handle_incoming_message_skips_nonstandard_bot_self_message():
    adapter = WeixinAdapter()
    adapter._credentials = {"accountId": "bot-1"}
    called = False

    async def _handler(ctx: UnifiedContext):
        nonlocal called
        called = True
        _ = ctx
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(
        {
            "from_user_id": "bot-1",
            "to_user_id": "bot-1",
            "message_type": 2,
            "client_id": "msg-self-1",
            "item_list": [
                {
                    "type": 6,
                    "link_item": {
                        "title": "bot message",
                        "url": "https://example.com",
                    },
                }
            ],
        }
    )

    assert called is False


@pytest.mark.asyncio
async def test_poll_loop_persists_sync_buf_preferentially(monkeypatch):
    adapter = WeixinAdapter()
    saved: list[str] = []

    async def _fake_get_updates(cursor: str, *, account_id: str = ""):
        assert cursor == "cursor-start"
        assert account_id == "bot-1"
        adapter._stop_event.set()
        return {
            "ret": 0,
            "msgs": [],
            "sync_buf": "cursor-next",
            "get_updates_buf": "cursor-legacy",
        }

    monkeypatch.setattr(
        adapter, "_load_sync_cursor_for_account", lambda account_id: "cursor-start"
    )
    monkeypatch.setattr(
        adapter,
        "_save_sync_cursor_for_account",
        lambda account_id, cursor: saved.append(f"{account_id}:{cursor}"),
    )
    monkeypatch.setattr(adapter, "_get_updates", _fake_get_updates)

    await adapter._poll_loop("bot-1")

    assert saved == ["bot-1:cursor-next"]


@pytest.mark.asyncio
async def test_poll_loop_continues_while_inbound_handler_runs(monkeypatch):
    adapter = WeixinAdapter()
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()
    handler_finished = asyncio.Event()
    second_poll_started = asyncio.Event()
    get_updates_calls = 0

    async def _fake_get_updates(cursor: str, *, account_id: str = ""):
        nonlocal get_updates_calls
        _ = cursor
        assert account_id == "bot-1"
        get_updates_calls += 1
        if get_updates_calls == 1:
            return {
                "ret": 0,
                "msgs": [{"client_id": "message-1"}],
                "sync_buf": "cursor-next",
            }
        second_poll_started.set()
        adapter._stop_event.set()
        return {"ret": 0, "msgs": [], "sync_buf": "cursor-final"}

    async def _fake_handle_incoming_message(raw_message):
        assert raw_message["client_id"] == "message-1"
        handler_started.set()
        await release_handler.wait()
        handler_finished.set()

    monkeypatch.setattr(
        adapter, "_load_sync_cursor_for_account", lambda account_id: "cursor-start"
    )
    monkeypatch.setattr(adapter, "_save_sync_cursor_for_account", lambda *_args: None)
    monkeypatch.setattr(adapter, "_get_updates", _fake_get_updates)
    monkeypatch.setattr(
        adapter, "_handle_incoming_message", _fake_handle_incoming_message
    )

    poll_task = asyncio.create_task(adapter._poll_loop("bot-1"))
    try:
        await asyncio.wait_for(handler_started.wait(), timeout=0.5)
        await asyncio.wait_for(second_poll_started.wait(), timeout=0.5)
    finally:
        release_handler.set()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(handler_finished.wait(), timeout=0.5)
        if not poll_task.done():
            adapter._stop_event.set()
            poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poll_task
        await adapter.stop()

    assert get_updates_calls == 2


@pytest.mark.asyncio
async def test_start_spawns_poll_task_per_session(monkeypatch):
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions(
        {
            "bot-1": _session("bot-1"),
            "bot-2": _session("bot-2"),
        }
    )
    started: list[str] = []
    release = asyncio.Event()

    async def _fake_ensure_client():
        return None

    async def _fake_ensure_credentials():
        return None

    async def _fake_poll_loop(account_id: str):
        started.append(account_id)
        await release.wait()

    monkeypatch.setattr(adapter, "_ensure_client", _fake_ensure_client)
    monkeypatch.setattr(adapter, "_ensure_credentials", _fake_ensure_credentials)
    monkeypatch.setattr(adapter, "_poll_loop", _fake_poll_loop)

    await adapter.start()
    await asyncio.sleep(0)

    assert sorted(adapter._poll_tasks) == ["bot-1", "bot-2"]
    assert sorted(started) == ["bot-1", "bot-2"]

    await adapter.stop()


@pytest.mark.asyncio
async def test_send_message_uses_scoped_context_token_and_session_account():
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-2": _session("bot-2")})
    adapter._context_tokens["bot-2::wx-user-1"] = "ctx-2"
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def _fake_api_post(
        endpoint, payload, *, timeout, token=None, session_account_id=""
    ):
        _ = timeout
        _ = token
        calls.append((endpoint, session_account_id, dict(payload)))
        return {"ret": 0}

    adapter._api_post = _fake_api_post  # type: ignore[method-assign]

    await adapter.send_message(
        "wx-user-1",
        "hello",
        session_account_id="bot-2",
    )

    assert len(calls) == 1
    endpoint, session_account_id, payload = calls[0]
    assert endpoint == "ilink/bot/sendmessage"
    assert session_account_id == "bot-2"
    assert payload["msg"]["to_user_id"] == "wx-user-1"
    assert payload["msg"]["context_token"] == "ctx-2"
    assert payload["msg"]["item_list"] == [{"type": 1, "text_item": {"text": "hello"}}]


@pytest.mark.asyncio
async def test_reply_video_sends_mp4_as_video_item(monkeypatch, tmp_path):
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video")
    sent_items: list[dict[str, object]] = []

    async def _fake_upload_media_file(
        *, file_path, user_id, media_kind, account_id=""
    ):
        assert file_path == video_path.resolve()
        assert user_id == "wx-user-1"
        assert media_kind == "video"
        assert account_id == "bot-1"
        return UploadedWeixinMedia(
            filekey="fk-1",
            download_encrypted_query_param="enc-1",
            aes_key_hex="00112233445566778899aabbccddeeff",
            plaintext_size=10,
            ciphertext_size=16,
        )

    async def _fake_send_media_item_to_user(
        *, user_id, context_token, media_item, caption="", account_id=""
    ):
        assert user_id == "wx-user-1"
        assert context_token == "ctx-1"
        assert caption == "请查收"
        assert account_id == "bot-1"
        sent_items.append(media_item)
        return SimpleNamespace(id="media-1")

    monkeypatch.setattr(adapter, "_upload_media_file", _fake_upload_media_file)
    monkeypatch.setattr(adapter, "_send_media_item_to_user", _fake_send_media_item_to_user)

    await adapter.reply_video(_build_context(), str(video_path), caption="请查收")

    assert sent_items
    assert sent_items[0]["type"] == 5
    assert sent_items[0]["video_item"]["video_size"] == 16


@pytest.mark.asyncio
async def test_reply_video_can_fall_back_to_file_attachment(
    monkeypatch, tmp_path
):
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video")
    sent_items: list[dict[str, object]] = []

    monkeypatch.setattr(
        "extension.channels.weixin.adapter.WEIXIN_SEND_VIDEO_AS_FILE", True
    )

    async def _fake_upload_media_file(
        *, file_path, user_id, media_kind, account_id=""
    ):
        assert file_path == video_path.resolve()
        assert user_id == "wx-user-1"
        assert media_kind == "file"
        assert account_id == "bot-1"
        return UploadedWeixinMedia(
            filekey="fk-1",
            download_encrypted_query_param="enc-1",
            aes_key_hex="00112233445566778899aabbccddeeff",
            plaintext_size=10,
            ciphertext_size=16,
        )

    async def _fake_send_media_item_to_user(
        *, user_id, context_token, media_item, caption="", account_id=""
    ):
        assert user_id == "wx-user-1"
        assert context_token == "ctx-1"
        assert caption == "请查收"
        assert account_id == "bot-1"
        sent_items.append(media_item)
        return SimpleNamespace(id="media-1")

    monkeypatch.setattr(adapter, "_upload_media_file", _fake_upload_media_file)
    monkeypatch.setattr(adapter, "_send_media_item_to_user", _fake_send_media_item_to_user)

    await adapter.reply_video(_build_context(), str(video_path), caption="请查收")

    assert sent_items
    assert sent_items[0]["type"] == 4
    assert sent_items[0]["file_item"]["file_name"] == "clip.mp4"


@pytest.mark.asyncio
async def test_send_media_item_sends_caption_after_successful_media(monkeypatch):
    adapter = WeixinAdapter()
    order: list[str] = []

    async def _fake_api_post(endpoint, payload, *, timeout, token=None, session_account_id=""):
        _ = (endpoint, payload, timeout, token, session_account_id)
        order.append("media")
        return {"ret": 0}

    async def _fake_send_text_to_user(user_id, text, context_token, *, account_id=""):
        _ = (user_id, text, context_token, account_id)
        order.append("caption")
        return SimpleNamespace(id="caption-1")

    monkeypatch.setattr(adapter, "_api_post", _fake_api_post)
    monkeypatch.setattr(adapter, "_send_text_to_user", _fake_send_text_to_user)

    await adapter._send_media_item_to_user(
        user_id="wx-user-1",
        context_token="ctx-1",
        media_item={"type": 4, "file_item": {"file_name": "clip.mp4"}},
        caption="请查收",
        account_id="bot-1",
    )

    assert order == ["media", "caption"]


@pytest.mark.asyncio
async def test_send_document_uses_cached_context_token(monkeypatch, tmp_path):
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    adapter._context_tokens["bot-1::wx-user-1"] = "ctx-1"
    doc_path = tmp_path / "report.pdf"
    doc_path.write_bytes(b"pdf")
    sent: list[dict[str, object]] = []

    async def _fake_upload_media_file(*, file_path, user_id, media_kind, account_id=""):
        assert file_path == doc_path.resolve()
        assert user_id == "wx-user-1"
        assert media_kind == "file"
        assert account_id == "bot-1"
        return UploadedWeixinMedia(
            filekey="fk-doc",
            download_encrypted_query_param="enc-doc",
            aes_key_hex="00112233445566778899aabbccddeeff",
            plaintext_size=3,
            ciphertext_size=16,
        )

    async def _fake_send_media_item_to_user(
        *, user_id, context_token, media_item, caption="", account_id=""
    ):
        assert user_id == "wx-user-1"
        assert context_token == "ctx-1"
        assert account_id == "bot-1"
        assert caption == "报告"
        sent.append(media_item)
        return SimpleNamespace(id="media-doc")

    monkeypatch.setattr(adapter, "_upload_media_file", _fake_upload_media_file)
    monkeypatch.setattr(adapter, "_send_media_item_to_user", _fake_send_media_item_to_user)

    await adapter.send_document(
        "wx-user-1",
        str(doc_path),
        filename="report.pdf",
        caption="报告",
        session_account_id="bot-1",
    )

    assert sent[0]["type"] == 4
    assert sent[0]["file_item"]["file_name"] == "report.pdf"


@pytest.mark.asyncio
async def test_reply_audio_uploads_binary_audio_as_file(monkeypatch, tmp_path):
    adapter = WeixinAdapter()
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"audio")
    uploaded_kinds: list[str] = []

    async def _fake_upload_media_file(*, file_path, user_id, media_kind, account_id=""):
        _ = (file_path, user_id, account_id)
        uploaded_kinds.append(media_kind)
        return UploadedWeixinMedia(
            filekey="fk-audio",
            download_encrypted_query_param="enc-audio",
            aes_key_hex="00112233445566778899aabbccddeeff",
            plaintext_size=5,
            ciphertext_size=16,
        )

    async def _fake_send_media_item_to_user(**kwargs):
        assert kwargs["media_item"]["type"] == 4
        assert kwargs["media_item"]["file_item"]["file_name"] == "voice.mp3"
        return SimpleNamespace(id="audio-file")

    monkeypatch.setattr(adapter, "_upload_media_file", _fake_upload_media_file)
    monkeypatch.setattr(adapter, "_send_media_item_to_user", _fake_send_media_item_to_user)

    await adapter.reply_audio(_build_context(), str(audio_path), caption="语音")

    assert uploaded_kinds == ["file"]


def test_log_updates_summary_emits_payload_sample_when_enabled(caplog):
    adapter = WeixinAdapter()
    adapter.debug_updates = True

    with caplog.at_level(logging.INFO):
        adapter._log_updates_summary(
            {
                "msgs": [
                    {
                        "from_user_id": "wx-user-1",
                        "item_list": [{"type": 6}],
                    }
                ],
                "sync_buf": "cursor-next",
                "get_updates_buf": "cursor-legacy",
            }
        )

    assert "Weixin getupdates summary" in caplog.text
    assert "\"from_user_id\": \"wx-user-1\"" in caplog.text


def _image_raw(
    *,
    user_id: str = "wx-user-1",
    account_id: str = "bot-1",
    file_id: str = "enc-image-1",
) -> dict:
    return {
        "from_user_id": user_id,
        "to_user_id": account_id,
        "bot_account_id": account_id,
        "context_token": "ctx-1",
        "message_type": 1,
        "client_id": f"client-{file_id}",
        "item_list": [
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "encrypt_query_param": file_id,
                        "aes_key": "MDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmY=",
                        "encrypt_type": 1,
                    },
                    "mid_size": 16,
                },
            }
        ],
    }


def _text_raw(
    *,
    text: str,
    user_id: str = "wx-user-1",
    account_id: str = "bot-1",
    client_id: str = "client-text",
) -> dict:
    return {
        "from_user_id": user_id,
        "to_user_id": account_id,
        "bot_account_id": account_id,
        "context_token": "ctx-1",
        "message_type": 1,
        "client_id": client_id,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


@pytest.mark.asyncio
async def test_inbound_merge_combines_text_and_image_into_one_dispatch():
    adapter = WeixinAdapter()
    adapter._inbound_merge_window_sec = 0.05
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    dispatched: list[UnifiedContext] = []

    async def _handler(ctx: UnifiedContext):
        dispatched.append(ctx)
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(_text_raw(text="这个手机怎么样"))
    await adapter._handle_incoming_message(_image_raw())
    await asyncio.sleep(0.12)
    await adapter.stop()

    assert len(dispatched) == 1
    message = dispatched[0].message
    assert message.type == MessageType.IMAGE
    assert message.caption == "这个手机怎么样"
    assert message.file_id == "enc-image-1"


@pytest.mark.asyncio
async def test_inbound_merge_image_then_text_sets_caption():
    adapter = WeixinAdapter()
    adapter._inbound_merge_window_sec = 0.05
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    dispatched: list[UnifiedContext] = []

    async def _handler(ctx: UnifiedContext):
        dispatched.append(ctx)
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(_image_raw())
    await adapter._handle_incoming_message(_text_raw(text="值不值得买"))
    await asyncio.sleep(0.12)
    await adapter.stop()

    assert len(dispatched) == 1
    assert dispatched[0].message.type == MessageType.IMAGE
    assert dispatched[0].message.caption == "值不值得买"


@pytest.mark.asyncio
async def test_inbound_merge_disabled_dispatches_immediately():
    adapter = WeixinAdapter()
    adapter._inbound_merge_window_sec = 0.0
    adapter._apply_runtime_sessions({"bot-1": _session("bot-1")})
    dispatched: list[str] = []

    async def _handler(ctx: UnifiedContext):
        dispatched.append(ctx.message.type.value)
        return None

    adapter.register_message_handler(_handler)

    await adapter._handle_incoming_message(_text_raw(text="hello"))
    await adapter._handle_incoming_message(_image_raw())

    assert dispatched == ["text", "image"]
    await adapter.stop()


def test_inbound_merge_default_is_disabled():
    assert DEFAULT_INBOUND_MERGE_WINDOW_SEC == 0.0
