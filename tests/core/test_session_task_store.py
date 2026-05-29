from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.heartbeat_store import heartbeat_store
from core.runtime_v2 import runtime_v2
from core.session_task_store import session_task_store
from core.task_inbox import task_inbox


def _reset_task_inbox(tmp_path: Path) -> None:
    root = (tmp_path / "task_inbox").resolve()
    tasks_root = (root / "tasks").resolve()
    archive_root = (root / "archive").resolve()
    events_path = (root / "events.jsonl").resolve()
    tasks_root.mkdir(parents=True, exist_ok=True)
    archive_root.mkdir(parents=True, exist_ok=True)
    task_inbox.persist = True
    task_inbox.root = root
    task_inbox.tasks_root = tasks_root
    task_inbox.archive_root = archive_root
    task_inbox.events_path = events_path
    task_inbox._loaded = False
    task_inbox._tasks = {}


def _reset_heartbeat_store(tmp_path: Path) -> None:
    root = (tmp_path / "runtime_tasks").resolve()
    root.mkdir(parents=True, exist_ok=True)
    heartbeat_store.root = root
    heartbeat_store._locks.clear()


@pytest.fixture
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setenv("IKAROS_RUNTIME_DB_PATH", str(tmp_path / "runtime.db"))
    _reset_task_inbox(tmp_path)
    _reset_heartbeat_store(tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_list_recent_completed_ignores_expired_completed_session(_isolated_state):
    session = await task_inbox.submit(
        source="user_chat",
        goal="帮我总结部署结果",
        user_id="u-2",
        metadata={"session_task_id": "tsk-expired-1"},
    )
    expired = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    )
    await task_inbox.update_status(
        session.task_id,
        "completed",
        event="session_completed",
        detail="done",
        metadata={
            "session_task_id": session.task_id,
            "resume_window_until": expired,
            "last_user_visible_summary": "部署已经完成。",
        },
    )

    rows = await session_task_store.list_recent_completed("u-2", limit=1)

    assert rows == []


@pytest.mark.asyncio
async def test_get_active_prefers_heartbeat_session_view(_isolated_state):
    session = await task_inbox.submit(
        source="user_chat",
        goal="帮我修复部署",
        user_id="u-3",
        metadata={
            "session_task_id": "tsk-active-1",
            "stage_id": "stage-2",
            "stage_title": "执行主要任务",
            "stage_index": 2,
            "stage_total": 3,
            "attempt_index": 1,
            "delivery_state": "pending",
            "last_user_visible_summary": "当前卡在重启服务。",
        },
    )
    await heartbeat_store.set_session_active_task(
        "u-3",
        {
            "id": "mgr-active-1",
            "session_task_id": session.task_id,
            "task_inbox_id": session.task_id,
            "goal": session.goal,
            "status": "waiting_user",
            "stage_index": 2,
            "stage_total": 3,
            "stage_id": "stage-2",
            "stage_title": "执行主要任务",
            "attempt_index": 1,
            "delivery_state": "retrying",
            "last_user_visible_summary": "任务暂时卡住了。",
        },
    )

    active = await session_task_store.get_active("u-3")

    assert active is not None
    assert active.status == "waiting_user"
    assert active.session_task_id == session.task_id
    assert active.current_stage_id == "stage-2"
    assert active.delivery_state == "retrying"
    assert "任务暂时卡住了" in active.last_user_visible_summary


@pytest.mark.asyncio
async def test_get_active_can_read_runtime_v2_task_without_legacy_active_state(
    _isolated_state,
):
    session = runtime_v2.ensure_session(
        session_id="telegram:u-rv2-active:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u-rv2-active",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="user",
        input_text="继续 Runtime v2 活跃任务",
        status="running",
    )
    task = runtime_v2.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="Runtime v2 活跃任务",
        status="waiting_user",
        metadata={
            "result_summary": "等待用户确认。",
        },
    )

    active = await session_task_store.get_active("u-rv2-active")

    assert active is not None
    assert active.session_task_id == task["id"]
    assert active.status == "waiting_user"
    assert active.task_goal == "Runtime v2 活跃任务"
    assert active.last_user_visible_summary == "等待用户确认。"


@pytest.mark.asyncio
async def test_list_recent_completed_reads_runtime_v2_resume_window(
    _isolated_state,
):
    resume_until = (datetime.now().astimezone() + timedelta(minutes=10)).isoformat(
        timespec="seconds"
    )
    legacy_task = await task_inbox.submit(
        source="user_chat",
        goal="legacy duplicate",
        user_id="u-rv2-completed",
    )
    await task_inbox.update_status(
        legacy_task.task_id,
        "completed",
        event="done",
        metadata={
            "resume_window_until": resume_until,
            "last_user_visible_summary": "legacy summary",
        },
    )
    session = runtime_v2.ensure_session(
        session_id="telegram:u-rv2-completed:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u-rv2-completed",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="user",
        input_text="Runtime v2 completed",
        status="running",
    )
    task = runtime_v2.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="Runtime v2 completed",
        status="running",
        metadata={
            "task_inbox_id": legacy_task.task_id,
            "resume_window_until": resume_until,
            "result_summary": "Runtime v2 summary",
        },
    )
    runtime_v2.update_task_status(task["id"], "succeeded")

    rows = await session_task_store.list_recent_completed("u-rv2-completed", limit=2)

    assert [row.session_task_id for row in rows] == [task["id"]]
    assert rows[0].last_user_visible_summary == "Runtime v2 summary"
