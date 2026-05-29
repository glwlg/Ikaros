from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from core.config import DATA_DIR
from core.runtime_v2 import runtime_v2
from core.state_store import (
    create_chat_session,
    get_session_entries,
    list_chat_sessions,
)
from core.platform.models import MessageType
from shared.queue.jsonl_queue import FileLock, JsonlTable


WEB_CHANNEL_ROOT = (Path(DATA_DIR) / "web_channel").resolve()
WEB_CHANNEL_INBOX_DIR = (WEB_CHANNEL_ROOT / "inbox").resolve()
WEB_CHANNEL_OUTBOX_DIR = (WEB_CHANNEL_ROOT / "outbox").resolve()
WEB_CHANNEL_UPLOADS_DIR = (WEB_CHANNEL_ROOT / "uploads").resolve()
WEB_CHANNEL_ARTIFACTS_DIR = (WEB_CHANNEL_ROOT / "artifacts").resolve()
WEB_CHANNEL_FILES_DIR = (WEB_CHANNEL_ROOT / "files").resolve()
WEB_CHANNEL_SESSIONS_DIR = (WEB_CHANNEL_ROOT / "sessions").resolve()
WEB_CHANNEL_INBOX_TABLE = JsonlTable(
    str((WEB_CHANNEL_INBOX_DIR / "events.jsonl").resolve())
)


for directory in (
    WEB_CHANNEL_ROOT,
    WEB_CHANNEL_INBOX_DIR,
    WEB_CHANNEL_OUTBOX_DIR,
    WEB_CHANNEL_UPLOADS_DIR,
    WEB_CHANNEL_ARTIFACTS_DIR,
    WEB_CHANNEL_FILES_DIR,
    WEB_CHANNEL_SESSIONS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: Any) -> str:
    raw = _safe_text(value)
    if not raw:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)


def _file_meta_path(file_id: str) -> Path:
    safe_id = _slug(file_id) or uuid.uuid4().hex
    return (WEB_CHANNEL_FILES_DIR / f"{safe_id}.json").resolve()


def _outbox_table(user_id: str) -> JsonlTable:
    safe_user_id = _slug(user_id) or "__anonymous__"
    return JsonlTable(str((WEB_CHANNEL_OUTBOX_DIR / f"{safe_user_id}.jsonl").resolve()))


def _session_path(user_id: str, session_id: str) -> Path:
    safe_user_id = _slug(user_id) or "__anonymous__"
    safe_session_id = _slug(session_id) or uuid.uuid4().hex
    return (
        WEB_CHANNEL_SESSIONS_DIR / safe_user_id / f"{safe_session_id}.json"
    ).resolve()


def _session_default(
    session_id: str, *, title: str = "", preferences: dict[str, Any] | None = None
) -> dict[str, Any]:
    current_time = now_iso()
    safe_title = _safe_text(title) or "新对话"
    return {
        "version": 1,
        "session": {
            "id": _safe_text(session_id),
            "title": safe_title,
            "preview": "",
            "message_count": 0,
            "created_at": current_time,
            "updated_at": current_time,
            "last_message_at": "",
            "preferences": dict(preferences or {}),
        },
        "messages": [],
    }


def _preview_for_message(message: dict[str, Any]) -> str:
    content = _safe_text(message.get("content"))
    if content:
        return content[:120]
    attachments = message.get("attachments")
    if isinstance(attachments, list) and attachments:
        first = attachments[0]
        if isinstance(first, dict):
            name = _safe_text(first.get("name")) or _safe_text(first.get("mime_type"))
            if name:
                return f"[附件] {name}"
    return ""


