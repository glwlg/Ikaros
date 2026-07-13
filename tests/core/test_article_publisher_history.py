import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_execute_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "extension/skills/learned/article_publisher/scripts/execute.py"
    )
    spec = importlib.util.spec_from_file_location(
        "article_publisher_history_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _collect(result):
    return [item async for item in result]


@pytest.mark.asyncio
async def test_list_titles_defaults_to_latest_twenty(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = _load_execute_module()
    history_path = (
        tmp_path / "user/skills/article_publisher/office_practice_history.jsonl"
    )
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        "\n".join(
            json.dumps(
                {"published_date": f"2026-06-{index:02d}", "title": f"标题{index}"},
                ensure_ascii=False,
            )
            for index in range(1, 26)
        ),
        encoding="utf-8",
    )
    ctx = SimpleNamespace(
        message=SimpleNamespace(user=SimpleNamespace(id="u1"), text="")
    )

    chunks = await _collect(module.execute(ctx, {"action": "list_titles"}))

    assert chunks[-1]["data"]["limit"] == 20
    assert len(chunks[-1]["data"]["titles"]) == 20
    assert chunks[-1]["data"]["titles"][0]["title"] == "标题25"
    assert chunks[-1]["data"]["titles"][-1]["title"] == "标题6"


@pytest.mark.asyncio
async def test_list_titles_clamps_limit_to_one_hundred(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = _load_execute_module()
    ctx = SimpleNamespace(
        message=SimpleNamespace(user=SimpleNamespace(id="u1"), text="")
    )

    chunks = await _collect(
        module.execute(ctx, {"action": "list_titles", "limit": 1000})
    )

    assert chunks[-1]["data"]["limit"] == 100


def test_draft_is_saved_under_fixed_data_directory(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = _load_execute_module()

    path = module.save_article_draft({"title": "固定目录测试", "sections": []})

    assert path.parent == (tmp_path / "user/skills/article_publisher/drafts").resolve()
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "固定目录测试"


@pytest.mark.asyncio
async def test_full_flow_returns_fixed_draft_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = _load_execute_module()
    article = {
        "title": "把会议纪要拆成待办清单",
        "author": "",
        "digest": "测试摘要",
        "cover_prompt": None,
        "sections": [{"content": "<p>测试正文</p>", "image_prompt": None}],
    }

    async def fake_search_stage(*_args, **_kwargs):
        return module.StageResult.success({"source_type": "local"})

    async def fake_write_stage(*_args, **_kwargs):
        return module.StageResult.success(dict(article))

    async def fake_illustrate_stage(*_args, **_kwargs):
        illustrated = dict(article)
        illustrated["images"] = {}
        return module.StageResult.success(illustrated)

    monkeypatch.setattr(module, "search_stage", fake_search_stage)
    monkeypatch.setattr(module, "write_stage", fake_write_stage)
    monkeypatch.setattr(module, "illustrate_stage", fake_illustrate_stage)
    ctx = SimpleNamespace(
        message=SimpleNamespace(user=SimpleNamespace(id="u1"), text="")
    )

    chunks = await _collect(
        module._run_full_flow(
            ctx,
            {},
            topic="AI办公效率：会议纪要",
            current_date="2026-07-13",
            publish=False,
            publish_channels=[],
            accounts={"wechat": None, "xiaohongshu": None},
            output_dir=str(tmp_path / "intermediate"),
        )
    )

    final = chunks[-1]
    draft_path = Path(final["data"]["draft_path"])
    assert final["ok"] is True
    assert (
        draft_path.parent
        == (tmp_path / "user/skills/article_publisher/drafts").resolve()
    )
    assert str(draft_path) in final["text"]
    assert (
        json.loads(draft_path.read_text(encoding="utf-8"))["title"] == article["title"]
    )
