import logging

from core.config import is_user_allowed
from core.document_artifacts import (
    MAX_DOCUMENT_FILE_SIZE_BYTES,
    append_pending_document_artifact,
    build_document_forward_text,
    describe_supported_document_formats,
    persist_document_artifact,
    pop_pending_document_artifacts,
)
from core.platform.exceptions import MediaProcessingError
from core.platform.models import UnifiedContext, MessageType
from .ai_handlers import _acknowledge_received
from .base_handlers import require_feature_access
from .media_utils import extract_media_input

logger = logging.getLogger(__name__)


async def handle_document(ctx: UnifiedContext) -> None:
    """
    处理文档消息。
    - 文档带说明时：立即转交主聊天入口处理。
    - 只收到文档时：先暂存文本工件，等待下一条文本消息。
    """
    user_id = ctx.message.user.id

    if not await is_user_allowed(user_id):
        return
    if not await require_feature_access(ctx, "chat"):
        return

    if ctx.message.type != MessageType.DOCUMENT:
        return

    try:
        media = await extract_media_input(
            ctx,
            expected_types={MessageType.DOCUMENT},
            auto_download=True,
        )
    except MediaProcessingError as exc:
        if exc.error_code == "unsupported_media_on_platform":
            await ctx.reply("❌ 当前平台暂不支持该文档消息格式。")
        else:
            await ctx.reply("❌ 当前平台暂时无法下载文档内容，请稍后重试。")
        return

    file_name = media.file_name
    mime_type = media.mime_type
    file_size = media.file_size
    file_bytes = media.content or b""
    caption = str(media.caption or "").strip()

    if not file_bytes:
        await ctx.reply("❌ 无法获取文档数据，请重新发送。")
        return

    if file_size and file_size > MAX_DOCUMENT_FILE_SIZE_BYTES:
        await ctx.reply("⚠️ 文档过大（超过 10MB），请发送较小的文档。")
        return

    try:
        artifact = persist_document_artifact(
            file_bytes=file_bytes,
            file_name=file_name,
            mime_type=mime_type,
        )
    except ValueError as exc:
        error_code = str(exc or "").strip()
        if error_code == "unsupported_document_type":
            await ctx.reply(
                "⚠️ 不支持的文档格式。\n\n"
                f"支持的格式：{describe_supported_document_formats()}"
            )
            return
        if error_code == "empty_document_text":
            await ctx.reply(
                "❌ 无法提取文档内容。\n\n"
                "可能的原因：\n"
                "• 文档是扫描版（图片）\n"
                "• 文档被加密保护\n"
                "• 文档格式损坏或内容为空"
            )
            return
        logger.error("Document artifact build failed: %s", exc, exc_info=True)
        await ctx.reply("❌ 文档处理失败，请稍后再试。")
        return
    except Exception as exc:
        logger.error("Document artifact build failed: %s", exc, exc_info=True)
        await ctx.reply("❌ 文档处理失败，请稍后再试。")
        return

    if caption:
        pending = pop_pending_document_artifacts(ctx.user_data)
        forward_text = build_document_forward_text([*pending, artifact], caption)
        from .ai_handlers import handle_ai_chat

        await handle_ai_chat(ctx, user_message_override=forward_text)
        return

    pending = append_pending_document_artifact(ctx.user_data, artifact)
    pending_count = len(pending)
    pending_hint = (
        f"\n当前待处理文件：{pending_count} 个。"
        if pending_count > 1
        else ""
    )
    await _acknowledge_received(ctx)
    await ctx.reply(
        "📄 已收到文件"
        f"《{artifact.file_name or 'document'}》，已临时保存。"
        "请继续发送你希望我对它做什么。"
        f"{pending_hint}"
    )
