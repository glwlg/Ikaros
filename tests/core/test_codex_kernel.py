import asyncio
import base64
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import core.agent_orchestrator as orchestrator_module
import core.codex_kernel as codex_kernel_module
from core.agent_orchestrator import AgentOrchestrator
from core.channel_runtime_store import channel_runtime_store
from core.codex_kernel import codex_kernel_provider
from core.codex_kernel_sessions import codex_kernel_sessions
from core.extension_router import ExtensionCandidate
from core.heartbeat_store import heartbeat_store
from core.platform.models import Chat, MessageType, UnifiedMessage, User
from core.task_inbox import task_inbox
from services.intent_router import RoutingDecision


class DummyContext:
    def __init__(self, user_id: str = "u1"):
        self.message = UnifiedMessage(
            id="m1",
            platform="telegram",
            user=User(id=user_id, username="tester"),
            chat=Chat(id=user_id, type="private"),
            date=datetime.now(),
            type=MessageType.TEXT,
            text="test",
        )
        self.user_data = {}
        self.platform_ctx = None
        self.platform_event = None
        self._adapter = SimpleNamespace(can_update_message=True)

    async def reply(self, *_args, **_kwargs):
        return SimpleNamespace(id="reply")

    async def edit_message(self, *_args, **_kwargs):
        return None

    async def send_chat_action(self, *_args, **_kwargs):
        return None


def _reset_task_inbox(tmp_path):
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


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("IKAROS_KERNEL", "codex")
    monkeypatch.setenv("DATA_DIR", str((tmp_path / "data").resolve()))
    _reset_task_inbox(tmp_path)
    runtime_root = (tmp_path / "runtime_tasks").resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(heartbeat_store, "root", runtime_root)
    heartbeat_store._locks.clear()

    async def fake_route(**_kwargs):
        return RoutingDecision(
            request_mode="task",
            candidate_skills=[],
            reason="task",
            confidence=0.9,
        )

    monkeypatch.setattr(orchestrator_module.intent_router, "route", fake_route)


def test_kernel_prompt_inherits_ikaros_base_identity(monkeypatch):
    captured = {}

    def fake_compose_base(**kwargs):
        captured.update(kwargs)
        return "【SOUL】\n# Test SOUL\n- persona: ikaros"

    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        fake_compose_base,
    )

    text = codex_kernel_module._kernel_prompt(
        user_request="修一下",
        message_history=[],
        request_mode="task",
        task_inbox_id="task-1",
        runtime_user_id="runtime-u",
        platform="telegram",
    )

    assert "【SOUL】" in text
    assert "persona: ikaros" in text
    assert text.index("【SOUL】") < text.index("【Ikaros runtime】")
    assert "【Codex kernel execution context】" not in text
    assert captured["runtime_user_id"] == "runtime-u"
    assert captured["platform"] == "telegram"
    assert captured["mode"] == "chat"
    assert captured["allowed_skill_names"] == []


def test_kernel_prompt_includes_filtered_ikaros_only_skill_catalog(
    monkeypatch,
    tmp_path,
):
    skill_dir = tmp_path / "teslamate"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# TeslaMate\n", encoding="utf-8")
    captured = {}

    def fake_compose_base(**kwargs):
        captured.update(kwargs)
        return "【SOUL】\n# Test SOUL"

    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        fake_compose_base,
    )
    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.get_enabled_skill_index",
        lambda: {
            "teslamate": {
                "name": "teslamate",
                "description": "TeslaMate 只读车况助手",
                "triggers": ["开车", "去了哪里", "行驶记录"],
                "allowed_roles": ["ikaros"],
                "skill_md_path": str(skill_md),
                "skill_dir": str(skill_dir),
                "entrypoint": "scripts/execute.py",
                "tool_exports": [
                    {
                        "name": "teslamate_query",
                        "prompt_hint": "用户询问开车去了哪里时调用。",
                    }
                ],
            },
            "web_search": {
                "name": "web_search",
                "description": "聚合网络搜索",
                "triggers": ["搜索"],
                "allowed_roles": ["ikaros"],
                "skill_md_path": str(tmp_path / "web_search" / "SKILL.md"),
                "skill_dir": str(tmp_path / "web_search"),
                "entrypoint": "scripts/execute.py",
            },
            "generate_image": {
                "name": "generate_image",
                "description": "文生图",
                "allowed_roles": ["ikaros"],
                "skill_md_path": str(tmp_path / "generate_image" / "SKILL.md"),
                "skill_dir": str(tmp_path / "generate_image"),
                "entrypoint": "scripts/execute.py",
            },
        },
    )
    monkeypatch.setattr(
        "core.tool_access_store.tool_access_store.is_tool_allowed",
        lambda **_kwargs: (True, {}),
    )

    text = codex_kernel_module._kernel_prompt(
        user_request="我这几天开车去了哪里",
        message_history=[],
        request_mode="chat",
        task_inbox_id="",
        runtime_user_id="runtime-u",
        platform="telegram",
        candidate_skill_names=["teslamate"],
    )

    assert captured["mode"] == "chat"
    assert captured["allowed_skill_names"] == []
    assert "【Ikaros-only local skills】" in text
    assert "- `teslamate`: TeslaMate 只读车况助手" in text
    assert "`web_search`" not in text
    assert "`generate_image`" not in text
    assert "本轮路由提示可能相关" not in text
    assert "triggers:" not in text
    assert "SKILL.md:" not in text
    assert "entrypoint:" not in text
    assert "exports:" not in text
    assert "prefer native Codex capabilities" in text
    assert "load_skill(skill_name" not in text


