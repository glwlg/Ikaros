from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.channel_runtime_store as channel_runtime_store_module
import core.heartbeat_store as heartbeat_store_module
import core.task_confirmation as task_confirmation_module
import core.task_manager as task_manager_module
import handlers.start_handlers as start_handlers
import user_context
from core.platform.models import Chat, MessageType, UnifiedMessage, User


class _DummyContext:
    def __init__(self, user_id: str, text: str = "/stop"):
        self.message = UnifiedMessage(
            id="m1",
            platform="telegram",
            user=User(id=user_id, username="tester"),
            chat=Chat(id=user_id, type="private"),
            date=datetime.now(),
            type=MessageType.TEXT,
            text=text,
        )
        self.replies: list[str] = []
        self.callback_data = ""
        self.callback_user_id = user_id

    async def reply(self, text, **kwargs):
        _ = kwargs
        self.replies.append(str(text))
        return SimpleNamespace(id="reply")

    async def answer_callback(self, *args, **kwargs):
        _ = (args, kwargs)
        return True


class _FakeTaskManager:
    def __init__(self, *, active_info=None, cancelled_desc=None):
        self.active_info = active_info
        self.cancelled_desc = cancelled_desc
        self.cancel_calls: list[str] = []

    def get_task_info(self, user_id: str):
        _ = user_id
        return self.active_info

    async def cancel_task(self, user_id: str):
        self.cancel_calls.append(str(user_id))
        return self.cancelled_desc


class _FakeHeartbeatStore:
    def __init__(self, active_task=None):
        self.active_task = active_task
        self.updated: list[tuple[str, dict]] = []
        self.released: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.delivery_targets: list[dict] = []

    async def get_session_active_task(self, user_id: str):
        _ = user_id
        return self.active_task

    def heartbeat_path(self, user_id: str):
        return Path(f"/tmp/{user_id}-heartbeat.md")

    async def update_session_active_task(self, user_id: str, **kwargs):
        self.updated.append((str(user_id), dict(kwargs)))

    async def release_lock(self, user_id: str):
        self.released.append(str(user_id))

    async def append_session_event(self, user_id: str, event: str):
        self.events.append((str(user_id), str(event)))

    async def set_delivery_target(
        self,
        user_id: str,
        platform: str,
        chat_id: str,
        *,
        session_id: str = "",
    ):
        self.delivery_targets.append(
            {
                "user_id": str(user_id),
                "platform": str(platform),
                "chat_id": str(chat_id),
                "session_id": str(session_id),
            }
        )


class _FakeChannelRuntimeStore:
    def __init__(self, active_task=None):
        self.active_task = active_task
        self.updated: list[dict] = []
        self.session_ids: list[dict] = []
        self.current_session_id = ""

    def get_active_task(self, *, platform: str = "", platform_user_id: str = "", runtime_key: str = ""):
        _ = (platform, platform_user_id, runtime_key)
        return self.active_task

    def update_active_task(
        self,
        *,
        platform: str = "",
        platform_user_id: str = "",
        runtime_key: str = "",
        **kwargs,
    ):
        payload = {
            "platform": str(platform),
            "platform_user_id": str(platform_user_id),
            "runtime_key": str(runtime_key),
        }
        payload.update(dict(kwargs))
        self.updated.append(payload)

    def set_session_id(
        self,
        *,
        session_id: str,
        platform: str = "",
        platform_user_id: str = "",
        runtime_key: str = "",
    ):
        self.current_session_id = str(session_id)
        self.session_ids.append(
            {
                "session_id": str(session_id),
                "platform": str(platform),
                "platform_user_id": str(platform_user_id),
                "runtime_key": str(runtime_key),
            }
        )

    def get_session_id(
        self,
        *,
        platform: str = "",
        platform_user_id: str = "",
        runtime_key: str = "",
    ):
        _ = (platform, platform_user_id, runtime_key)
        return self.current_session_id


class _FakeSubagentSupervisor:
    def __init__(self, result):
        self.result = dict(result)
        self.calls: list[dict] = []

    async def cancel_for_user(
        self, *, user_id: str, reason: str
    ):
        self.calls.append(
            {
                "user_id": str(user_id),
                "reason": str(reason),
            }
        )
        return dict(self.result)


