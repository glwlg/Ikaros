import base64

import pytest

from ikaros.dev import codex_app_server_client as client_module
from ikaros.dev.codex_app_server_client import CodexAppServerClient


@pytest.mark.asyncio
async def test_app_server_client_collects_agent_message_and_turn_completion(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "hel",
            },
        }
    )
    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "lo",
            },
        }
    )
    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed", "items": []},
            },
        }
    )

    turn = await client.wait_for_turn_completed(turn_id="turn-1")
    result = client.build_result(
        thread_id="thread-1",
        turn_id="turn-1",
        turn=turn,
        loaded_existing_thread=False,
    )

    assert result["ok"] is True
    assert result["stdout"] == "hello"
    assert result["transport"] == "app-server"
    assert result["transport_session_id"] == "thread-1"


@pytest.mark.asyncio
async def test_app_server_client_emits_agent_message_delta_events(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    events = []

    async def on_event(event, payload):
        events.append((event, payload))

    client.set_event_callback(on_event)

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "hello",
            },
        }
    )

    assert events[0][0] == "agent_message_delta"
    assert events[0][1]["turn_id"] == "turn-1"
    assert events[0][1]["text"] == "hello"


@pytest.mark.asyncio
async def test_app_server_client_emits_web_search_activity_events(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    events = []

    async def on_event(event, payload):
        events.append((event, payload))

    client.set_event_callback(on_event)

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "search-1",
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "queries": [
                            "technology news today",
                            "AI chip market",
                        ],
                    },
                },
            },
        }
    )

    assert events == [
        (
            "item_activity",
            {
                "method": "item/completed",
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "item_id": "search-1",
                "item_type": "web_search_call",
                "text": "搜索：technology news today；AI chip market",
            },
        )
    ]


def test_app_server_client_prefers_available_approval_decision(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
        approval_decision="accept",
    )

    assert (
        client._select_decision(["decline", "acceptForSession"], default="accept")
        == "acceptForSession"
    )


def test_app_server_client_reset_turn_state_clears_previous_output(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    client.completed_agent_messages["old"] = "old output"
    client.command_output["cmd"] = ["old command"]
    client.user_input_requests.append({"params": {"prompt": "old"}})

    client.reset_turn_state()

    result = client.build_result(
        thread_id="thread-1",
        turn_id="turn-1",
        turn={"id": "turn-1", "status": "completed"},
        loaded_existing_thread=False,
    )

    assert result["stdout"] == ""
    assert result["command_output"] == {}
    assert result["user_input_requests"] == []


@pytest.mark.asyncio
async def test_app_server_client_reuses_live_thread_without_resume(monkeypatch, tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    calls = []

    async def fake_request(method, params):
        calls.append((method, dict(params or {})))
        if method == "thread/start":
            return {"thread": {"id": "thread-live"}}
        raise AssertionError(f"unexpected request: {method}")

    monkeypatch.setattr(client, "request", fake_request)

    assert await client.open_thread() == ("thread-live", False)
    assert client.has_open_thread("thread-live") is True
    assert await client.open_thread(existing_thread_id="thread-live") == (
        "thread-live",
        True,
    )

    assert [method for method, _params in calls] == ["thread/start"]


@pytest.mark.asyncio
async def test_app_server_client_start_turn_accepts_local_image_input(monkeypatch, tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    calls = []

    async def fake_request(method, params):
        calls.append((method, dict(params or {})))
        if method == "turn/start":
            return {"turn": {"id": "turn-image"}}
        raise AssertionError(f"unexpected request: {method}")

    monkeypatch.setattr(client, "request", fake_request)

    turn_id = await client.start_turn(
        thread_id="thread-1",
        instruction="fallback text",
        input_items=[
            {"type": "text", "text": "看图"},
            {"type": "localImage", "path": str(tmp_path / "image.png")},
        ],
    )

    assert turn_id == "turn-image"
    assert calls[0][1]["input"] == [
        {"type": "text", "text": "看图"},
        {"type": "localImage", "path": str(tmp_path / "image.png")},
    ]


def test_app_server_client_completed_image_only_turn_has_empty_summary(tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
        request_timeout_sec=7,
    )

    assert client.request_timeout_sec == 7

    result = client.build_result(
        thread_id="thread-1",
        turn_id="turn-1",
        turn={"id": "turn-1", "status": "completed"},
        loaded_existing_thread=False,
    )

    assert result["ok"] is True
    assert result["stdout"] == ""
    assert result["summary"] == ""


@pytest.mark.asyncio
async def test_app_server_client_collects_local_image_files_from_completed_items(tmp_path):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "img-1",
                    "type": "generatedImage",
                    "image": {"filePath": str(image_path)},
                },
            },
        }
    )

    result = client.build_result(
        thread_id="thread-1",
        turn_id="turn-1",
        turn={"id": "turn-1", "status": "completed"},
        loaded_existing_thread=False,
    )

    assert result["files"] == [
        {
            "kind": "photo",
            "path": str(image_path.resolve()),
            "filename": "generated.png",
            "caption": "",
        }
    ]


