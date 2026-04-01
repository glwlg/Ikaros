from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from core.platform.models import UnifiedContext

logger = logging.getLogger(__name__)


TextReplyHook = Callable[
    [Any, str, Any],
    Awaitable[None],
]


@dataclass(slots=True)
class _RegisteredTextReplyHook:
    owner: str
    priority: int
    handler: TextReplyHook


class TextReplyHookRegistry:
    def __init__(self) -> None:
        self._after_reply: list[_RegisteredTextReplyHook] = []

    def register_after_reply(
        self,
        handler: TextReplyHook,
        *,
        owner: str,
        priority: int = 100,
    ) -> None:
        safe_owner = str(owner or "").strip() or "text_reply_hook"
        hooks = [item for item in self._after_reply if item.owner != safe_owner]
        hooks.append(
            _RegisteredTextReplyHook(
                owner=safe_owner,
                priority=int(priority),
                handler=handler,
            )
        )
        hooks.sort(key=lambda item: (item.priority, item.owner))
        self._after_reply = hooks

    async def dispatch_after_reply(
        self,
        ctx: UnifiedContext,
        text: str,
        response: Any,
    ) -> None:
        safe_text = str(text or "").strip()
        if not safe_text:
            return
        for item in list(self._after_reply):
            try:
                await item.handler(ctx, safe_text, response)
            except Exception:
                logger.warning(
                    "Text reply hook failed owner=%s",
                    item.owner,
                    exc_info=True,
                )


text_reply_hook_registry = TextReplyHookRegistry()