def test_kernel_prompt_omits_skill_catalog_without_routed_candidates(monkeypatch):
    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        lambda **_kwargs: "【SOUL】\n# Test SOUL",
    )
    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.get_enabled_skill_index",
        lambda: {
            "teslamate": {
                "name": "teslamate",
                "description": "TeslaMate 只读车况助手",
                "allowed_roles": ["ikaros"],
            },
        },
    )
    monkeypatch.setattr(
        "core.tool_access_store.tool_access_store.is_tool_allowed",
        lambda **_kwargs: (True, {}),
    )

    text = codex_kernel_module._kernel_prompt(
        user_request="你好",
        message_history=[],
        request_mode="chat",
        task_inbox_id="",
        runtime_user_id="runtime-u",
        platform="telegram",
        candidate_skill_names=[],
    )

    assert "【Ikaros-only local skills】" not in text
    assert "`teslamate`" not in text


def test_codex_turn_input_items_materializes_inline_image(tmp_path):
    png_bytes = b"\x89PNG\r\n\x1a\ninline"
    items = codex_kernel_module._codex_turn_input_items(
        instruction="看一下这张图",
        message_history=[
            {
                "role": "user",
                "parts": [
                    {"text": "看一下这张图"},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(png_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        thread_key="thread-inline",
    )

    assert items[0]["type"] == "text"
    assert "Attached local files" in items[0]["text"]
    assert items[1]["type"] == "localImage"
    image_path = items[1]["path"]
    assert image_path.endswith(".png")
    assert codex_kernel_module.Path(image_path).read_bytes() == png_bytes


def test_codex_generated_image_rows_reads_current_thread_directory(tmp_path):
    thread_dir = tmp_path / "data" / "codex" / "generated_images" / "thread-1"
    thread_dir.mkdir(parents=True)
    image_path = thread_dir / "ig_demo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    rows = codex_kernel_module._codex_generated_image_rows(
        thread_id="thread-1",
        since_ts=0,
    )

    assert rows == [
        {
            "kind": "photo",
            "path": str(image_path.resolve()),
            "filename": "ig_demo.png",
            "caption": "",
        }
    ]


def test_codex_session_image_rows_extracts_image_generation_event(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        codex_kernel_module.Path,
        "home",
        classmethod(lambda _cls: tmp_path),
    )
    png_bytes = b"\x89PNG\r\n\x1a\nsession"
    record = {
        "timestamp": "2026-05-23T10:19:28.168Z",
        "type": "event_msg",
        "payload": {
            "type": "image_generation_end",
            "call_id": "ig_session",
            "result": base64.b64encode(png_bytes).decode("ascii"),
        },
    }

    rows = codex_kernel_module._codex_session_image_rows_from_record(
        record,
        thread_id="thread-session",
        since_ts=0,
    )

    image_path = (
        tmp_path
        / ".codex"
        / "generated_images"
        / "thread-session"
        / "ig_session.png"
    )
    assert image_path.read_bytes() == png_bytes
    assert rows == [
        {
            "kind": "photo",
            "path": str(image_path.resolve()),
            "filename": "ig_session.png",
            "caption": "",
        }
    ]


def test_codex_session_completion_from_record_detects_task_complete():
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "type": "event_msg",
        "payload": {
            "type": "task_complete",
            "turn_id": "turn-session",
            "last_agent_message": "完成了。",
        },
    }

    completion = codex_kernel_module._codex_session_completion_from_record(
        record,
        since_ts=0,
    )

    assert completion == record["payload"]


def test_kernel_prompt_deduplicates_current_user_request_from_history(monkeypatch):
    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        lambda **_kwargs: "【SOUL】\n# Test SOUL",
    )
    monkeypatch.setattr(codex_kernel_module, "_codex_skill_catalog", lambda **_kwargs: "")

    text = codex_kernel_module._kernel_prompt(
        user_request="今天天气怎么样",
        message_history=[
            {
                "role": "system",
                "parts": [{"text": "【会话记忆种子】\n- 居住地：江苏无锡"}],
            },
            {"role": "user", "parts": [{"text": "今天天气怎么样"}]},
        ],
        request_mode="chat",
        task_inbox_id="",
        runtime_user_id="runtime-u",
        platform="telegram",
    )

    assert text.count("今天天气怎么样") == 1
    assert "system: 【会话记忆种子】" in text


def test_existing_thread_instruction_is_only_latest_user_message():
    text = codex_kernel_module._thread_user_instruction(user_request="继续聊")

    assert text == "继续聊"
    assert "Codex kernel execution context" not in text
    assert "Recent Ikaros conversation context" not in text


@pytest.mark.asyncio
async def test_codex_kernel_run_uses_runtime_identity_for_base_prompt(monkeypatch):
    prompt_kwargs = {}
    run_kwargs = {}

    def fake_compose_base(**kwargs):
        prompt_kwargs.update(kwargs)
        return "【SOUL】\n# Runtime SOUL"

    async def fake_run_turn(**kwargs):
        run_kwargs.update(kwargs)
        return {
            "ok": True,
            "stdout": "完成。",
            "summary": "完成。",
            "thread_id": "thread-runtime",
            "turn_id": "turn-runtime",
            "transport": "app-server",
            "stop_reason": "completed",
        }

    async def event_callback(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        fake_compose_base,
    )
    monkeypatch.setattr(codex_kernel_provider, "_run_turn", fake_run_turn)

    output = await codex_kernel_provider.run_for_orchestrator(
        ctx=None,
        runtime_ctx=SimpleNamespace(
            user_id="platform-user",
            runtime_user_id="runtime-user",
            task_id="task-runtime",
            task_inbox_id="",
            platform_name="telegram",
        ),
        message_history=[],
        task_goal="做事",
        request_mode="task",
        event_callback=event_callback,
    )

    assert output == "完成。"
    assert prompt_kwargs["runtime_user_id"] == "runtime-user"
    assert prompt_kwargs["platform"] == "telegram"
    assert "Runtime SOUL" in run_kwargs["instruction"]


@pytest.mark.asyncio
async def test_orchestrator_can_use_codex_kernel(monkeypatch):
    async def fake_run_turn(**_kwargs):
        return {
            "ok": True,
            "stdout": "Codex 完成了任务。",
            "summary": "Codex 完成了任务。",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "transport": "app-server",
            "stop_reason": "completed",
        }

    monkeypatch.setattr(codex_kernel_provider, "_run_turn", fake_run_turn)

    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator.extension_router, "route", lambda *_a, **_k: [])
    ctx = DummyContext(user_id="u-codex-done")
    chunks = [
        chunk
        async for chunk in orchestrator.handle_message(
            ctx,
            [{"role": "user", "parts": [{"text": "用 codex 做任务"}]}],
        )
    ]

    assert chunks == ["Codex 完成了任务。"]
    rows = await task_inbox.list_recent(user_id="u-codex-done", limit=1)
    assert len(rows) == 1
    assert rows[0].status == "completed"


