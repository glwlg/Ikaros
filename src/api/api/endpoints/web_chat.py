from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.api.binding_helpers import get_platform_user_ids
from api.auth.models import User
from api.auth.router import require_viewer
from api.auth.schemas import TtsRequest, WebInboundEventCreate, WebSessionCreate
from api.core.database import get_async_session
from core.channel_runtime_store import channel_runtime_store
from core.runtime_v2 import runtime_event_bus, runtime_v2
from core.state_paths import SINGLE_USER_SCOPE
from services.tts_service import synthesize_speech
from web_channel.store import (
    append_outbound_event,
    create_session_projection,
    enqueue_inbound_event,
    get_file_record,
    get_session_messages,
    get_session_projection,
    list_outbound_events,
    list_session_projections,
    register_artifact_file,
    register_upload_file,
    upsert_session_message,
)

router = APIRouter()


def _user_id(user: User) -> str:
    return str(user.id)


def _build_user_payload(user: User) -> dict[str, Any]:
    return {
        "user_id": _user_id(user),
        "username": user.username or user.email,
        "display_name": user.display_name or user.username or user.email,
    }


async def _source_user_ids(user: User, session: AsyncSession) -> list[str]:
    source_ids = [_user_id(user), SINGLE_USER_SCOPE]
    for platform in ("telegram", "weixin", "discord", "dingtalk"):
        source_ids.extend(await get_platform_user_ids(user.id, session, platform))
    output: list[str] = []
    seen: set[str] = set()
    for value in source_ids:
        safe = str(value or "").strip()
        if not safe or safe in seen:
            continue
        seen.add(safe)
        output.append(safe)
    return output


def _message_payload_for_user_event(
    session_id: str,
    payload: WebInboundEventCreate,
) -> dict[str, Any] | None:
    event_type = str(payload.type or "").strip()
    if event_type not in {"message_text", "message_file", "message_voice", "command"}:
        return None
    message_id = uuid.uuid4().hex
    if event_type in {"message_text", "command"}:
        content = str(payload.text or "").strip()
        message_type = "text"
    else:
        content = str(payload.caption or "").strip()
        message_type = "voice" if event_type == "message_voice" else "file"
    attachments = []
    if payload.file_id:
        attachments.append(
            {
                "id": payload.file_id,
                "file_id": payload.file_id,
                "kind": message_type,
                "name": str(payload.file_name or ""),
                "mime_type": str(payload.mime_type or "application/octet-stream"),
                "size": int(payload.file_size or 0),
            }
        )
    return {
        "id": message_id,
        "session_id": session_id,
        "role": "user",
        "content": content,
        "message_type": message_type,
        "attachments": attachments,
        "meta": dict(payload.metadata or {}),
    }


def _runtime_input_for_user_event(payload: WebInboundEventCreate) -> str:
    event_type = str(payload.type or "").strip()
    if event_type in {"message_text", "command"}:
        return str(payload.text or "").strip()
    return str(payload.caption or payload.text or "").strip()


@router.get("/sessions")
async def list_sessions(
    user: User = Depends(require_viewer),
    session: AsyncSession = Depends(get_async_session),
):
    source_user_ids = await _source_user_ids(user, session)
    return {
        "items": await list_session_projections(
            _user_id(user),
            source_user_ids=source_user_ids,
            limit=100,
        ),
    }


@router.post("/sessions")
async def create_session(
    payload: WebSessionCreate,
    user: User = Depends(require_viewer),
):
    session_id = uuid.uuid4().hex
    projection = await create_session_projection(
        user_id=_user_id(user),
        session_id=session_id,
        title=str(payload.title or "").strip(),
        preferences=dict(payload.preferences or {}),
    )
    channel_runtime_store.set_session_id(
        session_id=session_id,
        platform="web",
        platform_user_id=_user_id(user),
    )
    return projection["session"]


@router.get("/sessions/{session_id}/messages")
async def session_messages(
    session_id: str,
    user: User = Depends(require_viewer),
    session: AsyncSession = Depends(get_async_session),
):
    source_user_ids = await _source_user_ids(user, session)
    projection = await get_session_projection(
        _user_id(user),
        session_id,
        source_user_ids=source_user_ids,
    )
    channel_runtime_store.set_session_id(
        session_id=session_id,
        platform="web",
        platform_user_id=_user_id(user),
    )
    return {
        "session": projection.get("session") or {},
        "items": await get_session_messages(
            _user_id(user),
            session_id,
            source_user_ids=source_user_ids,
        ),
    }


