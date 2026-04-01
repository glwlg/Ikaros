from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

import core.config as config_module
import core.document_artifacts as document_artifacts
import core.task_manager as task_manager_module
from core.agent_input import (
    InlineInputResolution,
    PreparedAgentInput,
    ReplyMessageResolution,
)
from core.document_artifacts import DocumentArtifact, PENDING_DOCUMENT_ARTIFACTS_KEY
from core.platform.models import MessageType
from handlers import ai_handlers, document_handler
from handlers.media_utils import MediaInput


class _DummyOutgoingMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id
        self.id = message_id

    async def delete(self):
        return True


class _DummyContext:
    def __init__(self, *, message_type: MessageType, text: str = "", caption: str = ""):
        self.message = SimpleNamespace(
            type=message_type,
            text=text,
            caption=caption,
            user=SimpleNamespace(id="u-1"),
            chat=SimpleNamespace(id="c-1", type="private"),
            platform="telegram",
            reply_to_message=None,
            raw_data={},
            id="msg-1",
        )
        self.platform_ctx = SimpleNamespace(user_data={})
        self.user_data = self.platform_ctx.user_data
        self._adapter = SimpleNamespace(can_update_message=True)
        self.replies: list[tuple[object, dict]] = []
        self.edits: list[tuple[object, object, dict]] = []
        self.actions: list[tuple[str, dict]] = []
        self.reactions: list[str] = []

    async def reply(self, payload, **kwargs):
        self.replies.append((payload, dict(kwargs)))
        return _DummyOutgoingMessage(len(self.replies))

    async def edit_message(self, message_id, text, **kwargs):
        self.edits.append((message_id, text, dict(kwargs)))
        return True

    async def send_chat_action(self, action, **kwargs):
        self.actions.append((action, dict(kwargs)))
        return True

    async def set_message_reaction(self, emoji, **kwargs):
        _ = kwargs
        self.reactions.append(str(emoji))
        return True


@pytest.mark.asyncio
async def test_handle_document_with_caption_forwards_txt_artifact_to_ai_chat(
    monkeypatch, tmp_path
):
    captured: dict[str, object] = {}

    async def _allow_user(_user_id):
        return True

    async def _allow_feature(_ctx, _feature):
        return True

    async def _fake_extract_media_input(_ctx, **_kwargs):
        return MediaInput(
            type=MessageType.DOCUMENT,
            file_id="doc-1",
            mime_type="application/octet-stream",
            caption="总结一下",
            file_name="demo.txt",
            file_size=32,
            content="你好，ikaros".encode("utf-8"),
        )

    async def _fake_handle_ai_chat(ctx, user_message_override=None):
        captured["ctx"] = ctx
        captured["user_message_override"] = user_message_override

    monkeypatch.setattr(document_handler, "is_user_allowed", _allow_user)
    monkeypatch.setattr(document_handler, "require_feature_access", _allow_feature)
    monkeypatch.setattr(
        document_handler,
        "extract_media_input",
        _fake_extract_media_input,
    )
    monkeypatch.setattr(
        document_artifacts,
        "DOCUMENT_UPLOAD_ROOT",
        (tmp_path / "documents").resolve(),
    )
    monkeypatch.setattr(ai_handlers, "handle_ai_chat", _fake_handle_ai_chat)

    ctx = _DummyContext(message_type=MessageType.DOCUMENT, caption="总结一下")

    await document_handler.handle_document(ctx)

    assert captured["ctx"] is ctx
    forward_text = str(captured["user_message_override"] or "")
    assert "用户发送了一个文档" in forward_text
    assert "用户要求：总结一下" in forward_text
    assert "文本工件：" in forward_text
    assert PENDING_DOCUMENT_ARTIFACTS_KEY not in ctx.user_data

    match = re.search(r"文本工件：(?P<path>/\S+)", forward_text)
    assert match is not None
    text_path = match.group("path")
    assert text_path.startswith(str(tmp_path.resolve()))
    assert (tmp_path / "documents").exists()
    assert ctx.replies == []
    assert ctx.reactions == []
    assert ctx.user_data == {}
    assert ctx.actions == []
    assert _read_text(text_path) == "你好，ikaros"