@pytest.mark.asyncio
async def test_orchestrator_passes_candidate_skill_hints_to_codex(monkeypatch):
    captured = {}

    async def fake_run_for_orchestrator(**kwargs):
        captured.update(kwargs)
        return "Codex 完成了任务。"

    async def fake_route(**_kwargs):
        return RoutingDecision(
            request_mode="chat",
            task_tracking=False,
            candidate_skills=["teslamate"],
            reason="vehicle_history",
            confidence=0.91,
        )

    monkeypatch.setattr(
        codex_kernel_provider,
        "run_for_orchestrator",
        fake_run_for_orchestrator,
    )
    monkeypatch.setattr(orchestrator_module.intent_router, "route", fake_route)

    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator, "_runtime_tool_allowed", lambda **_kwargs: True)
    monkeypatch.setattr(
        orchestrator.extension_router,
        "route",
        lambda *_a, **_k: [
            ExtensionCandidate(
                name="teslamate",
                description="TeslaMate 只读车况助手",
                tool_name="ext_teslamate",
            )
        ],
    )
    ctx = DummyContext(user_id="u-codex-skill-hint")
    chunks = [
        chunk
        async for chunk in orchestrator.handle_message(
            ctx,
            [{"role": "user", "parts": [{"text": "我这几天开车去了哪里"}]}],
        )
    ]

    assert chunks == ["Codex 完成了任务。"]
    assert captured["candidate_skill_names"] == ["teslamate"]


