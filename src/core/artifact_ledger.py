from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.file_artifacts import merge_file_rows

ARTIFACT_LEDGER_USER_DATA_KEY = "artifact_ledger"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_text(value: Any, limit: int = 0) -> str:
    rendered = str(value or "").strip()
    return rendered[:limit] if limit > 0 else rendered


def _row_key(row: dict[str, Any]) -> str:
    path_text = _safe_text(row.get("path"))
    try:
        path_text = str(Path(path_text).expanduser().resolve()) if path_text else ""
    except Exception:
        pass
    kind = _safe_text(row.get("kind") or "document", 40).lower() or "document"
    filename = _safe_text(row.get("filename"), 240)
    return f"{kind}:{path_text}:{filename}"


def _ledger(user_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(user_data, dict):
        return []
    current = user_data.get(ARTIFACT_LEDGER_USER_DATA_KEY)
    if not isinstance(current, list):
        current = []
        user_data[ARTIFACT_LEDGER_USER_DATA_KEY] = current
    return current


def get_artifact_ledger(user_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [dict(item) for item in _ledger(user_data) if isinstance(item, dict)]


def record_artifact_receipts(
    user_data: dict[str, Any] | None,
    rows: list[dict[str, str]],
    *,
    status: str,
    source: str = "",
    target: str = "",
    error: str = "",
) -> list[dict[str, Any]]:
    ledger = _ledger(user_data)
    if not isinstance(user_data, dict):
        return []

    safe_status = _safe_text(status or "observed", 40).lower() or "observed"
    safe_source = _safe_text(source, 80)
    safe_target = _safe_text(target, 160)
    safe_error = _safe_text(error, 500)
    receipts: list[dict[str, Any]] = []
    existing_by_key = {
        _safe_text(item.get("key")): item for item in ledger if isinstance(item, dict)
    }

    for row in merge_file_rows(list(rows or [])):
        key = _row_key(row)
        if not key.strip(":"):
            continue
        receipt = {
            "key": key,
            "status": safe_status,
            "source": safe_source,
            "target": safe_target,
            "path": _safe_text(row.get("path")),
            "kind": _safe_text(row.get("kind") or "document", 40).lower()
            or "document",
            "filename": _safe_text(row.get("filename"), 240),
            "caption": _safe_text(row.get("caption"), 500),
            "updated_at": _now_iso(),
        }
        if safe_error:
            receipt["error"] = safe_error
        existing = existing_by_key.get(key)
        if isinstance(existing, dict):
            existing.update(receipt)
            receipts.append(dict(existing))
        else:
            ledger.append(receipt)
            existing_by_key[key] = receipt
            receipts.append(dict(receipt))
    return receipts
