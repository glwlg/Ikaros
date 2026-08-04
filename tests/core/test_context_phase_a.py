from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channel_runtime_store import channel_runtime_store
from core.context_assembler import SESSION_WORKING_PREFIX, context_assembler
from core.context_budget import (
    estimate_tokens,
    join_budgeted_blocks,
    select_recent_by_budget,
)
from core.state_store import get_session_entries, save_message
from services.session_compaction_service import (
    SESSION_MEMORY_PREFIX,
    SESSION_SUMMARY_PREFIX,
    session_compaction_service,
)
from user_context import SESSION_ID_KEY, get_user_context


class _DummyContext:
    def __init__(self, session_id: str, *, platform: str = "telegram", user_id: str = "u-1"):
        self.message = SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id="chat-1", type="private"),
            platform=platform,
            text="hi",
        )
        self.platform_ctx = SimpleNamespace(user_data={SESSION_ID_KEY: session_id})
        self.user_data = self.platform_ctx.user_data


def test_join_budgeted_blocks_protects_earlier_priority_block():
    long_term = "【长期记忆】\n" + "\n".join(f"- fact-{i}" for i in range(40))
    daily = "【近期记忆（2026-01-01）】\n" + "\n".join(f"- noise-{i}" for i in range(40))
    rendered = join_budgeted_blocks(
        [long_term, daily],
        max_chars=200,
        priority_first=True,
    )
    assert "【长期记忆】" in rendered
    assert "fact-0" in rendered
    # Daily should be dropped or only partially included after durable facts.
    assert rendered.index("【长期记忆】") == 0


def test_select_recent_by_budget_prefers_newest_within_token_cap():
    rows = [{"role": "user", "content": f"msg-{i} " + ("字" * 20)} for i in range(20)]
    selected = select_recent_by_budget(
        rows,
        token_budget=80,
        max_messages=50,
        min_messages=2,
    )
    assert len(selected) >= 2
    assert selected[-1]["content"].startswith("msg-19")
    assert selected[0]["content"].startswith("msg-")
    assert estimate_tokens("\n".join(r["content"] for r in selected)) <= 120


