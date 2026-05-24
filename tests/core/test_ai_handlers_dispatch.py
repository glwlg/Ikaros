import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from pathlib import Path

import pytest

from handlers import ai_handlers


@pytest.mark.asyncio
async def test_fetch_user_memory_snapshot_reads_markdown_store(monkeypatch):
    async def _fake_load_snapshot(_uid: str, **kwargs):
        del kwargs
        return "【长期记忆】\n- 居住地：江苏无锡"

    monkeypatch.setattr(
        ai_handlers.long_term_memory,
        "load_user_snapshot",
        _fake_load_snapshot,
    )
    rendered = await ai_handlers._fetch_user_memory_snapshot("u-1")
    assert "居住地：江苏无锡" in rendered


@pytest.mark.asyncio
async def test_should_include_memory_summary_for_task_requires_nonempty_request():
    assert await ai_handlers._should_include_memory_summary_for_task("部署这个仓库", "") is True
    assert await ai_handlers._should_include_memory_summary_for_task("", "上下文") is False


@pytest.mark.asyncio
async def test_build_subagent_instruction_with_context_uses_ikaros_memory(monkeypatch):
    async def _fake_collect(
        _ctx, *, user_id, current_user_message, max_messages=6, max_chars=1200
    ):
        del user_id, current_user_message, max_messages, max_chars
        return "- 用户: 上次让你记住我住在江苏无锡"

    async def _fake_fetch(_uid: str):
        return "- 居住地：江苏无锡"

    async def _fake_need_memory(_msg: str, _ctx: str) -> bool:
        return True

    monkeypatch.setattr(ai_handlers, "_collect_recent_dialog_context", _fake_collect)
    monkeypatch.setattr(ai_handlers, "_fetch_user_memory_snapshot", _fake_fetch)
    monkeypatch.setattr(
        ai_handlers, "_should_include_memory_summary_for_task", _fake_need_memory
    )

    instruction, meta = await ai_handlers._build_subagent_instruction_with_context(
        SimpleNamespace(),
        user_id="u-1",
        user_message="我住哪",
        subagent_has_memory=False,
    )
    assert "【用户记忆摘要（由 Ikaros 提供）】" in instruction
    assert meta["memory_summary_requested"] is True
    assert meta["memory_summary_included"] is True


@pytest.mark.asyncio
async def test_build_subagent_instruction_skips_memory_in_group_session(monkeypatch):
    async def _fake_collect(
        _ctx, *, user_id, current_user_message, max_messages=6, max_chars=1200
    ):
        del user_id, current_user_message, max_messages, max_chars
        return "- 用户: 我住在江苏无锡"

    async def _fake_fetch(_uid: str):
        raise AssertionError("group session should not load personal memory")

    async def _fake_need_memory(_msg: str, _ctx: str) -> bool:
        return True

    ctx = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(type="group")))
    monkeypatch.setattr(ai_handlers, "_collect_recent_dialog_context", _fake_collect)
    monkeypatch.setattr(ai_handlers, "_fetch_user_memory_snapshot", _fake_fetch)
    monkeypatch.setattr(
        ai_handlers, "_should_include_memory_summary_for_task", _fake_need_memory
    )

    instruction, meta = await ai_handlers._build_subagent_instruction_with_context(
        ctx,
        user_id="u-1",
        user_message="我住哪",
        subagent_has_memory=False,
    )
    assert "【用户记忆摘要（由 Ikaros 提供）】" not in instruction
    assert meta["private_session"] is False
    assert meta["memory_summary_requested"] is False


@pytest.mark.asyncio
async def test_build_subagent_instruction_with_context_skips_memory_when_subagent_has_it(
    monkeypatch,
):
    async def _fake_collect(
        _ctx, *, user_id, current_user_message, max_messages=6, max_chars=1200
    ):
        del user_id, current_user_message, max_messages, max_chars
        return ""

    async def _fake_fetch(_uid: str):
        raise AssertionError("should not fetch memory when subagent_has_memory=True")

    async def _fake_need_memory(_msg: str, _ctx: str) -> bool:
        return True

    monkeypatch.setattr(ai_handlers, "_collect_recent_dialog_context", _fake_collect)
    monkeypatch.setattr(ai_handlers, "_fetch_user_memory_snapshot", _fake_fetch)
    monkeypatch.setattr(
        ai_handlers, "_should_include_memory_summary_for_task", _fake_need_memory
    )

    instruction, meta = await ai_handlers._build_subagent_instruction_with_context(
        SimpleNamespace(),
        user_id="u-2",
        user_message="按我偏好推荐新闻",
        subagent_has_memory=True,
    )
    assert "【用户记忆摘要（由 Ikaros 提供）】" not in instruction
    assert meta["memory_summary_requested"] is True
    assert meta["memory_summary_included"] is False


@pytest.mark.asyncio
async def test_build_subagent_instruction_with_context_skips_memory_when_request_empty(
    monkeypatch,
):
    async def _fake_collect(
        _ctx, *, user_id, current_user_message, max_messages=6, max_chars=1200
    ):
        del user_id, current_user_message, max_messages, max_chars
        return "- 用户: 请部署仓库"

    async def _fake_fetch(_uid: str):
        raise AssertionError("should not fetch memory when not needed")

    monkeypatch.setattr(ai_handlers, "_collect_recent_dialog_context", _fake_collect)
    monkeypatch.setattr(ai_handlers, "_fetch_user_memory_snapshot", _fake_fetch)

    instruction, meta = await ai_handlers._build_subagent_instruction_with_context(
        SimpleNamespace(),
        user_id="u-3",
        user_message="",
        subagent_has_memory=False,
    )
    assert "【近期对话上下文】" in instruction
    assert "【用户记忆摘要（由 Ikaros 提供）】" not in instruction
    assert meta["memory_summary_requested"] is False
    assert meta["memory_summary_included"] is False