@router.get("/sessions/{session_id}/deliveries")
async def session_deliveries(
    session_id: str,
    user: User = Depends(require_viewer),
    session: AsyncSession = Depends(get_async_session),
):
    source_user_ids = await _source_user_ids(user, session)
    projection = await get_session_projection(
        _user_id(user),
        session_id,
        source_user_ids=source_user_ids,
    )
    runtime_session = runtime_v2.get_session(session_id)
    if not runtime_session:
        return {"session": projection.get("session") or {}, "items": []}
    return {
        "session": projection.get("session") or {},
        "items": runtime_v2.list_deliveries(session_id=session_id, limit=200),
    }


@router.get("/sessions/{session_id}/trace")
async def session_trace(
    session_id: str,
    user: User = Depends(require_viewer),
    session: AsyncSession = Depends(get_async_session),
):
    source_user_ids = await _source_user_ids(user, session)
    projection = await get_session_projection(
        _user_id(user),
        session_id,
        source_user_ids=source_user_ids,
    )
    trace = runtime_v2.get_session_trace(session_id)
    return {
        "session": projection.get("session") or trace.get("session") or {},
        "runtime": trace,
    }


@router.post("/sessions/{session_id}/events")
async def create_session_event(
    session_id: str,
    payload: WebInboundEventCreate,
    user: User = Depends(require_viewer),
):
    projection = await create_session_projection(
        user_id=_user_id(user),
        session_id=session_id,
    )
    message_projection = _message_payload_for_user_event(session_id, payload)
    if message_projection is not None:
        stored = await upsert_session_message(
            user_id=_user_id(user),
            session_id=session_id,
            message=message_projection,
        )
    else:
        stored = None
    runtime_session = runtime_v2.ensure_session(
        session_id=session_id,
        kind="web_workspace",
        platform="web",
        platform_user_id=_user_id(user),
        title=str((projection.get("session") or {}).get("title") or "").strip(),
        metadata={
            "source": "web_chat_api",
            "preview": _runtime_input_for_user_event(payload)[:120],
        },
    )
    runtime_turn = None
    if message_projection is not None:
        runtime_turn = runtime_v2.create_turn(
            session_id=runtime_session["id"],
            source="user",
            input_text=_runtime_input_for_user_event(payload),
            metadata={
                "web_message_id": str((stored or {}).get("id") or ""),
                "event_type": str(payload.type or "").strip(),
                "file_id": str(payload.file_id or ""),
            },
        )
    event_payload = {
        **_build_user_payload(user),
        "session_id": session_id,
        "text": payload.text,
        "file_id": payload.file_id,
        "file_name": payload.file_name,
        "file_size": payload.file_size,
        "mime_type": payload.mime_type,
        "caption": payload.caption,
        "callback_data": payload.callback_data,
        "metadata": payload.metadata or {},
        "message_id": (stored or {}).get("id"),
        "runtime_v2_session_id": runtime_session.get("id"),
        "runtime_v2_turn_id": (runtime_turn or {}).get("id", ""),
    }
    queued = await enqueue_inbound_event(
        {
            "type": str(payload.type or "").strip(),
            "owner_user_id": _user_id(user),
            "session_id": session_id,
            "payload": event_payload,
        }
    )
    if runtime_turn is not None:
        runtime_turn = runtime_v2.update_turn_status(
            runtime_turn["id"],
            "queued",
            metadata={
                "web_inbound_event_id": str(queued.get("id") or ""),
            },
        )
        runtime_event_bus.publish(
            session_id=runtime_session["id"],
            turn_id=runtime_turn["id"],
            event_type="user_message",
            payload={
                "text": _runtime_input_for_user_event(payload),
                "message_type": str((stored or {}).get("message_type") or ""),
                "file_id": str(payload.file_id or ""),
                "metadata": dict(payload.metadata or {}),
            },
        )
    channel_runtime_store.set_session_id(
        session_id=session_id,
        platform="web",
        platform_user_id=_user_id(user),
    )
    return {
        "queued": queued,
        "message": stored,
        "session": projection.get("session") or {},
        "runtime": {
            "session_id": runtime_session.get("id"),
            "turn_id": (runtime_turn or {}).get("id", ""),
        },
    }