@pytest.mark.asyncio
async def test_handle_document_without_caption_stashes_pending_txt_artifact(
    monkeypatch, tmp_path
):
    async def _allow_user(_user_id):
        return True

    async def _allow_feature(_ctx, _feature):
        return True

    async def _fake_extract_media_input(_ctx, **_kwargs):
        return MediaInput(
            type=MessageType.DOCUMENT,
            file_id="doc-2",
            mime_type="text/plain",
            caption="",
            file_name="meeting-notes.txt",
            file_size=48,
            content="会议纪要".encode("utf-8"),
        )

    monkeypatch.setattr(document_handler, "is_user_allowed", _allow_user)
    monkeypatch.setattr(document_handler, "require_feature_access", _allow_feature)
    monkeypatch.setattr(
        document_handler,
        "extract_media_input",
        _fake_extract_media_input,
    )
    monkeypatch.setattr(
        document_artifacts,
        "DOCUMENT_UPLOAD_ROOT",
        (tmp_path / "documents").resolve(),
    )

    ctx = _DummyContext(message_type=MessageType.DOCUMENT)

    await document_handler.handle_document(ctx)

    assert any("已临时保存" in str(payload) for payload, _kwargs in ctx.replies)
    pending = ctx.user_data[PENDING_DOCUMENT_ARTIFACTS_KEY]
    assert len(pending) == 1

    payload = pending[0]
    assert payload["file_name"] == "meeting-notes.txt"
    assert payload["original_path"] == payload["text_path"]
    assert _read_text(payload["text_path"]) == "会议纪要"


@pytest.mark.asyncio
async def test_handle_ai_chat_consumes_pending_document_artifacts(
    monkeypatch, tmp_path
):
    captured: dict[str, object] = {}
    add_message_calls: list[str] = []

    async def _allow_user(_user_id):
        return True

    async def _allow_feature(_ctx, _feature):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_build_agent_message_history(_ctx, **kwargs):
        user_message = str(kwargs.get("user_message") or "")
        captured["user_message"] = user_message
        return PreparedAgentInput(
            message_history=[{"role": "user", "parts": [{"text": user_message}]}],
            user_parts=[{"text": user_message}],
            final_user_message=user_message,
            current_resolution=InlineInputResolution(),
            reply_resolution=ReplyMessageResolution(),
            inline_inputs=[],
            detected_refs=[],
            errors=[],
            truncated_inline_count=0,
            has_inline_inputs=False,
            has_reply_media=False,
            extra_context="",
        )

    async def _fake_handle_message(_ctx, _message_history):
        yield "处理完成"

    async def _fake_add_message(_ctx, _user_id, role, content):
        if role == "user":
            add_message_calls.append(str(content))

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(ai_handlers, "require_feature_access", _allow_feature)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "bind_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _fake_add_message)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    async def _identity_process_code_files(_ctx, text):
        return text

    monkeypatch.setattr(
        ai_handlers,
        "process_and_send_code_files",
        _identity_process_code_files,
    )
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "is_cancelled",
        lambda _user_id: False,
    )
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "unregister_task",
        lambda _user_id: None,
    )
    monkeypatch.setattr(
        "core.agent_input.build_agent_message_history",
        _fake_build_agent_message_history,
    )
    monkeypatch.setattr(
        "core.agent_orchestrator.agent_orchestrator.handle_message",
        _fake_handle_message,
    )

    text_path = (tmp_path / "pending.txt").resolve()
    text_path.write_text("待处理内容", encoding="utf-8")
    artifact = DocumentArtifact(
        file_name="pending.txt",
        mime_type="text/plain",
        doc_type="txt",
        original_path=str(text_path),
        text_path=str(text_path),
    )

    ctx = _DummyContext(message_type=MessageType.TEXT, text="总结一下")
    ctx.user_data[PENDING_DOCUMENT_ARTIFACTS_KEY] = [artifact.to_payload()]

    await ai_handlers.handle_ai_chat(ctx)

    user_message = str(captured["user_message"] or "")
    assert "用户发送了一个文档" in user_message
    assert f"文本工件：{text_path}" in user_message
    assert "用户要求：总结一下" in user_message
    assert add_message_calls == [user_message]
    assert PENDING_DOCUMENT_ARTIFACTS_KEY not in ctx.user_data


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()