def test_pop_pending_ui_payload_merges_blocks():
    user_data = {
        "pending_ui": [
            {
                "actions": [
                    [{"text": "刷新", "callback_data": "rss_refresh"}],
                ]
            },
            {
                "actions": [
                    [{"text": "取消", "callback_data": "rss_cancel"}],
                ]
            },
        ]
    }

    ui_payload = ai_handlers._pop_pending_ui_payload(user_data)
    assert "pending_ui" not in user_data
    assert ui_payload is not None
    assert len(ui_payload["actions"]) == 2
    assert ui_payload["actions"][0][0]["text"] == "刷新"
    assert ui_payload["actions"][1][0]["text"] == "取消"


def test_stream_cut_index_prefers_sentence_boundary():
    text = "第一段内容。\n第二段内容继续输出"
    cut = ai_handlers._stream_cut_index(text, 14)
    assert cut <= 14
    assert cut >= 6
    assert text[:cut].endswith(("。", "\n"))


def test_stream_cut_index_falls_back_to_limit_without_boundary():
    text = "abcdefghijklmnopqrstuvwxyz"
    cut = ai_handlers._stream_cut_index(text, 10)
    assert cut == 10


def test_summarize_ikaros_tool_args_for_bash_command():
    label, value = ai_handlers._summarize_ikaros_tool_args(
        "bash",
        {"command": "docker stop uptime-kuma"},
    )

    assert label == "命令"
    assert value == "docker stop uptime-kuma"


def test_build_ikaros_progress_text_includes_command_and_result():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "tool_call_finished",
            "task_id": "mgr-1",
            "turn": 3,
            "recent_steps": [
                {
                    "name": "bash",
                    "status": "done",
                    "summary": "Command executed with code 0",
                    "detail_label": "命令",
                    "detail": "docker stop uptime-kuma",
                }
            ],
        }
    )

    assert "任务ID：`mgr-1`" in text
    assert "动作：`Shell` 执行完成" in text
    assert "命令：`docker stop uptime-kuma`" in text
    assert "结果：Command executed with code 0" in text


def test_build_ikaros_progress_text_hides_verbose_tool_output():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "tool_call_finished",
            "task_id": "mgr-verbose",
            "turn": 2,
            "recent_steps": [
                {
                    "name": "load_skill",
                    "status": "done",
                    "summary": "{'ok': True, 'content': '# Daily Query\\n\\n这是日常基础查询 skill...'}",
                    "detail_label": "技能",
                    "detail": "daily_query",
                }
            ],
        }
    )

    assert "技能：`daily_query`" in text
    assert "结果：技能已加载，正在继续执行。" in text
    assert "Daily Query" not in text


def test_build_ikaros_progress_text_hides_internal_preflight_success():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "tool_call_finished",
            "task_id": "mgr-auth-probe",
            "turn": 4,
            "ok": True,
            "history_visibility": "suppress_success",
            "recent_steps": [
                {
                    "name": "gh_cli",
                    "status": "done",
                    "summary": "auth probe ok for github.com",
                    "detail_label": "操作",
                    "detail": "auth_status",
                    "history_visibility": "suppress_success",
                }
            ],
        }
    )

    assert "结果：" not in text


def test_build_ikaros_progress_text_omits_final_response_action_line():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "final_response",
            "task_id": "mgr-final",
            "turn": 1,
            "final_preview": "你好呀，主人，今天想让我帮你做什么呀？",
        }
    )

    assert "任务ID：`mgr-final`" in text
    assert "摘要：你好呀，主人，今天想让我帮你做什么呀？" in text
    assert "动作：" not in text


def test_build_ikaros_progress_text_includes_codex_stream_preview():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "codex_agent_message",
            "task_id": "task-codex",
            "turn": 1,
            "final_preview": "正在检查代码。",
        }
    )

    assert text == "正在检查代码。"


def test_build_ikaros_progress_text_includes_codex_activity_preview():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "codex_activity",
            "task_id": "task-codex",
            "turn": 1,
            "final_preview": "搜索：今天 科技新闻",
        }
    )

    assert text == "搜索：今天 科技新闻"


def test_build_ikaros_progress_text_does_not_render_codex_command_output():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "codex_command_output",
            "task_id": "task-codex",
            "turn": 1,
            "summary": "pytest passed",
        }
    )

    assert "pytest passed" not in text
    assert "命令有输出" not in text


