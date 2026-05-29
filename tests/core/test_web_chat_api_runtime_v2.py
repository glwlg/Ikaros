from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.api.endpoints import web_chat
from api.auth.models import User, UserRole
from core import background_delivery as background_delivery_module
from core import runtime_delivery as runtime_delivery_module
from core.reply_hooks import text_reply_hook_registry
from core.runtime_v2 import RuntimeEventBus, RuntimeV2Store
from core.state_paths import SINGLE_USER_SCOPE
from extension.channels.web import adapter as web_adapter_module
from extension.channels.web.adapter import WebAdapter
from handlers import ai_handlers
from shared.queue.jsonl_queue import JsonlTable
from web_channel import store as web_store


@pytest.fixture
def web_chat_api_runtime(tmp_path, monkeypatch):
    runtime_store = RuntimeV2Store(db_path=tmp_path / "runtime.db")
    event_bus = RuntimeEventBus(runtime_store)
    root = tmp_path / "web_channel"
    paths = {
        "WEB_CHANNEL_ROOT": root,
        "WEB_CHANNEL_INBOX_DIR": root / "inbox",
        "WEB_CHANNEL_OUTBOX_DIR": root / "outbox",
        "WEB_CHANNEL_UPLOADS_DIR": root / "uploads",
        "WEB_CHANNEL_ARTIFACTS_DIR": root / "artifacts",
        "WEB_CHANNEL_FILES_DIR": root / "files",
        "WEB_CHANNEL_SESSIONS_DIR": root / "sessions",
    }
    for value in paths.values():
        Path(value).mkdir(parents=True, exist_ok=True)
    for name, value in paths.items():
        monkeypatch.setattr(web_store, name, value)
    monkeypatch.setattr(
        web_store,
        "WEB_CHANNEL_INBOX_TABLE",
        JsonlTable(str((paths["WEB_CHANNEL_INBOX_DIR"] / "events.jsonl").resolve())),
    )
    monkeypatch.setattr(web_store, "runtime_v2", runtime_store)
    monkeypatch.setattr(web_chat, "runtime_v2", runtime_store)
    monkeypatch.setattr(web_chat, "runtime_event_bus", event_bus)
    monkeypatch.setattr(ai_handlers, "runtime_v2", runtime_store)
    monkeypatch.setattr(web_adapter_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(web_adapter_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(runtime_delivery_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(runtime_delivery_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(background_delivery_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(background_delivery_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(background_delivery_module, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(text_reply_hook_registry, "_after_reply", [])

    async def _platform_user_ids(_user_id, _session, _platform):
        return []

    async def _fake_session():
        yield SimpleNamespace()

    async def _viewer():
        return User(
            id=50101,
            email="runtime-v2@example.test",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            role=UserRole.ADMIN,
            username="runtime-v2",
            display_name="Runtime v2 Tester",
        )

    monkeypatch.setattr(web_chat, "get_platform_user_ids", _platform_user_ids)
    app = FastAPI()
    app.include_router(web_chat.router, prefix="/api/v1/web-chat")
    app.dependency_overrides[web_chat.require_viewer] = _viewer
    app.dependency_overrides[web_chat.get_async_session] = _fake_session
    return app, runtime_store


def test_web_chat_api_message_event_creates_runtime_v2_turn_and_event(
    web_chat_api_runtime,
):
    app, runtime_store = web_chat_api_runtime

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 API", "preferences": {"tone": "test"}},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={
                "type": "message_text",
                "text": "用 Web API 走一轮 Runtime v2 会话",
                "metadata": {"case": "rv2-web-api"},
            },
        )
        assert posted.status_code == 200
        payload = posted.json()
        assert payload["runtime"]["session_id"] == session_id
        assert payload["runtime"]["turn_id"]

        turns = runtime_store.list_turns(session_id)
        assert len(turns) == 1
        assert turns[0]["source"] == "user"
        assert turns[0]["status"] == "queued"
        assert turns[0]["input_text"] == "用 Web API 走一轮 Runtime v2 会话"
        assert turns[0]["metadata"]["web_inbound_event_id"] == payload["queued"]["id"]

        events = runtime_store.list_events(session_id=session_id)
        assert [item["type"] for item in events] == ["user_message"]
        assert events[0]["turn_id"] == turns[0]["id"]
        assert events[0]["payload"]["metadata"] == {"case": "rv2-web-api"}

        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        assert inbound[0]["payload"]["runtime_v2_session_id"] == session_id
        assert inbound[0]["payload"]["runtime_v2_turn_id"] == turns[0]["id"]
        adapter = WebAdapter()
        ctx = asyncio.run(adapter._build_context(inbound[0]))
        assert ctx.user_data["runtime_v2_session_id"] == session_id
        assert ctx.user_data["runtime_v2_turn_id"] == turns[0]["id"]
        asyncio.run(adapter.reply_text(ctx, "Runtime v2 WebAdapter 回复"))
        asyncio.run(adapter.reply_video(ctx, b"fake video", caption="Runtime v2 视频"))

        events = runtime_store.list_events(session_id=session_id)
        event_types = [item["type"] for item in events]
        assert event_types == [
            "user_message",
            "assistant_message_final",
            "artifact_created",
            "assistant_message_final",
            "artifact_delivered",
        ]
        assert events[1]["payload"]["text"] == "Runtime v2 WebAdapter 回复"
        assert events[2]["payload"]["kind"] == "video"
        assert events[4]["payload"]["platform"] == "web"

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert [item["role"] for item in messages] == [
            "user",
            "assistant",
            "assistant",
        ], messages
        assert messages[0]["content"] == "用 Web API 走一轮 Runtime v2 会话"
        assert messages[1]["content"] == "Runtime v2 WebAdapter 回复"
        assert messages[2]["attachments"][0]["kind"] == "video"

        sessions = client.get("/api/v1/web-chat/sessions").json()["items"]
        by_id = {item["id"]: item for item in sessions}
        assert by_id[session_id]["preferences"]["source"] in {
            "runtime_v2",
            "web_channel",
        }


def test_web_chat_api_lists_runtime_v2_scheduled_session(web_chat_api_runtime):
    app, runtime_store = web_chat_api_runtime
    session = runtime_store.ensure_session(
        session_id="scheduler-task-api-ledger",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id=SINGLE_USER_SCOPE,
        title="Runtime v2 定时任务",
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="生成今日 AI 快讯",
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="scheduler_triggered",
        payload={"instruction": "生成今日 AI 快讯"},
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "今日 AI 快讯已完成"},
    )

    with TestClient(app) as client:
        sessions = client.get("/api/v1/web-chat/sessions").json()["items"]
        by_id = {item["id"]: item for item in sessions}
        scheduled = by_id["scheduler-task-api-ledger"]
        assert scheduled["preferences"]["source"] == "runtime_v2"
        assert scheduled["preferences"]["kind"] == "scheduled_task"
        assert scheduled["message_count"] == 2
        assert scheduled["preview"] == "今日 AI 快讯已完成"

        messages = client.get(
            "/api/v1/web-chat/sessions/scheduler-task-api-ledger/messages"
        ).json()["items"]
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert [item["content"] for item in messages] == [
            "生成今日 AI 快讯",
            "今日 AI 快讯已完成",
        ]


def test_web_chat_api_rejects_unowned_runtime_v2_session(web_chat_api_runtime):
    app, runtime_store = web_chat_api_runtime
    session = runtime_store.ensure_session(
        session_id="scheduler-task-private-api",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="other-platform-user",
        title="别人的定时任务",
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="私有输入",
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "私有输出"},
    )

    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/web-chat/sessions/scheduler-task-private-api/messages"
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/web-chat/sessions/scheduler-task-private-api/trace"
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/web-chat/sessions/scheduler-task-private-api/deliveries"
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/web-chat/sessions/scheduler-task-private-api/events",
                json={"type": "message_text", "text": "篡改"},
            ).status_code
            == 404
        )

    assert (
        runtime_store.get_session("scheduler-task-private-api")["platform_user_id"]
        == "other-platform-user"
    )


def test_web_chat_api_stream_reads_runtime_v2_events(web_chat_api_runtime):
    app, runtime_store = web_chat_api_runtime

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 stream"},
        )
        session_id = created.json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "流式事件测试"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]
        runtime_store.append_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type="text_delta",
            payload={"text": "第一段真实流式内容"},
        )
        runtime_store.append_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type="message_update",
            payload={"text": "第一段真实流式内容，继续补充"},
        )

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: user_message" in body
    assert "event: text_delta" in body
    assert "第一段真实流式内容" in body
    assert "event: message_update" in body
    assert '"runtime_v2": true' in body
    assert turn_id in body