@router.get("/sessions/{session_id}/stream")
async def session_stream(
    session_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    once: bool = Query(default=False),
    user: User = Depends(require_viewer),
):
    async def event_stream():
        last_seq = int(after or 0)
        runtime_session = runtime_v2.get_session(session_id)
        while True:
            if await request.is_disconnected():
                return
            if runtime_session:
                events = runtime_v2.list_events(
                    session_id=session_id,
                    after_seq=last_seq,
                    limit=100,
                )
            else:
                events = await list_outbound_events(
                    owner_user_id=_user_id(user),
                    session_id=session_id,
                    after_seq=last_seq,
                    limit=100,
                )
            if not events:
                yield ": keep-alive\n\n"
                if once:
                    return
                await asyncio.sleep(1.0)
                continue
            for event in events:
                last_seq = max(last_seq, int(event.get("seq") or 0))
                event_payload = dict(event.get("payload") or {})
                if runtime_session:
                    event_payload.setdefault("runtime_v2", True)
                    event_payload.setdefault("turn_id", event.get("turn_id") or "")
                    event_payload.setdefault("created_at", event.get("created_at") or "")
                payload = json.dumps(event_payload, ensure_ascii=False)
                yield (
                    f"id: {event.get('seq')}\n"
                    f"event: {event.get('type')}\n"
                    f"data: {payload}\n\n"
                )
            if once:
                return

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/uploads")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Query(default=""),
    user: User = Depends(require_viewer),
):
    suffix = Path(str(file.filename or "")).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        tmp_path = Path(handle.name)
        content = await file.read()
        handle.write(content)
    try:
        record = await register_upload_file(
            owner_user_id=_user_id(user),
            session_id=str(session_id or "").strip(),
            source_path=str(tmp_path),
            original_name=str(file.filename or "upload.bin"),
            mime_type=str(file.content_type or "application/octet-stream"),
            size=len(content),
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return record


@router.get("/files/{file_id}")
async def download_chat_file(
    file_id: str,
    user: User = Depends(require_viewer),
):
    record = await get_file_record(file_id)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="文件不存在")
    if str(record.get("owner_user_id") or "") != _user_id(user):
        raise HTTPException(status_code=403, detail="没有访问权限")
    path = Path(str(record.get("path") or "")).resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        media_type=str(record.get("mime_type") or "application/octet-stream"),
        filename=str(record.get("name") or path.name),
    )


@router.post("/sessions/{session_id}/tts")
async def create_tts_audio(
    session_id: str,
    payload: TtsRequest,
    user: User = Depends(require_viewer),
    session: AsyncSession = Depends(get_async_session),
):
    source_user_ids = await _source_user_ids(user, session)
    messages = await get_session_messages(
        _user_id(user),
        session_id,
        source_user_ids=source_user_ids,
    )
    target = next(
        (
            item
            for item in messages
            if str(item.get("id") or "") == str(payload.message_id or "")
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    content = str(target.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容为空")
    audio_bytes = await synthesize_speech(content, voice=payload.voice)
    if not audio_bytes:
        raise HTTPException(status_code=503, detail="TTS 当前不可用")
    artifact = await register_artifact_file(
        owner_user_id=_user_id(user),
        session_id=session_id,
        source=audio_bytes,
        file_name=f"{payload.message_id}.mp3",
        mime_type="audio/mpeg",
    )
    attachment = {
        "id": str(artifact.get("id") or ""),
        "file_id": str(artifact.get("id") or ""),
        "kind": "audio",
        "name": str(artifact.get("name") or ""),
        "mime_type": str(artifact.get("mime_type") or "audio/mpeg"),
        "size": int(artifact.get("size") or 0),
    }
    updated = await upsert_session_message(
        user_id=_user_id(user),
        session_id=session_id,
        message={
            "id": str(payload.message_id or ""),
            "role": str(target.get("role") or "assistant"),
            "content": content,
            "message_type": str(target.get("message_type") or "text"),
            "attachments": list(target.get("attachments") or []) + [attachment],
            "meta": {**dict(target.get("meta") or {}), "tts_generated": True},
        },
    )
    await append_outbound_event(
        owner_user_id=_user_id(user),
        session_id=session_id,
        event_type="audio_ready",
        payload={"message_id": payload.message_id, "attachment": attachment},
    )
    return {
        "message": updated,
        "attachment": attachment,
    }
