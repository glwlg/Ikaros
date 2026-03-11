import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "builtin"
        / "deep_research"
        / "scripts"
        / "execute.py"
    )
    spec = importlib.util.spec_from_file_location("deep_research_execute_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeProvider:
    def __init__(self, rows, calls):
        self._rows = list(rows)
        self._calls = calls

    async def search(self, **kwargs):
        self._calls.append(dict(kwargs))
        return list(self._rows)


@pytest.mark.asyncio
async def test_deep_research_uses_web_search_provider_chain_without_searxng(
    monkeypatch,
):
    module = _load_module()
    monkeypatch.delenv("SEARXNG_URL", raising=False)

    provider_calls: list[dict] = []

    class _FakeWebSearchModule:
        @staticmethod
        def build_fallback_provider_chain(*, queries=None):
            _ = queries
            return (
                _FakeProvider(
                    [
                        {
                            "title": "郭子仪 - 维基百科",
                            "url": "https://example.com/guo-ziyi",
                            "content": "郭子仪是唐代名将。",
                        }
                    ],
                    provider_calls,
                ),
                list(queries or []),
            )

    monkeypatch.setattr(
        module,
        "_load_web_search_execute_module",
        lambda: _FakeWebSearchModule(),
    )

    async def fake_fetch(url):
        assert url == "https://example.com/guo-ziyi"
        return "郭子仪，唐代名将，平定安史之乱的重要人物。"

    async def fake_generate_text(async_client, model, contents):
        _ = (async_client, model, contents)
        return "# Deep Research: 郭子仪\n\n结论：郭子仪是唐代中后期关键将领。"

    monkeypatch.setattr(module, "fetch_webpage_content", fake_fetch)
    monkeypatch.setattr(module, "generate_text", fake_generate_text)
    monkeypatch.setattr(module, "openai_async_client", object())

    outputs = []
    async for item in module.execute(
        SimpleNamespace(),
        {"topic": "郭子仪", "depth": 3, "language": "zh-CN"},
        runtime=None,
    ):
        outputs.append(item)

    assert provider_calls
    assert provider_calls[0]["query_text"] == "郭子仪"
    assert provider_calls[0]["categories_value"] == "general,news,it,science"
    assert provider_calls[0]["time_range"] == "year"

    final_payload = outputs[-1]
    assert isinstance(final_payload, dict)
    assert "深度研究报告" in str(final_payload.get("text") or "")
    files = dict(final_payload.get("files") or {})
    assert "deep_research_report.md" in files
    assert "郭子仪是唐代中后期关键将领。".encode("utf-8") in files[
        "deep_research_report.md"
    ]
