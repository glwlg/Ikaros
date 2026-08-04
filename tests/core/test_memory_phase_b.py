from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.audit_store import audit_store
from core.context_assembler import SESSION_MEMORY_PREFIX, SESSION_RETRIEVED_PREFIX
from core.memory_search import rank_memory_candidates, tokenize_query
from core.state_store import save_message
from user_context import SESSION_ID_KEY, get_user_context
import core.long_term_memory as long_term_memory_module
import core.memory_config as memory_config_module


def _redirect_audit_paths(tmp_path):
    audit_root = (tmp_path / "audit").resolve()
    versions_root = (tmp_path / "versions").resolve()
    index_root = (audit_root / "index").resolve()
    logs_root = (audit_root / "logs").resolve()
    for path in (audit_root, versions_root, index_root, logs_root):
        path.mkdir(parents=True, exist_ok=True)
    audit_store.audit_root = audit_root
    audit_store.versions_root = versions_root
    audit_store.index_root = index_root
    audit_store.logs_root = logs_root
    audit_store.events_path = (audit_root / "events.jsonl").resolve()
    audit_store._legacy_migrated = False


def _reset_ltm():
    memory_config_module.reset_memory_config_cache()
    long_term_memory_module.long_term_memory._provider = None
    long_term_memory_module.long_term_memory._provider_name = ""
    long_term_memory_module.long_term_memory._initialized = False
    long_term_memory_module.long_term_memory._init_lock = None
    long_term_memory_module.long_term_memory._ikaros_snapshot_cache = ""


def _setup_file_memory(tmp_path, monkeypatch):
    _redirect_audit_paths(tmp_path)
    data_dir = (tmp_path / "data").resolve()
    config_path = (tmp_path / "memory.json").resolve()
    config_path.write_text(
        '{"provider":"file","providers":{"file":{},"mem0":{}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEMORY_CONFIG_PATH", str(config_path))
    _reset_ltm()
    return data_dir


class _DummyContext:
    def __init__(self, session_id: str, *, user_id: str = "u-mem"):
        self.message = SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id="chat-1", type="private"),
            platform="telegram",
            text="hi",
        )
        self.user_data = {SESSION_ID_KEY: session_id}


def test_tokenize_and_rank_memory_candidates():
    tokens = tokenize_query("我住在无锡吗")
    assert "无锡" in tokens or any("无锡" in t for t in tokens)
    hits = rank_memory_candidates(
        [
            {"text": "居住地：无锡", "source": "core", "tier": "core"},
            {"text": "偏好称呼：老王", "source": "core", "tier": "core"},
            {"text": "喜欢吃面", "source": "archive", "tier": "archive"},
        ],
        query="无锡住哪里",
        limit=3,
    )
    assert hits
    assert "无锡" in hits[0].text


@pytest.mark.asyncio
async def test_remember_writes_core_and_search_finds_it(tmp_path, monkeypatch):
    data_dir = _setup_file_memory(tmp_path, monkeypatch)

    async def _fake_extract(text: str, *, max_facts: int = 8):
        del text, max_facts
        return ["居住地：无锡", "偏好称呼：老王"]

    monkeypatch.setattr(
        long_term_memory_module.markdown_memory_store,
        "extract_user_facts_ai",
        _fake_extract,
    )

    ok, detail = await long_term_memory_module.long_term_memory.remember_user(
        "u-mem",
        "请记住我住在无锡，叫老王",
        source="test",
        tier="core",
    )
    assert ok is True
    assert "无锡" in detail

    memory_text = (data_dir / "user" / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Core" in memory_text
    assert "居住地：无锡" in memory_text

    core = await long_term_memory_module.long_term_memory.load_core_snapshot("u-mem")
    assert "【核心记忆】" in core
    assert "无锡" in core

    hits = await long_term_memory_module.long_term_memory.search_user_memory(
        "u-mem",
        "我住在哪",
        limit=3,
    )
    assert hits
    assert any("无锡" in str(item.get("text") or "") for item in hits)


@pytest.mark.asyncio
async def test_forget_removes_matching_core_fact(tmp_path, monkeypatch):
    _setup_file_memory(tmp_path, monkeypatch)

    async def _fake_extract(text: str, *, max_facts: int = 8):
        del max_facts
        if "北京" in text:
            return ["居住地：北京"]
        return ["偏好称呼：老王"]

    monkeypatch.setattr(
        long_term_memory_module.markdown_memory_store,
        "extract_user_facts_ai",
        _fake_extract,
    )
    await long_term_memory_module.long_term_memory.remember_user(
        "u-mem", "记住我住北京", source="test"
    )
    await long_term_memory_module.long_term_memory.remember_user(
        "u-mem", "记住叫老王", source="test"
    )

    ok, detail = await long_term_memory_module.long_term_memory.forget_user(
        "u-mem",
        "北京",
    )
    assert ok is True
    assert "北京" in detail
    core = await long_term_memory_module.long_term_memory.load_core_snapshot("u-mem")
    assert "北京" not in core
    assert "老王" in core


@pytest.mark.asyncio
async def test_get_user_context_refreshes_core_and_injects_retrieved(
    tmp_path, monkeypatch
):
    _setup_file_memory(tmp_path, monkeypatch)

    async def _fake_extract(text: str, *, max_facts: int = 8):
        del text, max_facts
        return ["居住地：无锡", "项目偏好：喜欢简洁 API"]

    monkeypatch.setattr(
        long_term_memory_module.markdown_memory_store,
        "extract_user_facts_ai",
        _fake_extract,
    )
    await long_term_memory_module.long_term_memory.remember_user(
        "u-mem",
        "记住我住无锡，喜欢简洁 API",
        source="test",
    )
    # Push one fact into archive so retrieval can surface non-core content.
    await long_term_memory_module.long_term_memory.remember_user_facts(
        "u-mem",
        ["曾用过 n8n 做自动化"],
        source="test_archive",
        tier="archive",
    )

    session_id = "sess-b-lite"
    await save_message("u-mem", "user", "我之前用 n8n 做过什么", session_id)
    await save_message("u-mem", "model", "我查一下记忆。", session_id)

    ctx = _DummyContext(session_id, user_id="u-mem")
    history = await get_user_context(
        ctx,
        "u-mem",
        include_hidden_system=True,
        auto_compact=False,
        query_text="n8n 自动化",
    )
    system_texts = [
        item["parts"][0]["text"]
        for item in history
        if item.get("role") == "system"
    ]
    assert any(text.startswith(SESSION_MEMORY_PREFIX) for text in system_texts)
    memory_seed = next(
        text for text in system_texts if text.startswith(SESSION_MEMORY_PREFIX)
    )
    assert "无锡" in memory_seed or "核心记忆" in memory_seed
    assert any(
        text.startswith(SESSION_RETRIEVED_PREFIX) or "n8n" in text
        for text in system_texts
    )
    budget = ctx.user_data.get("last_context_budget") or {}
    assert "memory_seed" in (budget.get("layers_tokens") or {})
