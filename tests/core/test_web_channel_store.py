import pytest

from core.state_store import save_message
from core.runtime_v2 import runtime_v2
from web_channel import store as web_store


@pytest.mark.asyncio
async def test_web_sessions_merge_bound_channel_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions"
    )
    (tmp_path / "web_sessions").mkdir(parents=True, exist_ok=True)

    await web_store.create_session_projection(
        user_id="web-1",
        session_id="web-session",
        title="Web chat",
    )
    await save_message("telegram-user", "user", "来自 Telegram 的问题", "tg-session")
    await save_message("telegram-user", "model", "来自 Telegram 的回答", "tg-session")
    await save_message("user", "user", "[定时任务 #7] 每天新闻", "scheduler-task-7")
    await save_message("user", "model", "定时任务结果", "scheduler-task-7")

    sessions = await web_store.list_session_projections(
        "web-1",
        source_user_ids=["telegram-user", "user"],
        limit=20,
    )
    by_id = {item["id"]: item for item in sessions}

    assert "web-session" in by_id
    assert by_id["web-session"]["title"] == "Web chat"
    assert by_id["tg-session"]["preferences"]["kind"] == "channel"
    assert by_id["scheduler-task-7"]["preferences"]["kind"] == "scheduled_task"

    telegram_messages = await web_store.get_session_messages(
        "web-1",
        "tg-session",
        source_user_ids=["telegram-user"],
    )
    assert [item["role"] for item in telegram_messages] == ["user", "assistant"]
    assert telegram_messages[1]["content"] == "来自 Telegram 的回答"

    scheduler_messages = await web_store.get_session_messages(
        "web-1",
        "scheduler-task-7",
        source_user_ids=["user"],
    )
    assert scheduler_messages[-1]["content"] == "定时任务结果"


@pytest.mark.asyncio
async def test_web_sessions_include_runtime_v2_scheduler_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions_v2"
    )
    (tmp_path / "web_sessions_v2").mkdir(parents=True, exist_ok=True)

    session = runtime_v2.ensure_session(
        session_id="scheduler-task-42",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="user",
        title="每天 AI 新闻",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="抓取 AI 新闻",
    )
    runtime_v2.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="scheduler_triggered",
        payload={"instruction": "抓取 AI 新闻"},
    )
    runtime_v2.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "AI 新闻结果"},
    )

    sessions = await web_store.list_session_projections(
        "web-1",
        source_user_ids=["user"],
        limit=20,
    )
    by_id = {item["id"]: item for item in sessions}
    assert by_id["scheduler-task-42"]["preferences"]["source"] == "runtime_v2"
    assert by_id["scheduler-task-42"]["preferences"]["kind"] == "scheduled_task"

    messages = await web_store.get_session_messages(
        "web-1",
        "scheduler-task-42",
        source_user_ids=["user"],
    )
    assert [item["content"] for item in messages] == ["抓取 AI 新闻", "AI 新闻结果"]