@pytest.mark.asyncio
async def test_codex_kernel_reuses_thread_for_same_ikaros_session(monkeypatch):
    calls = []

    async def fake_run_turn(**kwargs):
        calls.append(dict(kwargs))
        suffix = len(calls)
        return {
            "ok": True,
            "stdout": f"完成 {suffix}",
            "summary": f"完成 {suffix}",
            "thread_id": "thread-session-1",
            "turn_id": f"turn-{suffix}",
            "transport": "app-server",
            "stop_reason": "completed",
        }

    monkeypatch.setattr(codex_kernel_provider, "_run_turn", fake_run_turn)

    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator.extension_router, "route", lambda *_a, **_k: [])

    ctx1 = DummyContext(user_id="u-codex-session")
    ctx1.user_data["current_session_id"] = "sess-one"
    chunks1 = [
        chunk
        async for chunk in orchestrator.handle_message(
            ctx1,
            [{"role": "user", "parts": [{"text": "第一句"}]}],
        )
    ]

    ctx2 = DummyContext(user_id="u-codex-session")
    ctx2.user_data["current_session_id"] = "sess-one"
    chunks2 = [
        chunk
        async for chunk in orchestrator.handle_message(
            ctx2,
            [{"role": "user", "parts": [{"text": "第二句"}]}],
        )
    ]

    assert chunks1 == ["完成 1"]
    assert chunks2 == ["完成 2"]
    assert calls[0]["existing_thread_id"] == ""
    assert calls[1]["existing_thread_id"] == "thread-session-1"
    assert "【SOUL】" in calls[0]["instruction"]
    assert calls[1]["instruction"] == "第二句"
    assert "【SOUL】" not in calls[1]["instruction"]
    assert "Codex kernel execution context" not in calls[1]["instruction"]
    assert "Recent Ikaros conversation context" not in calls[1]["instruction"]
    row = codex_kernel_sessions.get(
        user_id="u-codex-session",
        platform="telegram",
        session_id="sess-one",
    )
    assert row["codex_thread_id"] == "thread-session-1"
    assert row["codex_turn_id"] == "turn-2"


@pytest.mark.asyncio
async def test_codex_kernel_user_input_request_sets_waiting_user(monkeypatch):
    async def fake_run_turn(**_kwargs):
        return {
            "ok": True,
            "stdout": "还需要用户确认。",
            "summary": "还需要用户确认。",
            "thread_id": "thread-wait",
            "turn_id": "turn-wait",
            "transport": "app-server",
            "stop_reason": "completed",
            "user_input_requests": [{"params": {"prompt": "continue?"}}],
        }

    monkeypatch.setattr(codex_kernel_provider, "_run_turn", fake_run_turn)

    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator.extension_router, "route", lambda *_a, **_k: [])
    ctx = DummyContext(user_id="u-codex-wait")
    chunks = [
        chunk
        async for chunk in orchestrator.handle_message(
            ctx,
            [{"role": "user", "parts": [{"text": "做一半需要确认"}]}],
        )
    ]

    assert "3分钟内有效" in chunks[0]
    active = await heartbeat_store.get_session_active_task("u-codex-wait")
    assert active["status"] == "waiting_user"
    assert active["kernel_provider"] == "codex"
    assert active["codex_thread_id"] == "thread-wait"
    rows = await task_inbox.list_recent(user_id="u-codex-wait", limit=1)
    assert rows[0].status == "waiting_user"


