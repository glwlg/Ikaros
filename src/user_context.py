"""
用户对话上下文管理模块
使用 Markdown 会话文件持久化
"""

import uuid
import logging
from typing import Any, Literal, TYPE_CHECKING

from core.channel_runtime_store import channel_runtime_store
from core.state_store import (
    save_message,
    get_session_messages,
    get_session_entries,
    get_latest_session_id,
    replace_session_entries,
)
from core.context_assembler import (
    SESSION_MEMORY_PREFIX,
    SESSION_RETRIEVED_PREFIX,
    SESSION_SUMMARY_PREFIX,
    SESSION_WORKING_PREFIX,
    context_assembler,
)
from core.context_budget import default_assemble_recent_token_budget
from core.long_term_memory import long_term_memory
from core.llm_usage_store import set_current_llm_usage_session_id
from services.session_compaction_service import session_compaction_service

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

    explicit_session_id = _context_session_hint(context)

    if SESSION_ID_KEY in store:
        session_id = str(store[SESSION_ID_KEY])
        if explicit_session_id and explicit_session_id != session_id:
            session_id = explicit_session_id
            store[SESSION_ID_KEY] = session_id
        platform = _context_platform(context)
        if platform and str(user_id or "").strip():
            channel_runtime_store.set_session_id(
                session_id=session_id,
                platform=platform,
                platform_user_id=str(user_id),
            )
        set_current_llm_usage_session_id(session_id)
        return session_id

    session_id = explicit_session_id or await _resolve_preferred_session_id(context, user_id)
    store[SESSION_ID_KEY] = session_id
    set_current_llm_usage_session_id(session_id)
    return session_id


def _context_platform(context: TelegramContext | UnifiedContext) -> str:
    message = getattr(context, "message", None)
    return str(getattr(message, "platform", "") or "").strip().lower()


def _context_session_hint(context: TelegramContext | UnifiedContext) -> str:
    message = getattr(context, "message", None)
    raw_data = getattr(message, "raw_data", None)
    if isinstance(raw_data, dict):
        session_id = str(raw_data.get("session_id") or "").strip()
        if session_id:
            return session_id
    chat = getattr(message, "chat", None)
    platform = _context_platform(context)
    chat_id = str(getattr(chat, "id", "") or "").strip()
    if platform == "web" and chat_id:
        return chat_id
    return ""


async def _resolve_preferred_session_id(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
) -> str:
    safe_user_id = str(user_id or "").strip()
    if not safe_user_id:
        return str(uuid.uuid4())

    try:
        session_id = channel_runtime_store.get_session_id(
            platform=_context_platform(context),
            platform_user_id=safe_user_id,
        )
        if session_id:
            return session_id
    except Exception:
        logger.debug(
            "Failed to read delivery target while resolving session user=%s",
            safe_user_id,
            exc_info=True,
        )
    try:
        from core.heartbeat_store import heartbeat_store

        target = await heartbeat_store.get_delivery_target(safe_user_id)
        session_id = str(target.get("session_id") or "").strip()
        if session_id:
            return session_id
    except Exception:
        logger.debug(
            "Failed to read legacy heartbeat delivery target while resolving session user=%s",
            safe_user_id,
            exc_info=True,
        )

    return await get_latest_session_id(safe_user_id)


async def get_user_context(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
    *,
    limit: int = 100,
    include_hidden_system: bool = True,
    auto_compact: bool = True,
    query_text: str = "",
) -> list[dict]:
    """
    获取用户的对话上下文 (Async)

    Returns:
        对话历史列表，格式符合当前对话模型输入要求。
        组装顺序：核心记忆 → 工作状态 → 压缩摘要 → 相关记忆 → 最近对话。
    """
    session_id = await get_or_create_session_id(context, user_id)
    await _reconcile_sparse_session_history(str(user_id), session_id)
    compact_triggered = False
    if auto_compact:
        compact_result = await session_compaction_service.compact_session(
            user_id=str(user_id),
            session_id=session_id,
            force=False,
        )
        compact_triggered = bool(
            isinstance(compact_result, dict) and compact_result.get("compacted")
        )

    core_memory_text = ""
    retrieved_memory_text = ""
    retrieval_query = str(query_text or "").strip()
    if include_hidden_system and _is_private_session_context(context):
        try:
            core_memory_text = await long_term_memory.load_core_snapshot(
                str(user_id),
                max_chars=1200,
            )
        except Exception:
            logger.debug(
                "Failed to load core memory snapshot user=%s",
                user_id,
                exc_info=True,
            )
            core_memory_text = ""
        if not retrieval_query:
            retrieval_query = await _latest_user_text(str(user_id), session_id)
        if retrieval_query:
            try:
                hits = await long_term_memory.search_user_memory(
                    str(user_id),
                    retrieval_query,
                    limit=5,
                    include_daily=True,
                )
                # Avoid repeating facts already present in the core layer.
                core_blob = str(core_memory_text or "")
                filtered = [
                    hit
                    for hit in hits
                    if str(hit.get("text") or "").strip()
                    and str(hit.get("text") or "").strip() not in core_blob
                ]
                retrieved_memory_text = long_term_memory.render_retrieved_memory(
                    filtered,
                    max_chars=900,
                )
            except Exception:
                logger.debug(
                    "Failed to search user memory user=%s",
                    user_id,
                    exc_info=True,
                )
                retrieved_memory_text = ""

    packet = await context_assembler.assemble(
        user_id=str(user_id),
        session_id=session_id,
        platform=_context_platform(context),
        include_hidden_system=include_hidden_system,
        dialog_limit=limit,
        recent_token_budget=default_assemble_recent_token_budget(),
        compact_triggered=compact_triggered,
        core_memory_text=core_memory_text,
        retrieved_memory_text=retrieved_memory_text,
        query_text=retrieval_query,
    )
    # Stash budget for diagnostics / handlers without changing return type.
    store = getattr(context, "user_data", None)
    if isinstance(store, dict):
        store["last_context_budget"] = packet.budget.as_dict()
    return packet.messages