@pytest.mark.asyncio
async def test_web_chat_stream_switches_to_runtime_v2_after_session_is_created(
    web_chat_api_runtime,
    monkeypatch,
):
    _app, runtime_store = web_chat_api_runtime

    async def _no_sleep(_seconds):
        return None

    class _Request:
        async def is_disconnected(self):
            return False

    monkeypatch.setattr(web_chat.asyncio, "sleep", _no_sleep)
    user = User(
        id=50101,
        email="runtime-v2@example.test",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        role=UserRole.ADMIN,
        username="runtime-v2",
        display_name="Runtime v2 Tester",
    )
    response = await web_chat.session_stream(
        "late-runtime-session",
        _Request(),
        after=0,
        once=False,
        user=user,
        session=SimpleNamespace(),
    )
    iterator = response.body_iterator
    assert await anext(iterator) == ": keep-alive\n\n"

    session = runtime_store.ensure_session(
        session_id="late-runtime-session",
        kind="web_workspace",
        platform="web",
        platform_user_id=str(user.id),
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        source="user",
        input_text="late stream",
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "late runtime output"},
    )

    streamed = await anext(iterator)
    assert "event: assistant_message_final" in streamed
    assert "late runtime output" in streamed


def test_web_chat_api_context_delivers_artifact_through_runtime_delivery(
    web_chat_api_runtime,
    tmp_path,
):
    app, runtime_store = web_chat_api_runtime
    video_path = tmp_path / "rv2-video.mp4"
    video_path.write_bytes(b"fake video")

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 delivery"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "请发一个视频附件"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))
        result = asyncio.run(
            runtime_delivery_module.deliver_result_files(
                ctx=ctx,
                file_rows=[
                    {
                        "kind": "video",
                        "path": str(video_path),
                        "filename": "rv2-video.mp4",
                        "caption": "Runtime v2 delivery",
                    }
                ],
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
            )
        )

        assert [item["filename"] for item in result.delivered_rows] == [
            "rv2-video.mp4"
        ]
        deliveries = runtime_store.list_deliveries(session_id=session_id)
        assert [(item["platform"], item["status"]) for item in deliveries] == [
            ("web", "delivered")
        ]
        assert deliveries[0]["target"].startswith("web:")
        events = runtime_store.list_events(session_id=session_id)
        assert [item["type"] for item in events] == [
            "user_message",
            "artifact_created",
            "artifact_delivered",
        ]
        assert events[1]["payload"]["filename"] == "rv2-video.mp4"

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert messages[-1]["attachments"][0]["kind"] == "video"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: artifact_delivered" in body
    assert "event: artifact_created" in body
    assert "rv2-video.mp4" in body


