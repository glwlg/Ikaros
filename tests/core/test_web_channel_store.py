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


@pytest.mark.asyncio
async def test_web_session_messages_do_not_expose_unowned_runtime_session(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions_private"
    )
    (tmp_path / "web_sessions_private").mkdir(parents=True, exist_ok=True)

    session = runtime_v2.ensure_session(
        session_id="scheduler-task-private",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="owner-user",
        title="私有定时任务",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="私有请求",
    )
    runtime_v2.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "私有结果"},
    )

    projection = await web_store.get_session_projection(
        "web-1",
        "scheduler-task-private",
        source_user_ids=["other-user"],
    )
    assert projection["session"]["preferences"] == {}
    assert (
        await web_store.get_session_messages(
            "web-1",
            "scheduler-task-private",
            source_user_ids=["other-user"],
        )
    ) == []


@pytest.mark.asyncio
async def test_web_session_messages_merge_state_rows_with_runtime_artifacts(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions_merged"
    )
    (tmp_path / "web_sessions_merged").mkdir(parents=True, exist_ok=True)

    await save_message("owner-user", "model", "历史报告正文", "scheduler-task-merged")
    session = runtime_v2.ensure_session(
        session_id="scheduler-task-merged",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="owner-user",
        title="合并定时任务",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="生成报告",
    )
    runtime_v2.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="artifact_created",
        payload={
            "kind": "document",
            "filename": "report.txt",
            "path": "/tmp/report.txt",
        },
    )

    messages = await web_store.get_session_messages(
        "web-1",
        "scheduler-task-merged",
        source_user_ids=["owner-user"],
    )

    assert [item["content"] for item in messages] == [
        "历史报告正文",
        "[附件] report.txt",
    ]
    assert messages[-1]["attachments"][0]["name"] == "report.txt"


@pytest.mark.asyncio
async def test_web_session_messages_keep_distinct_runtime_attachments(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions_distinct"
    )
    (tmp_path / "web_sessions_distinct").mkdir(parents=True, exist_ok=True)

    await web_store.create_session_projection(
        user_id="owner-user",
        session_id="attachment-session",
    )
    await web_store.upsert_session_message(
        user_id="owner-user",
        session_id="attachment-session",
        message={
            "id": "projected-doc",
            "role": "assistant",
            "content": "[附件] old.txt",
            "message_type": "document",
            "attachments": [
                {
                    "kind": "document",
                    "file_id": "old-doc",
                    "name": "old.txt",
                }
            ],
        },
    )
    session = runtime_v2.ensure_session(
        session_id="attachment-session",
        kind="web_workspace",
        platform="web",
        platform_user_id="owner-user",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="user",
        input_text="生成新附件",
    )
    runtime_v2.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="artifact_created",
        payload={
            "artifact_id": "new-doc",
            "kind": "document",
            "filename": "new.txt",
            "path": "/tmp/new.txt",
        },
    )

    messages = await web_store.get_session_messages(
        "owner-user",
        "attachment-session",
    )

    assert [item["content"] for item in messages] == [
        "[附件] old.txt",
        "[附件] new.txt",
    ]


@pytest.mark.asyncio
async def test_web_session_runtime_messages_use_latest_event_window(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        web_store, "WEB_CHANNEL_SESSIONS_DIR", tmp_path / "web_sessions_latest"
    )
    (tmp_path / "web_sessions_latest").mkdir(parents=True, exist_ok=True)

    session = runtime_v2.ensure_session(
        session_id="long-runtime-session",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="owner-user",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="scheduler",
        input_text="long run",
    )
    for index in range(505):
        runtime_v2.append_event(
            session_id=session["id"],
            turn_id=turn["id"],
            event_type="assistant_message_final",
            payload={"text": f"message {index}"},
        )

    messages = await web_store.get_session_messages(
        "web-user",
        "long-runtime-session",
        source_user_ids=["owner-user"],
    )

    assert len(messages) == 500
    assert messages[0]["content"] == "message 5"
    assert messages[-1]["content"] == "message 504"
