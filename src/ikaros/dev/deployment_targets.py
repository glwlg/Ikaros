from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

from core.app_paths import deployment_targets_path


def _default_targets() -> Dict[str, Dict[str, str]]:
    return {
        "ikaros": {"service": "ikaros", "image": "ikaros-core"},
        "api": {"service": "ikaros-api", "image": "ikaros-api"},
    }


class DeploymentTargets:
    def __init__(self, config_path: str | None = None) -> None:
        resolved = str(config_path or "").strip()
        if resolved:
            self.config_path = str(Path(resolved).expanduser().resolve())
            return
        self.config_path = str(deployment_targets_path())

    def load(self) -> Dict[str, Dict[str, str]]:
        defaults = _default_targets()
        path = Path(self.config_path)
        if not path.exists():
            return defaults
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return defaults
        targets = payload.get("targets") if isinstance(payload, dict) else None
        if not isinstance(targets, dict):
            return defaults

        merged: Dict[str, Dict[str, str]] = {}
        for name, fallback in defaults.items():
            raw = targets.get(name)
            if not isinstance(raw, dict):
                merged[name] = dict(fallback)
                continue
            service = str(raw.get("service") or fallback["service"]).strip()
            image = str(raw.get("image") or fallback["image"]).strip()
            merged[name] = {
                "service": service or fallback["service"],
                "image": image or fallback["image"],
            }
        return merged

    def get(self, target_service: str) -> Dict[str, str] | None:
        safe_target = str(target_service or "").strip().lower()
        if not safe_target:
            return None
        targets = self.load()
        resolved = targets.get(safe_target)
        return dict(resolved) if isinstance(resolved, dict) else None


deployment_targets = DeploymentTargets()
