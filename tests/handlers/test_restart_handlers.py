from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import asyncio

import handlers.restart_handlers as restart_handlers
from core.platform.models import Chat, MessageType, UnifiedMessage, User
from handlers import restart_command as exported_restart_command


class _DummyContext:
    def __init__(self, text: str = "/restart", user_id: str = "u-restart"):
        self.message = UnifiedMessage(
            id="m-restart",
            platform="telegram",
            user=User(id=user_id, username="tester"),
            chat=Chat(id=user_id, type="private"),
            date=datetime.now(),
            type=MessageType.TEXT,
            text=text,
        )
        self.replies: list[str] = []

    async def reply(self, text, **kwargs):
        _ = kwargs
        self.replies.append(str(text))
        return SimpleNamespace(id="reply")


class _FakeStatusProcess:
    def __init__(self, returncode: int = 0, output: str = ""):
        self.returncode = returncode
        self._output = output

    async def communicate(self):
        return self._output.encode("utf-8"), b""


class _FakePopen:
    def __init__(self, pid: int = 4321):
        self.pid = pid


@pytest.mark.asyncio
async def test_restart_command_requires_admin(monkeypatch):
    async def _allow(_ctx):
        return True

    monkeypatch.setattr(restart_handlers, "check_permission_unified", _allow)
    monkeypatch.setattr(restart_handlers, "is_user_admin", lambda _user_id: False)

    ctx = _DummyContext("/restart")
    await restart_handlers.restart_command(ctx)

    assert ctx.replies == ["❌ 只有管理员可以执行此操作"]


@pytest.mark.asyncio
async def test_restart_command_returns_status_output(monkeypatch, tmp_path):
    async def _allow(_ctx):
        return True

    script_path = (tmp_path / "restart_services.sh").resolve()
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    monkeypatch.setattr(restart_handlers, "check_permission_unified", _allow)
    monkeypatch.setattr(restart_handlers, "is_user_admin", lambda _user_id: True)
    monkeypatch.setattr(restart_handlers, "_restart_script_path", lambda: script_path)

    async def _fake_create_subprocess_exec(*args, **kwargs):
        _ = args
        _ = kwargs
        return _FakeStatusProcess(
            returncode=0,
            output="ikaros: mode=shell_bg state=running\nikaros-api: mode=systemd_system state=active",
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    ctx = _DummyContext("/restart status")
    await restart_handlers.restart_command(ctx)

    assert ctx.replies
    reply = ctx.replies[-1]
    assert "Restart 状态" in reply
    assert "ikaros: mode=shell_bg state=running" in reply
    assert "ikaros-api: mode=systemd_system state=active" in reply


@pytest.mark.asyncio
async def test_restart_command_spawns_background_script(monkeypatch, tmp_path):
    async def _allow(_ctx):
        return True

    script_path = (tmp_path / "restart_services.sh").resolve()
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    log_path = (tmp_path / "restart-command.out.log").resolve()

    monkeypatch.setattr(restart_handlers, "check_permission_unified", _allow)
    monkeypatch.setattr(restart_handlers, "is_user_admin", lambda _user_id: True)
    monkeypatch.setattr(restart_handlers, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(restart_handlers, "_restart_log_path", lambda: log_path)

    popen_calls: list[dict] = []

    def _fake_popen(args, **kwargs):
        popen_calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return _FakePopen(pid=9876)

    monkeypatch.setattr(restart_handlers.subprocess, "Popen", _fake_popen)

    ctx = _DummyContext("/restart api")
    await restart_handlers.restart_command(ctx)

    assert popen_calls
    assert popen_calls[0]["args"] == ["bash", str(script_path), "api"]
    assert popen_calls[0]["kwargs"]["start_new_session"] is True
    assert ctx.replies
    reply = ctx.replies[-1]
    assert "已触发重启" in reply
    assert "9876" in reply
    assert str(log_path) in reply


def test_restart_command_is_exported_from_handlers_package():
    assert exported_restart_command is restart_handlers.restart_command


def test_core_commands_plugin_registers_restart_command():
    plugin_py = (
        Path(__file__).resolve().parents[2] / "extension" / "plugins" / "core_commands.py"
    )
    text = plugin_py.read_text(encoding="utf-8")

    assert 'register_command("restart", restart_command' in text