@pytest.mark.asyncio
async def test_send_result_files_returns_only_delivered_rows(tmp_path):
    image_path = tmp_path / "ok.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nok")
    missing_path = tmp_path / "missing.mp4"
    sent: list[tuple[str, str]] = []
    warnings: list[str] = []

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.message = SimpleNamespace(
                platform="telegram",
                chat=SimpleNamespace(id="chat-1"),
            )

        async def reply_photo(self, path, caption=None):
            sent.append(("photo", str(path)))
            return SimpleNamespace(id="photo-1")

        async def reply_video(self, path, caption=None):
            sent.append(("video", str(path)))
            return SimpleNamespace(id="video-1")

        async def reply_audio(self, path, caption=None):
            sent.append(("audio", str(path)))
            return SimpleNamespace(id="audio-1")

        async def reply_document(self, **kwargs):
            sent.append(("document", str(kwargs.get("filename") or "")))
            return SimpleNamespace(id="doc-1")

        async def reply(self, text, **kwargs):
            _ = kwargs
            warnings.append(str(text))
            return SimpleNamespace(id="warn-1")

    ctx = _Ctx()
    delivered = await ai_handlers._send_result_files(
        ctx,
        [
            {"kind": "photo", "path": str(image_path), "filename": "ok.png"},
            {"kind": "video", "path": str(missing_path), "filename": "missing.mp4"},
        ],
    )

    assert delivered == [
        {
            "path": str(image_path.resolve()),
            "kind": "photo",
            "filename": "ok.png",
            "caption": "",
        }
    ]
    assert sent == [("photo", str(image_path.resolve()))]
    assert "附件未能发送" in warnings[0]
    assert [
        (row["kind"], row["filename"], row["status"], row["target"])
        for row in ctx.user_data["artifact_ledger"]
    ] == [
        ("photo", "ok.png", "delivered", "telegram:chat-1"),
        ("video", "missing.mp4", "failed", "telegram:chat-1"),
    ]


@pytest.mark.asyncio
async def test_send_result_files_respects_adapter_capabilities(tmp_path):
    from core.platform.models import PlatformCapabilities

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    warnings: list[str] = []

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self._adapter = SimpleNamespace(
                capabilities=PlatformCapabilities(reply_video=False)
            )
            self.message = SimpleNamespace(
                platform="telegram",
                chat=SimpleNamespace(id="chat-1"),
            )

        async def reply_video(self, *_args, **_kwargs):
            raise AssertionError("unsupported video delivery should not be attempted")

        async def reply(self, text, **kwargs):
            _ = kwargs
            warnings.append(str(text))
            return SimpleNamespace(id="warn-1")

    ctx = _Ctx()
    delivered = await ai_handlers._send_result_files(
        ctx,
        [{"kind": "video", "path": str(video_path), "filename": "clip.mp4"}],
    )

    assert delivered == []
    assert "附件未能发送" in warnings[0]
    assert ctx.user_data["artifact_ledger"][0]["status"] == "failed"
    assert ctx.user_data["artifact_ledger"][0]["filename"] == "clip.mp4"


