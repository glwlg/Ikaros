from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict

from core.app_paths import data_dir


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_text(value: Any, limit: int = 0) -> str:
    rendered = str(value or "").strip()
    return rendered[:limit] if limit > 0 else rendered


class CodexKernelSessionStore:
    def __init__(self) -> None:
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return (data_dir() / "system" / "codex_kernel_sessions.json").resolve()

    def _default_payload(self) -> Dict[str, Any]:
        return {"version": 1, "sessions": {}}

    def _read_unlocked(self) -> Dict[str, Any]:
        default = self._default_payload()
        if not self.path.exists():
            return default
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        if not isinstance(loaded, dict):
            return default
        merged = dict(default)
        merged.update(loaded)
        sessions = merged.get("sessions")
        merged["sessions"] = dict(sessions) if isinstance(sessions, dict) else {}
        return merged

    def _write_unlocked(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def compose_key(*, user_id: str, platform: str, session_id: str) -> str:
        safe_user = _safe_text(user_id, 128)
        safe_platform = _safe_text(platform, 64).lower()
        safe_session = _safe_text(session_id, 160)
        if safe_platform:
            return f"{safe_platform}::{safe_user}::{safe_session}"
        return f"{safe_user}::{safe_session}"

    def get(
        self,
        *,
        user_id: str,
        platform: str,
        session_id: str,
    ) -> Dict[str, Any]:
        if not _safe_text(user_id, 128) or not _safe_text(session_id, 160):
            return {}
        key = self.compose_key(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        with self._lock:
            payload = self._read_unlocked()
            row = dict((payload.get("sessions") or {}).get(key) or {})
        return {
            "key": key,
            "user_id": _safe_text(row.get("user_id"), 128),
            "platform": _safe_text(row.get("platform"), 64).lower(),
            "session_id": _safe_text(row.get("session_id"), 160),
            "codex_thread_id": _safe_text(row.get("codex_thread_id"), 160),
            "codex_turn_id": _safe_text(row.get("codex_turn_id"), 160),
            "created_at": _safe_text(row.get("created_at"), 64),
            "updated_at": _safe_text(row.get("updated_at"), 64),
        }

    def upsert(
        self,
        *,
        user_id: str,
        platform: str,
        session_id: str,
        codex_thread_id: str,
        codex_turn_id: str = "",
    ) -> Dict[str, Any]:
        if not _safe_text(user_id, 128) or not _safe_text(session_id, 160):
            return {}
        key = self.compose_key(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        safe_thread = _safe_text(codex_thread_id, 160)
        if not safe_thread:
            return {}
        now = _now_iso()
        with self._lock:
            payload = self._read_unlocked()
            sessions = payload.setdefault("sessions", {})
            current = dict(sessions.get(key) or {})
            row = {
                "user_id": _safe_text(user_id, 128),
                "platform": _safe_text(platform, 64).lower(),
                "session_id": _safe_text(session_id, 160),
                "codex_thread_id": safe_thread,
                "codex_turn_id": _safe_text(codex_turn_id, 160),
                "created_at": _safe_text(current.get("created_at"), 64) or now,
                "updated_at": now,
            }
            sessions[key] = row
            self._write_unlocked(payload)
        return {"key": key, **row}

    def delete(
        self,
        *,
        user_id: str,
        platform: str,
        session_id: str,
    ) -> bool:
        if not _safe_text(user_id, 128) or not _safe_text(session_id, 160):
            return False
        key = self.compose_key(
            user_id=user_id,
            platform=platform,
            session_id=session_id,
        )
        with self._lock:
            payload = self._read_unlocked()
            sessions = payload.setdefault("sessions", {})
            existed = key in sessions
            sessions.pop(key, None)
            if existed:
                self._write_unlocked(payload)
            return existed


codex_kernel_sessions = CodexKernelSessionStore()
