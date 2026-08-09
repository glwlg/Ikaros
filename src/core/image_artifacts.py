from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.image_input_service import (
    DEFAULT_MAX_IMAGE_INPUT_BYTES,
    guess_image_mime_type,
)

PENDING_IMAGE_ARTIFACTS_KEY = "pending_image_artifacts"
IMAGE_UPLOAD_ROOT = (Path(tempfile.gettempdir()) / "ikaros" / "images").resolve()

_IMAGE_SUFFIX_BY_MIME = {
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(slots=True)
class ImageArtifact:
    path: str
    mime_type: str

    def to_payload(self) -> dict[str, str]:
        return {
            "path": str(self.path or "").strip(),
            "mime_type": str(self.mime_type or "").strip(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ImageArtifact | None:
        if not isinstance(payload, dict):
            return None
        path = str(payload.get("path") or "").strip()
        mime_type = str(payload.get("mime_type") or "").strip().lower()
        if not path or not mime_type.startswith("image/"):
            return None
        return cls(path=path, mime_type=mime_type)


def persist_image_artifact(
    *,
    file_bytes: bytes,
    mime_type: str | None,
    file_name: str | None = None,
    storage_root: str | Path | None = None,
) -> ImageArtifact:
    content = bytes(file_bytes or b"")
    if not content:
        raise ValueError("empty_image")
    if len(content) > DEFAULT_MAX_IMAGE_INPUT_BYTES:
        raise ValueError("image_too_large")

    resolved_mime = guess_image_mime_type(
        content,
        declared_mime=str(mime_type or ""),
        source_name=str(file_name or ""),
    )
    suffix = _IMAGE_SUFFIX_BY_MIME.get(resolved_mime)
    if not suffix:
        raise ValueError("unsupported_image_type")

    root = Path(storage_root or IMAGE_UPLOAD_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = (root / f"image_{uuid4().hex[:12]}{suffix}").resolve()
    path.write_bytes(content)
    return ImageArtifact(path=str(path), mime_type=resolved_mime)


def list_pending_image_artifacts(
    user_data: dict[str, Any] | None,
) -> list[ImageArtifact]:
    if not isinstance(user_data, dict):
        return []
    raw_items = user_data.get(PENDING_IMAGE_ARTIFACTS_KEY)
    if not isinstance(raw_items, list):
        return []

    artifacts: list[ImageArtifact] = []
    seen_paths: set[str] = set()
    for item in raw_items:
        artifact = ImageArtifact.from_payload(item)
        if artifact is None or artifact.path in seen_paths:
            continue
        if not Path(artifact.path).is_file():
            continue
        seen_paths.add(artifact.path)
        artifacts.append(artifact)
    return artifacts


def append_pending_image_artifact(
    user_data: dict[str, Any] | None,
    artifact: ImageArtifact,
) -> list[ImageArtifact]:
    if not isinstance(user_data, dict):
        return []
    pending = list_pending_image_artifacts(user_data)
    pending = [item for item in pending if item.path != artifact.path]
    pending.append(artifact)
    user_data[PENDING_IMAGE_ARTIFACTS_KEY] = [item.to_payload() for item in pending]
    return pending


def pop_pending_image_artifacts(
    user_data: dict[str, Any] | None,
) -> list[ImageArtifact]:
    pending = list_pending_image_artifacts(user_data)
    if isinstance(user_data, dict):
        user_data.pop(PENDING_IMAGE_ARTIFACTS_KEY, None)
    return pending


def cleanup_image_artifacts(artifacts: list[ImageArtifact]) -> None:
    for artifact in list(artifacts or []):
        with contextlib.suppress(OSError):
            Path(artifact.path).unlink()
