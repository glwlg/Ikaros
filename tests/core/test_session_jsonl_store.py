from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.state_store import (
    create_chat_session,
    get_session_entries,
    list_chat_sessions,
    replace_session_entries,
    save_message,
    search_messages,
)


@pytest.mark.asyncio
async def test_session_store_uses_jsonl_append(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    session_id = "sess-jsonl-1"
    await save_message("u-1", "user", "第一条", session_id)
    await save_message("u-1", "model", "回复一", session_id)
    await save_message("u-1", "user", "第二条", session_id)

    files = list((tmp_path / "user").rglob("*.jsonl"))
    files = [p for p in files if any("chat" in part for part in p.parts)]
    assert len(files) == 1
    path = files[0]
    assert path.suffix == ".jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 4  # meta + 3 messages

    records = [json.loads(line) for line in lines]
    assert records[0]["type"] == "session_meta"
    assert records[0]["session_id"] == session_id
    assert [row["type"] for row in records[1:]] == ["message", "message", "message"]
    assert [row["role"] for row in records[1:]] == ["user", "model", "user"]

    entries = await get_session_entries("u-1", session_id)
    assert entries == [
        {"role": "user", "content": "第一条"},
        {"role": "model", "content": "回复一"},
        {"role": "user", "content": "第二条"},
    ]


@pytest.mark.asyncio
async def test_replace_session_entries_rewrites_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    session_id = "sess-jsonl-replace"
    await save_message("u-1", "user", "旧1", session_id)
    await save_message("u-1", "model", "旧2", session_id)
    await save_message("u-1", "user", "旧3", session_id)

    ok = await replace_session_entries(
        "u-1",
        session_id,
        [
            {"role": "system", "content": "【会话压缩摘要】\n- 已压缩"},
            {"role": "user", "content": "新近"},
            {"role": "model", "content": "继续"},
        ],
    )
    assert ok is True
    entries = await get_session_entries("u-1", session_id)
    assert entries[0]["role"] == "system"
    assert entries[-1]["content"] == "继续"
    files = [
        p
        for p in (tmp_path / "user").rglob("*.jsonl")
        if any("chat" in part for part in p.parts)
    ]
    assert len(files) == 1
    # meta + 3 kept rows
    assert len([ln for ln in files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]) == 4


@pytest.mark.asyncio
async def test_search_and_list_ignore_system_and_use_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    session_id = "sess-jsonl-search"
    await create_chat_session("u-1", session_id)
    await save_message("u-1", "system", "【会话记忆种子】\n秘密项目内部标记", session_id)
    await save_message("u-1", "user", "请继续秘密项目", session_id)
    await save_message("u-1", "model", "好的", session_id)

    matched = await search_messages("u-1", "秘密项目", session_id=session_id, limit=10)
    assert len(matched) == 1
    assert matched[0]["role"] == "user"

    sessions = await list_chat_sessions("u-1", limit=10)
    assert sessions
    assert sessions[0]["session_id"] == session_id
    assert Path(sessions[0]["path"]).suffix == ".jsonl"