class _FakeSessionTaskStore:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot

    async def get_active(self, _user_id: str):
        return self.snapshot

    async def get(self, _task_id: str):
        return self.snapshot


@pytest.mark.asyncio
async def test_stop_command_cancels_subagent_tasks_and_updates_heartbeat(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_task_manager = _FakeTaskManager(
        active_info={
            "todo_path": "/tmp/todo.md",
            "heartbeat_path": "/tmp/heartbeat.md",
            "active_task_id": "hb-1",
        },
        cancelled_desc="subagent_background",
    )
    fake_heartbeat_store = _FakeHeartbeatStore(active_task=None)
    fake_subagent_supervisor = _FakeSubagentSupervisor(
        {
            "cancelled": 3,
            "task_ids": ["j-1", "j-2", "j-3"],
        }
    )

    monkeypatch.setattr(task_manager_module, "task_manager", fake_task_manager)
    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "core.subagent_supervisor.subagent_supervisor",
        fake_subagent_supervisor,
    )
    monkeypatch.setattr(
        start_handlers,
        "session_task_store",
        _FakeSessionTaskStore(),
    )

    ctx = _DummyContext("u-stop")
    await start_handlers.stop_command(ctx)

    assert fake_task_manager.cancel_calls == ["u-stop"]
    assert fake_subagent_supervisor.calls == [
        {
            "user_id": "u-stop",
            "reason": "cancelled_by_stop_command",
        }
    ]
    assert fake_heartbeat_store.updated
    assert fake_heartbeat_store.released == ["u-stop"]
    assert fake_heartbeat_store.events == [("u-stop", "user_cancelled:hb-1")]

    assert len(ctx.replies) == 2
    final_text = ctx.replies[-1]
    assert "已中断任务" in final_text
    assert "已取消 3 个后台子任务" in final_text


@pytest.mark.asyncio
async def test_stop_command_reports_no_active_task(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_task_manager = _FakeTaskManager(active_info=None, cancelled_desc=None)
    fake_heartbeat_store = _FakeHeartbeatStore(active_task=None)
    fake_subagent_supervisor = _FakeSubagentSupervisor(
        {
            "cancelled": 0,
            "task_ids": [],
        }
    )

    monkeypatch.setattr(task_manager_module, "task_manager", fake_task_manager)
    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "core.subagent_supervisor.subagent_supervisor",
        fake_subagent_supervisor,
    )
    monkeypatch.setattr(
        start_handlers,
        "session_task_store",
        _FakeSessionTaskStore(),
    )

    ctx = _DummyContext("u-idle")
    await start_handlers.stop_command(ctx)

    assert fake_task_manager.cancel_calls == ["u-idle"]
    assert len(ctx.replies) == 2
    assert "当前没有正在执行的任务" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_stop_command_renders_session_brief_when_available(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_task_manager = _FakeTaskManager(
        active_info={
            "todo_path": "/tmp/todo.md",
            "heartbeat_path": "/tmp/heartbeat.md",
            "active_task_id": "tsk-session-1",
        },
        cancelled_desc="subagent_background",
    )
    fake_heartbeat_store = _FakeHeartbeatStore(active_task=None)
    fake_subagent_supervisor = _FakeSubagentSupervisor(
        {
            "cancelled": 1,
            "task_ids": ["j-1"],
        }
    )

    snapshot = SimpleNamespace(
        session_task_id="tsk-session-1",
        stage_index=2,
        stage_total=3,
        stage_title="验证结果并整理交付",
    )

    monkeypatch.setattr(task_manager_module, "task_manager", fake_task_manager)
    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "core.subagent_supervisor.subagent_supervisor",
        fake_subagent_supervisor,
    )
    monkeypatch.setattr(
        start_handlers,
        "session_task_store",
        _FakeSessionTaskStore(snapshot=snapshot),
    )

    ctx = _DummyContext("u-stop-brief")
    await start_handlers.stop_command(ctx)

    final_text = ctx.replies[-1]
    assert "任务：`tsk-session-1`" in final_text
    assert "阶段：2/3 - 验证结果并整理交付" in final_text


