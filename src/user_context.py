"""
用户对话上下文管理模块
使用 Markdown 会话文件持久化
"""

import uuid
import logging
from typing import Any, Literal, TYPE_CHECKING

from core.state_store import (
    save_message,
    get_session_messages,
    get_session_entries,
    get_latest_session_id,
)
from core.markdown_memory_store import markdown_memory_store
from services.session_compaction_service import (
    SESSION_MEMORY_PREFIX,
    SESSION_SUMMARY_PREFIX,
    session_compaction_service,
)

logger = logging.getLogger(__name__)

SESSION_ID_KEY = "current_session_id"


from core.platform.models import UnifiedContext

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

    TelegramContext = ContextTypes.DEFAULT_TYPE
else:
    TelegramContext = Any


async def get_or_create_session_id(
    context: TelegramContext | UnifiedContext, user_id: int | str
) -> str:
    """获取当前 Session ID，如果内存没有，尝试从 DB 获取最新的"""
    store = getattr(context, "user_data", None)
    if store is None:
        setattr(context, "user_data", {})
        store = getattr(context, "user_data", {})

    if SESSION_ID_KEY in store:
        return str(store[SESSION_ID_KEY])

    # 从 DB 获取
    session_id = await get_latest_session_id(user_id)
    store[SESSION_ID_KEY] = session_id
    return session_id


async def get_user_context(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    *,
    limit: int = 100,
    include_hidden_system: bool = True,
    auto_compact: bool = True,
) -> list[dict]:
    """
    获取用户的对话上下文 (Async)

    Returns:
        对话历史列表，格式符合当前对话模型输入要求
    """
    session_id = await get_or_create_session_id(context, user_id)
    if include_hidden_system:
        await _ensure_session_memory_seed(context, user_id, session_id)
    if auto_compact:
        await session_compaction_service.compact_session(
            user_id=str(user_id),
            session_id=session_id,
            force=False,
        )
    return await get_session_messages(
        user_id,
        session_id,
        limit=limit,
        include_system=include_hidden_system,
        preserve_system_prefixes=(SESSION_MEMORY_PREFIX, SESSION_SUMMARY_PREFIX),
        preserve_system_limit=2,
    )


async def add_message(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    role: Literal["user", "model"],
    content: str,
) -> None:
    """
    添加一条消息到用户上下文 (Async)
    """
    session_id = await get_or_create_session_id(context, user_id)
    await save_message(user_id, role, content, session_id)


async def get_recent_dialog_messages(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    *,
    limit: int = 10,
) -> list[dict]:
    session_id = await get_or_create_session_id(context, user_id)
    return await get_session_messages(
        user_id,
        session_id,
        limit=limit,
        include_system=False,
    )


async def compact_current_session(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    *,
    force: bool = True,
) -> dict[str, Any]:
    session_id = await get_or_create_session_id(context, user_id)
    return await session_compaction_service.compact_session(
        user_id=str(user_id),
        session_id=session_id,
        force=force,
    )


def clear_context(context: TelegramContext | UnifiedContext) -> None:
    """
    清除用户的对话上下文 (开启新会话)
    不删除历史记录，只是生成新的 session_id
    """
    new_session_id = str(uuid.uuid4())
    store = getattr(context, "user_data", None)
    if store is None:
        setattr(context, "user_data", {})
        store = getattr(context, "user_data", {})
    store[SESSION_ID_KEY] = new_session_id
    logger.info(f"Started new session: {new_session_id}")


async def get_context_length(
    context: TelegramContext | UnifiedContext, user_id: int | str
) -> int:
    """获取用户当前上下文的消息数量"""
    history = await get_user_context(
        context,
        user_id,
        auto_compact=False,
    )
    return len(history)


def _is_private_session_context(context: TelegramContext | UnifiedContext) -> bool:
    message = getattr(context, "message", None)
    chat = getattr(message, "chat", None)
    chat_type = str(getattr(chat, "type", "") or "").strip().lower()
    if chat_type in {"private", "group", "supergroup", "channel"}:
        return chat_type == "private"
    return True


async def _ensure_session_memory_seed(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    session_id: str,
) -> None:
    if not _is_private_session_context(context):
        return
    existing_rows = await get_session_entries(user_id, session_id)
    if any(
        str(item.get("role") or "").strip().lower() == "system"
        and str(item.get("content") or "").startswith(SESSION_MEMORY_PREFIX)
        for item in existing_rows
    ):
        return
    try:
        memory_snapshot = markdown_memory_store.load_snapshot(
            str(user_id),
            include_daily=True,
            max_chars=2400,
        )
    except Exception:
        memory_snapshot = ""
    if not str(memory_snapshot or "").strip():
        return
    memory_seed = (
        f"{SESSION_MEMORY_PREFIX}\n"
        "以下内容仅在本会话开始时加载一次。"
        "回答用户本人相关问题时优先参考这些事实；如果其中没有答案，请明确说明未知。\n\n"
        f"{str(memory_snapshot).strip()}"
    )
    await save_message(user_id, "system", memory_seed, session_id)