@pytest.mark.asyncio
async def test_codex_waiting_resume_uses_existing_thread(monkeypatch):
    task = await task_inbox.submit(
        source="user_chat",
        goal="继续 Codex 任务",
        user_id="u-codex-resume",
        metadata={
            "kernel_provider": "codex",
            "kernel_status": "waiting_user",
            "codex_thread_id": "thread-existing",
        },
    )
    active = {
        "id": "runtime-codex-resume",
        "session_task_id": task.task_id,
        "task_inbox_id": task.task_id,
        "goal": task.goal,
        "status": "waiting_user",
        "source": "message",
        "needs_confirmation": True,
        "confirmation_deadline": "2999-01-01T00:00:00+00:00",
        "kernel_provider": "codex",
        "kernel_status": "waiting_user",
        "codex_thread_id": "thread-existing",
    }
    channel_runtime_store.set_active_task(
        active,
        platform="telegram",
        platform_user_id="u-codex-resume",
    )
    await heartbeat_store.set_session_active_task("u-codex-resume", active)
    captured = {}
    prompt_kwargs = {}

    def fake_compose_base(**kwargs):
        prompt_kwargs.update(kwargs)
        return "【SOUL】\n# Resume SOUL"

    monkeypatch.setattr(
        codex_kernel_module.prompt_composer,
        "compose_base",
        fake_compose_base,
    )

    async def fake_run_turn(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "stdout": "继续后完成。",
            "summary": "继续后完成。",
            "thread_id": "thread-existing",
            "turn_id": "turn-next",
            "transport": "app-server",
            "stop_reason": "completed",
        }

    monkeypatch.setattr(codex_kernel_provider, "_run_turn", fake_run_turn)

    result = await codex_kernel_provider.resume_waiting_task(
        user_id="u-codex-resume",
        platform="telegram",
        user_message="继续",
        source="text",
    )

    assert result["ok"] is True
    assert result["message"] == "继续后完成。"
    assert captured["existing_thread_id"] == "thread-existing"
    assert captured["instruction"] == "继续"
    assert "Resume SOUL" not in captured["instruction"]
    assert "Resume SOUL" in captured["new_thread_instruction"]
    assert prompt_kwargs["runtime_user_id"] == "u-codex-resume"
    assert prompt_kwargs["platform"] == "telegram"
    stored = await task_inbox.get(task.task_id)
    assert stored.status == "completed"
    assert await heartbeat_store.get_session_active_task("u-codex-resume") is None


@pytest.mark.asyncio
async def test_codex_kernel_keeps_app_server_client_resident(monkeypatch):
    await codex_kernel_module.close_persistent_codex_kernel_client()

    instances = []

    class FakeCodexClient:
        def __init__(self, **kwargs):
            self.kwargs = dict(kwargs)
            self.closed = False
            self.event_callback = None
            self.started = 0
            self.initialized = 0
            self.reset_count = 0
            self.turn_inputs: list[str] = []
            self.stderr_text = ""
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            self.reset_count += 1

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            self.started += 1

        async def initialize(self):
            self.initialized += 1
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-resident", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id
            self.turn_inputs.append(instruction)
            return f"turn-{len(self.turn_inputs)}"

        async def wait_for_turn_completed(self, *, turn_id):
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": f"完成 {turn_id}",
                "summary": f"完成 {turn_id}",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "ikaros_codex_command",
        lambda: ["codex", "app-server", "--listen", "stdio://"],
    )

    result1 = await codex_kernel_provider._run_turn(
        user_id="u-resident",
        task_id="task-1",
        task_inbox_id="",
        instruction="第一句",
        platform="telegram",
    )
    result2 = await codex_kernel_provider._run_turn(
        user_id="u-resident",
        task_id="task-2",
        task_inbox_id="",
        instruction="第二句",
        platform="telegram",
        existing_thread_id="thread-resident",
    )

    assert result1["stdout"] == "完成 turn-1"
    assert result2["stdout"] == "完成 turn-2"
    assert len(instances) == 1
    assert instances[0].started == 1
    assert instances[0].initialized == 1
    assert instances[0].reset_count == 2
    assert instances[0].turn_inputs == ["第一句", "第二句"]
    assert instances[0].closed is False

    await codex_kernel_module.close_persistent_codex_kernel_client()
    assert instances[0].closed is True


