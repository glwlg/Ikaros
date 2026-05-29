from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.runtime_v2 import RuntimeV2Store, RuntimeV2TransitionError


def _count_open_fds_for_path(path: Path) -> int:
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.exists():
        pytest.skip("/proc/self/fd is not available on this platform")
    target = str(path.resolve())
    count = 0
    for fd in fd_dir.iterdir():
        try:
            linked = os.readlink(fd)
        except OSError:
            continue
        linked = linked.removesuffix(" (deleted)")
        if linked == target or linked.startswith(f"{target}-"):
            count += 1
    return count


def test_runtime_v2_records_session_turn_event_artifact_and_delivery(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")

    session = store.ensure_session(
        session_id="telegram:u1:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u1",
        title="主会话",
    )
    turn = store.create_turn(
        session_id=session["id"],
        source="user",
        input_text="画一张图",
        kernel_provider="codex",
    )
    running = store.update_turn_status(turn["id"], "running", external_turn_id="t-cx")
    event = store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="text_delta",
        payload={"text": "我来画"},
    )
    image = tmp_path / "demo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    artifact = store.record_artifact(
        session_id=session["id"],
        turn_id=turn["id"],
        kind="photo",
        path=str(image),
        source="codex_kernel",
    )
    delivery = store.record_delivery(
        artifact_id=artifact["id"],
        platform="telegram",
        target="telegram:u1",
        status="delivered",
    )

    assert running["status"] == "running"
    assert event["seq"] == 1
    assert artifact["kind"] == "photo"
    assert artifact["sha256"]
    assert delivery["status"] == "delivered"
    assert store.list_events(session_id=session["id"])[0]["payload"]["text"] == "我来画"
    assert store.get_turn(turn["id"])["input_text"] == "画一张图"
    assert [item["id"] for item in store.list_turns(session["id"])] == [turn["id"]]
    deliveries = store.list_deliveries(session_id=session["id"])
    assert [(item["artifact_id"], item["target"]) for item in deliveries] == [
        (artifact["id"], "telegram:u1")
    ]


def test_runtime_v2_closes_sqlite_connections_between_operations(tmp_path):
    db_path = tmp_path / "runtime.db"
    store = RuntimeV2Store(db_path)

    before = _count_open_fds_for_path(db_path)
    for index in range(20):
        session = store.ensure_session(
            session_id=f"telegram:u{index}:main",
            platform_user_id=f"u{index}",
        )
        turn = store.create_turn(session_id=session["id"], input_text=f"hello {index}")
        store.append_event(
            session_id=session["id"],
            turn_id=turn["id"],
            event_type="assistant_message_final",
            payload={"text": "ok"},
        )
        assert store.get_session(session["id"])
        assert store.list_events(session_id=session["id"])
        assert store.list_sessions(platform_user_ids=[f"u{index}"])

    assert _count_open_fds_for_path(db_path) <= before