def test_web_chat_api_serves_owned_runtime_v2_artifact_file(
    web_chat_api_runtime,
    tmp_path,
):
    app, runtime_store = web_chat_api_runtime
    document_path = tmp_path / "runtime-artifact.txt"
    document_path.write_text("runtime artifact body", encoding="utf-8")
    session = runtime_store.ensure_session(
        session_id="scheduler-task-artifact-download",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id=SINGLE_USER_SCOPE,
        title="Runtime artifact download",
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="生成文件",
    )
    artifact = runtime_store.record_artifact(
        session_id=session["id"],
        turn_id=turn["id"],
        kind="document",
        path=str(document_path),
        source="test",
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="artifact_created",
        payload={
            "artifact_id": artifact["id"],
            "kind": "document",
            "filename": artifact["filename"],
            "path": artifact["path"],
            "mime": artifact["mime"],
        },
    )

    with TestClient(app) as client:
        messages = client.get(
            "/api/v1/web-chat/sessions/scheduler-task-artifact-download/messages"
        ).json()["items"]
        file_id = messages[-1]["attachments"][0]["file_id"]
        response = client.get(f"/api/v1/web-chat/files/{file_id}")

    assert response.status_code == 200
    assert response.content == b"runtime artifact body"
    assert response.headers["content-type"].startswith("text/plain")


def test_web_chat_api_runtime_trace_includes_turn_events_artifacts_and_deliveries(
    web_chat_api_runtime,
    tmp_path,
):
    app, runtime_store = web_chat_api_runtime
    document_path = tmp_path / "trace-report.txt"
    document_path.write_text("trace report", encoding="utf-8")

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 trace"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "请生成 trace"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))
        asyncio.run(
            runtime_delivery_module.deliver_result_files(
                ctx=ctx,
                file_rows=[
                    {
                        "kind": "document",
                        "path": str(document_path),
                        "filename": "trace-report.txt",
                    }
                ],
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
            )
        )
        runtime_store.update_turn_status(turn_id, "running")
        runtime_store.update_turn_status(turn_id, "succeeded")
        runtime_store.upsert_kernel_session(
            session_id=session_id,
            provider="codex",
            external_thread_id="thread-trace-api",
            external_turn_id="turn-trace-api",
        )
        runtime_store.create_task(
            session_id=session_id,
            turn_id=turn_id,
            goal="trace task",
            status="succeeded",
        )

        response = client.get(f"/api/v1/web-chat/sessions/{session_id}/trace")

    assert response.status_code == 200
    trace = response.json()["runtime"]
    assert trace["session"]["id"] == session_id
    assert trace["kernel_sessions"][0]["external_thread_id"] == "thread-trace-api"
    assert trace["turns"][0]["id"] == turn_id
    assert trace["turns"][0]["status"] == "succeeded"
    assert [event["type"] for event in trace["events"]] == [
        "user_message",
        "artifact_created",
        "artifact_delivered",
    ]
    assert trace["artifacts"][0]["filename"] == "trace-report.txt"
    assert trace["deliveries"][0]["artifact_filename"] == "trace-report.txt"
    assert trace["tasks"][0]["goal"] == "trace task"


