from types import SimpleNamespace

import pytest

from api.api.endpoints import scheduler as scheduler_endpoint


def _patch_platform_uid(monkeypatch):
    async def fake_get_primary_platform_user_id(user_id, session):
        assert user_id == 42
        assert session == "session"
        return "telegram-user"

    monkeypatch.setattr(
        scheduler_endpoint,
        "get_primary_platform_user_id",
        fake_get_primary_platform_user_id,
    )


def _patch_reload(monkeypatch):
    calls = []

    async def fake_reload_scheduler_runtime():
        calls.append("reload")

    monkeypatch.setattr(
        scheduler_endpoint,
        "_reload_scheduler_runtime",
        fake_reload_scheduler_runtime,
    )
    return calls


@pytest.mark.asyncio
async def test_scheduler_list_endpoint_returns_paused_tasks(monkeypatch):
    async def fake_get_all_scheduled_tasks(user_id):
        assert user_id == "telegram-user"
        return [
            {
                "id": 1,
                "crontab": "0 8 * * *",
                "instruction": "paused task",
                "is_active": False,
            }
        ]

    _patch_platform_uid(monkeypatch)
    monkeypatch.setattr(
        scheduler_endpoint.scheduler_store,
        "get_all_scheduled_tasks",
        fake_get_all_scheduled_tasks,
    )

    result = await scheduler_endpoint.get_tasks(
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert result == [
        {
            "id": 1,
            "crontab": "0 8 * * *",
            "instruction": "paused task",
            "is_active": False,
        }
    ]


@pytest.mark.asyncio
async def test_scheduler_create_endpoint_reloads_runtime(monkeypatch):
    async def fake_add_scheduled_task(
        crontab, instruction, user_id, run_calendar="always", **kwargs
    ):
        assert crontab == "15 8 * * *"
        assert instruction == "早报"
        assert user_id == "telegram-user"
        assert run_calendar == "trading_days"
        return 11

    _patch_platform_uid(monkeypatch)
    reload_calls = _patch_reload(monkeypatch)
    monkeypatch.setattr(
        scheduler_endpoint.scheduler_store,
        "add_scheduled_task",
        fake_add_scheduled_task,
    )

    result = await scheduler_endpoint.create_task(
        scheduler_endpoint.TaskCreate(
            crontab="15 8 * * *",
            instruction="早报",
            run_calendar="trading_days",
        ),
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert result == {"success": True}
    assert reload_calls == ["reload"]


@pytest.mark.asyncio
async def test_scheduler_update_endpoint_reloads_runtime(monkeypatch):
    async def fake_update_scheduled_task(
        task_id, user_id, *, crontab, instruction, run_calendar=None
    ):
        assert task_id == 9
        assert user_id == "telegram-user"
        assert crontab == "20 11 * * *"
        assert instruction is None
        assert run_calendar == "weekdays"
        return True

    _patch_platform_uid(monkeypatch)
    reload_calls = _patch_reload(monkeypatch)
    monkeypatch.setattr(
        scheduler_endpoint.scheduler_store,
        "update_scheduled_task",
        fake_update_scheduled_task,
    )

    result = await scheduler_endpoint.update_task(
        9,
        scheduler_endpoint.TaskUpdate(crontab="20 11 * * *", run_calendar="weekdays"),
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert result == {"success": True}
    assert reload_calls == ["reload"]


@pytest.mark.asyncio
async def test_scheduler_status_endpoint_reloads_runtime(monkeypatch):
    async def fake_update_task_status(task_id, is_active, user_id):
        assert task_id == 8
        assert is_active is False
        assert user_id == "telegram-user"
        return True

    _patch_platform_uid(monkeypatch)
    reload_calls = _patch_reload(monkeypatch)
    monkeypatch.setattr(
        scheduler_endpoint.scheduler_store,
        "update_task_status",
        fake_update_task_status,
    )

    result = await scheduler_endpoint.update_task_status(
        8,
        scheduler_endpoint.TaskStatusUpdate(is_active=False),
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert result == {"success": True}
    assert reload_calls == ["reload"]


@pytest.mark.asyncio
async def test_scheduler_delete_endpoint_reloads_runtime(monkeypatch):
    async def fake_delete_task(task_id, user_id):
        assert task_id == 7
        assert user_id == "telegram-user"

    _patch_platform_uid(monkeypatch)
    reload_calls = _patch_reload(monkeypatch)
    monkeypatch.setattr(
        scheduler_endpoint.scheduler_store,
        "delete_task",
        fake_delete_task,
    )

    result = await scheduler_endpoint.delete_task(
        7,
        current_user=SimpleNamespace(id=42),
        session="session",
    )

    assert result == {"success": True}
    assert reload_calls == ["reload"]