def _dedupe_texts(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        safe = _safe_text(value)
        if not safe or safe in seen:
            continue
        seen.add(safe)
        output.append(safe)
    return output


def _state_session_kind(session_id: str) -> str:
    if _safe_text(session_id).startswith("scheduler-task-"):
        return "scheduled_task"
    return "channel"


def _state_session_projection(
    item: dict[str, Any],
    *,
    source_user_id: str,
) -> dict[str, Any]:
    session_id = _safe_text(item.get("session_id"))
    kind = _state_session_kind(session_id)
    title = _safe_text(item.get("title")) or (
        "定时任务" if kind == "scheduled_task" else "历史会话"
    )
    return {
        "id": session_id,
        "title": title,
        "preview": _safe_text(item.get("preview")),
        "message_count": int(item.get("message_count") or 0),
        "created_at": _safe_text(item.get("created_at")),
        "updated_at": _safe_text(item.get("updated_at")),
        "last_message_at": _safe_text(item.get("updated_at")),
        "preferences": {
            "source": "state_store",
            "source_user_id": _safe_text(source_user_id),
            "kind": kind,
        },
    }


def _runtime_session_projection(item: dict[str, Any]) -> dict[str, Any]:
    session_id = _safe_text(item.get("id"))
    kind = _safe_text(item.get("kind")) or _state_session_kind(session_id)
    title = _safe_text(item.get("title")) or (
        "定时任务" if kind == "scheduled_task" else "历史会话"
    )
    updated_at = _safe_text(item.get("updated_at"))
    event_summary = _runtime_session_event_summary(session_id)
    last_message_at = _safe_text(event_summary.get("last_message_at")) or updated_at
    return {
        "id": session_id,
        "title": title,
        "preview": _safe_text((item.get("metadata") or {}).get("preview"))
        or _safe_text(event_summary.get("preview")),
        "message_count": int(event_summary.get("message_count") or 0),
        "created_at": _safe_text(item.get("created_at")),
        "updated_at": updated_at,
        "last_message_at": last_message_at,
        "preferences": {
            "source": "runtime_v2",
            "kind": kind,
            "platform": _safe_text(item.get("platform")),
            "platform_user_id": _safe_text(item.get("platform_user_id")),
        },
    }


def _state_entry_message(
    item: dict[str, str],
    *,
    session_id: str,
    source_user_id: str,
    index: int,
) -> dict[str, Any]:
    role = _safe_text(item.get("role")).lower()
    return {
        "id": f"history-{_slug(source_user_id)}-{index}",
        "session_id": _safe_text(session_id),
        "role": "assistant" if role == "model" else (role or "user"),
        "content": str(item.get("content") or ""),
        "status": "completed",
        "message_type": "text",
        "attachments": [],
        "actions": [],
        "meta": {
            "source": "state_store",
            "source_user_id": _safe_text(source_user_id),
        },
        "created_at": "",
        "updated_at": "",
    }


def _runtime_event_message(event: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    event_type = _safe_text(event.get("type"))
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    role = ""
    content = ""
    message_type = "text"
    attachments: list[dict[str, Any]] = []

    if event_type in {"user_message", "scheduler_triggered"}:
        role = "user"
        content = _safe_text(payload.get("text") or payload.get("instruction"))
    elif event_type in {
        "assistant_message_final",
        "message_update",
        "background_message_sent",
    }:
        role = "assistant"
        content = _safe_text(payload.get("text"))
        message_type = _safe_text(payload.get("message_type")) or "text"
        attachments = [
            dict(item)
            for item in list(payload.get("attachments") or [])
            if isinstance(item, dict)
        ]
    elif event_type == "artifact_created":
        role = "assistant"
        kind = _safe_text(payload.get("kind")) or "document"
        filename = _safe_text(payload.get("filename")) or Path(
            _safe_text(payload.get("path"))
        ).name
        message_type = kind
        content = f"[附件] {filename}".strip()
        attachments = [
            {
                "id": _safe_text(payload.get("artifact_id"))
                or _safe_text(payload.get("path")),
                "file_id": _safe_text(payload.get("artifact_id"))
                or _safe_text(payload.get("path")),
                "kind": kind,
                "name": filename,
                "mime_type": _safe_text(payload.get("mime")),
                "path": _safe_text(payload.get("path")),
            }
        ]
    elif event_type == "request_user_input":
        role = "assistant"
        content = _safe_text(payload.get("prompt")) or "需要用户补充输入。"
    elif event_type == "delivery_failed":
        role = "assistant"
        path_text = _safe_text(payload.get("path"))
        filename = _safe_text(payload.get("filename")) or (
            Path(path_text).name if path_text else ""
        )
        error = _safe_text(payload.get("error"))
        target = _safe_text(payload.get("target"))
        subject = filename or _safe_text(payload.get("artifact_id")) or "附件"
        content = f"附件发送失败：{subject}"
        details = "；".join(part for part in [target, error] if part)
        if details:
            content = f"{content}（{details}）"

    if not role or not content:
        return {}
    return {
        "id": f"runtime-{event.get('seq')}",
        "session_id": _safe_text(session_id),
        "role": role,
        "content": content,
        "status": "completed",
        "message_type": message_type,
        "attachments": attachments,
        "actions": [],
        "meta": {"source": "runtime_v2", "event_type": event_type},
        "created_at": _safe_text(event.get("created_at")),
        "updated_at": _safe_text(event.get("created_at")),
    }


def _runtime_event_messages_for_event(
    event: dict[str, Any],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    event_type = _safe_text(event.get("type"))
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if event_type == "artifact_created":
        artifact_payloads = [
            dict(item)
            for item in list(payload.get("artifacts") or [])
            if isinstance(item, dict)
        ]
        if not artifact_payloads:
            artifact_payloads = [
                dict(item)
                for item in list(payload.get("files") or [])
                if isinstance(item, dict)
            ]
        if artifact_payloads:
            messages: list[dict[str, Any]] = []
            for index, artifact in enumerate(artifact_payloads, start=1):
                event_copy = {
                    **dict(event),
                    "payload": {
                        **artifact,
                        "artifact_id": artifact.get("id")
                        or artifact.get("artifact_id")
                        or artifact.get("path"),
                        "source": payload.get("source") or artifact.get("source"),
                    },
                }
                message = _runtime_event_message(event_copy, session_id=session_id)
                if message:
                    message["id"] = f"runtime-{event.get('seq')}-{index}"
                    messages.append(message)
            return messages
    message = _runtime_event_message(event, session_id=session_id)
    return [message] if message else []


def _message_key(message: dict[str, Any]) -> tuple[Any, ...]:
    attachments = [
        (
            _safe_text(item.get("kind")),
            _safe_text(item.get("name")) or _safe_text(item.get("path")),
        )
        for item in list(message.get("attachments") or [])
        if isinstance(item, dict)
    ]
    return (
        _safe_text(message.get("role")),
        _safe_text(message.get("content")),
        _safe_text(message.get("message_type")),
        tuple(attachments),
    )


def _merge_projection_and_runtime_messages(
    projection_messages: list[dict[str, Any]],
    runtime_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not projection_messages:
        return list(runtime_messages)
    output = list(projection_messages)
    seen = {_message_key(item) for item in output}
    projection_attachment_kinds = {
        _safe_text(attachment.get("kind"))
        for item in output
        for attachment in list(item.get("attachments") or [])
        if isinstance(attachment, dict)
    }
    for message in runtime_messages:
        key = _message_key(message)
        if key in seen:
            continue
        attachments = [
            item
            for item in list(message.get("attachments") or [])
            if isinstance(item, dict)
        ]
        if attachments and any(
            _safe_text(item.get("kind")) in projection_attachment_kinds
            for item in attachments
        ):
            continue
        output.append(message)
        seen.add(key)
    return output


def _runtime_event_messages(session_id: str) -> list[dict[str, Any]]:
    runtime_events = runtime_v2.list_events(session_id=session_id, limit=500)
    return [
        message
        for event in runtime_events
        for message in _runtime_event_messages_for_event(event, session_id=session_id)
    ]


def _runtime_session_event_summary(session_id: str) -> dict[str, Any]:
    messages = _runtime_event_messages(session_id)
    if not messages:
        return {}
    return {
        "message_count": len(messages),
        "preview": _preview_for_message(messages[-1]),
        "last_message_at": _safe_text(messages[-1].get("updated_at"))
        or _safe_text(messages[-1].get("created_at")),
    }


async def _read_session_payload(user_id: str, session_id: str) -> dict[str, Any]:
    path = _session_path(user_id, session_id)
    lock = path.with_suffix(path.suffix + ".lock")
    async with FileLock(lock):
        if not path.exists():
            return _session_default(session_id)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return _session_default(session_id)
        if not isinstance(loaded, dict):
            return _session_default(session_id)
        payload = _session_default(session_id)
        payload.update(loaded)
        session_meta = payload.get("session")
        payload["session"] = (
            {**payload["session"], **session_meta}
            if isinstance(session_meta, dict)
            else payload["session"]
        )
        messages = payload.get("messages")
        payload["messages"] = list(messages) if isinstance(messages, list) else []
        return payload


async def _write_session_payload(
    user_id: str, session_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    path = _session_path(user_id, session_id)
    lock = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    async with FileLock(lock):
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return payload


def infer_message_type(
    *,
    mime_type: str | None = None,
    file_name: str | None = None,
    force_voice: bool = False,
) -> MessageType:
    if force_voice:
        return MessageType.VOICE
    mime = _safe_text(mime_type).lower()
    guessed = mime
    if not guessed and file_name:
        guessed = _safe_text(mimetypes.guess_type(file_name)[0]).lower()
    if guessed.startswith("image/"):
        return MessageType.IMAGE
    if guessed.startswith("video/"):
        return MessageType.VIDEO
    if guessed.startswith("audio/"):
        if "ogg" in guessed or "opus" in guessed or "webm" in guessed:
            return MessageType.VOICE
        return MessageType.AUDIO
    return MessageType.DOCUMENT


async def register_upload_file(
    *,
    owner_user_id: str,
    source_path: str,
    original_name: str,
    mime_type: str,
    size: int,
    session_id: str = "",
) -> dict[str, Any]:
    file_id = uuid.uuid4().hex
    suffix = (
        Path(original_name).suffix or mimetypes.guess_extension(mime_type or "") or ""
    )
    target_path = (WEB_CHANNEL_UPLOADS_DIR / f"{file_id}{suffix}").resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)
    payload = {
        "id": file_id,
        "storage": "upload",
        "path": str(target_path),
        "owner_user_id": _safe_text(owner_user_id),
        "session_id": _safe_text(session_id),
        "name": _safe_text(original_name) or target_path.name,
        "mime_type": _safe_text(mime_type) or "application/octet-stream",
        "size": int(size or 0),
        "created_at": now_iso(),
    }
    _file_meta_path(file_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


async def register_artifact_file(
    *,
    owner_user_id: str,
    source: str | bytes,
    file_name: str,
    mime_type: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    file_id = uuid.uuid4().hex
    suffix = Path(file_name).suffix or mimetypes.guess_extension(mime_type or "") or ""
    target_path = (WEB_CHANNEL_ARTIFACTS_DIR / f"{file_id}{suffix}").resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, bytes):
        target_path.write_bytes(source)
    else:
        shutil.copyfile(str(source), target_path)
    resolved_mime = (
        _safe_text(mime_type)
        or _safe_text(mimetypes.guess_type(file_name)[0])
        or "application/octet-stream"
    )
    payload = {
        "id": file_id,
        "storage": "artifact",
        "path": str(target_path),
        "owner_user_id": _safe_text(owner_user_id),
        "session_id": _safe_text(session_id),
        "name": _safe_text(file_name) or target_path.name,
        "mime_type": resolved_mime,
        "size": int(target_path.stat().st_size),
        "created_at": now_iso(),
    }
    _file_meta_path(file_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


async def get_file_record(file_id: str) -> dict[str, Any] | None:
    path = _file_meta_path(file_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


async def load_file_bytes(file_id: str) -> bytes:
    record = await get_file_record(file_id)
    if not isinstance(record, dict):
        raise FileNotFoundError(file_id)
    path = Path(str(record.get("path") or "")).resolve()
    if not path.exists():
        raise FileNotFoundError(file_id)
    return path.read_bytes()


async def enqueue_inbound_event(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "created_at": now_iso(),
        "claimed_at": "",
        "processed_at": "",
        **dict(payload or {}),
    }
    await WEB_CHANNEL_INBOX_TABLE.append(normalized)
    return normalized


async def claim_inbound_events(*, limit: int = 20) -> list[dict[str, Any]]:
    claimed: list[dict[str, Any]] = []
    claim_time = now_iso()
    async with WEB_CHANNEL_INBOX_TABLE._inproc_lock:
        async with FileLock(WEB_CHANNEL_INBOX_TABLE.lock_path):
            rows = WEB_CHANNEL_INBOX_TABLE._read_all_unlocked()
            changed = False
            for row in rows:
                if len(claimed) >= max(1, int(limit)):
                    break
                if _safe_text(row.get("status")).lower() != "pending":
                    continue
                row["status"] = "claimed"
                row["claimed_at"] = claim_time
                claimed.append(dict(row))
                changed = True
            if changed:
                WEB_CHANNEL_INBOX_TABLE._write_all_unlocked(rows)
    return claimed


async def ack_inbound_event(
    event_id: str, *, status: str = "done", error: str = ""
) -> None:
    async with WEB_CHANNEL_INBOX_TABLE._inproc_lock:
        async with FileLock(WEB_CHANNEL_INBOX_TABLE.lock_path):
            rows = WEB_CHANNEL_INBOX_TABLE._read_all_unlocked()
            changed = False
            for row in rows:
                if _safe_text(row.get("id")) != _safe_text(event_id):
                    continue
                row["status"] = _safe_text(status) or "done"
                row["processed_at"] = now_iso()
                row["error"] = _safe_text(error)
                changed = True
                break
            if changed:
                WEB_CHANNEL_INBOX_TABLE._write_all_unlocked(rows)


async def fail_inbound_event(event_id: str, error: str) -> None:
    await ack_inbound_event(event_id, status="failed", error=error)


async def append_outbound_event(
    *,
    owner_user_id: str,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    table = _outbox_table(owner_user_id)
    async with table._inproc_lock:
        async with FileLock(table.lock_path):
            existing = table._read_all_unlocked()
            seq = len(existing) + 1
            event = {
                "seq": seq,
                "id": uuid.uuid4().hex,
                "session_id": _safe_text(session_id),
                "type": _safe_text(event_type),
                "created_at": now_iso(),
                "payload": dict(payload or {}),
            }
            existing.append(event)
            table._write_all_unlocked(existing)
    return event


async def list_outbound_events(
    *,
    owner_user_id: str,
    after_seq: int = 0,
    session_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    table = _outbox_table(owner_user_id)
    rows = await table.read_all()
    target_session_id = _safe_text(session_id)
    output: list[dict[str, Any]] = []
    for row in rows:
        try:
            seq = int(row.get("seq") or 0)
        except Exception:
            seq = 0
        if seq <= int(after_seq or 0):
            continue
        if target_session_id and _safe_text(row.get("session_id")) not in {
            "",
            target_session_id,
        }:
            continue
        output.append(dict(row))
        if len(output) >= max(1, int(limit)):
            break
    return output


async def ensure_session_projection(
    *,
    user_id: str,
    session_id: str,
    title: str = "",
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_user_id = _safe_text(user_id)
    safe_session_id = _safe_text(session_id)
    path = _session_path(safe_user_id, safe_session_id)
    lock = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    async with FileLock(lock):
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = _session_default(safe_session_id)
        else:
            payload = _session_default(safe_session_id)
        if not isinstance(payload, dict):
            payload = _session_default(safe_session_id)
        payload = _session_default(safe_session_id) | payload
        session = payload.get("session")
        if not isinstance(session, dict):
            session = _session_default(safe_session_id)["session"]
            payload["session"] = session
        payload["messages"] = list(payload.get("messages") or [])
        changed = False
        if title and _safe_text(session.get("title")) in {"", "新对话"}:
            session["title"] = _safe_text(title)
            changed = True
        if preferences:
            current_preferences = session.get("preferences")
            if not isinstance(current_preferences, dict):
                current_preferences = {}
            session["preferences"] = {**current_preferences, **dict(preferences)}
            changed = True
        if changed or not path.exists():
            session["updated_at"] = now_iso()
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    await create_chat_session(safe_user_id, safe_session_id)
    runtime_v2.ensure_session(
        session_id=safe_session_id,
        kind="web_workspace",
        platform="web",
        platform_user_id=safe_user_id,
        title=title,
        metadata={"source": "web_channel_projection"},
    )
    return await _read_session_payload(safe_user_id, safe_session_id)


async def create_session_projection(
    *,
    user_id: str,
    session_id: str,
    title: str = "",
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await ensure_session_projection(
        user_id=user_id,
        session_id=session_id,
        title=title,
        preferences=preferences,
    )


async def upsert_session_message(
    *,
    user_id: str,
    session_id: str,
    message: dict[str, Any],
) -> dict[str, Any]:
    safe_user_id = _safe_text(user_id)
    safe_session_id = _safe_text(session_id)
    await ensure_session_projection(user_id=safe_user_id, session_id=safe_session_id)
    path = _session_path(safe_user_id, safe_session_id)
    lock = path.with_suffix(path.suffix + ".lock")
    async with FileLock(lock):
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = _session_default(safe_session_id)
        else:
            payload = _session_default(safe_session_id)
        if not isinstance(payload, dict):
            payload = _session_default(safe_session_id)
        session = payload.get("session")
        if not isinstance(session, dict):
            session = _session_default(safe_session_id)["session"]
            payload["session"] = session
        rows = list(payload.get("messages") or [])
        payload["messages"] = rows
        safe_message_id = _safe_text(message.get("id")) or uuid.uuid4().hex
        existing = None
        for row in rows:
            if _safe_text(row.get("id")) == safe_message_id:
                existing = row
                break
        current_time = now_iso()
        normalized = {
            "id": safe_message_id,
            "session_id": safe_session_id,
            "role": _safe_text(message.get("role")) or "assistant",
            "content": str(message.get("content") or ""),
            "status": _safe_text(message.get("status")) or "completed",
            "message_type": _safe_text(message.get("message_type")) or "text",
            "attachments": list(message.get("attachments") or []),
            "actions": list(message.get("actions") or []),
            "meta": dict(message.get("meta") or {}),
            "created_at": _safe_text(message.get("created_at")) or current_time,
            "updated_at": current_time,
        }
        if existing is not None:
            existing.update(normalized)
            target = existing
        else:
            rows.append(normalized)
            target = normalized
        if target["role"] == "user" and _safe_text(session.get("title")) in {
            "",
            "新对话",
        }:
            preview_title = _preview_for_message(target)
            if preview_title:
                session["title"] = preview_title[:48]
        session["preview"] = _preview_for_message(target)
        session["message_count"] = len(rows)
        session["updated_at"] = current_time
        session["last_message_at"] = target["updated_at"]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return dict(target)


async def get_session_projection(
    user_id: str,
    session_id: str,
    *,
    source_user_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    safe_user_id = _safe_text(user_id)
    safe_session_id = _safe_text(session_id)
    if _session_path(safe_user_id, safe_session_id).exists():
        return await ensure_session_projection(
            user_id=safe_user_id,
            session_id=safe_session_id,
        )

    runtime_session = runtime_v2.get_session(safe_session_id)
    if runtime_session:
        return {
            "version": 1,
            "session": _runtime_session_projection(runtime_session),
            "messages": [],
        }

    for source_user_id in _dedupe_texts([safe_user_id, *list(source_user_ids or [])]):
        for item in await list_chat_sessions(source_user_id, limit=200):
            if _safe_text(item.get("session_id")) != safe_session_id:
                continue
            return {
                "version": 1,
                "session": _state_session_projection(
                    item,
                    source_user_id=source_user_id,
                ),
                "messages": [],
            }
    return await ensure_session_projection(
        user_id=safe_user_id,
        session_id=safe_session_id,
    )


async def get_session_messages(
    user_id: str,
    session_id: str,
    *,
    source_user_ids: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    safe_user_id = _safe_text(user_id)
    safe_session_id = _safe_text(session_id)
    projection_messages: list[dict[str, Any]] = []
    if _session_path(safe_user_id, safe_session_id).exists():
        payload = await ensure_session_projection(
            user_id=safe_user_id,
            session_id=safe_session_id,
        )
        projection_messages = list(payload.get("messages") or [])

    runtime_messages = _runtime_event_messages(safe_session_id)
    if projection_messages:
        return _merge_projection_and_runtime_messages(
            projection_messages,
            runtime_messages,
        )

    for source_user_id in _dedupe_texts([safe_user_id, *list(source_user_ids or [])]):
        rows = await get_session_entries(source_user_id, safe_session_id)
        if not rows:
            continue
        return [
            _state_entry_message(
                item,
                session_id=safe_session_id,
                source_user_id=source_user_id,
                index=index,
            )
            for index, item in enumerate(rows, start=1)
        ]

    if runtime_messages:
        return runtime_messages

    payload = await ensure_session_projection(
        user_id=safe_user_id,
        session_id=safe_session_id,
    )
    return list(payload.get("messages") or [])


async def list_session_projections(
    user_id: str,
    *,
    source_user_ids: list[str] | tuple[str, ...] = (),
    limit: int = 50,
) -> list[dict[str, Any]]:
    safe_user_id = _slug(user_id) or "__anonymous__"
    root = (WEB_CHANNEL_SESSIONS_DIR / safe_user_id).resolve()
    rows_by_id: dict[str, dict[str, Any]] = {}
    if root.exists():
        for path in root.glob("*.json"):
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(loaded, dict):
                continue
            session_meta = loaded.get("session")
            if not isinstance(session_meta, dict):
                continue
            row = dict(session_meta)
            session_id = _safe_text(row.get("id"))
            if session_id:
                rows_by_id[session_id] = row

    for source_user_id in _dedupe_texts([str(user_id), *list(source_user_ids or [])]):
        fallback_sessions = await list_chat_sessions(source_user_id, limit=limit)
        for item in fallback_sessions:
            row = _state_session_projection(item, source_user_id=source_user_id)
            session_id = _safe_text(row.get("id"))
            if not session_id:
                continue
            existing = rows_by_id.get(session_id)
            if existing:
                existing_count = int(existing.get("message_count") or 0)
                row_count = int(row.get("message_count") or 0)
                if row_count <= existing_count:
                    continue
            rows_by_id[session_id] = row

    runtime_sessions = runtime_v2.list_sessions(
        platform_user_ids=_dedupe_texts([str(user_id), *list(source_user_ids or [])]),
        limit=max(100, int(limit or 50)),
    )
    for item in runtime_sessions:
        row = _runtime_session_projection(item)
        session_id = _safe_text(row.get("id"))
        if not session_id:
            continue
        existing = rows_by_id.get(session_id)
        if existing:
            existing_updated = _safe_text(existing.get("updated_at"))
            row_updated = _safe_text(row.get("updated_at"))
            if existing_updated and existing_updated >= row_updated:
                continue
        rows_by_id[session_id] = row

    rows = list(rows_by_id.values())
    rows.sort(
        key=lambda item: (
            _safe_text(item.get("updated_at")),
            _safe_text(item.get("last_message_at")),
            _safe_text(item.get("id")),
        ),
        reverse=True,
    )
    return rows[: max(1, int(limit))]
