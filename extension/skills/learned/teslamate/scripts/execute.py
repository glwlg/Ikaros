from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.skill_cli import (
    add_common_arguments,
    merge_params,
    prepare_default_env,
    run_execute_cli,
)

try:
    from .service import teslamate_service
except ImportError:
    from service import teslamate_service

prepare_default_env(REPO_ROOT)


async def execute(ctx, params: dict, runtime=None) -> dict:
    _ = (ctx, runtime)
    return await teslamate_service.handle(
        action=str(params.get("action") or "status"),
        car_id=_optional_int(params.get("car_id")),
        car_name=str(params.get("car_name") or params.get("car") or "").strip(),
        limit=_int_or_default(params.get("limit"), 5),
        days=_int_or_default(params.get("days"), 30),
    )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(default if value is None or value == "" else value)
    except Exception:
        return default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TeslaMate read-only skill.")
    add_common_arguments(parser)
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        help="status | drives | charges | summary",
    )
    parser.add_argument("--car-id", type=int, default=None, help="TeslaMate car id")
    parser.add_argument("--car-name", default="", help="Car name/VIN/model filter")
    parser.add_argument("--limit", type=int, default=5, help="Rows for drives/charges")
    parser.add_argument("--days", type=int, default=30, help="Days for summary")
    return parser


def _params_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return merge_params(
        args,
        {
            "action": str(args.action or "status").strip(),
            "car_id": args.car_id,
            "car_name": str(args.car_name or "").strip(),
            "limit": int(args.limit or 5),
            "days": int(args.days or 30),
        },
    )


async def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return await run_execute_cli(execute, args=args, params=_params_from_args(args))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