@pytest.mark.asyncio
async def test_codex_kernel_completes_from_session_task_complete(monkeypatch, tmp_path):
    await codex_kernel_module.close_persistent_codex_kernel_client()
    session_file = tmp_path / "rollout-thread-session.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": datetime.now().astimezone().isoformat(),
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn-session",
                    "last_agent_message": None,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    instances = []

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""
            self.wait_cancelled = False
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-session", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id, instruction
            return "turn-session"

        async def wait_for_turn_completed(self, *, turn_id):
            del turn_id
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.wait_cancelled = True
                raise

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "完成",
                "summary": "完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": turn.get("status"),
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "_codex_session_files_for_thread",
        lambda _thread_id: [session_file],
    )

    result = await codex_kernel_provider._run_turn(
        user_id="u-session-complete",
        task_id="task-session",
        task_inbox_id="",
        instruction="画图",
        platform="telegram",
    )

    assert result["ok"] is True
    assert result["turn"]["source"] == "codex_session_task_complete"
    assert "codex_client_recycled" not in result
    assert instances[0].closed is False

    await codex_kernel_module.close_persistent_codex_kernel_client()


@pytest.mark.asyncio
async def test_codex_kernel_keeps_client_after_file_result(monkeypatch, tmp_path):
    await codex_kernel_module.close_persistent_codex_kernel_client()
    image_path = tmp_path / "codex-image.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    instances = []

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-files", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id, instruction
            return "turn-files"

        async def wait_for_turn_completed(self, *, turn_id):
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "",
                "summary": "",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
                "files": [
                    {
                        "kind": "photo",
                        "path": str(image_path),
                        "filename": "codex-image.png",
                    }
                ],
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)

    result = await codex_kernel_provider._run_turn(
        user_id="u-files",
        task_id="task-files",
        task_inbox_id="",
        instruction="画图",
        platform="telegram",
    )

    assert "codex_client_recycled" not in result
    assert instances[0].closed is False

    await codex_kernel_module.close_persistent_codex_kernel_client()


@pytest.mark.asyncio
async def test_codex_kernel_retries_setup_after_request_timeout(monkeypatch):
    await codex_kernel_module.close_persistent_codex_kernel_client()
    instances = []

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            if len(instances) == 1:
                raise asyncio.TimeoutError()
            return existing_thread_id or "thread-retry", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id, instruction
            return "turn-retry"

        async def wait_for_turn_completed(self, *, turn_id):
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "完成",
                "summary": "完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)

    result = await codex_kernel_provider._run_turn(
        user_id="u-retry",
        task_id="task-retry",
        task_inbox_id="",
        instruction="继续",
        platform="telegram",
    )

    assert result["ok"] is True
    assert result["thread_id"] == "thread-retry"
    assert len(instances) == 2
    assert instances[0].closed is True
    assert instances[1].closed is False

    await codex_kernel_module.close_persistent_codex_kernel_client()


@pytest.mark.asyncio
async def test_codex_kernel_does_not_rotate_thread_after_resume_timeout(monkeypatch):
    await codex_kernel_module.close_persistent_codex_kernel_client()
    instances = []
    turn_inputs = []

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            if existing_thread_id == "thread-stuck":
                raise asyncio.TimeoutError()
            return existing_thread_id or "thread-fresh", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            turn_inputs.append({"thread_id": thread_id, "instruction": instruction})
            return "turn-fresh"

        async def wait_for_turn_completed(self, *, turn_id):
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "换新 thread 后完成",
                "summary": "换新 thread 后完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)

    result = await codex_kernel_provider._run_turn(
        user_id="u-rotate",
        task_id="task-rotate",
        task_inbox_id="",
        instruction="最新用户消息",
        platform="telegram",
        existing_thread_id="thread-stuck",
        new_thread_instruction="完整新 thread 上下文 + 最新用户消息",
    )

    assert result["ok"] is False
    assert result["error_code"] == "timeout"
    assert result["thread_id"] == ""
    assert result["turn_id"] == ""
    assert len(instances) == 2
    assert instances[0].closed is True
    assert turn_inputs == []

    await codex_kernel_module.close_persistent_codex_kernel_client()


