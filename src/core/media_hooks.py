from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.platform.models import MessageType, UnifiedContext, UnifiedMessage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IncomingMediaInterceptResult:
    handled: bool = False
    forward_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReplyContextHookResult:
    handled: bool = False
    extra_context: str = ""
    detected_refs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


IncomingMediaInterceptor = Callable[
    [UnifiedContext],
    Awaitable[IncomingMediaInterceptResult | dict[str, Any] | None],
]
ReplyContextProvider = Callable[
    [UnifiedContext, UnifiedMessage],
    Awaitable[ReplyContextHookResult | dict[str, Any] | None],
]


@dataclass(slots=True)
class _RegisteredIncomingInterceptor:
    owner: str
    priority: int
    handler: IncomingMediaInterceptor


@dataclass(slots=True)
class _RegisteredReplyProvider:
    owner: str
    priority: int
    handler: ReplyContextProvider


class MediaHookRegistry:
    def __init__(self) -> None:
        self._incoming: dict[MessageType, list[_RegisteredIncomingInterceptor]] = {}
        self._reply: dict[MessageType, list[_RegisteredReplyProvider]] = {}

    def register_incoming_interceptor(
        self,
        message_type: MessageType,
        handler: IncomingMediaInterceptor,
        *,
        owner: str,
        priority: int = 100,
    ) -> None:
        safe_owner = str(owner or "").strip() or f"incoming:{message_type.value}"
        bucket = list(self._incoming.get(message_type) or [])
        bucket = [item for item in bucket if item.owner != safe_owner]
        bucket.append(
            _RegisteredIncomingInterceptor(
                owner=safe_owner,
                priority=int(priority),
                handler=handler,
            )
        )
        bucket.sort(key=lambda item: (item.priority, item.owner))
        self._incoming[message_type] = bucket

    def register_reply_context_provider(
        self,
        message_type: MessageType,
        handler: ReplyContextProvider,
        *,
        owner: str,
        priority: int = 100,
    ) -> None:
        safe_owner = str(owner or "").strip() or f"reply:{message_type.value}"
        bucket = list(self._reply.get(message_type) or [])
        bucket = [item for item in bucket if item.owner != safe_owner]
        bucket.append(
            _RegisteredReplyProvider(
                owner=safe_owner,
                priority=int(priority),
                handler=handler,
            )
        )
        bucket.sort(key=lambda item: (item.priority, item.owner))
        self._reply[message_type] = bucket

    async def dispatch_incoming(
        self,
        ctx: UnifiedContext,
    ) -> IncomingMediaInterceptResult:
        message_type = getattr(getattr(ctx, "message", None), "type", None)
        if not isinstance(message_type, MessageType):
            return IncomingMediaInterceptResult()

        for item in list(self._incoming.get(message_type) or []):
            try:
                outcome = await item.handler(ctx)
            except Exception:
                logger.warning(
                    "Incoming media interceptor failed owner=%s type=%s",
                    item.owner,
                    message_type.value,
                    exc_info=True,
                )
                continue
            normalized = self._normalize_incoming_outcome(outcome)
            if normalized.handled:
                return normalized
        return IncomingMediaInterceptResult()

    async def dispatch_reply_context(
        self,
        ctx: UnifiedContext,
        reply_to: UnifiedMessage,
    ) -> ReplyContextHookResult:
        message_type = getattr(reply_to, "type", None)
        if not isinstance(message_type, MessageType):
            return ReplyContextHookResult()

        for item in list(self._reply.get(message_type) or []):
            try:
                outcome = await item.handler(ctx, reply_to)
            except Exception:
                logger.warning(
                    "Reply context provider failed owner=%s type=%s",
                    item.owner,
                    message_type.value,
                    exc_info=True,
                )
                continue
            normalized = self._normalize_reply_outcome(outcome)
            if normalized.handled:
                return normalized
        return ReplyContextHookResult()

    @staticmethod
    def _normalize_incoming_outcome(
        outcome: IncomingMediaInterceptResult | dict[str, Any] | None,
    ) -> IncomingMediaInterceptResult:
        if isinstance(outcome, IncomingMediaInterceptResult):
            return outcome
        if not isinstance(outcome, dict):
            return IncomingMediaInterceptResult()
        return IncomingMediaInterceptResult(
            handled=bool(outcome.get("handled")),
            forward_text=str(outcome.get("forward_text") or ""),
            metadata=(
                dict(outcome.get("metadata"))
                if isinstance(outcome.get("metadata"), dict)
                else {}
            ),
        )

    @staticmethod
    def _normalize_reply_outcome(
        outcome: ReplyContextHookResult | dict[str, Any] | None,
    ) -> ReplyContextHookResult:
        if isinstance(outcome, ReplyContextHookResult):
            return outcome
        if not isinstance(outcome, dict):
            return ReplyContextHookResult()
        detected_refs = outcome.get("detected_refs")
        errors = outcome.get("errors")
        return ReplyContextHookResult(
            handled=bool(outcome.get("handled")),
            extra_context=str(outcome.get("extra_context") or ""),
            detected_refs=(
                [str(item).strip() for item in detected_refs if str(item).strip()]
                if isinstance(detected_refs, list)
                else []
            ),
            errors=(
                [str(item).strip() for item in errors if str(item).strip()]
                if isinstance(errors, list)
                else []
            ),
        )


media_hook_registry = MediaHookRegistry()

