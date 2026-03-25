from __future__ import annotations

from core.storage_service import now_iso, storage_service, system_state_path


def _cache_path():
    return system_state_path("download_video", "video_cache.md")


async def save_video_cache(file_id: str, file_path: str) -> None:
    payload = await storage_service.read(_cache_path(), {})
    if not isinstance(payload, dict):
        payload = {}
    fid = str(file_id or "").strip()
    if not fid:
        return
    payload[fid] = {
        "file_path": str(file_path or "").strip(),
        "created_at": now_iso(),
    }
    await storage_service.write(_cache_path(), payload)


async def get_video_cache(file_id: str) -> str | None:
    payload = await storage_service.read(_cache_path(), {})
    if not isinstance(payload, dict):
        return None
    item = payload.get(str(file_id or "").strip())
    if isinstance(item, dict):
        return str(item.get("file_path") or "") or None
    if isinstance(item, str):
        return item or None
    return None


__all__ = ["get_video_cache", "save_video_cache"]