def test_web_chat_api_exposes_failed_artifact_delivery_receipts(
    web_chat_api_runtime,
    tmp_path,
):
    app, runtime_store = web_chat_api_runtime
    missing_path = tmp_path / "missing-video.mp4"

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 failed delivery"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "请发一个不存在的视频附件"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))
        result = asyncio.run(
            runtime_delivery_module.deliver_result_files(
                ctx=ctx,
                file_rows=[
                    {
                        "kind": "video",
                        "path": str(missing_path),
                        "filename": "missing-video.mp4",
                    }
                ],
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
                warn_on_failed=False,
            )
        )

        assert result.delivered_rows == []
        assert [item["filename"] for item in result.failed_rows] == [
            "missing-video.mp4"
        ]
        deliveries = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/deliveries"
        ).json()["items"]
        assert [
            (
                item["platform"],
                item["status"],
                item["error"],
                item["artifact_filename"],
            )
            for item in deliveries
        ] == [
            ("web", "failed", "artifact file missing", "missing-video.mp4")
        ]

        events = runtime_store.list_events(session_id=session_id)
        assert [event["type"] for event in events] == [
            "user_message",
            "artifact_created",
            "delivery_failed",
        ]
        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert messages[-1]["content"].startswith("附件发送失败：missing-video.mp4")
        assert messages[-1]["meta"]["event_type"] == "delivery_failed"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: delivery_failed" in body
    assert "artifact file missing" in body


def test_web_chat_api_background_document_delivery_records_runtime_artifact(
    web_chat_api_runtime,
    monkeypatch,
):
    app, runtime_store = web_chat_api_runtime
    sent_documents: list[dict] = []
    sent_messages: list[dict] = []

    class _FakeAdapter:
        async def send_document(self, **kwargs):
            sent_documents.append(dict(kwargs))
            return SimpleNamespace(id="doc-bg")

        async def send_message(self, **kwargs):
            sent_messages.append(dict(kwargs))
            return SimpleNamespace(id="msg-bg")

    monkeypatch.setenv("BACKGROUND_PUSH_FILE_ENABLED", "true")
    monkeypatch.setenv("BACKGROUND_PUSH_FILE_THRESHOLD", "32")
    monkeypatch.setenv("BACKGROUND_PUSH_MAX_TEXT_CHUNKS", "1")

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 background delivery"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "生成一份定时任务报告"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        ok = asyncio.run(
            background_delivery_module.push_background_text(
                platform="web",
                chat_id="session-bg",
                text="定时任务报告正文" * 40,
                adapter=_FakeAdapter(),
                filename_prefix="scheduler",
                ui={
                    "actions": [
                        [
                            {
                                "text": "进入会话",
                                "callback_data": "schsess_enter_9",
                            }
                        ]
                    ]
                },
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
                runtime_source="scheduler_report",
            )
        )

        assert ok is True
        assert sent_documents
        assert sent_documents[0]["filename"].startswith("scheduler-")
        assert sent_messages[-1]["ui"]["actions"][0][0]["callback_data"] == (
            "schsess_enter_9"
        )

        events = runtime_store.list_events(session_id=session_id)
        assert [event["type"] for event in events] == [
            "user_message",
            "artifact_created",
            "artifact_delivered",
            "background_message_sent",
        ]
        artifact_path = Path(events[1]["payload"]["path"])
        assert artifact_path.exists()
        assert events[1]["payload"]["source"] == "scheduler_report"
        assert events[2]["payload"]["target"] == "web:session-bg"
        assert events[3]["payload"]["message_id"] == "msg-bg"

        deliveries = runtime_store.list_deliveries(session_id=session_id)
        assert [(item["platform"], item["target"], item["status"]) for item in deliveries] == [
            ("web", "web:session-bg", "delivered")
        ]

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert [item["role"] for item in messages] == [
            "user",
            "assistant",
            "assistant",
        ]
        assert messages[1]["attachments"][0]["kind"] == "document"
        assert messages[1]["attachments"][0]["name"].startswith("scheduler-")
        assert messages[2]["content"] == "可继续进入对应会话处理。"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: artifact_created" in body
    assert "event: artifact_delivered" in body
    assert "event: background_message_sent" in body
    assert "scheduler_report" in body