@pytest.mark.asyncio
async def test_app_server_client_ignores_local_document_files_from_completed_items(tmp_path):
    doc_path = tmp_path / "SKILL.md"
    doc_path.write_text("# Skill notes\n", encoding="utf-8")
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "doc-1",
                    "type": "generatedFile",
                    "file": {"filePath": str(doc_path)},
                },
            },
        }
    )

    assert client.files == []


@pytest.mark.asyncio
async def test_app_server_client_writes_image_generation_result_and_emits_file_event(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        client_module.Path,
        "home",
        classmethod(lambda _cls: tmp_path),
    )
    png_bytes = b"\x89PNG\r\n\x1a\nfake"
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    events = []

    async def on_event(event, payload):
        events.append((event, payload))

    client.set_event_callback(on_event)

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {
                    "id": "ig_demo",
                    "type": "image_generation_call",
                    "result": base64.b64encode(png_bytes).decode("ascii"),
                },
            },
        }
    )

    image_path = (
        tmp_path / ".codex" / "generated_images" / "thread-1" / "ig_demo.png"
    )
    assert image_path.read_bytes() == png_bytes
    assert client.files == [
        {
            "kind": "photo",
            "path": str(image_path.resolve()),
            "filename": "ig_demo.png",
            "caption": "",
        }
    ]
    assert events == [
        (
            "generated_files",
            {
                "method": "item/completed",
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "item_id": "ig_demo",
                "files": client.files,
            },
        )
    ]


@pytest.mark.asyncio
async def test_app_server_client_collects_image_generation_end_event_payload(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        client_module.Path,
        "home",
        classmethod(lambda _cls: tmp_path),
    )
    png_bytes = b"\x89PNG\r\n\x1a\nevent"
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    events = []

    async def on_event(event, payload):
        events.append((event, payload))

    client.set_event_callback(on_event)

    await client._handle_payload(
        {
            "jsonrpc": "2.0",
            "method": "event_msg",
            "params": {
                "threadId": "thread-2",
                "turnId": "turn-2",
                "payload": {
                    "type": "image_generation_end",
                    "call_id": "ig_event",
                    "result": base64.b64encode(png_bytes).decode("ascii"),
                },
            },
        }
    )

    image_path = (
        tmp_path / ".codex" / "generated_images" / "thread-2" / "ig_event.png"
    )
    assert image_path.read_bytes() == png_bytes
    assert events[0][0] == "generated_files"
    assert events[0][1]["files"][0]["path"] == str(image_path.resolve())


@pytest.mark.asyncio
async def test_app_server_client_records_user_input_requests(monkeypatch, tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    responses = []
    events = []

    async def on_event(event, payload):
        events.append((event, dict(payload)))

    async def fake_send_response(request_id, *, result=None, error=None):
        responses.append((request_id, result, error))

    monkeypatch.setattr(client, "_send_response", fake_send_response)
    client.set_event_callback(on_event)

    await client._handle_request(
        "req-1",
        "item/tool/requestUserInput",
        {"prompt": "Need confirmation"},
    )

    result = client.build_result(
        thread_id="thread-1",
        turn_id="turn-1",
        turn={"id": "turn-1", "status": "completed"},
        loaded_existing_thread=False,
    )

    assert responses == [("req-1", {"answers": {}}, None)]
    assert result["user_input_requests"][0]["params"]["prompt"] == "Need confirmation"
    assert events == [
        (
            "request_user_input",
            {
                "at": result["user_input_requests"][0]["at"],
                "method": "item/tool/requestUserInput",
                "params": {"prompt": "Need confirmation"},
            },
        )
    ]
