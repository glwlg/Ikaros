from __future__ import annotations

from datetime import datetime
from typing import Any

from core.platform.models import Chat, MessageType, UnifiedMessage, User


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _as_datetime(raw_ms: Any) -> datetime:
    try:
        millis = int(raw_ms)
        if millis > 0:
            return datetime.fromtimestamp(millis / 1000)
    except Exception:
        pass
    return datetime.now()


def _extract_text(raw_message: dict[str, Any]) -> str:
    items = raw_message.get("item_list") or []
    parts: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == 1:
            text_item = item.get("text_item") or {}
            text = _safe_text(text_item.get("text"))
            if text:
                parts.append(text)
        elif item_type == 2:
            parts.append("(image)")
        elif item_type == 3:
            voice_item = item.get("voice_item") or {}
            text = _safe_text(voice_item.get("text"))
            parts.append(text or "(voice)")
        elif item_type == 4:
            file_item = item.get("file_item") or {}
            name = _safe_text(file_item.get("file_name")) or "unknown"
            parts.append(f"(file: {name})")
        elif item_type == 5:
            parts.append("(video)")

    return "\n".join(part for part in parts if part).strip() or "(empty message)"


def map_weixin_message(raw_message: dict[str, Any]) -> UnifiedMessage:
    sender_id = _safe_text(raw_message.get("from_user_id")) or "unknown"
    sender_name = (
        _safe_text(raw_message.get("from_user_name"))
        or _safe_text(raw_message.get("from_user_nickname"))
        or _safe_text(raw_message.get("nickname"))
    )
    message_id = (
        _safe_text(raw_message.get("client_id"))
        or _safe_text(raw_message.get("msg_id"))
        or _safe_text(raw_message.get("message_id"))
        or str(int(datetime.now().timestamp() * 1000))
    )

    user = User(
        id=sender_id,
        username=sender_name or sender_id,
        first_name=sender_name or sender_id,
        is_bot=False,
        raw_data={"platform": "weixin"},
    )
    chat = Chat(
        id=sender_id,
        type="private",
        title=sender_name or None,
    )

    return UnifiedMessage(
        id=message_id,
        platform="weixin",
        user=user,
        chat=chat,
        date=_as_datetime(raw_message.get("create_time_ms")),
        type=MessageType.TEXT,
        text=_extract_text(raw_message),
        raw_data=dict(raw_message or {}),
    )