def test_web_chat_api_scheduler_cron_turn_succeeds_and_is_visible(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.scheduler as scheduler_module
    import core.state_store as state_store_module
    from core.agent_orchestrator import agent_orchestrator

    app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)

    async def _fake_build_history(ctx, *, user_message, **_kwargs):
        assert ctx.user_data["current_session_id"] == "scheduler-task-job-web"
        assert "目标任务描述：生成报告" in user_message
        return SimpleNamespace(
            message_history=[{"role": "user", "parts": [{"text": user_message}]}],
            detected_refs=[],
            has_inline_inputs=False,
            truncated_inline_count=0,
            errors=[],
        )

    async def _fake_handle_message(ctx, _message_history):
        assert ctx.user_data["runtime_v2_session_id"] == "scheduler-task-job-web"
        assert ctx.user_data["runtime_v2_turn_id"]
        yield "调度完成"

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scheduler_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(scheduler_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(state_store_module, "create_chat_session", _noop)
    monkeypatch.setattr(state_store_module, "save_message", _noop)

    asyncio.run(
        scheduler_module.run_skill_cron_job(
            "生成报告",
            user_id=SINGLE_USER_SCOPE,
            platform="web",
            need_push=False,
            scheduled_task_id="job-web",
        )
    )

    turns = runtime_store.list_turns("scheduler-task-job-web")
    assert [turn["status"] for turn in turns] == ["succeeded"]
    assert turns[0]["metadata"]["scheduled_task_id"] == "job-web"
    events = runtime_store.list_events(session_id="scheduler-task-job-web")
    assert [event["type"] for event in events] == [
        "scheduler_triggered",
        "assistant_message_final",
    ]

    with TestClient(app) as client:
        sessions = client.get("/api/v1/web-chat/sessions").json()["items"]
        by_id = {item["id"]: item for item in sessions}
        assert by_id["scheduler-task-job-web"]["preferences"]["kind"] == (
            "scheduled_task"
        )
        messages = client.get(
            "/api/v1/web-chat/sessions/scheduler-task-job-web/messages"
        ).json()["items"]

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "生成报告"
    assert messages[1]["content"] == "调度完成"


def test_scheduler_cron_preserves_kernel_terminal_runtime_turn(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.scheduler as scheduler_module
    import core.state_store as state_store_module
    from core.agent_orchestrator import agent_orchestrator

    _app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)

    async def _fake_build_history(ctx, *, user_message, **_kwargs):
        return SimpleNamespace(
            message_history=[{"role": "user", "parts": [{"text": user_message}]}],
            detected_refs=[],
            has_inline_inputs=False,
            truncated_inline_count=0,
            errors=[],
        )

    async def _fake_handle_message(ctx, _message_history):
        turn_id = ctx.user_data["runtime_v2_turn_id"]
        runtime_store.update_turn_status(
            turn_id,
            "succeeded",
            metadata={"closed_by": "fake_kernel"},
        )
        yield "kernel 已完成"

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scheduler_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(scheduler_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(state_store_module, "create_chat_session", _noop)
    monkeypatch.setattr(state_store_module, "save_message", _noop)

    asyncio.run(
        scheduler_module.run_skill_cron_job(
            "生成报告",
            user_id=SINGLE_USER_SCOPE,
            platform="web",
            need_push=False,
            scheduled_task_id="job-terminal",
        )
    )

    turn = runtime_store.list_turns("scheduler-task-job-terminal")[0]
    assert turn["status"] == "succeeded"
    assert turn["metadata"]["closed_by"] == "fake_kernel"


def test_scheduler_cron_preserves_kernel_waiting_runtime_turn(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.scheduler as scheduler_module
    import core.state_store as state_store_module
    from core.agent_orchestrator import agent_orchestrator

    _app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)

    async def _fake_build_history(ctx, *, user_message, **_kwargs):
        return SimpleNamespace(
            message_history=[{"role": "user", "parts": [{"text": user_message}]}],
            detected_refs=[],
            has_inline_inputs=False,
            truncated_inline_count=0,
            errors=[],
        )

    async def _fake_handle_message(ctx, _message_history):
        turn_id = ctx.user_data["runtime_v2_turn_id"]
        runtime_store.update_turn_status(
            turn_id,
            "waiting_user",
            metadata={"waiting_user_prompt": "需要人工确认"},
        )
        yield "需要人工确认"

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scheduler_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(scheduler_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(state_store_module, "create_chat_session", _noop)
    monkeypatch.setattr(state_store_module, "save_message", _noop)

    asyncio.run(
        scheduler_module.run_skill_cron_job(
            "生成报告",
            user_id=SINGLE_USER_SCOPE,
            platform="web",
            need_push=False,
            scheduled_task_id="job-waiting",
        )
    )

    turn = runtime_store.list_turns("scheduler-task-job-waiting")[0]
    assert turn["status"] == "waiting_user"
    assert turn["metadata"]["waiting_user_prompt"] == "需要人工确认"


def test_web_chat_api_context_delivers_final_text_through_runtime_delivery(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator

    app, runtime_store = web_chat_api_runtime

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

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_build_history(_ctx, *, user_message, **_kwargs):
        return SimpleNamespace(
            current_resolution=None,
            reply_resolution=None,
            inline_inputs=[],
            truncated_inline_count=0,
            errors=[],
            detected_refs=[],
            has_inline_inputs=False,
            has_reply_media=False,
            final_user_message=user_message,
            user_parts=[{"text": user_message}],
        )

    async def _fake_handle_message(_ctx, _message_history):
        yield "这是 Runtime v2 final 文本"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(ai_handlers, "require_feature_access", _allow_feature)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "bind_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers,
        "process_and_send_code_files",
        _identity_process_code_files,
    )
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "is_cancelled",
        lambda _uid: False,
    )
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "unregister_task",
        lambda _uid: None,
    )

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 final text"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "请回复一段最终文本"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]
        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))

        asyncio.run(ai_handlers.handle_ai_chat(ctx))

        events = runtime_store.list_events(session_id=session_id)
        assert [event["type"] for event in events] == [
            "user_message",
            "assistant_message_final",
        ]
        assert events[1]["turn_id"] == turn_id
        assert events[1]["payload"]["text"] == "这是 Runtime v2 final 文本"
        turn = runtime_store.get_turn(turn_id)
        assert turn["status"] == "succeeded"
        assert turn["metadata"]["handler"] == "handle_ai_chat"
        assert turn["metadata"]["response_chars"] == len("这是 Runtime v2 final 文本")

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert [item["role"] for item in messages] == [
            "user",
            "assistant",
        ], messages
        assert messages[-1]["content"] == "这是 Runtime v2 final 文本"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: assistant_message_final" in body
    assert "这是 Runtime v2 final 文本" in body