@pytest.mark.asyncio
async def test_button_callback_continue_resumes_waiting_task(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_heartbeat_store = _FakeHeartbeatStore(
        active_task={"id": "mgr-continue", "status": "waiting_user"}
    )

    class _FakeClosureService:
        def __init__(self):
            self.calls: list[dict] = []

        async def resume_waiting_task(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {"ok": True, "message": "✅ 已恢复执行，正在继续推进阶段 2/3。"}

    fake_service = _FakeClosureService()

    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        fake_service,
    )
    monkeypatch.setattr(
        start_handlers,
        "session_task_store",
        _FakeSessionTaskStore(),
    )

    ctx = _DummyContext("u-callback", text="noop")
    ctx.callback_data = "task_continue"

    result = await start_handlers.button_callback(ctx)

    assert result == start_handlers.CONVERSATION_END
    assert fake_service.calls == [
        {
            "user_id": "u-callback",
            "user_message": "",
            "source": "button",
        }
    ]
    assert fake_heartbeat_store.events == [
        ("u-callback", "user_confirm_continue:mgr-continue")
    ]
    assert "已恢复执行" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_button_callback_continue_expires_stale_confirmation(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    expired = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat(
        timespec="seconds"
    )
    fake_heartbeat_store = _FakeHeartbeatStore(
        active_task={
            "id": "mgr-expired",
            "status": "waiting_user",
            "confirmation_deadline": expired,
        }
    )
    fake_channel_store = _FakeChannelRuntimeStore(
        active_task={
            "id": "mgr-expired",
            "status": "waiting_user",
            "confirmation_deadline": expired,
        }
    )

    class _FakeClosureService:
        async def resume_waiting_task(self, **kwargs):
            _ = kwargs
            raise AssertionError("expired confirmation should not resume")

    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        channel_runtime_store_module,
        "channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        _FakeClosureService(),
    )

    ctx = _DummyContext("u-callback", text="noop")
    ctx.callback_data = "task_continue"

    result = await start_handlers.button_callback(ctx)

    assert result == start_handlers.CONVERSATION_END
    assert fake_channel_store.updated[-1]["clear_active"] is True
    assert fake_heartbeat_store.updated[-1][1]["clear_active"] is True
    assert fake_heartbeat_store.events == [
        ("u-callback", "confirmation_expired:mgr-expired")
    ]
    assert "已超过 3 分钟" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_button_callback_stop_closes_runtime_v2_waiting_task(
    monkeypatch,
    tmp_path,
):
    from core.runtime_v2 import RuntimeV2Store

    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    runtime_store = RuntimeV2Store(tmp_path / "runtime.db")
    monkeypatch.setattr(task_confirmation_module, "runtime_v2", runtime_store)
    session = runtime_store.ensure_session(
        session_id="telegram:u-callback:main",
        platform="telegram",
        platform_user_id="u-callback",
    )
    turn = runtime_store.create_turn(session_id=session["id"], status="running")
    turn = runtime_store.update_turn_status(turn["id"], "waiting_user")
    task = runtime_store.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="等待按钮确认",
        status="running",
    )
    task = runtime_store.update_task_status(task["id"], "waiting_user")
    active_task = {
        "id": "mgr-stop",
        "status": "waiting_user",
        "runtime_v2_session_id": session["id"],
        "runtime_v2_turn_id": turn["id"],
        "runtime_v2_task_id": task["id"],
    }
    fake_heartbeat_store = _FakeHeartbeatStore(active_task=active_task)
    fake_channel_store = _FakeChannelRuntimeStore(active_task=active_task)
    interrupt_calls: list[dict] = []

    async def _fake_interrupt(**kwargs):
        interrupt_calls.append(dict(kwargs))
        return None

    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        channel_runtime_store_module,
        "channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr(
        "core.codex_kernel.interrupt_codex_kernel_task",
        _fake_interrupt,
    )

    ctx = _DummyContext("u-callback", text="noop")
    ctx.callback_data = "task_stop"

    result = await start_handlers.button_callback(ctx)

    assert result == start_handlers.CONVERSATION_END
    assert interrupt_calls == [
        {"user_id": "u-callback", "task_id": "mgr-stop", "task_inbox_id": ""}
    ]
    assert fake_channel_store.updated[-1]["clear_active"] is True
    assert fake_heartbeat_store.updated[-1][1]["clear_active"] is True
    assert runtime_store.get_turn(turn["id"])["status"] == "cancelled"
    assert runtime_store.get_task(task["id"])["status"] == "cancelled"
    events = runtime_store.list_events(session_id=session["id"])
    assert events[-1]["type"] == "task.user_confirm_stop"
    assert "已停止" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_new_command_resets_active_task_state(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_task_manager = _FakeTaskManager(
        active_info={
            "active_task_id": "mgr-new-1",
        },
        cancelled_desc=None,
    )
    fake_heartbeat_store = _FakeHeartbeatStore(
        active_task={"id": "mgr-new-1", "status": "waiting_user"}
    )
    fake_channel_store = _FakeChannelRuntimeStore(
        active_task={"id": "mgr-new-1", "status": "waiting_user"}
    )
    fake_subagent_supervisor = _FakeSubagentSupervisor(
        {
            "cancelled": 1,
            "task_ids": ["subagent-1"],
        }
    )

    monkeypatch.setattr(task_manager_module, "task_manager", fake_task_manager)
    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        channel_runtime_store_module,
        "channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr(user_context, "channel_runtime_store", fake_channel_store)
    monkeypatch.setattr(
        "core.subagent_supervisor.subagent_supervisor",
        fake_subagent_supervisor,
    )

    ctx = _DummyContext("u-new", text="/new")
    await start_handlers.handle_new_command(ctx)

    assert fake_task_manager.cancel_calls == ["u-new"]
    assert fake_subagent_supervisor.calls == [
        {
            "user_id": "u-new",
            "reason": "reset_by_new_command",
        }
    ]
    assert fake_channel_store.updated == [
        {
            "platform": "telegram",
            "platform_user_id": "u-new",
            "runtime_key": "",
            "status": "cancelled",
            "needs_confirmation": False,
            "confirmation_deadline": "",
            "clear_active": True,
            "result_summary": "Reset by /new command.",
        }
    ]
    assert fake_heartbeat_store.updated == [
        (
            "u-new",
            {
                "status": "cancelled",
                "needs_confirmation": False,
                "confirmation_deadline": "",
                "clear_active": True,
                "result_summary": "Reset by /new command.",
            },
        )
    ]
    assert fake_heartbeat_store.released == ["u-new"]
    assert fake_heartbeat_store.events == [("u-new", "user_new_session:mgr-new-1")]
    assert fake_channel_store.session_ids
    assert "已开启新对话" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_scheduler_session_button_enters_and_main_command_exits(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(start_handlers, "check_permission_unified", _allow)

    fake_channel_store = _FakeChannelRuntimeStore()
    fake_heartbeat_store = _FakeHeartbeatStore(active_task=None)
    monkeypatch.setattr(
        channel_runtime_store_module,
        "channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr(heartbeat_store_module, "heartbeat_store", fake_heartbeat_store)

    ctx = _DummyContext("u-scheduler", text="")
    ctx.user_data = {"current_session_id": "main-session"}
    ctx.callback_data = "schsess_enter_9"

    await start_handlers.handle_scheduler_session_callback(ctx)

    assert ctx.user_data["current_session_id"] == "scheduler-task-9"
    assert ctx.user_data["codex_kernel_session_platform"] == "scheduler"
    assert ctx.user_data["codex_kernel_session_user_id"] == "user"
    assert (
        ctx.user_data[start_handlers.SCHEDULER_SESSION_RETURN_KEY]
        == "main-session"
    )
    assert fake_channel_store.session_ids[-1] == {
        "session_id": "scheduler-task-9",
        "platform": "telegram",
        "platform_user_id": "u-scheduler",
        "runtime_key": "",
    }
    assert fake_heartbeat_store.delivery_targets[-1]["session_id"] == "scheduler-task-9"
    assert "已进入定时任务 #9" in ctx.replies[-1]

    await start_handlers.main_session_command(ctx)

    assert ctx.user_data["current_session_id"] == "main-session"
    assert "codex_kernel_session_platform" not in ctx.user_data
    assert "codex_kernel_session_user_id" not in ctx.user_data
    assert fake_channel_store.session_ids[-1] == {
        "session_id": "main-session",
        "platform": "telegram",
        "platform_user_id": "u-scheduler",
        "runtime_key": "",
    }
    assert fake_heartbeat_store.delivery_targets[-1]["session_id"] == "main-session"
    assert "已回到主会话" in ctx.replies[-1]