@pytest.mark.asyncio
async def test_load_user_snapshot_keeps_long_term_before_daily(tmp_path, monkeypatch):
    import core.long_term_memory as long_term_memory_module
    import core.memory_config as memory_config_module
    from core.audit_store import audit_store

    audit_root = (tmp_path / "audit").resolve()
    versions_root = (tmp_path / "versions").resolve()
    audit_store.audit_root = audit_root
    audit_store.versions_root = versions_root
    audit_store.index_root = (audit_root / "index").resolve()
    audit_store.logs_root = (audit_root / "logs").resolve()
    audit_store.events_path = (audit_root / "events.jsonl").resolve()
    for path in (
        audit_store.audit_root,
        audit_store.versions_root,
        audit_store.index_root,
        audit_store.logs_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    data_dir = (tmp_path / "data").resolve()
    config_path = (tmp_path / "memory.json").resolve()
    config_path.write_text(
        '{"provider":"file","providers":{"file":{},"mem0":{}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEMORY_CONFIG_PATH", str(config_path))
    memory_config_module.reset_memory_config_cache()
    long_term_memory_module.long_term_memory._provider = None
    long_term_memory_module.long_term_memory._provider_name = ""
    long_term_memory_module.long_term_memory._initialized = False
    long_term_memory_module.long_term_memory._init_lock = None

    async def _fake_extract(text: str, *, max_facts: int = 8):
        del text, max_facts
        return ["居住地：无锡", "偏好称呼：老王", "职业：工程师"]

    monkeypatch.setattr(
        long_term_memory_module.markdown_memory_store,
        "extract_user_facts_ai",
        _fake_extract,
    )

    await long_term_memory_module.long_term_memory.remember_user(
        "u-snap",
        "请记住我住在无锡，叫老王，是工程师",
        source="test",
    )
    # Inflate daily with noise so naive tail truncation would drop long-term.
    daily_path = long_term_memory_module.markdown_memory_store.daily_path("u-snap")
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(
        "# day\n\n" + "\n".join(f"- [{i:02d}:00:00] noise line {i} " + ("x" * 40) for i in range(80)),
        encoding="utf-8",
    )

    snapshot = await long_term_memory_module.long_term_memory.load_user_snapshot(
        "u-snap",
        include_daily=True,
        max_chars=180,
    )
    assert "【核心记忆】" in snapshot or "【长期记忆】" in snapshot
    assert "居住地：无锡" in snapshot or "老王" in snapshot or "工程师" in snapshot


@pytest.mark.asyncio
async def test_compact_archives_older_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    session_id = "sess-archive"
    await save_message(
        "u-1",
        "system",
        f"{SESSION_MEMORY_PREFIX}\n- 用户常住无锡",
        session_id,
    )
    for index in range(30):
        role = "user" if index % 2 == 0 else "model"
        await save_message("u-1", role, f"archive-msg-{index} " + ("内容" * 40), session_id)

    async def _fake_summary(**kwargs):
        _ = kwargs
        return "- 摘要：归档测试"

    monkeypatch.setattr(
        session_compaction_service,
        "_summarize_history",
        _fake_summary,
    )

    result = await session_compaction_service.compact_session(
        user_id="u-1",
        session_id=session_id,
        force=True,
        keep_recent=6,
        keep_recent_tokens=5000,
    )

    rows = await get_session_entries("u-1", session_id)
    dialog_rows = [row for row in rows if row["role"] in {"user", "model"}]

    assert result["ok"] is True
    assert result["compacted"] is True
    assert result["archived"] is True
    assert result["archive_path"]
    archive_path = Path(result["archive_path"])
    assert archive_path.exists()
    assert archive_path.suffix == ".jsonl"
    archive_text = archive_path.read_text(encoding="utf-8")
    assert "archive-msg-0" in archive_text
    assert '"type":"message"' in archive_text or '"type": "message"' in archive_text
    assert len(dialog_rows) == 6
    assert any(row["content"].startswith(SESSION_SUMMARY_PREFIX) for row in rows)


@pytest.mark.asyncio
async def test_get_user_context_injects_working_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    session_id = "sess-working"
    user_id = "u-working"
    await save_message(user_id, "user", "继续刚才的任务", session_id)
    await save_message(user_id, "model", "好的。", session_id)

    channel_runtime_store.set_active_task(
        {
            "id": "task-42",
            "status": "waiting_user",
            "goal": "部署到 staging 并回报结果",
            "last_blocking_reason": "需要确认是否继续发布",
            "needs_confirmation": True,
        },
        platform="telegram",
        platform_user_id=user_id,
    )

    async def _fake_load_snapshot(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(
        "user_context.long_term_memory.load_user_snapshot",
        _fake_load_snapshot,
    )

    ctx = _DummyContext(session_id, user_id=user_id)
    history = await get_user_context(
        ctx,
        user_id,
        include_hidden_system=True,
        auto_compact=False,
    )

    system_texts = [
        item["parts"][0]["text"]
        for item in history
        if item.get("role") == "system"
    ]
    assert any(text.startswith(SESSION_WORKING_PREFIX) for text in system_texts)
    working = next(text for text in system_texts if text.startswith(SESSION_WORKING_PREFIX))
    assert "task-42" in working
    assert "waiting_user" in working
    assert "部署到 staging" in working
    assert isinstance(ctx.user_data.get("last_context_budget"), dict)
    assert ctx.user_data["last_context_budget"]["layers_tokens"].get("working", 0) > 0


@pytest.mark.asyncio
async def test_context_assembler_layer_order(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    session_id = "sess-order"
    user_id = "u-order"
    await save_message(
        user_id,
        "system",
        f"{SESSION_MEMORY_PREFIX}\n- 偏好：简洁",
        session_id,
    )
    await save_message(
        user_id,
        "system",
        f"{SESSION_SUMMARY_PREFIX}\n- 历史：讨论过部署",
        session_id,
    )
    await save_message(user_id, "user", "你好", session_id)
    await save_message(user_id, "model", "你好呀", session_id)

    channel_runtime_store.set_active_task(
        {
            "id": "task-order",
            "status": "running",
            "goal": "写周报",
        },
        platform="telegram",
        platform_user_id=user_id,
    )

    packet = await context_assembler.assemble(
        user_id=user_id,
        session_id=session_id,
        platform="telegram",
        include_hidden_system=True,
    )
    roles_and_prefixes = []
    for item in packet.messages:
        role = item["role"]
        text = item["parts"][0]["text"]
        if role == "system":
            if text.startswith(SESSION_MEMORY_PREFIX):
                roles_and_prefixes.append("memory")
            elif text.startswith(SESSION_WORKING_PREFIX):
                roles_and_prefixes.append("working")
            elif text.startswith(SESSION_SUMMARY_PREFIX):
                roles_and_prefixes.append("summary")
        else:
            roles_and_prefixes.append(role)
    assert roles_and_prefixes[:3] == ["memory", "working", "summary"]
    assert roles_and_prefixes[3:] == ["user", "model"]