def test_runtime_delivery_records_text_delivery_failure(web_chat_api_runtime):
    _app, runtime_store = web_chat_api_runtime
    session = runtime_store.ensure_session(
        session_id="web:text-failed",
        kind="web_workspace",
        platform="web",
        platform_user_id="web-user",
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        source="user",
        input_text="触发文本发送失败",
    )

    class _FailingContext:
        message = SimpleNamespace(
            platform="web",
            chat=SimpleNamespace(id="web-user"),
        )
        user_data = {}

        async def reply(self, *_args, **_kwargs):
            raise RuntimeError("send failed")

    with pytest.raises(RuntimeError, match="send failed"):
        asyncio.run(
            runtime_delivery_module.deliver_text_message(
                ctx=_FailingContext(),
                payload="这条会发送失败",
                runtime_session_id=session["id"],
                runtime_turn_id=turn["id"],
                runtime_store=runtime_store,
            )
        )

    events = runtime_store.list_events(session_id=session["id"])
    assert [event["type"] for event in events] == ["delivery_failed"]
    assert events[0]["payload"]["kind"] == "text"
    assert events[0]["payload"]["error"] == "send failed"


def test_web_chat_api_context_marks_runtime_turn_failed_on_agent_error(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator

    app, runtime_store = web_chat_api_runtime

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

    async def _fake_build_history(_ctx, *, user_message, **_kwargs):
        return SimpleNamespace(
            current_resolution=None,
            reply_resolution=None,
            inline_inputs=[],
            truncated_inline_count=0,
            errors=[],
            detected_refs=[],
            has_inline_inputs=False,
            has_reply_media=False,
            final_user_message=user_message,
            user_parts=[{"text": user_message}],
        )

    async def _raise_agent_error(_ctx, _message_history):
        raise RuntimeError("fake agent exploded")
        yield ""

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(ai_handlers, "require_feature_access", _allow_feature)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "bind_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _raise_agent_error)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "is_cancelled",
        lambda _uid: False,
    )
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "unregister_task",
        lambda _uid: None,
    )

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 failed text"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "触发一次失败"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]
        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))

        asyncio.run(ai_handlers.handle_ai_chat(ctx))

        turn = runtime_store.get_turn(turn_id)
        assert turn["status"] == "failed"
        assert turn["error"] == "fake agent exploded"
        assert turn["metadata"]["handler"] == "handle_ai_chat"
        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert "Agent 运行出错" in messages[-1]["content"]


