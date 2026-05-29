import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_write_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = (
        repo_root
        / "extension"
        / "skills"
        / "learned"
        / "article_publisher"
        / "scripts"
    )
    for path in (repo_root, repo_root / "src", scripts_dir):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    module_path = scripts_dir / "ap_stages" / "write.py"
    spec = importlib.util.spec_from_file_location(
        "article_publisher_prompt_style_test",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_article_prompt_locks_wechat_ai_fast_news_style(monkeypatch):
    module = _load_write_module()
    captured: dict[str, str] = {}

    monkeypatch.setattr(module, "select_model_for_role", lambda _role: "demo-model")
    monkeypatch.setattr(
        module,
        "get_client_for_model",
        lambda _model, is_async=True: object() if is_async else None,
    )

    async def fake_generate_text(async_client, model, contents, config=None):
        _ = (async_client, model, config)
        captured["prompt"] = str(contents)
        return json.dumps(
            {
                "title": "5月25日AI快讯:300亿还不够AI烧",
                "author": "硅基天平",
                "digest": "测试摘要",
                "cover_prompt": "300亿不够烧",
                "sections": [
                    {
                        "content": (
                            '<section style="margin:30px 0 14px;'
                            'padding:10px 12px;border-left:4px solid #ff7a1a;'
                            'background:#fff7ed;border-radius:6px;font-size:17px;'
                            'line-height:1.55;color:#171717;font-weight:700;'
                            'letter-spacing:0;">测试标题</section>'
                            '<p style="font-size:15px;line-height:1.9;color:#2f3437;'
                            'margin:0 0 12px;letter-spacing:0;">测试正文</p>'
                        ),
                        "image_prompt": None,
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(module, "generate_text", fake_generate_text)

    result = await module._generate_article_json(
        "最新中国人工智能新闻快讯",
        "素材：5月月之暗面、阶跃星辰等国产大模型融资超过300亿元。",
    )

    assert result["title"] == "5月25日AI快讯:300亿还不够AI烧"
    prompt = captured["prompt"]
    assert "营销号的注意力机制" in prompt
    assert "大数字 + 冲突/反常识/悬念" in prompt
    assert "300亿还不够AI烧" in prompt
    assert "不要只用裸 <h2>" in prompt
    assert "draft/get 回读保留" in prompt
    assert "短段落优先" in prompt
    assert "禁止要求、暗示或输出 SVG" in prompt
    assert "illustrate 阶段生成栅格图片" in prompt
