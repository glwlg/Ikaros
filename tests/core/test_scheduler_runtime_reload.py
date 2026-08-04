import pytest

import core.scheduler as scheduler_module
from core.runtime_v2 import RuntimeV2Store


class _FakeScheduler:
    def __init__(self):
        self.jobs = []
        self.added = []

    def get_jobs(self):
        return list(self.jobs)

    def add_job(self, func, trigger, *, id, args=None, replace_existing=True, **kwargs):
        self.added.append(
            {
                "func": func,
                "trigger": trigger,
                "id": id,
                "args": list(args or []),
                "replace_existing": replace_existing,
                "kwargs": dict(kwargs),
            }
        )


@pytest.mark.asyncio
async def test_scheduler_reconcile_skips_unchanged_store(monkeypatch):
    calls = 0

    async def fake_reload_scheduler_jobs():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(scheduler_module, "_scheduler_store_revision", 7)
    monkeypatch.setattr(scheduler_module, "_scheduled_tasks_store_revision", lambda: 7)
    monkeypatch.setattr(
        scheduler_module,
        "reload_scheduler_jobs",
        fake_reload_scheduler_jobs,
    )

    await scheduler_module.reconcile_scheduler_jobs()

    assert calls == 0


@pytest.mark.asyncio
async def test_scheduler_reconcile_reloads_changed_store(monkeypatch):
    calls = 0

    async def fake_reload_scheduler_jobs():
        nonlocal calls
        calls += 1
        scheduler_module._scheduler_store_revision = 11

    monkeypatch.setattr(scheduler_module, "_scheduler_store_revision", 7)
    monkeypatch.setattr(scheduler_module, "_scheduled_tasks_store_revision", lambda: 11)
    monkeypatch.setattr(
        scheduler_module,
        "reload_scheduler_jobs",
        fake_reload_scheduler_jobs,
    )

    await scheduler_module.reconcile_scheduler_jobs()

    assert calls == 1
    assert scheduler_module._scheduler_store_revision == 11


@pytest.mark.asyncio
async def test_reload_scheduler_jobs_mirrors_runtime_v2_jobs(monkeypatch, tmp_path):
    fake_scheduler = _FakeScheduler()
    runtime_store = RuntimeV2Store(tmp_path / "runtime.db")
    runtime_store.ensure_session(
        session_id="scheduler-task-stale",
        kind="scheduled_task",
    )
    runtime_store.upsert_scheduler_job(
        job_id="stale",
        session_id="scheduler-task-stale",
        crontab="0 7 * * *",
        instruction="旧任务",
    )

    async def fake_get_all_active_tasks():
        return [
            {
                "id": "job-42",
                "crontab": "10 8 * * *",
                "instruction": "生成今日 AI 快讯",
                "platform": "telegram",
                "chat_id": "chat-42",
                "user_id": "owner-42",
                "need_push": False,
            }
        ]

    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "runtime_v2", runtime_store)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_tasks",
        fake_get_all_active_tasks,
    )
    monkeypatch.setattr(scheduler_module, "_scheduled_tasks_store_revision", lambda: 42)

    await scheduler_module.reload_scheduler_jobs()

    session = runtime_store.get_session("scheduler-task-job-42")
    job = runtime_store.get_scheduler_job("job-42")
    assert session["kind"] == "scheduled_task"
    assert session["platform_user_id"] == "owner-42"
    assert session["metadata"]["scheduled_task_id"] == "job-42"
    assert job["session_id"] == "scheduler-task-job-42"
    assert job["crontab"] == "10 8 * * *"
    assert job["instruction"] == "生成今日 AI 快讯"
    assert job["enabled"] == 1
    assert job["metadata"]["need_push"] is False
    assert runtime_store.get_scheduler_job("stale")["enabled"] == 0
    assert fake_scheduler.added[0]["id"] == "cron_db_job-42"
    assert fake_scheduler.added[0]["args"][1] == "owner-42"
    assert fake_scheduler.added[0]["args"][-3:] == [
        "scheduler-task-job-42",
        "job-42",
        "always",
    ]
    assert job["metadata"]["run_calendar"] == "always"


def test_start_dynamic_skill_scheduler_registers_idempotent_jobs(monkeypatch):
    fake_scheduler = _FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    scheduler_module.start_dynamic_skill_scheduler()

    assert [item["id"] for item in fake_scheduler.added] == [
        "scheduler_initial_reload",
        "scheduler_store_reconcile",
    ]
    assert [item["replace_existing"] for item in fake_scheduler.added] == [True, True]
