from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core.state_io import read_json, write_json
from core.storage_service import system_state_path, user_state_path


async def _rewrite_state_file(old_path: Path, new_path: Path) -> bool:
    if not old_path.exists() or new_path.exists():
        return False
    payload = await read_json(old_path, None)
    await write_json(new_path, payload)
    old_path.unlink()
    return True


async def migrate_skill_storage_layout() -> dict[str, int]:
    migrated = 0
    skipped = 0

    simple_moves = [
        (
            user_state_path("", "accounts.md"),
            user_state_path("", "credential_manager", "credentials.md"),
        ),
        (
            user_state_path("", "rss", "subscriptions.md"),
            user_state_path("", "rss_subscribe", "subscriptions.md"),
        ),
        (
            user_state_path("", "automation", "reminders.md"),
            user_state_path("", "reminder", "reminders.md"),
        ),
        (
            user_state_path("", "automation", "scheduled_tasks.md"),
            user_state_path("", "scheduler_manager", "scheduled_tasks.md"),
        ),
        (
            user_state_path("", "stock", "watchlist.md"),
            user_state_path("", "stock_watch", "watchlist.md"),
        ),
        (
            system_state_path("video_cache.md"),
            system_state_path("download_video", "video_cache.md"),
        ),
    ]

    for old_path, new_path in simple_moves:
        if await _rewrite_state_file(old_path, new_path):
            migrated += 1
        else:
            skipped += 1

    old_delivery_target_path = user_state_path("", "automation", "delivery_targets.md")
    rss_delivery_target_path = user_state_path(
        "", "rss_subscribe", "delivery_target.md"
    )
    stock_delivery_target_path = user_state_path(
        "", "stock_watch", "delivery_target.md"
    )
    if old_delivery_target_path.exists():
        payload = await read_json(old_delivery_target_path, {})
        if not isinstance(payload, dict):
            payload = {}

        wrote_delivery_target = False
        rss_target = payload.get("rss")
        if isinstance(rss_target, dict) and not rss_delivery_target_path.exists():
            await write_json(rss_delivery_target_path, rss_target)
            wrote_delivery_target = True

        stock_target = payload.get("stock")
        if isinstance(stock_target, dict) and not stock_delivery_target_path.exists():
            await write_json(stock_delivery_target_path, stock_target)
            wrote_delivery_target = True

        if wrote_delivery_target or (
            rss_delivery_target_path.exists() and stock_delivery_target_path.exists()
        ):
            old_delivery_target_path.unlink()
            migrated += 1
        else:
            skipped += 1
    else:
        skipped += 1

    return {"migrated": migrated, "skipped": skipped}


async def _main() -> int:
    summary = await migrate_skill_storage_layout()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