def test_build_ikaros_progress_text_includes_loop_guard_details():
    text = ai_handlers._build_ikaros_progress_text(
        {
            "event": "loop_guard",
            "task_id": "mgr-loop",
            "turn": 2,
            "repeat_details": (
                "第1次（回合 1）：`read` 参数 {\"path\": \"a.txt\"}\n"
                "第2次（回合 2）：`read` 参数 {\"path\": \"a.txt\"}"
            ),
        }
    )

    assert "动作：检测到重复调用，已触发循环保护" in text
    assert "重复调用：" in text
    assert "\"path\": \"a.txt\"" in text


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_treats_text_as_adjustment(monkeypatch):
    class _FakeChannelRuntimeStore:
        def get_active_task(self, **kwargs):
            _ = kwargs
            return {"id": "mgr-1", "status": "waiting_user"}

        def update_active_task(self, **kwargs):
            _ = kwargs
            return None

    class _FakeHeartbeatStore:
        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {"id": "mgr-1", "status": "waiting_user"}

        async def update_session_active_task(self, user_id: str, **kwargs):
            _ = (user_id, kwargs)
            return None

        async def release_lock(self, user_id: str):
            _ = user_id
            return True

        async def append_session_event(self, user_id: str, event: str):
            _ = (user_id, event)
            return None

    class _FakeClosureService:
        def __init__(self):
            self.calls: list[dict] = []

        async def resume_waiting_task(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "ok": True,
                "message": "✅ 已记录你的补充说明，正在继续推进阶段 1/2。",
            }

    fake_service = _FakeClosureService()
    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        _FakeChannelRuntimeStore(),
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", _FakeHeartbeatStore())
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        fake_service,
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(user=SimpleNamespace(id="u-1"))

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(
        _Ctx(),
        "把范围限制在最近 7 天，并先检查容器状态",
    )

    assert handled is True
    assert fake_service.calls == [
        {
            "user_id": "u-1",
            "user_message": "把范围限制在最近 7 天，并先检查容器状态",
            "source": "text",
        }
    ]
    assert "已记录你的补充说明" in replies[-1]


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_ignores_cross_channel_new_video_request(
    monkeypatch,
):
    class _FakeChannelRuntimeStore:
        def get_active_task(self, **kwargs):
            _ = kwargs
            return None

    class _FakeHeartbeatStore:
        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {"id": "mgr-telegram", "status": "waiting_user"}

    class _FakeClosureService:
        async def resume_waiting_task(self, **kwargs):
            _ = kwargs
            raise AssertionError("new request should not resume the waiting task")

    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        _FakeChannelRuntimeStore(),
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", _FakeHeartbeatStore())
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        _FakeClosureService(),
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="weixin",
        )

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(
        _Ctx(),
        "下载视频 https://x.com/wangchangfu88/status/2057414957743120721/video/1?s=46",
    )

    assert handled is False
    assert replies == []


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_allows_explicit_continue_from_fallback(
    monkeypatch,
):
    class _FakeChannelRuntimeStore:
        def get_active_task(self, **kwargs):
            _ = kwargs
            return None

    class _FakeHeartbeatStore:
        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {"id": "mgr-telegram", "status": "waiting_user"}

    class _FakeClosureService:
        def __init__(self):
            self.calls: list[dict] = []

        async def resume_waiting_task(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {"ok": True, "message": "✅ 已恢复执行，正在继续推进阶段 2/3。"}

    fake_service = _FakeClosureService()
    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        _FakeChannelRuntimeStore(),
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", _FakeHeartbeatStore())
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        fake_service,
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="weixin",
        )

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(_Ctx(), "继续")

    assert handled is True
    assert fake_service.calls == [
        {
            "user_id": "u-1",
            "user_message": "",
            "source": "text",
        }
    ]
    assert "已恢复执行" in replies[-1]


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_stops_on_explicit_stop(monkeypatch):
    class _FakeChannelRuntimeStore:
        def __init__(self):
            self.updated: list[dict] = []

        def get_active_task(self, **kwargs):
            _ = kwargs
            return {"id": "mgr-stop", "status": "waiting_user"}

        def update_active_task(self, **kwargs):
            self.updated.append(dict(kwargs))
            return None

    class _FakeHeartbeatStore:
        def __init__(self):
            self.updated: list[tuple[str, dict]] = []
            self.released: list[str] = []
            self.events: list[tuple[str, str]] = []

        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {"id": "mgr-stop", "status": "waiting_user"}

        async def update_session_active_task(self, user_id: str, **kwargs):
            self.updated.append((str(user_id), dict(kwargs)))

        async def release_lock(self, user_id: str):
            self.released.append(str(user_id))

        async def append_session_event(self, user_id: str, event: str):
            self.events.append((str(user_id), str(event)))

    class _FakeClosureService:
        async def resume_waiting_task(self, **kwargs):
            _ = kwargs
            raise AssertionError("stop should not resume the waiting task")

    fake_channel_store = _FakeChannelRuntimeStore()
    fake_heartbeat_store = _FakeHeartbeatStore()
    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        _FakeClosureService(),
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="telegram",
        )

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(_Ctx(), "停止")

    assert handled is True
    assert fake_channel_store.updated[-1]["clear_active"] is True
    assert fake_heartbeat_store.updated[-1][1]["clear_active"] is True
    assert fake_heartbeat_store.released == ["u-1"]
    assert fake_heartbeat_store.events == [("u-1", "user_confirm_stop:mgr-stop")]
    assert "已停止" in replies[-1]


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_expires_stale_confirmation(monkeypatch):
    expired = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat(
        timespec="seconds"
    )

    class _FakeChannelRuntimeStore:
        def __init__(self):
            self.updated: list[dict] = []

        def get_active_task(self, **kwargs):
            _ = kwargs
            return {
                "id": "mgr-expired",
                "status": "waiting_user",
                "confirmation_deadline": expired,
            }

        def update_active_task(self, **kwargs):
            self.updated.append(dict(kwargs))
            return None

    class _FakeHeartbeatStore:
        def __init__(self):
            self.updated: list[tuple[str, dict]] = []
            self.released: list[str] = []
            self.events: list[tuple[str, str]] = []

        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {
                "id": "mgr-expired",
                "status": "waiting_user",
                "confirmation_deadline": expired,
            }

        async def update_session_active_task(self, user_id: str, **kwargs):
            self.updated.append((str(user_id), dict(kwargs)))

        async def release_lock(self, user_id: str):
            self.released.append(str(user_id))

        async def append_session_event(self, user_id: str, event: str):
            self.events.append((str(user_id), str(event)))

    class _FakeClosureService:
        async def resume_waiting_task(self, **kwargs):
            _ = kwargs
            raise AssertionError("expired confirmation should not resume")

    fake_channel_store = _FakeChannelRuntimeStore()
    fake_heartbeat_store = _FakeHeartbeatStore()
    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        _FakeClosureService(),
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="telegram",
        )

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(_Ctx(), "继续")

    assert handled is True
    assert fake_channel_store.updated[-1]["clear_active"] is True
    assert fake_heartbeat_store.updated[-1][1]["clear_active"] is True
    assert fake_heartbeat_store.events == [
        ("u-1", "confirmation_expired:mgr-expired")
    ]
    assert "已超过 3 分钟" in replies[-1]


