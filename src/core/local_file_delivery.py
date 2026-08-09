import os
from pathlib import Path

from core.config import get_local_file_delivery_max_bytes


def _resolve_target_path(path: str, task_workspace_root: str = "") -> Path:
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("path is required")

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        base = Path(task_workspace_root or os.getcwd()).expanduser()
        candidate = base / candidate
    return candidate.resolve(strict=False)


def _sensitive_path_reason(path_obj: Path) -> str:
    basename = path_obj.name.strip().lower()
    if basename == ".env" or basename.startswith(".env."):
        return f"environment file blocked: {basename}"

    return ""


def validate_local_delivery_target(
    path: str,
    *,
    task_workspace_root: str = "",
    platform: str = "",
    max_bytes: int | None = None,
) -> tuple[Path | None, str]:
    try:
        path_obj = _resolve_target_path(path, task_workspace_root=task_workspace_root)
    except Exception as exc:
        return None, str(exc)

    sensitive_reason = _sensitive_path_reason(path_obj)
    if sensitive_reason:
        return None, sensitive_reason

    if not path_obj.exists():
        return None, f"file does not exist: {path_obj}"
    if not path_obj.is_file():
        return None, f"path is not a file: {path_obj}"
    if not os.access(path_obj, os.R_OK):
        return None, f"file is not readable by bot process: {path_obj}"

    size_bytes = int(path_obj.stat().st_size or 0)
    configured_max_bytes = get_local_file_delivery_max_bytes(platform)
    effective_max_bytes = max(
        1,
        int(max_bytes or configured_max_bytes),
    )
    if size_bytes > effective_max_bytes:
        return None, f"file is too large to send: {size_bytes} bytes"

    return path_obj, ""