def test_runtime_v2_rejects_invalid_terminal_transition(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    session = store.ensure_session(session_id="s1")
    turn = store.create_turn(session_id=session["id"])

    store.update_turn_status(turn["id"], "running")
    store.update_turn_status(turn["id"], "succeeded")

    with pytest.raises(RuntimeV2TransitionError):
        store.update_turn_status(turn["id"], "running")


def test_runtime_v2_task_state_machine_rejects_invalid_terminal_transition(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    session = store.ensure_session(session_id="task-state-session")
    turn = store.create_turn(session_id=session["id"], input_text="run task")
    task = store.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="state machine task",
    )

    store.update_task_status(task["id"], "running")
    store.update_task_status(task["id"], "succeeded")

    with pytest.raises(RuntimeV2TransitionError):
        store.update_task_status(task["id"], "running")


def test_runtime_v2_tracks_kernel_thread_per_session(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    store.ensure_session(
        session_id="scheduler-task-9",
        kind="scheduled_task",
        platform="scheduler",
        platform_user_id="user",
    )

    store.upsert_kernel_session(
        session_id="scheduler-task-9",
        provider="codex",
        external_thread_id="thread-1",
        external_turn_id="turn-1",
    )
    store.upsert_kernel_session(
        session_id="scheduler-task-9",
        provider="codex",
        external_thread_id="thread-1",
        external_turn_id="turn-2",
    )

    row = store.get_kernel_session(session_id="scheduler-task-9", provider="codex")
    assert row["external_thread_id"] == "thread-1"
    assert row["external_turn_id"] == "turn-2"


def test_runtime_v2_disables_stale_scheduler_jobs(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    store.ensure_session(session_id="scheduler-task-old", kind="scheduled_task")
    store.ensure_session(session_id="scheduler-task-live", kind="scheduled_task")
    store.upsert_scheduler_job(
        job_id="old",
        session_id="scheduler-task-old",
        crontab="0 8 * * *",
        instruction="old task",
    )
    store.upsert_scheduler_job(
        job_id="live",
        session_id="scheduler-task-live",
        crontab="0 9 * * *",
        instruction="live task",
    )

    assert store.disable_scheduler_jobs_except({"live"}) == 1

    assert store.get_scheduler_job("old")["enabled"] == 0
    assert store.get_scheduler_job("live")["enabled"] == 1


def test_runtime_v2_expires_stale_waiting_user_turn_and_task(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    session = store.ensure_session(session_id="waiting-session", kind="channel_chat")
    turn = store.create_turn(session_id=session["id"], input_text="需要确认")
    store.update_turn_status(turn["id"], "running")
    store.update_turn_status(turn["id"], "waiting_user")
    task = store.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="等待确认",
        status="running",
    )
    store.update_task_status(task["id"], "waiting_user")

    result = store.expire_stale_work(
        waiting_user_ttl_sec=180,
        now=datetime.now().astimezone() + timedelta(seconds=181),
    )

    assert result == {"turns": 1, "tasks": 1}
    assert store.get_turn(turn["id"])["status"] == "expired"
    assert store.get_task(task["id"])["status"] == "expired"
    events = store.list_events(session_id=session["id"])
    assert [event["type"] for event in events] == [
        "runtime.expired",
        "task.expired",
    ]
    assert events[0]["payload"]["expired_after_sec"] == 180


def test_runtime_v2_session_trace_collects_runtime_objects(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    session = store.ensure_session(session_id="trace-session", kind="web_workspace")
    turn = store.create_turn(session_id=session["id"], input_text="trace me")
    store.upsert_kernel_session(
        session_id=session["id"],
        provider="codex",
        external_thread_id="thread-trace",
    )
    store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="assistant_message_final",
        payload={"text": "done"},
    )
    artifact_path = tmp_path / "trace.txt"
    artifact_path.write_text("trace", encoding="utf-8")
    artifact = store.record_artifact(
        session_id=session["id"],
        turn_id=turn["id"],
        path=str(artifact_path),
        kind="document",
    )
    store.record_delivery(
        artifact_id=artifact["id"],
        platform="web",
        target="web:trace",
        status="delivered",
    )
    store.create_task(session_id=session["id"], turn_id=turn["id"], goal="trace task")
    store.upsert_scheduler_job(
        job_id="trace-job",
        session_id=session["id"],
        crontab="0 8 * * *",
        instruction="trace job",
    )

    trace = store.get_session_trace(session["id"])

    assert trace["session"]["id"] == "trace-session"
    assert trace["kernel_sessions"][0]["external_thread_id"] == "thread-trace"
    assert trace["turns"][0]["input_text"] == "trace me"
    assert trace["events"][0]["payload"]["text"] == "done"
    assert trace["artifacts"][0]["filename"] == "trace.txt"
    assert trace["deliveries"][0]["artifact_filename"] == "trace.txt"
    assert trace["tasks"][0]["goal"] == "trace task"
    assert trace["scheduler_jobs"][0]["id"] == "trace-job"


def test_runtime_v2_lists_user_tasks_and_marks_deleted(tmp_path):
    store = RuntimeV2Store(tmp_path / "runtime.db")
    session = store.ensure_session(
        session_id="telegram:u-task:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u-task",
    )
    other_session = store.ensure_session(
        session_id="telegram:other:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="other",
    )
    turn = store.create_turn(
        session_id=session["id"],
        source="user",
        input_text="继续处理",
        kernel_provider="codex",
    )
    task = store.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="Runtime v2 task",
        status="running",
        metadata={"source": "user_chat"},
    )
    store.create_task(
        session_id=other_session["id"],
        goal="Other user task",
        status="running",
    )

    rows = store.list_tasks_for_user(platform_user_id="u-task")

    assert [row["id"] for row in rows] == [task["id"]]
    assert rows[0]["kernel_provider"] == "codex"
    assert rows[0]["turn_source"] == "user"

    deleted = store.mark_task_deleted(task["id"], reason="menu cleanup")

    assert deleted["status"] == "cancelled"
    assert deleted["metadata"]["deleted"] is True
    assert store.list_tasks_for_user(platform_user_id="u-task") == []
    visible_with_deleted = store.list_tasks_for_user(
        platform_user_id="u-task",
        include_deleted=True,
    )
    assert visible_with_deleted[0]["id"] == task["id"]
    assert store.list_events(session_id=session["id"])[0]["type"] == "task.deleted"