@pytest.mark.asyncio
async def test_try_handle_waiting_confirmation_clears_expired_fallback_task_on_new_request(
    monkeypatch,
):
    expired = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat(
        timespec="seconds"
    )

    class _FakeChannelRuntimeStore:
        def __init__(self):
            self.updated: list[dict] = []

        def get_active_task(self, **kwargs):
            _ = kwargs
            return None

        def update_active_task(self, **kwargs):
            self.updated.append(dict(kwargs))
            return None

    class _FakeHeartbeatStore:
        def __init__(self):
            self.updated: list[tuple[str, dict]] = []
            self.released: list[str] = []
            self.events: list[tuple[str, str]] = []

        async def get_session_active_task(self, user_id: str):
            _ = user_id
            return {
                "id": "mgr-expired-fallback",
                "status": "waiting_user",
                "needs_confirmation": True,
                "confirmation_deadline": expired,
            }

        async def update_session_active_task(self, user_id: str, **kwargs):
            self.updated.append((str(user_id), dict(kwargs)))

        async def release_lock(self, user_id: str):
            self.released.append(str(user_id))

        async def append_session_event(self, user_id: str, event: str):
            self.events.append((str(user_id), str(event)))

    class _FakeClosureService:
        async def resume_waiting_task(self, **kwargs):
            _ = kwargs
            raise AssertionError("new request should not resume expired fallback task")

    fake_channel_store = _FakeChannelRuntimeStore()
    fake_heartbeat_store = _FakeHeartbeatStore()
    monkeypatch.setattr(
        "core.channel_runtime_store.channel_runtime_store",
        fake_channel_store,
    )
    monkeypatch.setattr("core.heartbeat_store.heartbeat_store", fake_heartbeat_store)
    monkeypatch.setattr(
        "ikaros.relay.closure_service.ikaros_closure_service",
        _FakeClosureService(),
    )

    replies: list[str] = []

    class _Ctx:
        message = SimpleNamespace(
            user=SimpleNamespace(id="u-1"),
            platform="weixin",
        )

        async def reply(self, text, **kwargs):
            _ = kwargs
            replies.append(str(text))
            return SimpleNamespace(id="reply")

    handled = await ai_handlers._try_handle_waiting_confirmation(
        _Ctx(),
        "下载视频 https://x.com/a/b",
    )

    assert handled is False
    assert replies == []
    assert fake_channel_store.updated[-1]["clear_active"] is True
    assert fake_heartbeat_store.updated[-1][1]["clear_active"] is True
    assert fake_heartbeat_store.released == ["u-1"]
    assert fake_heartbeat_store.events == [
        ("u-1", "confirmation_expired:mgr-expired-fallback")
    ]


def test_build_runtime_phrase_pools_uses_natural_fallbacks():
    received, loading = ai_handlers._build_runtime_phrase_pools("u-1")

    assert received == ["我看一下。"]
    assert loading == ["我还在看。"]


class _DummyOutgoingMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id
        self.id = message_id

    async def delete(self):
        return True


class _DummyChatContext:
    def __init__(self):
        self.message = SimpleNamespace(
            text="帮我画一张猫狗大战",
            chat=SimpleNamespace(id="c-1", type="private"),
            user=SimpleNamespace(id="u-1"),
            platform="telegram",
            reply_to_message=None,
            raw_data={},
            id="msg-1",
        )
        self.platform_ctx = SimpleNamespace(user_data={})
        self.user_data = {}
        self._adapter = SimpleNamespace(can_update_message=True)
        self.replies: list[tuple[object, dict]] = []
        self.edits: list[tuple[object, object, dict]] = []
        self.photos: list[tuple[object, object, dict]] = []
        self.videos: list[tuple[object, object, dict]] = []
        self.documents: list[tuple[object, object, object, dict]] = []
        self.actions: list[tuple[str, dict]] = []
        self.reactions: list[str] = []
        self.fail_reaction = False

    async def reply(self, payload, **kwargs):
        self.replies.append((payload, dict(kwargs)))
        return _DummyOutgoingMessage(len(self.replies))

    async def edit_message(self, message_id, text, **kwargs):
        self.edits.append((message_id, text, dict(kwargs)))
        return True

    async def send_chat_action(self, action, **kwargs):
        self.actions.append((action, dict(kwargs)))
        return True

    async def set_message_reaction(self, emoji, **kwargs):
        _ = kwargs
        if self.fail_reaction:
            raise RuntimeError("reaction failed")
        self.reactions.append(str(emoji))
        return True

    async def reply_photo(self, photo, caption=None, **kwargs):
        self.photos.append((photo, caption, dict(kwargs)))
        return True

    async def reply_video(self, video, caption=None, **kwargs):
        self.videos.append((video, caption, dict(kwargs)))
        return True

    async def reply_document(self, document, filename=None, caption=None, **kwargs):
        self.documents.append((document, filename, caption, dict(kwargs)))
        return True


class _EditFailingChatContext(_DummyChatContext):
    async def edit_message(self, message_id, text, **kwargs):
        from core.platform.exceptions import MessageSendError

        self.edits.append((message_id, text, dict(kwargs)))
        raise MessageSendError("httpx.ConnectError:")


class _DraftCapableChatContext(_DummyChatContext):
    def __init__(self):
        super().__init__()
        self.drafts: list[dict] = []

        async def _send_message_draft(**kwargs):
            self.drafts.append(dict(kwargs))
            return True

        self._adapter = SimpleNamespace(
            can_update_message=True,
            send_message_draft=_send_message_draft,
        )


@pytest.mark.asyncio
async def test_handle_ai_chat_silently_ignores_unauthorized_user(monkeypatch):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module

    async def _deny_user(_user_id):
        return False

    async def _forbidden(*_args, **_kwargs):
        raise AssertionError("unauthorized request should short-circuit")

    monkeypatch.setattr(config_module, "is_user_allowed", _deny_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _forbidden,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _forbidden)

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert not ctx.replies
    assert not ctx.edits
    assert not ctx.photos
    assert not ctx.documents


@pytest.mark.asyncio
async def test_handle_ai_chat_does_not_attach_plain_path_from_final_text(
    monkeypatch, tmp_path
):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    image_path = (tmp_path / "catdog.png").resolve()
    image_path.write_bytes(b"png")

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, _message_history):
        yield f"✅ 图片已成功生成！\n文件路径: `{image_path}`\n请查收。"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(ai_handlers, "ikaros_kernel_provider", lambda: "native")
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert not ctx.photos


