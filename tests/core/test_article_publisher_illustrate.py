import importlib.util
import sys
from pathlib import Path

import pytest


def _load_illustrate_module():
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
    module_path = scripts_dir / "ap_stages" / "illustrate.py"
    spec = importlib.util.spec_from_file_location(
        "article_publisher_illustrate_test",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SvgImageCtx:
    async def run_skill(self, skill_name: str, params: dict):
        assert skill_name == "generate_image"
        assert "禁止 SVG" in str(params.get("prompt") or "")
        return {"files": {"bad.svg": b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"}}


@pytest.mark.asyncio
async def test_illustrate_rejects_svg_payload_from_generate_image():
    module = _load_illustrate_module()

    cover_bytes, section_images, generated_files = await module._generate_images(
        _SvgImageCtx(),
        {
            "cover_prompt": "公众号封面，禁止 SVG",
            "sections": [
                {
                    "content": "<p>正文</p>",
                    "image_prompt": "中文信息图，禁止 SVG",
                }
            ],
        },
        author="Ikaros",
    )

    assert cover_bytes is None
    assert section_images == {}
    assert generated_files == {}
