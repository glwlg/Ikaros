"""
服务 handlers - 向后兼容层

重新导出各子模块中的函数，保持现有代码的兼容性。
新代码推荐直接从对应子模块导入。
"""

import logging
from core.state_store import search_messages
from .base_handlers import check_permission_unified
from core.platform.models import UnifiedContext
from user_context import compact_current_session

# 从子模块导入

from .feature_handlers import (
    feature_command,
    handle_feature_input,
    save_feature_command,
)

logger = logging.getLogger(__name__)


async def chatlog_command(ctx: UnifiedContext) -> None:
    """处理 /chatlog <keyword> 对话检索命令。"""
    if not await check_permission_unified(ctx):
        return

    text = str(ctx.message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await ctx.reply("用法: `/chatlog <关键词>`")
        return

    keyword = parts[1].strip()
    user_id = str(ctx.message.user.id)
    rows = await search_messages(user_id=user_id, keyword=keyword, limit=10)
    if not rows:
        await ctx.reply("未找到匹配对话。")
        return

    lines = [f"🔎 对话检索：`{keyword}`（最近 {len(rows)} 条）"]
    for row in rows:
        lines.append(
            f"- `{row.get('created_at', '')}` | {row.get('role')} | {str(row.get('content') or '')[:120]}"
        )
    await ctx.reply("\n".join(lines))


async def compact_command(ctx: UnifiedContext) -> None:
    """处理 /compact，对当前会话执行手动压缩。"""
    if not await check_permission_unified(ctx):
        return

    user_id = str(ctx.message.user.id)
    result = await compact_current_session(ctx, user_id, force=True)
    if not bool(result.get("ok")):
        await ctx.reply("⚠️ 当前会话压缩失败，请稍后重试。")
        return

    if not bool(result.get("compacted")):
        reason = str(result.get("reason") or "").strip().lower()
        if reason == "nothing_to_compact":
            await ctx.reply("ℹ️ 当前会话没有可压缩的更早历史。")
            return
        dialog_count = int(result.get("dialog_count") or 0)
        await ctx.reply(
            f"ℹ️ 当前会话共 {dialog_count} 条原始消息，暂未达到需要压缩的程度。"
        )
        return

    await ctx.reply(
        "🗜️ 已压缩 "
        f"{int(result.get('compressed_count') or 0)} 条历史，"
        "保留最近 "
        f"{int(result.get('kept_recent') or 0)} 条原始消息。"
    )


# 导出所有函数
__all__ = [
    "chatlog_command",
    "compact_command",
    # Reminder
    # Feature
    "feature_command",
    "handle_feature_input",
    "save_feature_command",
]
