from __future__ import annotations

import logging
from typing import Any

from core.storage_service import now_iso, storage_service, user_state_path

logger = logging.getLogger(__name__)


def _credentials_path(user_id: int | str):
    return user_state_path(user_id, "credential_manager", "credentials.md")


async def _read_credentials(user_id: int | str) -> dict[str, dict[str, Any]]:
    payload = await storage_service.read(_credentials_path(user_id), {})
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for service, item in payload.items():
        if not isinstance(item, dict):
            continue
        result[str(service)] = {
            "data": dict(item.get("data") or {}),
            "updated_at": str(item.get("updated_at") or now_iso()),
        }
    return result


async def add_credential(
    user_id: int | str,
    service: str,
    data: dict[str, Any],
) -> bool:
    try:
        service_name = str(service or "").strip()
        if not service_name:
            return False
        payload = await _read_credentials(user_id)
        payload[service_name] = {
            "data": dict(data or {}),
            "updated_at": now_iso(),
        }
        await storage_service.write(_credentials_path(user_id), payload)
        return True
    except Exception as exc:
        logger.error("Error adding credential: %s", exc)
        return False


async def get_credential(user_id: int | str, service: str) -> dict[str, Any] | None:
    try:
        payload = await _read_credentials(user_id)
        item = payload.get(str(service or "").strip())
        if not isinstance(item, dict):
            return None
        return dict(item.get("data") or {})
    except Exception as exc:
        logger.error("Error getting credential: %s", exc)
        return None


async def list_credentials(user_id: int | str) -> list[str]:
    try:
        payload = await _read_credentials(user_id)
        return sorted(payload.keys())
    except Exception as exc:
        logger.error("Error listing credentials: %s", exc)
        return []


async def delete_credential(user_id: int | str, service: str) -> bool:
    try:
        payload = await _read_credentials(user_id)
        key = str(service or "").strip()
        if key not in payload:
            return False
        payload.pop(key, None)
        await storage_service.write(_credentials_path(user_id), payload)
        return True
    except Exception as exc:
        logger.error("Error deleting credential: %s", exc)
        return False


__all__ = [
    "add_credential",
    "delete_credential",
    "get_credential",
    "list_credentials",
]
