from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import handlers.task_handlers as task_handlers_module
from core.platform.models import PlatformCapabilities
from core.runtime_v2 import runtime_v2
from core.skill_menu import make_callback
from core.task_inbox import task_inbox
from handlers import task_command as exported_task_command
from handlers.task_handlers import TASK_MENU_NS, handle_task_callback, task_command


class _FakeUser:
    def __init__(self, user_id: str):
        self.id = user_id


class _FakeMessage:
    def __init__(self, text: str, user_id: str):
        self.id = "msg-task"
        self.text = text
        self.user = _FakeUser(user_id)
        self.platform = "telegram"
        self.chat = SimpleNamespace(id=f"chat-{user_id}")


class _FakeContext:
    def __init__(self, text: str, user_id: str = "u-task"):
        self.message = _FakeMessage(text, user_id)
        self.user_data: dict = {}
        self.callback_data: str | None = None
        self.replies: list[str] = []
        self.edits: list[str] = []
        self.edited_uis: list[dict | None] = []
        self.callback_answers = 0

    async def reply(self, text: str, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(id="reply")

    async def edit_message(self, message_id: str, text: str, **kwargs):
        self.edits.append(text)
        self.edited_uis.append(kwargs.get("ui"))
        return SimpleNamespace(id=message_id)

    async def answer_callback(self, *args, **kwargs):
        self.callback_answers += 1


@pytest.fixture(autouse=True)
def _isolate_runtime_v2(monkeypatch, tmp_path):
    monkeypatch.setenv("IKAROS_RUNTIME_DB_PATH", str(tmp_path / "runtime.db"))


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


@pytest.mark.asyncio
async def test_task_command_lists_recent_ikaros_tasks(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    first = await task_inbox.submit(
        source="user_chat",
        goal="修复 PR 冲突并重新提交",
        user_id="u-task",
    )
    second = await task_inbox.submit(
        source="heartbeat",
        goal="检查未完成任务并完成他们",
        user_id="u-task",
        metadata={
            "followup": {
                "done_when": "GitHub pull request merged",
                "refs": {"pr_url": "https://github.com/example/repo/pull/42"},
            }
        },
    )
    await task_inbox.update_status(first.task_id, "running", event="work_started")
    await task_inbox.update_status(
        second.task_id,
        "waiting_external",
        event="followup_waiting",
    )

    ctx = _FakeContext("/task", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    reply = ctx.replies[-1]
    assert "最近 10 个任务" in reply
    assert second.task_id in reply
    assert "waiting_external" in reply
    assert "GitHub pull request merged" in reply
    assert "pull/42" in reply
    assert "waiting_external | heartbeat" in reply


@pytest.mark.asyncio
async def test_task_command_recent_alias_and_limit_10(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    for idx in range(12):
        task = await task_inbox.submit(
            source="user_chat",
            goal=f"任务-{idx}",
            user_id="u-task",
        )
        await task_inbox.update_status(task.task_id, "completed", event="done")

    ctx = _FakeContext("/task recent", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    reply = ctx.replies[-1]
    assert reply.count("- `") == 10


@pytest.mark.asyncio
async def test_task_command_skips_heartbeat_tasks_by_default(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    user_task = await task_inbox.submit(
        source="user_chat",
        goal="用户发起的任务",
        user_id="u-task",
    )
    heartbeat_task = await task_inbox.submit(
        source="heartbeat",
        goal="heartbeat 跟进任务",
        user_id="u-task",
    )
    await task_inbox.update_status(user_task.task_id, "running", event="running")
    await task_inbox.update_status(
        heartbeat_task.task_id,
        "running",
        event="running",
    )

    ctx = _FakeContext("/task", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    reply = ctx.replies[-1]
    assert user_task.task_id in reply
    assert heartbeat_task.task_id not in reply


@pytest.mark.asyncio
async def test_task_command_keeps_heartbeat_followup_tasks(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    heartbeat_followup = await task_inbox.submit(
        source="heartbeat",
        goal="heartbeat 跟进 PR",
        user_id="u-task",
        metadata={
            "followup": {
                "done_when": "GitHub pull request merged",
            }
        },
    )
    await task_inbox.update_status(
        heartbeat_followup.task_id,
        "waiting_external",
        event="followup_waiting",
    )

    ctx = _FakeContext("/task", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    assert heartbeat_followup.task_id in ctx.replies[-1]


@pytest.mark.asyncio
async def test_active_confirmation_row_clears_expired_waiting_task(monkeypatch):
    expired_active = {
        "id": "mgr-expired",
        "status": "waiting_user",
        "confirmation_deadline": "2000-01-01T00:00:00+00:00",
    }
    channel_updates: list[dict] = []
    heartbeat_updates: list[tuple[str, dict]] = []
    released: list[str] = []
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        task_handlers_module.channel_runtime_store,
        "get_active_task",
        lambda **_kwargs: expired_active,
    )
    monkeypatch.setattr(
        task_handlers_module.channel_runtime_store,
        "update_active_task",
        lambda **kwargs: channel_updates.append(dict(kwargs)),
    )

    async def _update_active(user_id: str, **kwargs):
        heartbeat_updates.append((str(user_id), dict(kwargs)))

    async def _release(user_id: str):
        released.append(str(user_id))

    async def _append_event(user_id: str, event: str):
        events.append((str(user_id), str(event)))

    monkeypatch.setattr(
        task_handlers_module.heartbeat_store,
        "update_session_active_task",
        _update_active,
    )
    monkeypatch.setattr(task_handlers_module.heartbeat_store, "release_lock", _release)
    monkeypatch.setattr(
        task_handlers_module.heartbeat_store,
        "append_session_event",
        _append_event,
    )

    row = await task_handlers_module._active_confirmation_row("u-task")

    assert row == []
    assert channel_updates[-1]["clear_active"] is True
    assert heartbeat_updates[-1][1]["clear_active"] is True
    assert released == ["u-task"]
    assert events == [("u-task", "confirmation_expired:mgr-expired")]


@pytest.mark.asyncio
async def test_task_command_hides_completed_heartbeat_followup_tasks(
    monkeypatch, tmp_path
):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    completed_followup = await task_inbox.submit(
        source="heartbeat",
        goal="heartbeat 已完成的 PR 跟进",
        user_id="u-task",
        metadata={
            "followup": {
                "done_when": "GitHub pull request merged",
            }
        },
    )
    await task_inbox.update_status(
        completed_followup.task_id,
        "completed",
        event="completed",
        result={"summary": "PR 已关闭，无需继续跟进。"},
        output={"text": "PR 已关闭，无需继续跟进。"},
    )

    ctx = _FakeContext("/task", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    assert completed_followup.task_id not in ctx.replies[-1]


@pytest.mark.asyncio
async def test_task_command_rejects_unknown_subcommand(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    ctx = _FakeContext("/task foo", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    assert "用法" in ctx.replies[-1]


@pytest.mark.asyncio
async def test_task_command_open_only_lists_unfinished_tasks(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    open_task = await task_inbox.submit(
        source="user_chat",
        goal="仍在处理中的任务",
        user_id="u-task",
    )
    done_task = await task_inbox.submit(
        source="user_chat",
        goal="已经完成的任务",
        user_id="u-task",
    )
    await task_inbox.update_status(open_task.task_id, "waiting_external", event="wait")
    await task_inbox.update_status(done_task.task_id, "completed", event="done")

    ctx = _FakeContext("/task open", user_id="u-task")
    await task_command(ctx)

    assert ctx.replies
    reply = ctx.replies[-1]
    assert open_task.task_id in reply
    assert done_task.task_id not in reply


@pytest.mark.asyncio
async def test_task_command_lists_runtime_v2_tasks_first_and_deduplicates_legacy(
    monkeypatch, tmp_path
):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    legacy_task = await task_inbox.submit(
        source="user_chat",
        goal="旧 inbox 里的同一个任务",
        user_id="u-task",
    )
    await task_inbox.update_status(legacy_task.task_id, "running", event="running")
    session = runtime_v2.ensure_session(
        session_id="telegram:u-task:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u-task",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="user",
        input_text="Runtime v2 任务",
        status="running",
        kernel_provider="codex",
    )
    runtime_task = runtime_v2.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="Runtime v2 任务",
        status="running",
        metadata={
            "source": "user_chat",
            "task_inbox_id": legacy_task.task_id,
        },
    )

    ctx = _FakeContext("/task open", user_id="u-task")
    await task_command(ctx)

    reply = ctx.replies[-1]
    assert runtime_task["id"] in reply
    assert legacy_task.task_id not in reply
    assert "kernel:codex" in reply


@pytest.mark.asyncio
async def test_task_menu_can_delete_runtime_v2_task(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    session = runtime_v2.ensure_session(
        session_id="telegram:u-task:main",
        kind="channel_chat",
        platform="telegram",
        platform_user_id="u-task",
    )
    turn = runtime_v2.create_turn(
        session_id=session["id"],
        source="user",
        input_text="Runtime v2 删除测试",
        status="running",
    )
    runtime_task = runtime_v2.create_task(
        session_id=session["id"],
        turn_id=turn["id"],
        goal="Runtime v2 删除测试",
        status="waiting_external",
        metadata={"source": "user_chat"},
    )

    ctx = _FakeContext("/task open", user_id="u-task")
    await task_command(ctx)

    ctx.callback_data = make_callback(TASK_MENU_NS, "delete", "open", 0, runtime_task["id"])
    await handle_task_callback(ctx)
    assert "确认删除任务" in ctx.edits[-1]

    ctx.callback_data = make_callback(
        TASK_MENU_NS,
        "deleteconfirm",
        "open",
        0,
        runtime_task["id"],
    )
    await handle_task_callback(ctx)

    deleted = runtime_v2.get_task(runtime_task["id"])
    assert deleted["status"] == "cancelled"
    assert deleted["metadata"]["deleted"] is True
    assert runtime_v2.list_tasks_for_user(platform_user_id="u-task") == []
    assert "已删除任务" in ctx.edits[-1]


@pytest.mark.asyncio
async def test_task_menu_can_delete_task_and_clear_active_state(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    task = await task_inbox.submit(
        source="heartbeat",
        goal="总会失败的跟进任务",
        user_id="u-task",
    )
    await task_inbox.update_status(task.task_id, "waiting_external", event="wait")

    update_calls: list[dict] = []
    session_events: list[tuple[str, str]] = []
    active = {
        "id": task.task_id,
        "task_inbox_id": task.task_id,
        "session_task_id": task.task_id,
        "status": "waiting_external",
    }

    async def _get_active(_user_id: str):
        return active

    async def _update_active(_user_id: str, **kwargs):
        update_calls.append(dict(kwargs))
        return None

    async def _append_event(user_id: str, message: str):
        session_events.append((user_id, message))

    monkeypatch.setattr(
        task_handlers_module.heartbeat_store,
        "get_session_active_task",
        _get_active,
    )
    monkeypatch.setattr(
        task_handlers_module.heartbeat_store,
        "update_session_active_task",
        _update_active,
    )
    monkeypatch.setattr(
        task_handlers_module.heartbeat_store,
        "append_session_event",
        _append_event,
    )

    ctx = _FakeContext("/task open", user_id="u-task")
    await task_command(ctx)

    ctx.callback_data = make_callback(TASK_MENU_NS, "delete", "open", 0, task.task_id)
    await handle_task_callback(ctx)

    assert ctx.edits
    assert "确认删除任务" in ctx.edits[-1]

    ctx.callback_data = make_callback(
        TASK_MENU_NS,
        "deleteconfirm",
        "open",
        0,
        task.task_id,
    )
    await handle_task_callback(ctx)

    assert await task_inbox.get(task.task_id) is None
    assert any(call.get("clear_active") is True for call in update_calls)
    assert session_events == [("u-task", f"user_deleted_task:{task.task_id}")]
    assert "已删除任务" in ctx.edits[-1]


@pytest.mark.asyncio
async def test_task_menu_delete_callbacks_fit_telegram_limit(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    task = await task_inbox.submit(
        source="user_chat",
        goal="删除一个最近任务，确保 Telegram callback_data 不超长",
        user_id="u-task",
    )

    ctx = _FakeContext("/task recent", user_id="u-task")
    await task_command(ctx)

    ctx.callback_data = make_callback(TASK_MENU_NS, "show", "recent", 0)
    await handle_task_callback(ctx)

    detail_ui = ctx.edited_uis[-1]
    delete_callback = detail_ui["actions"][0][0]["callback_data"]
    assert len(delete_callback.encode("utf-8")) <= 64

    ctx.callback_data = delete_callback
    await handle_task_callback(ctx)

    confirm_ui = ctx.edited_uis[-1]
    confirm_callback = confirm_ui["actions"][0][0]["callback_data"]
    assert len(confirm_callback.encode("utf-8")) <= 64

    ctx.callback_data = confirm_callback
    await handle_task_callback(ctx)

    assert await task_inbox.get(task.task_id) is None
    assert "已删除任务" in ctx.edits[-1]


@pytest.mark.asyncio
async def test_task_detail_shows_artifact_delivery_summary(monkeypatch, tmp_path):
    _reset_task_inbox(tmp_path)

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)

    task = await task_inbox.submit(
        source="user_chat",
        goal="生成一张图",
        user_id="u-task",
    )
    await task_inbox.append_event(
        task.task_id,
        "artifact_delivery",
        detail="delivered=1; failed=1",
        extra={
            "delivered": [{"filename": "ok.png", "kind": "photo"}],
            "failed": [{"filename": "lost.mp4", "kind": "video"}],
        },
    )

    ctx = _FakeContext("/task recent", user_id="u-task")
    await task_command(ctx)

    ctx.callback_data = make_callback(TASK_MENU_NS, "show", "recent", 0)
    await handle_task_callback(ctx)

    assert "附件投递" in ctx.edits[-1]
    assert "delivered=1; failed=1" in ctx.edits[-1]


@pytest.mark.asyncio
async def test_task_diag_shows_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _reset_task_inbox(tmp_path)
    task_handlers_module.heartbeat_store.root = (tmp_path / "runtime_tasks").resolve()
    task_handlers_module.heartbeat_store.root.mkdir(parents=True, exist_ok=True)
    task_handlers_module.heartbeat_store._locks.clear()

    async def _allow(_ctx):
        return True

    monkeypatch.setattr("handlers.task_handlers.check_permission_unified", _allow)
    monkeypatch.setattr(task_handlers_module, "ikaros_kernel_provider", lambda: "codex")
    monkeypatch.setattr(
        task_handlers_module,
        "adapter_manager",
        SimpleNamespace(
            _adapters={
                "telegram": SimpleNamespace(
                    capabilities=PlatformCapabilities(
                        edit_message=True,
                        reply_photo=True,
                        reply_video=True,
                        reply_audio=True,
                        reply_document=True,
                    )
                ),
                "weixin": SimpleNamespace(
                    capabilities=PlatformCapabilities(
                        edit_message=False,
                        reply_photo=True,
                        reply_video=False,
                        reply_audio=True,
                        reply_document=True,
                    )
                ),
            }
        ),
    )

    task = await task_inbox.submit(
        source="user_chat",
        goal="生成图片",
        user_id="u-task",
    )
    await task_inbox.update_status(task.task_id, "running", event="running")
    task_handlers_module.channel_runtime_store.set_session_id(
        session_id="sess-diag",
        platform="telegram",
        platform_user_id="u-task",
    )
    task_handlers_module.channel_runtime_store.set_active_task(
        {
            "id": "active-diag",
            "status": "running",
            "goal": "生成图片",
            "kernel_provider": "codex",
        },
        platform="telegram",
        platform_user_id="u-task",
    )
    await task_handlers_module.heartbeat_store.set_delivery_target(
        "u-task",
        "telegram",
        "chat-u-task",
        session_id="sess-diag",
    )
    task_handlers_module.codex_kernel_sessions.upsert(
        user_id="u-task",
        platform="telegram",
        session_id="sess-diag",
        codex_thread_id="thread-diag",
        codex_turn_id="turn-diag",
    )

    ctx = _FakeContext("/task diag", user_id="u-task")
    ctx.user_data["artifact_ledger"] = [
        {"status": "delivered", "filename": "ok.png"},
        {"status": "failed", "filename": "bad.mp4"},
    ]
    await task_command(ctx)

    reply = ctx.replies[-1]
    assert "Ikaros 运行诊断" in reply
    assert "Kernel：`codex`" in reply
    assert "Channels：telegram(edit; photo+video+audio+document)" in reply
    assert "weixin(no-edit; photo+audio+document)" in reply
    assert "channel active：`active-diag`" in reply
    assert "TaskInbox：open=1" in reply
    assert "Artifact ledger：delivered=1; failed=1; pending=0" in reply
    assert "近期质量：failed=0; artifact_failed=0" in reply
    assert "Codex thread：`thread-diag`" in reply


def test_task_command_is_exported_from_handlers_package():
    assert exported_task_command is task_command


def test_core_commands_plugin_registers_task_command():
    plugin_py = (
        Path(__file__).resolve().parents[2] / "extension" / "plugins" / "core_commands.py"
    )
    text = plugin_py.read_text(encoding="utf-8")

    assert 'register_command("task", task_command' in text
