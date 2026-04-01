from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_env_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (project_root() / path).resolve()
    return path.resolve()


def env_path() -> Path:
    return (project_root() / ".env").resolve()


def app_home() -> Path:
    raw = str(os.getenv("IKAROS_HOME") or "").strip()
    if raw:
        return _resolve_env_path(raw)
    return (Path.home() / ".ikaros").resolve()


def data_dir() -> Path:
    raw = str(os.getenv("DATA_DIR") or "").strip()
    if raw:
        return _resolve_env_path(raw)
    return (app_home() / "data").resolve()


def config_dir() -> Path:
    return (app_home() / "config").resolve()


def models_config_path() -> Path:
    raw = str(os.getenv("MODELS_CONFIG_PATH") or "").strip()
    if raw:
        return _resolve_env_path(raw)
    return (config_dir() / "models.json").resolve()


def memory_config_path() -> Path:
    raw = str(os.getenv("MEMORY_CONFIG_PATH") or "").strip()
    if raw:
        return _resolve_env_path(raw)
    return (config_dir() / "memory.json").resolve()


def deployment_targets_path() -> Path:
    raw = str(os.getenv("X_DEPLOYMENT_TARGETS_FILE") or "").strip()
    if raw:
        return _resolve_env_path(raw)
    return (config_dir() / "deployment_targets.yaml").resolve()
