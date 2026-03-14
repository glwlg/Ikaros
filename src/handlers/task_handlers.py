from __future__ import annotations

from typing import Any

from core.platform.models import UnifiedContext
from core.task_inbox import task_inbox

from .base_handlers import check_permission_unified


def _parse_subcommand(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "recent", ""
    parts = raw.split(maxsplit=2)
    if not parts or not parts[0].startswith("/task"):
        return "recent", ""
    if len(parts) == 1:
        return "recent", ""
    cmd = parts[1].strip().lower()
    args = parts[2].strip() if len(parts) >= 3 else ""
    return cmd, args


def _compact(text: Any, limit: int = 48) -> str:
    raw = str(text or "").strip().replace("\n", " ")
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)] + "…"


def _should_show_task(item: Any) -> bool:
    source = str(getattr(item, "source", "") or "").strip().lower()
    if source != "heartbeat":
        return True
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status == "waiting_external"


async def task_command(ctx: UnifiedContext) -> None:
    if not await check_permission_unified(ctx):
        return

    text = getattr(ctx.message, "text", "") or ""
    sub, _args = _parse_subcommand(text)
    if sub not in {"recent", "list", "ls", "open"}:
        await ctx.reply("用法: `/task`、`/task recent` 或 `/task open`")
        return

    user_id = str(ctx.message.user.id)
    if sub == "open":
        rows = await task_inbox.list_open(user_id=user_id, limit=10)
        title = "🧾 最近 10 个未完成任务"
    else:
        rows = await task_inbox.list_recent(user_id=user_id, limit=10)
        title = "🧾 最近 10 个任务"
    rows = [row for row in rows if _should_show_task(row)]
    if not rows:
        await ctx.reply("当前没有 manager 任务记录。")
        return

    lines = [title]
    for item in rows:
        metadata = dict(item.metadata or {}) if isinstance(item.metadata, dict) else {}
        followup = metadata.get("followup")
        followup_obj = dict(followup) if isinstance(followup, dict) else {}
        followup_bits: list[str] = []
        done_when = _compact(followup_obj.get("done_when"), limit=40)
        refs = followup_obj.get("refs")
        refs_obj = dict(refs) if isinstance(refs, dict) else {}
        pr_url = _compact(refs_obj.get("pr_url"), limit=48)
        if done_when:
            followup_bits.append(done_when)
        if pr_url:
            followup_bits.append(pr_url)
        suffix = f" | {' | '.join(followup_bits)}" if followup_bits else ""
        lines.append(
            f"- `{item.task_id}` | {item.status} | {item.source} | {_compact(item.updated_at, 19)} | {_compact(item.goal, 40)}{suffix}"
        )
    await ctx.reply("\n".join(lines))