async def _latest_user_text(user_id: str, session_id: str) -> str:
    rows = await get_session_entries(str(user_id), str(session_id))
    for row in reversed(rows):
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        text = str(row.get("content") or "").strip()
        if text:
            return text
    return ""


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


def _task_session_id(task: Any) -> str:
    for source in (getattr(task, "metadata", {}), getattr(task, "payload", {})):
        if not isinstance(source, dict):
            continue
        session_id = str(source.get("session_id") or "").strip()
        if session_id:
            return session_id
    return ""


def _task_visible_text(task: Any) -> str:
    for candidate in (
        getattr(task, "final_output", ""),
        dict(getattr(task, "output", {}) or {}).get("text"),
        dict(getattr(task, "result", {}) or {}).get("summary"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


async def _reconcile_sparse_session_history(user_id: str, session_id: str) -> None:
    safe_user_id = str(user_id or "").strip()
    safe_session_id = str(session_id or "").strip()
    if not safe_user_id or not safe_session_id:
        return

    existing_rows = await get_session_entries(safe_user_id, safe_session_id)
    visible_rows = [
        row
        for row in existing_rows
        if str(row.get("role") or "").strip().lower() in {"user", "model"}
        and str(row.get("content") or "").strip()
    ]
    if len(visible_rows) > 1:
        return

    try:
        from core.task_inbox import task_inbox

        recent_tasks = await task_inbox.list_recent(user_id=safe_user_id, limit=30)
    except Exception:
        logger.debug(
            "Failed to load task inbox while reconciling session user=%s session=%s",
            safe_user_id,
            safe_session_id,
            exc_info=True,
        )
        return

    candidate_tasks = [
        task
        for task in recent_tasks
        if str(getattr(task, "source", "") or "").strip().lower() == "user_chat"
        and _task_session_id(task) == safe_session_id
    ]
    if not candidate_tasks:
        return
    candidate_tasks.sort(
        key=lambda item: (
            str(getattr(item, "created_at", "") or ""),
            str(getattr(item, "updated_at", "") or ""),
        )
    )
    merged_rows = [
        row
        for row in existing_rows
        if str(row.get("role") or "").strip().lower() == "system"
        and str(row.get("content") or "").strip()
    ]
    seen_pairs = {
        (
            str(item.get("role") or "").strip().lower(),
            str(item.get("content") or "").strip(),
        )
        for item in merged_rows
    }
    for task in candidate_tasks:
        user_text = str(getattr(task, "goal", "") or "").strip()
        model_text = _task_visible_text(task)
        for role, content in (("user", user_text), ("model", model_text)):
            if not content or (role, content) in seen_pairs:
                continue
            merged_rows.append({"role": role, "content": content})
            seen_pairs.add((role, content))
    if merged_rows == existing_rows:
        return
    await replace_session_entries(safe_user_id, safe_session_id, merged_rows)


async def bind_delivery_target(
    context: TelegramContext | UnifiedContext,
    user_id: int | str,
) -> str:
    """Bind the current visible chat/session so async pushes can rejoin this session."""
    safe_user_id = str(user_id or "").strip()
    if not safe_user_id:
        return ""

    session_id = await get_or_create_session_id(context, safe_user_id)
    message = getattr(context, "message", None)
    platform = str(getattr(message, "platform", "") or "").strip()
    chat = getattr(message, "chat", None)
    chat_id = str(getattr(chat, "id", "") or "").strip()
    if not platform or not chat_id:
        return session_id

    try:
        channel_runtime_store.set_session_id(
            session_id=session_id,
            platform=platform,
            platform_user_id=safe_user_id,
        )
    except Exception:
        logger.debug("Failed to bind delivery target for user=%s", safe_user_id, exc_info=True)
    return session_id


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
    for key in (
        "runtime_v2_session_id",
        "runtime_v2_turn_id",
        "runtime_v2_task_id",
    ):
        store.pop(key, None)
    message = getattr(context, "message", None)
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    user = getattr(message, "user", None)
    user_id = str(getattr(user, "id", "") or "").strip()
    if platform and user_id:
        channel_runtime_store.set_session_id(
            session_id=new_session_id,
            platform=platform,
            platform_user_id=user_id,
        )
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