@pytest.mark.asyncio
async def test_handle_ai_chat_slow_ikaros_path_does_not_send_dot_placeholder(
    monkeypatch,
):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    original_sleep = asyncio.sleep
    clock = {"now": 1000.0}

    async def _fast_sleep(delay, result=None):
        clock["now"] += float(delay or 0.0)
        await original_sleep(0)
        return result

    async def _fake_handle_message(_ctx, _message_history):
        await original_sleep(0)
        await original_sleep(0)
        yield "最终结果"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(ai_handlers, "ikaros_kernel_provider", lambda: "native")
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(ai_handlers.time, "time", lambda: clock["now"])

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    reply_texts = [payload.get("text") if isinstance(payload, dict) else payload for payload, _ in ctx.replies]
    assert "..." not in reply_texts
    assert "." not in reply_texts
    assert ".." not in reply_texts
    assert reply_texts == ["最终结果"]


@pytest.mark.asyncio
async def test_handle_ai_chat_reacts_and_skips_immediate_placeholder(monkeypatch):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, _message_history):
        yield "好的，已处理。"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(ai_handlers, "ikaros_kernel_provider", lambda: "native")
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.reactions == ["👀"]
    assert ctx.replies
    assert ctx.replies[0][0] != "..."
    assert [payload for payload, _kwargs in ctx.replies] == [{"text": "好的，已处理。"}]


@pytest.mark.asyncio
async def test_handle_ai_chat_falls_back_to_reply_when_edit_fails(monkeypatch):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    saved_messages: list[tuple[str, str, str]] = []

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _record_message(_ctx, user_id, role, text):
        saved_messages.append((str(user_id), str(role), str(text)))

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    clock = {"now": 3000.0}

    async def _fake_handle_message(_ctx, _message_history):
        clock["now"] += 1.5
        yield "Codex 已正常回复"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _record_message)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )
    monkeypatch.setattr(ai_handlers.time, "time", lambda: clock["now"])

    ctx = _EditFailingChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    reply_payloads = [payload for payload, _kwargs in ctx.replies]
    assert {"text": "Codex 已正常回复"} in reply_payloads
    assert not any("Agent 运行出错" in str(payload) for payload in reply_payloads)
    assert ("u-1", "model", "Codex 已正常回复") in saved_messages


@pytest.mark.asyncio
async def test_handle_ai_chat_codex_progress_edits_message_instead_of_draft(
    monkeypatch,
):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from core.runtime_callbacks import get_runtime_callback
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    clock = {"now": 4000.0}

    async def _fake_handle_message(ctx, _message_history):
        callback = get_runtime_callback(ctx, "ikaros_progress_callback")
        assert callback is not None
        clock["now"] += 1.2
        await callback(
            {
                "event": "codex_agent_message",
                "task_id": "task-codex",
                "turn": 1,
                "text_preview": "正在抓取新闻详情。",
            }
        )
        yield "抓取完成。"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )
    monkeypatch.setattr(ai_handlers.time, "time", lambda: clock["now"])

    ctx = _DraftCapableChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.drafts == []
    assert any("正在抓取新闻详情" in str(text) for _msg_id, text, _kwargs in ctx.edits)


@pytest.mark.asyncio
async def test_handle_ai_chat_sends_codex_result_images(monkeypatch, tmp_path):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.task_inbox import task_inbox
    from core.agent_orchestrator import agent_orchestrator
    from core.runtime_callbacks import get_runtime_callback
    from handlers import message_utils

    task_inbox.persist = True
    task_inbox.root = (tmp_path / "task_inbox").resolve()
    task_inbox.tasks_root = (task_inbox.root / "tasks").resolve()
    task_inbox.archive_root = (task_inbox.root / "archive").resolve()
    task_inbox.events_path = (task_inbox.root / "events.jsonl").resolve()
    task_inbox.root.mkdir(parents=True, exist_ok=True)
    task_inbox.tasks_root.mkdir(parents=True, exist_ok=True)
    task_inbox.archive_root.mkdir(parents=True, exist_ok=True)
    task_inbox._loaded = False
    task_inbox._tasks = {}
    task = await task_inbox.submit(
        source="user_chat",
        goal="画一张猫狗大战",
        user_id="u-1",
    )

    image_path = tmp_path / "codex-image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(ctx, _message_history):
        callback = get_runtime_callback(ctx, "ikaros_progress_callback")
        assert callback is not None
        await callback(
            {
                "event": "codex_result_files",
                "files": [
                    {
                        "kind": "photo",
                        "path": str(image_path),
                        "filename": image_path.name,
                    }
                ],
            }
        )
        yield "画好了。"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.user_data["task_inbox_id"] = task.task_id

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.photos == [(str(image_path.resolve()), None, {})]
    assert ctx.user_data["artifact_ledger"][0]["status"] == "delivered"
    assert ctx.user_data["artifact_ledger"][0]["filename"] == image_path.name
    stored = await task_inbox.get(task.task_id)
    assert stored is not None
    assert stored.events[-1]["event"] == "artifact_delivery"
    assert stored.events[-1]["extra"]["delivered"][0]["filename"] == image_path.name


@pytest.mark.asyncio
async def test_handle_ai_chat_sends_codex_markdown_video_link(monkeypatch, tmp_path):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake mp4")

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, _message_history):
        yield f"已下载完成，Master。\n\n文件路径：[clip.mp4]({video_path})"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(ai_handlers, "ikaros_kernel_provider", lambda: "codex")
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.videos == [(str(video_path.resolve()), None, {})]
    assert ctx.user_data["artifact_ledger"][0]["status"] == "delivered"
    assert ctx.user_data["artifact_ledger"][0]["kind"] == "video"


