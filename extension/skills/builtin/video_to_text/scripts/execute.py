from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
SRC_ROOT = REPO_ROOT / "src"
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from core.extension_base import SkillExtension
from core.media_hooks import media_hook_registry
from core.platform.models import MessageType, UnifiedContext

try:
    from .video_text_service import (
        execute_video_to_text,
        process_current_video_message,
        provide_reply_video_context,
        video_to_text_enabled,
    )
except ImportError:
    from video_text_service import (
        execute_video_to_text,
        process_current_video_message,
        provide_reply_video_context,
        video_to_text_enabled,
    )


async def execute(
    ctx: UnifiedContext,
    params: dict[str, Any],
    runtime=None,
) -> dict[str, Any]:
    _ = runtime
    return await execute_video_to_text(
        path=str(params.get("path") or ""),
        ctx=ctx,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a local video into a Markdown artifact.")
    parser.add_argument("--path", default="", help="Local video path")
    return parser


async def _main_async() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    
    def _progress(message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] {message}", file=sys.stderr, flush=True)

    result = await execute_video_to_text(path=args.path, progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


class VideoToTextSkillExtension(SkillExtension):
    name = "video_to_text_extension"
    skill_name = "video_to_text"

    def register(self, runtime) -> None:
        _ = runtime
        if not video_to_text_enabled():
            return
        media_hook_registry.register_incoming_interceptor(
            MessageType.VIDEO,
            process_current_video_message,
            owner=self.skill_name,
            priority=50,
        )
        media_hook_registry.register_reply_context_provider(
            MessageType.VIDEO,
            provide_reply_video_context,
            owner=self.skill_name,
            priority=50,
        )


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
