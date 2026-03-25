from __future__ import annotations

from typing import Any

from core.storage_service import now_iso, storage_service, system_state_path


def _cache_path():
    return system_state_path("video_to_text", "artifact_cache.md")


def build_cache_key(platform: str, file_id: str) -> str:
    safe_platform = str(platform or "").strip().lower()
    safe_file_id = str(file_id or "").strip()
    if not safe_platform or not safe_file_id:
        return ""
    return f"{safe_platform}:{safe_file_id}"


async def get_cached_artifact(platform: str, file_id: str) -> dict[str, Any] | None:
    cache_key = build_cache_key(platform, file_id)
    if not cache_key:
        return None
    payload = await storage_service.read(_cache_path(), {})
    if not isinstance(payload, dict):
        return None
    item = payload.get(cache_key)
    return dict(item) if isinstance(item, dict) else None


async def save_cached_artifact(
    platform: str,
    file_id: str,
    *,
    artifact_path: str,
    source_video_path: str,
    mime_type: str = "",
    workspace_path: str = "",
    audio_track_path: str = "",
    segment_audio_dir: str = "",
    segment_text_dir: str = "",
    progress_log_path: str = "",
    duration_seconds: float | None = None,
    frame_count: int = 0,
    transcript_segment_count: int = 0,
    diagnostics: list[str] | None = None,
) -> None:
    cache_key = build_cache_key(platform, file_id)
    if not cache_key:
        return
    payload = await storage_service.read(_cache_path(), {})
    if not isinstance(payload, dict):
        payload = {}
    payload[cache_key] = {
        "artifact_path": str(artifact_path or "").strip(),
        "source_video_path": str(source_video_path or "").strip(),
        "mime_type": str(mime_type or "").strip(),
        "workspace_path": str(workspace_path or "").strip(),
        "audio_track_path": str(audio_track_path or "").strip(),
        "segment_audio_dir": str(segment_audio_dir or "").strip(),
        "segment_text_dir": str(segment_text_dir or "").strip(),
        "progress_log_path": str(progress_log_path or "").strip(),
        "duration_seconds": duration_seconds,
        "frame_count": int(frame_count or 0),
        "transcript_segment_count": int(transcript_segment_count or 0),
        "diagnostics": [
            str(item).strip()
            for item in list(diagnostics or [])
            if str(item).strip()
        ],
        "created_at": now_iso(),
    }
    await storage_service.write(_cache_path(), payload)


__all__ = [
    "build_cache_key",
    "get_cached_artifact",
    "save_cached_artifact",
]