@pytest.mark.asyncio
async def test_handle_ai_chat_sends_codex_labeled_relative_video_path(
    monkeypatch, tmp_path
):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    video_path = tmp_path / "video_abc.mp4"
    video_path.write_bytes(b"fake mp4")

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, _message_history):
        yield "已下载完成，Master。\n\n文件路径：video_abc.mp4\n格式：MP4"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(ai_handlers, "ikaros_kernel_provider", lambda: "codex")
    monkeypatch.setattr(ai_handlers, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "is_cancelled",
        lambda _uid: False,
    )
    monkeypatch.setattr(
        task_manager_module.task_manager,
        "unregister_task",
        lambda _uid: None,
    )

    ctx = _DummyChatContext()
    ctx.message.platform = "weixin"

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.videos == [(str(video_path.resolve()), None, {})]
    assert ctx.user_data["artifact_ledger"][0]["status"] == "delivered"
    assert ctx.user_data["artifact_ledger"][0]["target"] == "weixin:c-1"


@pytest.mark.asyncio
async def test_handle_ai_chat_replies_full_text_when_final_response_exceeds_edit_preview(
    monkeypatch,
):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_process_reply_message(_ctx):
        return message_utils.ReplyMessageResolution()

    async def _identity_process_code_files(_ctx, text):
        return text

    original_sleep = asyncio.sleep
    clock = {"now": 2000.0}
    long_text = "长文" * 1100

    async def _fast_sleep(delay, result=None):
        clock["now"] += float(delay or 0.0)
        await original_sleep(0)
        return result

    async def _fake_handle_message(_ctx, _message_history):
        await original_sleep(0)
        clock["now"] += 1.5
        yield long_text

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(heartbeat_module.heartbeat_store, "set_delivery_target", _noop)
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        message_utils, "process_reply_message", _fake_process_reply_message
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(ai_handlers.time, "time", lambda: clock["now"])

    ctx = _DummyChatContext()

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.edits
    assert len(ctx.edits) == 1
    assert any(payload == {"text": long_text} for payload, _kwargs in ctx.replies)


@pytest.mark.asyncio
async def test_handle_ai_chat_injects_inline_image_inputs_from_text(monkeypatch):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    captured_history: list[dict] = []
    image_url = "https://example.com/cam.jpg"
    resolved_input = message_utils.ResolvedInlineInput(
        mime_type="image/jpeg",
        content=b"fake-jpeg-bytes",
        source_kind="url",
        source_ref=image_url,
    )

    async def _fake_build_agent_message_history(_ctx, **kwargs):
        _ = kwargs
        user_parts = [
            {"text": "请分析这张图片"},
            agent_input_module.inline_input_to_part(resolved_input),
        ]
        return agent_input_module.PreparedAgentInput(
            message_history=[{"role": "user", "parts": user_parts}],
            user_parts=user_parts,
            final_user_message="请分析这张图片",
            inline_inputs=[resolved_input],
            current_resolution=message_utils.InlineInputResolution(
                inputs=[resolved_input],
                detected_refs=[image_url],
                errors=[],
            ),
            reply_resolution=message_utils.ReplyMessageResolution(),
            detected_refs=[image_url],
            errors=[],
            has_inline_inputs=True,
        )

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, message_history):
        captured_history.extend(message_history)
        yield "已分析"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_agent_message_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.message.text = image_url

    await ai_handlers.handle_ai_chat(ctx)

    user_message = captured_history[-1]
    parts = user_message["parts"]
    assert parts[0]["text"] == "请分析这张图片"
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert parts[1]["inline_data"]["data"]


@pytest.mark.asyncio
async def test_handle_ai_chat_does_not_fail_fast_for_plain_web_url(monkeypatch):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _identity_process_code_files(_ctx, text):
        return text

    captured_history: list[dict] = []

    async def _fake_handle_message(_ctx, message_history):
        captured_history.extend(message_history)
        yield "已分析"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.message.text = "https://github.com/public-apis/public-apis"

    await ai_handlers.handle_ai_chat(ctx)

    assert not any(
        "没有成功加载任何图片" in str(payload)
        for payload, _kwargs in ctx.replies
    )
    assert captured_history[-1]["parts"] == [{"text": ctx.message.text}]


@pytest.mark.asyncio
async def test_handle_ai_chat_offers_video_actions_only_for_pure_video_link(monkeypatch):
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)

    ctx = _DummyChatContext()
    ctx.message.text = "https://youtu.be/UnjFg0vz2W?si=eDn1yV01_X1fcEM"

    await ai_handlers.handle_ai_chat(ctx)

    assert ctx.user_data["pending_video_url"] == ctx.message.text
    assert any("已识别视频链接" in str(payload) for payload, _kwargs in ctx.replies)


@pytest.mark.asyncio
async def test_handle_ai_chat_does_not_offer_video_actions_for_mixed_text_and_video_link(
    monkeypatch,
):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_build_agent_message_history(_ctx, **kwargs):
        user_message = str(kwargs.get("user_message") or "")
        user_parts = [{"text": user_message}]
        return agent_input_module.PreparedAgentInput(
            message_history=[{"role": "user", "parts": user_parts}],
            user_parts=user_parts,
            final_user_message=user_message,
            inline_inputs=[],
            current_resolution=message_utils.InlineInputResolution(),
            reply_resolution=message_utils.ReplyMessageResolution(),
            detected_refs=[],
            errors=[],
            has_inline_inputs=False,
        )

    captured_history: list[dict] = []

    async def _fake_handle_message(_ctx, message_history):
        captured_history.extend(message_history)
        yield "已分析"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_agent_message_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.message.text = (
        "https://youtu.be/UnjFg0vz2W?si=eDn1yV01_X1fcEM 下载这个视频，"
        "然后转为文本，最后写成小红书文案"
    )

    await ai_handlers.handle_ai_chat(ctx)

    assert "pending_video_url" not in ctx.user_data
    assert not any("已识别视频链接" in str(payload) for payload, _kwargs in ctx.replies)
    assert captured_history[-1]["parts"] == [{"text": ctx.message.text}]


