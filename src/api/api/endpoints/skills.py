from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.models import User
from api.auth.router import require_operator
from core.runtime_config_store import runtime_config_store

router = APIRouter()


class SkillEnabledPatch(BaseModel):
    enabled: bool


class SkillInfo(BaseModel):
    name: str
    description: str
    source: str
    enabled: bool
    triggers: list[str]
    ikaros_only: bool


def _get_skill_registry() -> Any:
    from extension.skills.registry import skill_registry

    return skill_registry


@router.get("")
async def list_skills(
    _: User = Depends(require_operator),
) -> dict[str, Any]:
    skill_registry = _get_skill_registry()
    skill_registry.refresh_if_changed()
    disabled_skills = runtime_config_store.get_disabled_skills()

    skills: list[dict[str, Any]] = []
    for name, info in skill_registry.get_skill_index().items():
        if bool(info.get("ikaros_only")):
            continue
        skills.append(
            {
                "name": name,
                "description": str(info.get("description") or "")[:500],
                "source": info.get("source", ""),
                "enabled": name not in disabled_skills,
                "triggers": list(info.get("triggers") or []),
                "ikaros_only": bool(info.get("ikaros_only")),
            }
        )

    return {"skills": skills}


@router.patch("/{skill_name}/enabled")
async def patch_skill_enabled(
    skill_name: str,
    payload: SkillEnabledPatch,
    _: User = Depends(require_operator),
) -> dict[str, Any]:
    skill_registry = _get_skill_registry()
    skill_registry.refresh_if_changed()

    skill_info = skill_registry.get_skill(skill_name)
    if not skill_info:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    if bool(skill_info.get("ikaros_only")):
        raise HTTPException(status_code=400, detail="Cannot toggle ikaros_only skill")

    runtime_config_store.set_skill_enabled(
        skill_name,
        payload.enabled,
        actor="admin",
        reason="admin_toggle_skill",
    )

    disabled_skills = runtime_config_store.get_disabled_skills()
    return {
        "name": skill_name,
        "enabled": skill_name not in disabled_skills,
    }