from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import threading
import uuid
import zlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from core.app_paths import data_dir

SESSION_KINDS = {"channel_chat", "scheduled_task", "web_workspace", "system"}
RUNTIME_STATUSES = {
    "queued",
    "running",
    "waiting_user",
    "waiting_external",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}
STATUS_TRANSITIONS = {
    "queued": {"running", "cancelled", "expired", "failed"},
    "running": {
        "waiting_user",
        "waiting_external",
        "succeeded",
        "failed",
        "cancelled",
        "expired",
    },
    "waiting_user": {"running", "cancelled", "expired", "failed"},
    "waiting_external": {"running", "succeeded", "failed", "cancelled", "expired"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "expired": set(),
}


class RuntimeV2TransitionError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _safe_text(value: Any, limit: int = 0) -> str:
    rendered = str(value or "").strip()
    return rendered[:limit] if limit > 0 else rendered


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(minimum, value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any) -> dict[str, Any]:
    try:
        loaded = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    payload = dict(row)
    for key in ("metadata_json", "payload_json"):
        if key in payload:
            target = "metadata" if key == "metadata_json" else "payload"
            payload[target] = _json_loads(payload.pop(key))
    return payload


def _status(value: Any) -> str:
    token = _safe_text(value, 40).lower()
    return token if token in RUNTIME_STATUSES else "queued"


def _kind(value: Any) -> str:
    token = _safe_text(value, 40).lower()
    return token if token in SESSION_KINDS else "channel_chat"


def _sha256(path_text: str) -> str:
    path = Path(path_text).expanduser()
    if not path.exists() or not path.is_file():
        return ""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_iso(value: Any) -> datetime | None:
    text = _safe_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _assert_transition(current: str, target: str) -> None:
    current_status = _status(current)
    target_status = _status(target)
    if current_status == target_status:
        return
    allowed = STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise RuntimeV2TransitionError(
            f"invalid runtime status transition: {current_status} -> {target_status}"
        )


class RuntimeV2Store:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path).expanduser().resolve() if db_path else None
        self._lock = threading.RLock()

    @property
    def db_path(self) -> Path:
        raw = _safe_text(os.getenv("IKAROS_RUNTIME_DB_PATH"))
        if raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = (data_dir() / path).resolve()
            return path.resolve()
        if self._db_path is not None:
            return self._db_path
        return (data_dir() / "runtime.db").resolve()

    def _connect(self) -> sqlite3.Connection:
        path = self.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(conn)
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                platform_user_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                current_kernel_provider TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_owner
                ON sessions(platform, platform_user_id, updated_at);

            CREATE TABLE IF NOT EXISTS kernel_sessions (
                session_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                external_thread_id TEXT NOT NULL DEFAULT '',
                external_turn_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(session_id, provider),
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user',
                input_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                kernel_provider TEXT NOT NULL DEFAULT '',
                external_turn_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session
                ON turns(session_id, updated_at);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_session_turn
                ON events(session_id, turn_id, seq);

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'document',
                path TEXT NOT NULL DEFAULT '',
                mime TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                sha256 TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(session_id, turn_id, path),
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_session
                ON artifacts(session_id, updated_at);

            CREATE TABLE IF NOT EXISTS deliveries (
                id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_deliveries_artifact
                ON deliveries(artifact_id, platform, target);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scheduler_jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                crontab TEXT NOT NULL DEFAULT '',
                instruction TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                chat_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            """
        )

    def ensure_session(
        self,
        *,
        session_id: str = "",
        kind: str = "channel_chat",
        platform: str = "",
        platform_user_id: str = "",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_id = _safe_text(session_id, 180) or uuid.uuid4().hex
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (safe_id,)).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO sessions(
                        id, kind, platform, platform_user_id, title,
                        created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_id,
                        _kind(kind),
                        _safe_text(platform, 64).lower(),
                        _safe_text(platform_user_id, 160),
                        _safe_text(title, 240),
                        now,
                        now,
                        _json_dumps(metadata or {}),
                    ),
                )
            else:
                current = _json_loads(row["metadata_json"])
                if metadata:
                    current.update(dict(metadata))
                existing_owner = _safe_text(row["platform_user_id"], 160)
                requested_owner = _safe_text(platform_user_id, 160)
                next_owner = existing_owner or requested_owner
                conn.execute(
                    """
                    UPDATE sessions
                    SET kind = ?, platform = ?, platform_user_id = ?,
                        title = COALESCE(NULLIF(?, ''), title),
                        updated_at = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        _kind(kind),
                        _safe_text(platform, 64).lower(),
                        next_owner,
                        _safe_text(title, 240),
                        now,
                        _json_dumps(current),
                        safe_id,
                    ),
                )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM sessions WHERE id = ?", (safe_id,)).fetchone()
            )

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (_safe_text(session_id, 180),),
                ).fetchone()
            )

    def list_sessions(
        self,
        *,
        platform_user_ids: list[str] | tuple[str, ...] = (),
        kinds: list[str] | tuple[str, ...] = (),
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        user_ids = [_safe_text(item, 160) for item in platform_user_ids if _safe_text(item)]
        if user_ids:
            clauses.append(
                "platform_user_id IN (" + ",".join(["?"] * len(user_ids)) + ")"
            )
            args.extend(user_ids)
        safe_kinds = [_kind(item) for item in kinds if _safe_text(item)]
        if safe_kinds:
            clauses.append("kind IN (" + ",".join(["?"] * len(safe_kinds)) + ")")
            args.extend(safe_kinds)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(max(1, int(limit or 1)))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions {where} ORDER BY updated_at DESC LIMIT ?",
                args,
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def create_turn(
        self,
        *,
        session_id: str,
        source: str = "user",
        input_text: str = "",
        kernel_provider: str = "",
        status: str = "queued",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            raise ValueError("session_id is required")
        safe_status = _status(status)
        now = _now_iso()
        turn_id = uuid.uuid4().hex
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO turns(
                    id, session_id, source, input_text, status, kernel_provider,
                    started_at, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    safe_session_id,
                    _safe_text(source, 80) or "user",
                    str(input_text or ""),
                    safe_status,
                    _safe_text(kernel_provider, 60),
                    now if safe_status == "running" else "",
                    now,
                    now,
                    _json_dumps(metadata or {}),
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, safe_session_id),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            )

    def update_turn_status(
        self,
        turn_id: str,
        status: str,
        *,
        error: str = "",
        external_turn_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_turn_id = _safe_text(turn_id, 180)
        target = _status(status)
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM turns WHERE id = ?", (safe_turn_id,)).fetchone()
            if row is None:
                return {}
            _assert_transition(str(row["status"] or ""), target)
            current = _json_loads(row["metadata_json"])
            if metadata:
                current.update(dict(metadata))
            started_at = str(row["started_at"] or "")
            completed_at = str(row["completed_at"] or "")
            if target == "running" and not started_at:
                started_at = now
            if target in TERMINAL_STATUSES and not completed_at:
                completed_at = now
            conn.execute(
                """
                UPDATE turns
                SET status = ?, error = COALESCE(NULLIF(?, ''), error),
                    external_turn_id = COALESCE(NULLIF(?, ''), external_turn_id),
                    started_at = ?, completed_at = ?, updated_at = ?,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    target,
                    _safe_text(error, 2000),
                    _safe_text(external_turn_id, 180),
                    started_at,
                    completed_at,
                    now,
                    _json_dumps(current),
                    safe_turn_id,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, row["session_id"]),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM turns WHERE id = ?", (safe_turn_id,)).fetchone()
            )

    def get_turn(self, turn_id: str) -> dict[str, Any]:
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM turns WHERE id = ?",
                    (_safe_text(turn_id, 180),),
                ).fetchone()
            )

    def list_turns(self, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return []
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM turns
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (safe_session_id, max(1, int(limit or 1))),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def append_event(
        self,
        *,
        session_id: str,
        event_type: str,
        turn_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return {}
        now = _now_iso()
        with self._lock, self._connection() as conn:
            seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM events WHERE session_id = ?",
                    (safe_session_id,),
                ).fetchone()["seq"]
                or 1
            )
            conn.execute(
                """
                INSERT INTO events(session_id, turn_id, seq, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_session_id,
                    _safe_text(turn_id, 180),
                    seq,
                    _safe_text(event_type, 120) or "event",
                    _json_dumps(payload or {}),
                    now,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, safe_session_id),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM events WHERE session_id = ? AND seq = ?",
                    (safe_session_id, seq),
                ).fetchone()
            )

    def _append_event_conn(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        event_type: str,
        turn_id: str = "",
        payload: dict[str, Any] | None = None,
        created_at: str = "",
    ) -> None:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return
        seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM events WHERE session_id = ?",
                (safe_session_id,),
            ).fetchone()["seq"]
            or 1
        )
        conn.execute(
            """
            INSERT INTO events(session_id, turn_id, seq, type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                safe_session_id,
                _safe_text(turn_id, 180),
                seq,
                _safe_text(event_type, 120) or "event",
                _json_dumps(payload or {}),
                created_at or _now_iso(),
            ),
        )

    def list_events(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        after_seq: int = 0,
        limit: int = 200,
        latest: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["session_id = ?", "seq > ?"]
        args: list[Any] = [_safe_text(session_id, 180), int(after_seq or 0)]
        if _safe_text(turn_id):
            clauses.append("turn_id = ?")
            args.append(_safe_text(turn_id, 180))
        args.append(max(1, int(limit or 1)))
        order = "DESC" if latest else "ASC"
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM events
                WHERE {' AND '.join(clauses)}
                ORDER BY seq {order}
                LIMIT ?
                """,
                args,
            ).fetchall()
            if latest:
                rows = list(reversed(rows))
            return [_row_to_dict(row) for row in rows]

    def get_kernel_session(self, *, session_id: str, provider: str) -> dict[str, Any]:
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute(
                    """
                    SELECT * FROM kernel_sessions
                    WHERE session_id = ? AND provider = ?
                    """,
                    (_safe_text(session_id, 180), _safe_text(provider, 60)),
                ).fetchone()
            )

    def list_kernel_sessions(self, session_id: str) -> list[dict[str, Any]]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return []
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM kernel_sessions
                WHERE session_id = ?
                ORDER BY updated_at ASC, provider ASC
                """,
                (safe_session_id,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def upsert_kernel_session(
        self,
        *,
        session_id: str,
        provider: str,
        external_thread_id: str,
        external_turn_id: str = "",
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        safe_provider = _safe_text(provider, 60)
        if not safe_session_id or not safe_provider:
            return {}
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM kernel_sessions
                WHERE session_id = ? AND provider = ?
                """,
                (safe_session_id, safe_provider),
            ).fetchone()
            current = _json_loads(row["metadata_json"]) if row is not None else {}
            if metadata:
                current.update(dict(metadata))
            if row is None:
                conn.execute(
                    """
                    INSERT INTO kernel_sessions(
                        session_id, provider, external_thread_id, external_turn_id,
                        status, created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_session_id,
                        safe_provider,
                        _safe_text(external_thread_id, 180),
                        _safe_text(external_turn_id, 180),
                        _safe_text(status, 60) or "active",
                        now,
                        now,
                        _json_dumps(current),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE kernel_sessions
                    SET external_thread_id = COALESCE(NULLIF(?, ''), external_thread_id),
                        external_turn_id = COALESCE(NULLIF(?, ''), external_turn_id),
                        status = ?, updated_at = ?, metadata_json = ?
                    WHERE session_id = ? AND provider = ?
                    """,
                    (
                        _safe_text(external_thread_id, 180),
                        _safe_text(external_turn_id, 180),
                        _safe_text(status, 60) or "active",
                        now,
                        _json_dumps(current),
                        safe_session_id,
                        safe_provider,
                    ),
                )
            conn.execute(
                """
                UPDATE sessions
                SET current_kernel_provider = ?, updated_at = ?
                WHERE id = ?
                """,
                (safe_provider, now, safe_session_id),
            )
            conn.commit()
            return self.get_kernel_session(session_id=safe_session_id, provider=safe_provider)

    def record_artifact(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        kind: str = "document",
        path: str = "",
        mime: str = "",
        filename: str = "",
        source: str = "",
        status: str = "created",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return {}
        resolved_path = ""
        if _safe_text(path):
            try:
                resolved_path = str(Path(path).expanduser().resolve())
            except Exception:
                resolved_path = _safe_text(path)
        safe_filename = _safe_text(filename, 240) or (
            Path(resolved_path).name if resolved_path else ""
        )
        safe_mime = _safe_text(mime, 120)
        if not safe_mime and safe_filename:
            safe_mime = _safe_text(mimetypes.guess_type(safe_filename)[0], 120)
        now = _now_iso()
        with self._lock, self._connection() as conn:
            existing = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE session_id = ? AND turn_id = ? AND path = ?
                """,
                (safe_session_id, _safe_text(turn_id, 180), resolved_path),
            ).fetchone()
            artifact_id = str(existing["id"]) if existing is not None else uuid.uuid4().hex
            current = _json_loads(existing["metadata_json"]) if existing is not None else {}
            if metadata:
                current.update(dict(metadata))
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO artifacts(
                        id, session_id, turn_id, kind, path, mime, filename, sha256,
                        source, status, created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        safe_session_id,
                        _safe_text(turn_id, 180),
                        _safe_text(kind, 40).lower() or "document",
                        resolved_path,
                        safe_mime,
                        safe_filename,
                        _sha256(resolved_path),
                        _safe_text(source, 80),
                        _safe_text(status, 40).lower() or "created",
                        now,
                        now,
                        _json_dumps(current),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE artifacts
                    SET kind = ?, mime = ?, filename = ?, sha256 = COALESCE(NULLIF(?, ''), sha256),
                        source = COALESCE(NULLIF(?, ''), source),
                        status = ?, updated_at = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        _safe_text(kind, 40).lower() or "document",
                        safe_mime,
                        safe_filename,
                        _sha256(resolved_path),
                        _safe_text(source, 80),
                        _safe_text(status, 40).lower() or "created",
                        now,
                        _json_dumps(current),
                        artifact_id,
                    ),
                )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
            )

    def record_artifacts(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        source: str = "",
        status: str = "created",
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in list(rows or []):
            if not isinstance(row, dict):
                continue
            artifact = self.record_artifact(
                session_id=session_id,
                turn_id=turn_id,
                kind=row.get("kind") or "document",
                path=row.get("path") or "",
                mime=row.get("mime") or row.get("mime_type") or "",
                filename=row.get("filename") or row.get("name") or "",
                source=source,
                status=status,
                metadata={"caption": _safe_text(row.get("caption"), 500)},
            )
            if artifact:
                output.append(artifact)
        return output

    def list_artifacts(
        self,
        *,
        session_id: str = "",
        turn_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if _safe_text(session_id):
            clauses.append("session_id = ?")
            args.append(_safe_text(session_id, 180))
        if _safe_text(turn_id):
            clauses.append("turn_id = ?")
            args.append(_safe_text(turn_id, 180))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(max(1, int(limit or 1)))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM artifacts
                {where}
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        safe_artifact_id = _safe_text(artifact_id, 180)
        if not safe_artifact_id:
            return {}
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM artifacts WHERE id = ?",
                    (safe_artifact_id,),
                ).fetchone()
            )

    def record_delivery(
        self,
        *,
        artifact_id: str,
        platform: str,
        target: str,
        status: str,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_artifact_id = _safe_text(artifact_id, 180)
        if not safe_artifact_id:
            return {}
        now = _now_iso()
        delivery_id = uuid.uuid4().hex
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO deliveries(
                    id, artifact_id, platform, target, status, error,
                    created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    safe_artifact_id,
                    _safe_text(platform, 64).lower(),
                    _safe_text(target, 240),
                    _safe_text(status, 40).lower(),
                    _safe_text(error, 1000),
                    now,
                    now,
                    _json_dumps(metadata or {}),
                ),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM deliveries WHERE id = ?",
                    (delivery_id,),
                ).fetchone()
            )

    def list_deliveries(
        self,
        *,
        session_id: str = "",
        artifact_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if _safe_text(artifact_id):
            clauses.append("d.artifact_id = ?")
            args.append(_safe_text(artifact_id, 180))
        if _safe_text(session_id):
            clauses.append("a.session_id = ?")
            args.append(_safe_text(session_id, 180))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(max(1, int(limit or 1)))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    d.*,
                    a.session_id AS session_id,
                    a.turn_id AS turn_id,
                    a.kind AS artifact_kind,
                    a.path AS artifact_path,
                    a.filename AS artifact_filename,
                    a.mime AS artifact_mime
                FROM deliveries d
                LEFT JOIN artifacts a ON a.id = d.artifact_id
                {where}
                ORDER BY d.created_at ASC, d.id ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def create_task(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        goal: str = "",
        status: str = "queued",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            raise ValueError("session_id is required")
        task_id = uuid.uuid4().hex
        now = _now_iso()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks(id, session_id, turn_id, goal, status, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    safe_session_id,
                    _safe_text(turn_id, 180),
                    str(goal or ""),
                    _status(status),
                    now,
                    now,
                    _json_dumps(metadata or {}),
                ),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            )

    def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_task_id = _safe_text(task_id, 180)
        target = _status(status)
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (safe_task_id,)).fetchone()
            if row is None:
                return {}
            _assert_transition(str(row["status"] or ""), target)
            current = _json_loads(row["metadata_json"])
            if metadata:
                current.update(dict(metadata))
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (target, now, _json_dumps(current), safe_task_id),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM tasks WHERE id = ?", (safe_task_id,)).fetchone()
            )

    def get_task(self, task_id: str) -> dict[str, Any]:
        safe_task_id = _safe_text(task_id, 180)
        if not safe_task_id:
            return {}
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute("SELECT * FROM tasks WHERE id = ?", (safe_task_id,)).fetchone()
            )

    def list_tasks(self, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return []
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (safe_session_id, max(1, int(limit or 1))),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def list_tasks_for_user(
        self,
        *,
        platform_user_id: str,
        statuses: list[str] | tuple[str, ...] = (),
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        safe_user_id = _safe_text(platform_user_id, 160)
        if not safe_user_id:
            return []
        status_values = [_status(item) for item in statuses if _safe_text(item)]
        clauses = ["s.platform_user_id = ?"]
        args: list[Any] = [safe_user_id]
        if status_values:
            clauses.append("t.status IN (" + ",".join(["?"] * len(status_values)) + ")")
            args.extend(status_values)
        args.append(max(1, int(limit or 1)))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.*,
                    s.kind AS session_kind,
                    s.platform AS platform,
                    s.platform_user_id AS platform_user_id,
                    s.title AS session_title,
                    tr.source AS turn_source,
                    tr.input_text AS turn_input_text,
                    tr.status AS turn_status,
                    tr.kernel_provider AS kernel_provider
                FROM tasks t
                JOIN sessions s ON s.id = t.session_id
                LEFT JOIN turns tr ON tr.id = t.turn_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.updated_at DESC, t.created_at DESC, t.id ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
        tasks = [_row_to_dict(row) for row in rows]
        if include_deleted:
            return tasks
        return [
            task
            for task in tasks
            if not bool(dict(task.get("metadata") or {}).get("deleted"))
        ]

    def mark_task_deleted(self, task_id: str, *, reason: str = "") -> dict[str, Any]:
        safe_task_id = _safe_text(task_id, 180)
        if not safe_task_id:
            return {}
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (safe_task_id,)).fetchone()
            if row is None:
                return {}
            current_status = _status(row["status"])
            target_status = current_status
            if current_status not in TERMINAL_STATUSES:
                _assert_transition(current_status, "cancelled")
                target_status = "cancelled"
            metadata = _json_loads(row["metadata_json"])
            metadata.update(
                {
                    "deleted": True,
                    "deleted_at": now,
                    "delete_reason": _safe_text(reason, 240),
                }
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (target_status, now, _json_dumps(metadata), safe_task_id),
            )
            self._append_event_conn(
                conn,
                session_id=str(row["session_id"] or ""),
                turn_id=str(row["turn_id"] or ""),
                event_type="task.deleted",
                payload={
                    "task_id": safe_task_id,
                    "previous_status": current_status,
                    "status": target_status,
                    "reason": _safe_text(reason, 240),
                },
                created_at=now,
            )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM tasks WHERE id = ?", (safe_task_id,)).fetchone()
            )

    def expire_stale_work(
        self,
        *,
        waiting_user_ttl_sec: int | None = None,
        waiting_external_ttl_sec: int | None = None,
        running_ttl_sec: int | None = None,
        queued_ttl_sec: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, int]:
        ttl_by_status = {
            "waiting_user": (
                _env_int("IKAROS_RUNTIME_V2_WAITING_USER_TTL_SEC", 180, 0)
                if waiting_user_ttl_sec is None
                else max(0, int(waiting_user_ttl_sec))
            ),
            "waiting_external": (
                _env_int("IKAROS_RUNTIME_V2_WAITING_EXTERNAL_TTL_SEC", 0, 0)
                if waiting_external_ttl_sec is None
                else max(0, int(waiting_external_ttl_sec))
            ),
            "running": (
                _env_int("IKAROS_RUNTIME_V2_RUNNING_TTL_SEC", 6 * 60 * 60, 0)
                if running_ttl_sec is None
                else max(0, int(running_ttl_sec))
            ),
            "queued": (
                _env_int("IKAROS_RUNTIME_V2_QUEUED_TTL_SEC", 60 * 60, 0)
                if queued_ttl_sec is None
                else max(0, int(queued_ttl_sec))
            ),
        }
        active_statuses = {status for status, ttl in ttl_by_status.items() if ttl > 0}
        if not active_statuses:
            return {"turns": 0, "tasks": 0}

        now_dt = now or datetime.now().astimezone()
        if now_dt.tzinfo is None:
            now_dt = now_dt.astimezone()
        now_text = now_dt.isoformat(timespec="microseconds")

        def _stale(row: sqlite3.Row) -> tuple[bool, int]:
            status = _status(row["status"])
            ttl = int(ttl_by_status.get(status) or 0)
            if ttl <= 0:
                return False, ttl
            updated_at = _parse_iso(row["updated_at"]) or _parse_iso(row["created_at"])
            if updated_at is None:
                return False, ttl
            return (now_dt - updated_at).total_seconds() >= ttl, ttl

        expired_turns = 0
        expired_tasks = 0
        placeholders = ",".join(["?"] * len(active_statuses))
        args = sorted(active_statuses)
        with self._lock, self._connection() as conn:
            turn_rows = conn.execute(
                f"""
                SELECT * FROM turns
                WHERE status IN ({placeholders})
                ORDER BY updated_at ASC
                """,
                args,
            ).fetchall()
            for row in turn_rows:
                is_stale, ttl = _stale(row)
                if not is_stale:
                    continue
                _assert_transition(str(row["status"] or ""), "expired")
                metadata = _json_loads(row["metadata_json"])
                metadata.update(
                    {
                        "expired_by": "runtime_v2_janitor",
                        "expired_after_sec": ttl,
                    }
                )
                conn.execute(
                    """
                    UPDATE turns
                    SET status = 'expired',
                        error = COALESCE(NULLIF(error, ''), ?),
                        completed_at = COALESCE(NULLIF(completed_at, ''), ?),
                        updated_at = ?,
                        metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        f"Runtime v2 turn expired after {ttl}s.",
                        now_text,
                        now_text,
                        _json_dumps(metadata),
                        row["id"],
                    ),
                )
                self._append_event_conn(
                    conn,
                    session_id=str(row["session_id"] or ""),
                    turn_id=str(row["id"] or ""),
                    event_type="runtime.expired",
                    payload={
                        "object": "turn",
                        "status": row["status"],
                        "expired_after_sec": ttl,
                    },
                    created_at=now_text,
                )
                expired_turns += 1

            task_rows = conn.execute(
                f"""
                SELECT * FROM tasks
                WHERE status IN ({placeholders})
                ORDER BY updated_at ASC
                """,
                args,
            ).fetchall()
            for row in task_rows:
                is_stale, ttl = _stale(row)
                if not is_stale:
                    continue
                _assert_transition(str(row["status"] or ""), "expired")
                metadata = _json_loads(row["metadata_json"])
                metadata.update(
                    {
                        "expired_by": "runtime_v2_janitor",
                        "expired_after_sec": ttl,
                    }
                )
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'expired', updated_at = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (now_text, _json_dumps(metadata), row["id"]),
                )
                self._append_event_conn(
                    conn,
                    session_id=str(row["session_id"] or ""),
                    turn_id=str(row["turn_id"] or ""),
                    event_type="task.expired",
                    payload={
                        "object": "task",
                        "task_id": row["id"],
                        "status": row["status"],
                        "expired_after_sec": ttl,
                    },
                    created_at=now_text,
                )
                expired_tasks += 1

            if expired_turns or expired_tasks:
                conn.commit()
        return {"turns": expired_turns, "tasks": expired_tasks}

    def upsert_scheduler_job(
        self,
        *,
        job_id: str,
        session_id: str,
        crontab: str,
        instruction: str,
        platform: str = "",
        chat_id: str = "",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_job_id = _safe_text(job_id, 120)
        safe_session_id = _safe_text(session_id, 180)
        if not safe_job_id or not safe_session_id:
            return {}
        now = _now_iso()
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE id = ?",
                (safe_job_id,),
            ).fetchone()
            current = _json_loads(row["metadata_json"]) if row is not None else {}
            if metadata:
                current.update(dict(metadata))
            if row is None:
                conn.execute(
                    """
                    INSERT INTO scheduler_jobs(
                        id, session_id, crontab, instruction, platform, chat_id,
                        enabled, created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_job_id,
                        safe_session_id,
                        _safe_text(crontab, 120),
                        str(instruction or ""),
                        _safe_text(platform, 64).lower(),
                        _safe_text(chat_id, 160),
                        1 if enabled else 0,
                        now,
                        now,
                        _json_dumps(current),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE scheduler_jobs
                    SET session_id = ?, crontab = ?, instruction = ?, platform = ?,
                        chat_id = ?, enabled = ?, updated_at = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        safe_session_id,
                        _safe_text(crontab, 120),
                        str(instruction or ""),
                        _safe_text(platform, 64).lower(),
                        _safe_text(chat_id, 160),
                        1 if enabled else 0,
                        now,
                        _json_dumps(current),
                        safe_job_id,
                    ),
                )
            conn.commit()
            return _row_to_dict(
                conn.execute("SELECT * FROM scheduler_jobs WHERE id = ?", (safe_job_id,)).fetchone()
            )

    def create_scheduler_job(
        self,
        *,
        crontab: str,
        instruction: str,
        owner_user_id: str = "",
        platform: str = "",
        chat_id: str = "",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT id FROM scheduler_jobs").fetchall()
            max_id = 0
            for row in rows:
                try:
                    max_id = max(max_id, int(str(row["id"] or "").strip()))
                except Exception:
                    continue
            while True:
                job_id = str(max_id + 1)
                session_id = f"scheduler-task-{job_id}"
                if not conn.execute(
                    "SELECT 1 FROM scheduler_jobs WHERE id = ?", (job_id,)
                ).fetchone() and not conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                ).fetchone():
                    break
                max_id += 1
            owner = _safe_text(owner_user_id, 160)
            session_metadata = {
                "scheduled_task_id": job_id,
                "delivery_platform": _safe_text(platform, 64).lower(),
                "delivery_chat_id": _safe_text(chat_id, 160),
            }
            job_metadata = dict(metadata or {})
            if owner:
                job_metadata.setdefault("created_by_user_id", owner)
            conn.execute(
                """
                INSERT INTO sessions(
                    id, kind, platform, platform_user_id, title,
                    created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    "scheduled_task",
                    "scheduler",
                    owner,
                    _safe_text(instruction, 240),
                    now,
                    now,
                    _json_dumps(session_metadata),
                ),
            )
            conn.execute(
                """
                INSERT INTO scheduler_jobs(
                    id, session_id, crontab, instruction, platform, chat_id,
                    enabled, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    session_id,
                    _safe_text(crontab, 120),
                    str(instruction or ""),
                    _safe_text(platform, 64).lower(),
                    _safe_text(chat_id, 160),
                    1 if enabled else 0,
                    now,
                    now,
                    _json_dumps(job_metadata),
                ),
            )
            conn.commit()
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM scheduler_jobs WHERE id = ?", (job_id,)
                ).fetchone()
            )

    def get_scheduler_job(self, job_id: str) -> dict[str, Any]:
        with self._lock, self._connection() as conn:
            return _row_to_dict(
                conn.execute(
                    "SELECT * FROM scheduler_jobs WHERE id = ?",
                    (_safe_text(job_id, 120),),
                ).fetchone()
            )

    def list_scheduler_jobs(
        self,
        *,
        session_id: str = "",
        platform_user_id: str = "",
        enabled: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if _safe_text(session_id):
            clauses.append("j.session_id = ?")
            args.append(_safe_text(session_id, 180))
        if _safe_text(platform_user_id):
            clauses.append("s.platform_user_id = ?")
            args.append(_safe_text(platform_user_id, 160))
        if enabled is not None:
            clauses.append("j.enabled = ?")
            args.append(1 if enabled else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(max(1, int(limit or 1)))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT j.*, s.platform_user_id AS platform_user_id
                FROM scheduler_jobs j
                LEFT JOIN sessions s ON s.id = j.session_id
                {where}
                ORDER BY j.updated_at DESC, j.id ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def next_scheduler_job_id(self) -> int:
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT id FROM scheduler_jobs").fetchall()
        max_id = 0
        for row in rows:
            try:
                max_id = max(max_id, int(str(row["id"] or "").strip()))
            except Exception:
                continue
        return max_id + 1

    def delete_scheduler_job(self, job_id: str) -> bool:
        safe_job_id = _safe_text(job_id, 120)
        if not safe_job_id:
            return False
        with self._lock, self._connection() as conn:
            result = conn.execute(
                "DELETE FROM scheduler_jobs WHERE id = ?",
                (safe_job_id,),
            )
            conn.commit()
            return bool(result.rowcount)

    def scheduler_jobs_revision(self) -> int:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM scheduler_jobs
                """
            ).fetchone()
        token = f"{int(row['count'] or 0)}|{str(row['updated_at'] or '')}"
        return int(zlib.crc32(token.encode("utf-8")))

    def get_session_trace(self, session_id: str) -> dict[str, Any]:
        safe_session_id = _safe_text(session_id, 180)
        if not safe_session_id:
            return {}
        session = self.get_session(safe_session_id)
        if not session:
            return {}
        return {
            "session": session,
            "kernel_sessions": self.list_kernel_sessions(safe_session_id),
            "turns": self.list_turns(safe_session_id, limit=500),
            "events": self.list_events(session_id=safe_session_id, limit=1000),
            "artifacts": self.list_artifacts(session_id=safe_session_id, limit=500),
            "deliveries": self.list_deliveries(session_id=safe_session_id, limit=500),
            "tasks": self.list_tasks(safe_session_id, limit=200),
            "scheduler_jobs": self.list_scheduler_jobs(
                session_id=safe_session_id,
                limit=100,
            ),
        }

    def disable_scheduler_jobs_except(
        self,
        active_job_ids: list[str] | tuple[str, ...] | set[str],
    ) -> int:
        safe_ids = {
            _safe_text(item, 120)
            for item in list(active_job_ids or [])
            if _safe_text(item)
        }
        now = _now_iso()
        with self._lock, self._connection() as conn:
            if safe_ids:
                placeholders = ",".join(["?"] * len(safe_ids))
                result = conn.execute(
                    f"""
                    UPDATE scheduler_jobs
                    SET enabled = 0, updated_at = ?
                    WHERE id NOT IN ({placeholders}) AND enabled != 0
                    """,
                    [now, *sorted(safe_ids)],
                )
            else:
                result = conn.execute(
                    """
                    UPDATE scheduler_jobs
                    SET enabled = 0, updated_at = ?
                    WHERE enabled != 0
                    """,
                    (now,),
                )
            conn.commit()
            return int(result.rowcount or 0)

    def build_quality_report(self, *, limit: int = 100) -> dict[str, Any]:
        with self._lock, self._connection() as conn:
            turns = conn.execute(
                """
                SELECT id, session_id, status, error, kernel_provider
                FROM turns
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 1)),),
            ).fetchall()
            failed_deliveries = conn.execute(
                """
                SELECT COUNT(*) AS count FROM deliveries
                WHERE status NOT IN ('delivered', 'succeeded', 'ok')
                """
            ).fetchone()["count"]
            failed_delivery_rows = conn.execute(
                """
                SELECT
                    d.platform,
                    d.target,
                    d.error,
                    a.session_id AS session_id,
                    a.turn_id AS turn_id,
                    a.kind AS artifact_kind,
                    a.filename AS artifact_filename
                FROM deliveries d
                LEFT JOIN artifacts a ON a.id = d.artifact_id
                WHERE d.status NOT IN ('delivered', 'succeeded', 'ok')
                ORDER BY d.updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 1)),),
            ).fetchall()
            kernel_timeouts = conn.execute(
                """
                SELECT COUNT(*) AS count FROM events
                WHERE type LIKE 'kernel.%' AND payload_json LIKE '%timeout%'
                """
            ).fetchone()["count"]
        status_counts: dict[str, int] = {}
        recent_failures: list[str] = []
        recent_failed_turns: list[dict[str, str]] = []
        for row in turns:
            status = _safe_text(row["status"], 40) or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "failed" and _safe_text(row["error"]):
                error = _safe_text(row["error"], 200)
                recent_failures.append(error)
                recent_failed_turns.append(
                    {
                        "turn_id": _safe_text(row["id"], 80),
                        "session_id": _safe_text(row["session_id"], 180),
                        "trace_path": (
                            "/api/v1/web-chat/sessions/"
                            f"{_safe_text(row['session_id'], 180)}/trace"
                        ),
                        "kernel_provider": _safe_text(row["kernel_provider"], 60),
                        "error": error,
                    }
                )
        delivery_failure_counts: dict[str, int] = {}
        recent_delivery_failures: list[dict[str, str]] = []
        for row in failed_delivery_rows:
            platform = _safe_text(row["platform"], 64) or "unknown"
            kind = _safe_text(row["artifact_kind"], 40) or "document"
            key = f"{platform}:{kind}"
            delivery_failure_counts[key] = delivery_failure_counts.get(key, 0) + 1
            recent_delivery_failures.append(
                {
                    "platform": platform,
                    "target": _safe_text(row["target"], 240),
                    "session_id": _safe_text(row["session_id"], 180),
                    "turn_id": _safe_text(row["turn_id"], 180),
                    "trace_path": (
                        "/api/v1/web-chat/sessions/"
                        f"{_safe_text(row['session_id'], 180)}/trace"
                    ),
                    "artifact_kind": kind,
                    "artifact_filename": _safe_text(row["artifact_filename"], 240),
                    "error": _safe_text(row["error"], 200),
                }
            )
        recommendations: list[str] = []
        suggested_tests: list[str] = []
        if status_counts.get("failed"):
            recommendations.append("把最近失败 turn 沉淀成回归测试或 skill 文档修正。")
            suggested_tests.append("为最近失败 turn 添加 fake kernel/session 回归测试。")
        if failed_deliveries:
            recommendations.append("检查 artifact delivery receipt，定位失败平台。")
            top_delivery_key = max(
                delivery_failure_counts,
                key=delivery_failure_counts.get,
                default="",
            )
            if top_delivery_key:
                platform, _, kind = top_delivery_key.partition(":")
                suggested_tests.append(
                    f"为 {platform} {kind} artifact delivery 添加 adapter 回归测试。"
                )
        if kernel_timeouts:
            recommendations.append("检查 kernel timeout 和 thread resume 耗时。")
            suggested_tests.append("为 Codex resume/timeout 添加长会话回归测试。")
        if not recommendations:
            recommendations.append("Runtime v2 暂未发现明显异常。")
        return {
            "status_counts": status_counts,
            "recent_failures": recent_failures,
            "recent_failed_turns": recent_failed_turns,
            "artifact_delivery_failed": int(failed_deliveries or 0),
            "delivery_failure_counts": delivery_failure_counts,
            "recent_delivery_failures": recent_delivery_failures,
            "kernel_timeouts": int(kernel_timeouts or 0),
            "recommendations": recommendations,
            "suggested_tests": suggested_tests,
        }


class RuntimeEventBus:
    def __init__(self, store: RuntimeV2Store) -> None:
        self.store = store

    def publish(
        self,
        *,
        session_id: str,
        event_type: str,
        turn_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.append_event(
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            payload=payload or {},
        )


runtime_v2 = RuntimeV2Store()
runtime_event_bus = RuntimeEventBus(runtime_v2)