@pytest.mark.asyncio
async def test_handle_ai_chat_limits_inline_inputs_to_five(monkeypatch):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    captured_history: list[dict] = []
    refs = [f"https://example.com/{idx}.jpg" for idx in range(6)]
    resolved_inputs = [
        message_utils.ResolvedInlineInput(
            mime_type="image/jpeg",
            content=f"image-{idx}".encode("utf-8"),
            source_kind="url",
            source_ref=ref,
        )
        for idx, ref in enumerate(refs[:5])
    ]

    async def _fake_build_agent_message_history(_ctx, **kwargs):
        _ = kwargs
        user_parts = [{"text": "请结合这些图片回答"}]
        for item in resolved_inputs:
            user_parts.append(agent_input_module.inline_input_to_part(item))
        return agent_input_module.PreparedAgentInput(
            message_history=[{"role": "user", "parts": user_parts}],
            user_parts=user_parts,
            final_user_message="请结合这些图片回答",
            inline_inputs=list(resolved_inputs),
            current_resolution=message_utils.InlineInputResolution(
                inputs=list(resolved_inputs),
                detected_refs=list(refs),
                errors=[],
            ),
            reply_resolution=message_utils.ReplyMessageResolution(),
            detected_refs=list(refs),
            errors=[],
            truncated_inline_count=1,
            has_inline_inputs=True,
        )

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _fake_handle_message(_ctx, message_history):
        captured_history.extend(message_history)
        yield "已分析"

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_agent_message_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _fake_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.message.text = " ".join(refs)

    await ai_handlers.handle_ai_chat(ctx)

    user_message = captured_history[-1]
    assert len(user_message["parts"]) == 6
    assert any(
        "本次仅使用前 5 张" in str(payload)
        for payload, _kwargs in ctx.replies
    )


@pytest.mark.asyncio
async def test_handle_ai_chat_fails_fast_when_image_refs_cannot_be_loaded(monkeypatch):
    import core.agent_input as agent_input_module
    import core.config as config_module
    import core.heartbeat_store as heartbeat_module
    import core.task_manager as task_manager_module
    from core.agent_orchestrator import agent_orchestrator
    from handlers import message_utils

    async def _allow_user(_user_id):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    async def _false(*_args, **_kwargs):
        return False

    async def _empty_history(*_args, **_kwargs):
        return []

    async def _fake_build_agent_message_history(_ctx, **kwargs):
        _ = kwargs
        return agent_input_module.PreparedAgentInput(
            message_history=[{"role": "user", "parts": [{"text": "broken"}]}],
            user_parts=[{"text": "broken"}],
            final_user_message="broken",
            inline_inputs=[],
            current_resolution=message_utils.InlineInputResolution(
                inputs=[],
                detected_refs=["https://example.com/broken.jpg"],
                errors=["https://example.com/broken.jpg"],
            ),
            reply_resolution=message_utils.ReplyMessageResolution(),
            detected_refs=["https://example.com/broken.jpg"],
            errors=["https://example.com/broken.jpg"],
            has_inline_inputs=False,
        )

    async def _identity_process_code_files(_ctx, text):
        return text

    async def _forbidden_handle_message(_ctx, _message_history):
        raise AssertionError("orchestrator should not run when no image input resolved")
        yield ""

    monkeypatch.setattr(config_module, "is_user_allowed", _allow_user)
    monkeypatch.setattr(
        heartbeat_module.heartbeat_store,
        "set_delivery_target",
        _noop,
    )
    monkeypatch.setattr(ai_handlers, "add_message", _noop)
    monkeypatch.setattr(ai_handlers, "increment_stat", _noop)
    monkeypatch.setattr(ai_handlers, "_try_handle_waiting_confirmation", _false)
    monkeypatch.setattr(ai_handlers, "_try_handle_memory_commands", _false)
    monkeypatch.setattr(ai_handlers, "get_user_context", _empty_history)
    monkeypatch.setattr(
        ai_handlers, "process_and_send_code_files", _identity_process_code_files
    )
    monkeypatch.setattr(
        agent_input_module,
        "build_agent_message_history",
        _fake_build_agent_message_history,
    )
    monkeypatch.setattr(agent_orchestrator, "handle_message", _forbidden_handle_message)
    monkeypatch.setattr(task_manager_module.task_manager, "register_task", _noop)
    monkeypatch.setattr(
        task_manager_module.task_manager, "is_cancelled", lambda _uid: False
    )
    monkeypatch.setattr(
        task_manager_module.task_manager, "unregister_task", lambda _uid: None
    )

    ctx = _DummyChatContext()
    ctx.message.text = "https://example.com/broken.jpg"

    await ai_handlers.handle_ai_chat(ctx)

    assert any(
        "没有成功加载任何图片" in str(payload)
        for payload, _kwargs in ctx.replies
    )