def test_web_chat_api_context_marks_runtime_turn_cancelled_on_task_cancel(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator

    app, runtime_store = web_chat_api_runtime

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

    async def _fake_build_history(_ctx, *, user_message, **_kwargs):
        return SimpleNamespace(
            current_resolution=None,
            reply_resolution=None,
            inline_inputs=[],
            truncated_inline_count=0,
            errors=[],
            detected_refs=[],
            has_inline_inputs=False,
            has_reply_media=False,
            final_user_message=user_message,
            user_parts=[{"text": user_message}],
        )

    async def _cancelled_agent(_ctx, _message_history):
        yield "这一段不应进入最终回复"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(ai_handlers, "require_feature_access", _allow_feature)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "bind_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _cancelled_agent)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "is_cancelled",
        lambda _uid: True,
    )
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "unregister_task",
        lambda _uid: None,
    )

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 cancelled text"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "触发一次取消"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]
        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(ai_handlers.handle_ai_chat(ctx))

        turn = runtime_store.get_turn(turn_id)
        assert turn["status"] == "cancelled"
        assert turn["metadata"]["handler"] == "handle_ai_chat"


def test_web_chat_api_video_option_turn_succeeds_without_agent(
    web_chat_api_runtime,
    monkeypatch,
):
    import core.config as config_module
    from core.agent_orchestrator import agent_orchestrator

    app, runtime_store = web_chat_api_runtime

    async def _allow_user(_user_id):
        return True

    async def _allow_feature(_ctx, _feature):
        return True

    async def _false(*_args, **_kwargs):
        return False

    async def _agent_should_not_run(*_args, **_kwargs):
        raise AssertionError("video option path should not invoke agent")
        yield ""

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(ai_handlers, "require_feature_access", _allow_feature)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(agent_orchestrator, "handle_message", _agent_should_not_run)

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 video option"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
                json={
                    "type": "message_text",
                    "text": "https://x.com/wangchangfu88/status/2057414957743120721?s=46",
                },
            )
        turn_id = posted.json()["runtime"]["turn_id"]
        inbound = asyncio.run(web_store.claim_inbound_events(limit=1))
        ctx = asyncio.run(WebAdapter()._build_context(inbound[0]))

        asyncio.run(ai_handlers.handle_ai_chat(ctx))

        turn = runtime_store.get_turn(turn_id)
        assert turn["status"] == "succeeded"
        assert turn["metadata"]["handled_by"] == "video_link_options"
        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert "已识别视频链接" in messages[-1]["content"]


def test_web_chat_api_stream_reads_codex_kernel_raw_text_events(
    web_chat_api_runtime,
    monkeypatch,
):
    from core import codex_kernel as codex_kernel_module

    app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-runtime-stream", bool(
                existing_thread_id
            )

        async def start_turn(self, *, thread_id, instruction):
            assert thread_id == "thread-runtime-stream"
            assert instruction == "查一下科技新闻"
            return "turn-runtime-stream"

        async def wait_for_turn_completed(self, *, turn_id):
            assert turn_id == "turn-runtime-stream"
            assert self.event_callback is not None
            await self.event_callback(
                "agent_message_delta",
                {
                    "turn_id": turn_id,
                    "item_id": "msg-1",
                    "delta": "我正在查公开新闻来源。",
                    "text": "我正在查公开新闻来源。",
                },
            )
            await self.event_callback(
                "agent_message_completed",
                {
                    "turn_id": turn_id,
                    "item_id": "msg-1",
                    "text": "我查到了三条值得看的科技新闻。",
                },
            )
            return {"id": turn_id, "status": "completed"}

        def build_result(self, *, thread_id, turn_id, turn, loaded_existing_thread):
            return {
                "ok": True,
                "stdout": "完成",
                "summary": "完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(codex_kernel_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "ikaros_codex_command",
        lambda: ["codex", "app-server", "--listen", "stdio://"],
    )

    async def _run_codex_turn(session_id: str, turn_id: str):
        await codex_kernel_module.close_persistent_codex_kernel_client()
        try:
            return await codex_kernel_module.codex_kernel_provider._run_turn(
                user_id="50101",
                task_id="task-runtime-stream",
                task_inbox_id="",
                instruction="查一下科技新闻",
                platform="web",
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
            )
        finally:
            await codex_kernel_module.close_persistent_codex_kernel_client()

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 Codex stream"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "查一下科技新闻"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        result = asyncio.run(_run_codex_turn(session_id, turn_id))
        assert result["ok"] is True

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: text_delta" in body
    assert "event: message_update" in body
    assert "我正在查公开新闻来源。" in body
    assert "我查到了三条值得看的科技新闻。" in body
    assert "Ikaros 正在处理请求" not in body
    assert "回合：" not in body


