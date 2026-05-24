from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS_DIR))

from ap_stages import StageResult
from ap_stages.write import _generate_article_json as _new_generate_article_json
from ap_utils import read_local_material_context, topic_slug


async def _generate_article_json(topic: str, context: str, ctx=None) -> dict[str, Any]:
    _ = ctx
    return await _new_generate_article_json(topic, context)


def _context_from_research(data: dict[str, Any]) -> str:
    context = str(data.get("context") or data.get("material_context") or "").strip()
    if context:
        return context

    parts: list[str] = []
    for source in list(data.get("sources") or []):
        if not isinstance(source, dict):
            continue
        content = str(source.get("content") or "").strip()
        if content:
            parts.append(content)
            continue
        paths = source.get("paths")
        if isinstance(paths, (list, tuple, set)):
            material_paths = [Path(str(path)).expanduser().resolve() for path in paths]
            if material_paths:
                parts.append(read_local_material_context(material_paths))
    return "\n---\n".join(part for part in parts if part.strip()).strip()


async def write_stage(
    source: str,
    *,
    output_dir: str | None = None,
    topic: str | None = None,
    ctx=None,
) -> StageResult:
    source_path = Path(str(source or "")).expanduser().resolve()
    if not source_path.exists():
        return StageResult.fail(f"Source file not found: {source}")

    safe_topic = str(topic or "").strip()
    if source_path.suffix.lower() == ".json":
        try:
            research_data = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return StageResult.fail(f"Invalid research JSON: {exc}")
        if not isinstance(research_data, dict):
            return StageResult.fail("Invalid research JSON: root is not an object")
        safe_topic = safe_topic or str(research_data.get("topic") or "").strip()
        context = _context_from_research(research_data)
    else:
        safe_topic = safe_topic or source_path.stem
        try:
            context = read_local_material_context([source_path])
        except Exception as exc:
            return StageResult.fail(f"素材读取失败: {exc}")

    if not safe_topic:
        safe_topic = "未命名主题"
    if not context:
        return StageResult.fail("无写作素材输入")

    article_data = await _generate_article_json(safe_topic, context, ctx=ctx)
    out_root = Path(output_dir or source_path.parent).resolve()
    out_dir = out_root / topic_slug(safe_topic)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "article.json"
    out_path.write_text(
        json.dumps(article_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return StageResult.success(article_data, output_path=str(out_path))