@pytest.mark.asyncio
async def test_codex_kernel_continues_when_start_turn_response_times_out_after_task_started(
    monkeypatch,
):
    await codex_kernel_module.close_persistent_codex_kernel_client()
    instances = []
    waited_turn_ids = []

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""
            instances.append(self)

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-live", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id, instruction
            raise asyncio.TimeoutError()

        async def wait_for_turn_completed(self, *, turn_id):
            waited_turn_ids.append(turn_id)
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "已完成",
                "summary": "已完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    async def fake_wait_for_started_turn(**kwargs):
        assert kwargs["thread_id"] == "thread-live"
        return "turn-observed"

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "_wait_for_codex_session_started_turn",
        fake_wait_for_started_turn,
    )

    result = await codex_kernel_provider._run_turn(
        user_id="u-start-timeout",
        task_id="task-start-timeout",
        task_inbox_id="",
        instruction="再来一张",
        platform="telegram",
        existing_thread_id="thread-live",
    )

    assert result["ok"] is True
    assert result["thread_id"] == "thread-live"
    assert result["turn_id"] == "turn-observed"
    assert result["loaded_existing_session"] is True
    assert "codex_thread_rotated" not in result
    assert waited_turn_ids == ["turn-observed"]
    assert len(instances) == 1
    assert instances[0].closed is False

    await codex_kernel_module.close_persistent_codex_kernel_client()


@pytest.mark.asyncio
async def test_codex_kernel_streams_app_server_agent_deltas(monkeypatch):
    await codex_kernel_module.close_persistent_codex_kernel_client()

    class FakeCodexClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.event_callback = None
            self.stderr_text = ""

        def is_running(self):
            return not self.closed

        def reset_turn_state(self):
            return None

        def set_event_callback(self, callback):
            self.event_callback = callback

        async def start(self):
            return None

        async def initialize(self):
            return {}

        async def open_thread(self, *, existing_thread_id=""):
            return existing_thread_id or "thread-stream", bool(existing_thread_id)

        async def start_turn(self, *, thread_id, instruction):
            del thread_id, instruction
            return "turn-stream"

        async def wait_for_turn_completed(self, *, turn_id):
            if self.event_callback is not None:
                await self.event_callback(
                    "agent_message_delta",
                    {
                        "turn_id": turn_id,
                        "item_id": "msg-1",
                        "delta": "处理中",
                        "text": "处理中",
                    },
                )
                await self.event_callback(
                    "command_output_delta",
                    {
                        "turn_id": turn_id,
                        "item_id": "cmd-1",
                        "delta": "pytest passed",
                        "text": "pytest passed",
                    },
                )
            return {"id": turn_id, "status": "completed"}

        def build_result(
            self,
            *,
            thread_id,
            turn_id,
            turn,
            loaded_existing_thread,
        ):
            return {
                "ok": True,
                "stdout": "完成",
                "summary": "完成",
                "thread_id": thread_id,
                "turn_id": turn_id,
                "turn": dict(turn),
                "transport": "app-server",
                "stop_reason": "completed",
                "loaded_existing_session": loaded_existing_thread,
            }

        async def close(self):
            self.closed = True

    events = []

    async def event_callback(event, payload):
        events.append((event, dict(payload)))
        return None

    monkeypatch.setattr(codex_kernel_module, "CodexAppServerClient", FakeCodexClient)
    monkeypatch.setattr(
        codex_kernel_module,
        "ikaros_codex_command",
        lambda: ["codex", "app-server", "--listen", "stdio://"],
    )

    result = await codex_kernel_provider._run_turn(
        user_id="u-stream",
        task_id="task-stream",
        task_inbox_id="",
        instruction="做事",
        platform="telegram",
        event_callback=event_callback,
    )

    assert result["stdout"] == "完成"
    assert [event for event, _payload in events] == ["codex_agent_message"]
    assert events[0][1]["text_preview"] == "处理中"

    await codex_kernel_module.close_persistent_codex_kernel_client()