def test_web_chat_api_messages_render_codex_batch_artifact_events(
    web_chat_api_runtime,
    monkeypatch,
    tmp_path,
):
    from core import codex_kernel as codex_kernel_module

    app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)
    image_path = tmp_path / "codex-image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-runtime-artifact", bool(
                existing_thread_id
            )

        async def start_turn(self, *, thread_id, instruction):
            assert thread_id == "thread-runtime-artifact"
            assert instruction == "生成一张图片"
            return "turn-runtime-artifact"

        async def wait_for_turn_completed(self, *, turn_id):
            return {"id": turn_id, "status": "completed"}

        def build_result(self, *, thread_id, turn_id, turn, loaded_existing_thread):
            return {
                "ok": True,
                "stdout": "",
                "summary": "",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
                "files": [
                    {
                        "kind": "photo",
                        "path": str(image_path),
                        "filename": "codex-image.png",
                    }
                ],
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(codex_kernel_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "ikaros_codex_command",
        lambda: ["codex", "app-server", "--listen", "stdio://"],
    )

    async def _run_codex_turn(session_id: str, turn_id: str):
        await codex_kernel_module.close_persistent_codex_kernel_client()
        try:
            return await codex_kernel_module.codex_kernel_provider._run_turn(
                user_id="50101",
                task_id="task-runtime-artifact",
                task_inbox_id="",
                instruction="生成一张图片",
                platform="web",
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
            )
        finally:
            await codex_kernel_module.close_persistent_codex_kernel_client()

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 Codex artifact"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "生成一张图片"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        result = asyncio.run(_run_codex_turn(session_id, turn_id))
        assert result["ok"] is True

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert messages[-1]["attachments"][0]["kind"] == "photo"
        assert messages[-1]["attachments"][0]["name"] == "codex-image.png"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: artifact_created" in body
    assert "codex-image.png" in body


def test_web_chat_api_stream_reads_codex_request_user_input_event(
    web_chat_api_runtime,
    monkeypatch,
):
    from core import codex_kernel as codex_kernel_module

    app, runtime_store = web_chat_api_runtime
    event_bus = RuntimeEventBus(runtime_store)

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-runtime-wait", bool(
                existing_thread_id
            )

        async def start_turn(self, *, thread_id, instruction):
            assert thread_id == "thread-runtime-wait"
            assert instruction == "执行到需要确认"
            return "turn-runtime-wait"

        async def wait_for_turn_completed(self, *, turn_id):
            assert turn_id == "turn-runtime-wait"
            assert self.event_callback is not None
            await self.event_callback(
                "request_user_input",
                {
                    "turn_id": turn_id,
                    "method": "item/tool/requestUserInput",
                    "params": {"prompt": "请选择继续还是停止"},
                },
            )
            return {"id": turn_id, "status": "completed"}

        def build_result(self, *, thread_id, turn_id, turn, loaded_existing_thread):
            return {
                "ok": True,
                "stdout": "还需要用户确认。",
                "summary": "还需要用户确认。",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
                "user_input_requests": [
                    {"params": {"prompt": "请选择继续还是停止"}}
                ],
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(codex_kernel_module, "runtime_event_bus", event_bus)
    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "ikaros_codex_command",
        lambda: ["codex", "app-server", "--listen", "stdio://"],
    )

    async def _run_codex_turn(session_id: str, turn_id: str):
        await codex_kernel_module.close_persistent_codex_kernel_client()
        try:
            return await codex_kernel_module.codex_kernel_provider._run_turn(
                user_id="50101",
                task_id="task-runtime-wait",
                task_inbox_id="",
                instruction="执行到需要确认",
                platform="web",
                runtime_session_id=session_id,
                runtime_turn_id=turn_id,
            )
        finally:
            await codex_kernel_module.close_persistent_codex_kernel_client()

    with TestClient(app) as client:
        session_id = client.post(
            "/api/v1/web-chat/sessions",
            json={"title": "Runtime v2 Codex waiting"},
        ).json()["id"]
        posted = client.post(
            f"/api/v1/web-chat/sessions/{session_id}/events",
            json={"type": "message_text", "text": "执行到需要确认"},
        )
        turn_id = posted.json()["runtime"]["turn_id"]

        result = asyncio.run(_run_codex_turn(session_id, turn_id))
        assert result["user_input_requests"][0]["params"]["prompt"] == (
            "请选择继续还是停止"
        )
        assert runtime_store.get_turn(turn_id)["status"] == "waiting_user"

        messages = client.get(
            f"/api/v1/web-chat/sessions/{session_id}/messages"
        ).json()["items"]
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert messages[-1]["content"] == "请选择继续还是停止"
        assert messages[-1]["meta"]["event_type"] == "request_user_input"

        with client.stream(
            "GET",
            f"/api/v1/web-chat/sessions/{session_id}/stream?once=true",
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: request_user_input" in body
    assert "请选择继续还是停止" in body
