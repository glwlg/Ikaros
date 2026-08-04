from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.artifact_ledger import record_artifact_receipts
from core.file_artifacts import merge_file_rows
from core.runtime_v2 import runtime_event_bus, runtime_v2

logger = logging.getLogger(__name__)


@dataclass
class RuntimeDeliveryResult:
    delivered_rows: list[dict[str, str]] = field(default_factory=list)
    failed_rows: list[dict[str, str]] = field(default_factory=list)
    failed_names: list[str] = field(default_factory=list)
    target: str = ""


@dataclass
class RuntimeTextDeliveryResult:
    message: Any = None
    event: dict[str, Any] = field(default_factory=dict)
    target: str = ""


def _ctx_supports_result_kind(ctx: Any, kind: str) -> bool:
    adapter = getattr(ctx, "_adapter", None)
    capabilities = getattr(adapter, "capabilities", None)
    supports = getattr(capabilities, "supports_reply_kind", None)
    if callable(supports):
        return bool(supports(kind))
    return True


def _prepare_file_rows(file_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    prepared_rows: list[dict[str, str]] = []
    for item in list(file_rows or []):
        if not isinstance(item, dict):
            continue
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        try:
            resolved_path = str(Path(path_text).expanduser().resolve())
        except Exception:
            continue
        kind = str(item.get("kind") or "document").strip().lower() or "document"
        filename = str(item.get("filename") or "").strip() or Path(resolved_path).name
        prepared_rows.append(
            {
                "path": resolved_path,
                "kind": kind,
                "filename": filename,
                "caption": str(item.get("caption") or "").strip()[:500],
            }
        )
    return prepared_rows


def _target_for_ctx(ctx: Any) -> tuple[str, str, str]:
    message = getattr(ctx, "message", None)
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    chat_id = str(getattr(getattr(message, "chat", None), "id", "") or "").strip()
    target = f"{platform}:{chat_id}" if platform or chat_id else ""
    return platform, chat_id, target


def _runtime_artifacts_by_path(
    *,
    runtime_session_id: str,
    runtime_turn_id: str,
    rows: list[dict[str, str]],
    source: str,
    runtime_store: Any | None = None,
) -> dict[str, dict[str, Any]]:
    if not runtime_session_id:
        return {}
    artifact_by_path: dict[str, dict[str, Any]] = {}
    store = runtime_store or runtime_v2
    try:
        artifacts = store.record_artifacts(
            session_id=runtime_session_id,
            turn_id=runtime_turn_id,
            rows=rows,
            source=source,
        )
    except Exception:
        logger.warning(
            "Runtime v2 artifact registration failed; continuing delivery.",
            exc_info=True,
        )
        return {}
    for artifact in artifacts:
        artifact_path = str(artifact.get("path") or "").strip()
        if artifact_path:
            artifact_by_path[artifact_path] = artifact
        with contextlib.suppress(Exception):
            _publish_runtime_event(
                runtime_store=runtime_store,
                session_id=runtime_session_id,
                turn_id=runtime_turn_id,
                event_type="artifact_created",
                payload={
                    "artifact_id": artifact.get("id"),
                    "kind": artifact.get("kind"),
                    "path": artifact.get("path"),
                    "filename": artifact.get("filename"),
                    "mime": artifact.get("mime"),
                    "source": source,
                },
            )
    return artifact_by_path


def _publish_runtime_event(
    *,
    runtime_store: Any | None = None,
    session_id: str,
    event_type: str,
    turn_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if runtime_store is not None:
        return runtime_store.append_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            payload=payload or {},
        )
    return runtime_event_bus.publish(
        session_id=session_id,
        turn_id=turn_id,
        event_type=event_type,
        payload=payload or {},
    )


def _record_runtime_delivery(
    *,
    artifact: dict[str, Any] | None,
    runtime_session_id: str,
    runtime_turn_id: str,
    platform: str,
    target: str,
    path: str,
    status: str,
    error: str = "",
    runtime_store: Any | None = None,
) -> None:
    if not artifact:
        return
    artifact_id = str(artifact.get("id") or "")
    if not artifact_id:
        return
    store = runtime_store or runtime_v2
    try:
        store.record_delivery(
            artifact_id=artifact_id,
            platform=platform,
            target=target,
            status=status,
            error=error,
        )
        event_type = "artifact_delivered" if status == "delivered" else "delivery_failed"
        payload: dict[str, Any] = {
            "artifact_id": artifact_id,
            "platform": platform,
            "target": target,
            "path": path,
        }
        if error:
            payload["error"] = error
        _publish_runtime_event(
            runtime_store=runtime_store,
            session_id=runtime_session_id,
            turn_id=runtime_turn_id,
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        logger.warning("Runtime v2 delivery receipt failed.", exc_info=True)


async def _send_prepared_row(ctx: Any, item: dict[str, str]) -> None:
    path_obj = Path(str(item.get("path") or "")).expanduser().resolve()
    caption = str(item.get("caption") or "").strip() or None
    filename = str(item.get("filename") or path_obj.name).strip() or path_obj.name
    kind = str(item.get("kind") or "document").strip().lower() or "document"
    if kind == "photo":
        await ctx.reply_photo(str(path_obj), caption=caption)
    elif kind == "video":
        await ctx.reply_video(str(path_obj), caption=caption)
    elif kind == "audio":
        await ctx.reply_audio(str(path_obj), caption=caption)
    else:
        document: str | bytes = str(path_obj)
        output_name = filename
        if filename.lower().endswith(".md"):
            with contextlib.suppress(Exception):
                from services.md_converter import adapt_md_file_for_platform

                adapted_bytes, adapted_name = adapt_md_file_for_platform(
                    file_bytes=path_obj.read_bytes(),
                    filename=filename,
                    platform=str(getattr(getattr(ctx, "message", None), "platform", "") or ""),
                )
                document = adapted_bytes
                output_name = adapted_name
        await ctx.reply_document(
            document=document,
            filename=output_name,
            caption=caption,
        )


@contextlib.contextmanager
def _runtime_delivery_marker(ctx: Any):
    user_data = getattr(ctx, "user_data", None)
    if not isinstance(user_data, dict):
        yield
        return
    previous = user_data.get("_runtime_delivery_managed")
    user_data["_runtime_delivery_managed"] = True
    try:
        yield
    finally:
        if previous is None:
            user_data.pop("_runtime_delivery_managed", None)
        else:
            user_data["_runtime_delivery_managed"] = previous


async def deliver_result_files(
    *,
    ctx: Any,
    file_rows: list[dict[str, Any]],
    runtime_session_id: str = "",
    runtime_turn_id: str = "",
    source: str = "channel_delivery",
    ledger_source: str = "result_files",
    warn_on_failed: bool = True,
    runtime_store: Any | None = None,
) -> RuntimeDeliveryResult:
    prepared_rows = _prepare_file_rows(file_rows)
    result = RuntimeDeliveryResult()
    platform, _chat_id, target = _target_for_ctx(ctx)
    result.target = target
    artifact_by_path = _runtime_artifacts_by_path(
        runtime_session_id=runtime_session_id,
        runtime_turn_id=runtime_turn_id,
        rows=prepared_rows,
        source=source,
        runtime_store=runtime_store,
    )

    for item in merge_file_rows(prepared_rows):
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        path_obj = Path(path_text).expanduser().resolve()
        filename = str(item.get("filename") or path_obj.name).strip() or path_obj.name
        kind = str(item.get("kind") or "document").strip().lower() or "document"
        artifact = artifact_by_path.get(str(path_obj))
        if not path_obj.exists() or not path_obj.is_file():
            result.failed_names.append(filename)
            result.failed_rows.append(dict(item))
            _record_runtime_delivery(
                artifact=artifact,
                runtime_session_id=runtime_session_id,
                runtime_turn_id=runtime_turn_id,
                platform=platform,
                target=target,
                path=str(path_obj),
                status="failed",
                error="artifact file missing",
                runtime_store=runtime_store,
            )
            continue
        if not _ctx_supports_result_kind(ctx, kind):
            result.failed_names.append(filename)
            result.failed_rows.append(dict(item))
            _record_runtime_delivery(
                artifact=artifact,
                runtime_session_id=runtime_session_id,
                runtime_turn_id=runtime_turn_id,
                platform=platform,
                target=target,
                path=str(path_obj),
                status="failed",
                error=f"platform does not support {kind}",
                runtime_store=runtime_store,
            )
            continue
        try:
            with _runtime_delivery_marker(ctx):
                await _send_prepared_row(ctx, dict(item))
            result.delivered_rows.append(dict(item))
            _record_runtime_delivery(
                artifact=artifact,
                runtime_session_id=runtime_session_id,
                runtime_turn_id=runtime_turn_id,
                platform=platform,
                target=target,
                path=str(path_obj),
                status="delivered",
                runtime_store=runtime_store,
            )
        except Exception:
            result.failed_names.append(filename)
            result.failed_rows.append(dict(item))
            _record_runtime_delivery(
                artifact=artifact,
                runtime_session_id=runtime_session_id,
                runtime_turn_id=runtime_turn_id,
                platform=platform,
                target=target,
                path=str(path_obj),
                status="failed",
                error="attachment delivery failed",
                runtime_store=runtime_store,
            )
            logger.warning("Failed to send result attachment: %s", path_obj, exc_info=True)

    record_artifact_receipts(
        getattr(ctx, "user_data", None),
        result.delivered_rows,
        status="delivered",
        source=ledger_source,
        target=target,
    )
    record_artifact_receipts(
        getattr(ctx, "user_data", None),
        result.failed_rows,
        status="failed",
        source=ledger_source,
        target=target,
        error="attachment delivery failed",
    )
    if warn_on_failed and result.failed_names:
        preview = "、".join(result.failed_names[:3])
        suffix = " 等" if len(result.failed_names) > 3 else ""
        with contextlib.suppress(Exception):
            await ctx.reply(
                f"⚠️ 有 {len(result.failed_names)} 个附件未能发送：{preview}{suffix}"
            )
    return result


async def deliver_agent_message(
    *,
    ctx: Any,
    text: str = "",
    file_rows: list[dict[str, Any]] | None = None,
    runtime_session_id: str = "",
    runtime_turn_id: str = "",
    runtime_store: Any | None = None,
) -> dict[str, Any]:
    """Deliver an intermediate agent message and/or attachments immediately.

    Unlike the normal result-file path, this function is intended for a tool
    call made while the agent is still running.  Delivered files are recorded
    but are not returned as pending artifacts, so the outer final-response
    handler will not send them a second time.
    """

    rendered_text = str(text or "").strip()
    delivered_text = False
    if rendered_text:
        await deliver_text_message(
            ctx=ctx,
            payload=rendered_text,
            runtime_session_id=runtime_session_id,
            runtime_turn_id=runtime_turn_id,
            event_type="agent_message_sent",
            runtime_store=runtime_store,
        )
        delivered_text = True

    file_result = RuntimeDeliveryResult()
    if file_rows:
        file_result = await deliver_result_files(
            ctx=ctx,
            file_rows=file_rows,
            runtime_session_id=runtime_session_id,
            runtime_turn_id=runtime_turn_id,
            source="agent_tool",
            ledger_source="agent_message",
            warn_on_failed=False,
            runtime_store=runtime_store,
        )

    return {
        "delivered_text": delivered_text,
        "delivered_files": list(file_result.delivered_rows),
        "failed_files": list(file_result.failed_rows),
        "target": file_result.target,
    }


def _payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("text") or "")
    return str(payload or "")


async def deliver_text_message(
    *,
    ctx: Any,
    payload: Any,
    runtime_session_id: str = "",
    runtime_turn_id: str = "",
    edit_message_id: Any = None,
    event_type: str = "assistant_message_final",
    reply_kwargs: dict[str, Any] | None = None,
    edit_kwargs: dict[str, Any] | None = None,
    runtime_store: Any | None = None,
) -> RuntimeTextDeliveryResult:
    platform, _chat_id, target = _target_for_ctx(ctx)
    result = RuntimeTextDeliveryResult(target=target)
    text = _payload_text(payload)
    try:
        with _runtime_delivery_marker(ctx):
            if edit_message_id is not None:
                result.message = await ctx.edit_message(
                    edit_message_id,
                    text,
                    **dict(edit_kwargs or {}),
                )
            else:
                result.message = await ctx.reply(payload, **dict(reply_kwargs or {}))
    except Exception as exc:
        if runtime_session_id:
            with contextlib.suppress(Exception):
                _publish_runtime_event(
                    runtime_store=runtime_store,
                    session_id=runtime_session_id,
                    turn_id=runtime_turn_id,
                    event_type="delivery_failed",
                    payload={
                        "kind": "text",
                        "text_preview": text[:500],
                        "platform": platform,
                        "target": target,
                        "delivery": "edit" if edit_message_id is not None else "reply",
                        "error": str(exc),
                    },
                )
        raise
    if runtime_session_id:
        try:
            result.event = _publish_runtime_event(
                runtime_store=runtime_store,
                session_id=runtime_session_id,
                turn_id=runtime_turn_id,
                event_type=event_type,
                payload={
                    "text": text,
                    "platform": platform,
                    "target": target,
                    "delivery": "edit" if edit_message_id is not None else "reply",
                    "message_id": str(
                        getattr(result.message, "message_id", "")
                        or getattr(result.message, "id", "")
                        or edit_message_id
                        or ""
                    ),
                },
            )
        except Exception:
            logger.warning("Runtime v2 text delivery event failed.", exc_info=True)
    return result
