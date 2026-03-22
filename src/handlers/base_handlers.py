import logging
from core.platform.models import UnifiedContext, CONVERSATION_END
from core.config import is_user_allowed

logger = logging.getLogger(__name__)


def get_effective_user_id(context: UnifiedContext) -> str:
    callback_user_id = getattr(context, "callback_user_id", None)
    if callback_user_id:
        return str(callback_user_id)

    explicit_user = getattr(context, "user", None)
    if explicit_user is not None and getattr(explicit_user, "id", None) is not None:
        return str(explicit_user.id)

    message = getattr(context, "message", None)
    message_user = getattr(message, "user", None)
    if message_user is not None and getattr(message_user, "id", None) is not None:
        return str(message_user.id)
    return ""


async def check_permission_unified(context: UnifiedContext) -> bool:
    """Unified permission check"""
    user_id = get_effective_user_id(context)
    if not await is_user_allowed(user_id):
        logger.info("Ignoring unauthorized message from user_id=%s", user_id)
        return False
    return True


async def edit_callback_message(
    ctx: UnifiedContext,
    text: str,
    *,
    ui: dict | None = None,
    message_id: str | None = None,
    no_change_text: str = "当前已是该页面",
    **kwargs,
):
    target_message_id = str(message_id or ctx.message.id or "").strip()
    result = await ctx.edit_message(target_message_id, text, ui=ui, **kwargs)
    await ctx.answer_callback(text=no_change_text if result is None else None)
    return result


async def cancel(ctx: UnifiedContext) -> int:
    """取消当前操作"""
    await ctx.reply("操作已取消。\n\n发送消息继续 AI 对话，或使用 /download 下载视频。")
    return CONVERSATION_END
