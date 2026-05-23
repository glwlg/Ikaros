import pytest

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
async def test_app_server_client_records_user_input_requests(monkeypatch, tmp_path):
    client = CodexAppServerClient(
        command=["codex", "app-server"],
        cwd=str(tmp_path),
        env={},
        timeout_sec=30,
    )
    responses = []

    async def fake_send_response(request_id, *, result=None, error=None):
        responses.append((request_id, result, error))

    monkeypatch.setattr(client, "_send_response", fake_send_response)

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
