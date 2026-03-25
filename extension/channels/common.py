from __future__ import annotations

from core.media_hooks import media_hook_registry
from core.platform.models import MessageType
from handlers import (
    button_callback,
    handle_ai_chat,
    handle_ai_photo,
    handle_sticker_message,
)
from handlers.document_handler import handle_document
from handlers.voice_handler import handle_voice_message

COMMON_CALLBACK_PATTERN = (
    "^(?!back_to_main_cancel$|unsub_|stock_|stkm_|rssm_|sch_del_|schm_|depm_|credm_|"
    "dlym_|dlm_|skill_|skills_|home_|helpm_|hbm_|taskm_|accu_|model_|usagem_|"
    "chatlog_|compact_|del_rss_|del_stock_|action_|large_file_).*$"
)


async def route_message_by_type(ctx):
    msg_type = ctx.message.type
    if msg_type == MessageType.IMAGE:
        await handle_ai_photo(ctx)
    elif msg_type == MessageType.VIDEO:
        outcome = await media_hook_registry.dispatch_incoming(ctx)
        if outcome.handled:
            if outcome.forward_text:
                await handle_ai_chat(ctx, user_message_override=outcome.forward_text)
            return
        await ctx.reply("⚠️ 当前未注册视频文本化处理器，暂时无法处理视频。")
    elif msg_type in {MessageType.AUDIO, MessageType.VOICE}:
        await handle_voice_message(ctx)
    elif msg_type == MessageType.DOCUMENT:
        await handle_document(ctx)
    elif msg_type == MessageType.STICKER:
        await handle_sticker_message(ctx)
    else:
        await handle_ai_chat(ctx)


__all__ = ["COMMON_CALLBACK_PATTERN", "button_callback", "route_message_by_type"]
