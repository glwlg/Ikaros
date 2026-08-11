from __future__ import annotations

import io
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from api.auth.models import User
from api.auth.router import require_admin, require_operator
from api.services.admin_audit import record_admin_audit
from core.config import DATA_DIR
from core.runtime_config_store import runtime_config_store

router = APIRouter()

SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IMPORT_MAX_FILES = 100
_IMPORT_MAX_FILE_BYTES = 1024 * 1024
_IMPORT_MAX_TOTAL_BYTES = 8 * 1024 * 1024


class SkillEnabledPatch(BaseModel):
    enabled: bool


class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    triggers: list[str] = []
    content: str = ""


class SkillInfo(BaseModel):
    name: str
    description: str
    source: str
    enabled: bool
    triggers: list[str]
    ikaros_only: bool


def _client_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is None:
        return ""
    return str(request.client.host or "").strip()


def _actor(user: User) -> str:
    return f"{user.id}:{user.email}"


def _get_skill_registry() -> Any:
    from extension.skills.registry import skill_registry

    return skill_registry


def _learned_skills_dir(registry: Any) -> Path:
    return Path(str(registry.skills_dir)) / "learned"


def _skill_backup_dir() -> Path:
    return (Path(DATA_DIR) / "kernel" / "skill-backups").resolve()


def _backup_skill_dir(skill_dir: Path, name: str) -> Path | None:
    if not skill_dir.is_dir():
        return None
    backup_dir = _skill_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = shutil.make_archive(
        str(backup_dir / f"{name}-{timestamp}"),
        "zip",
        root_dir=skill_dir,
    )
    return Path(archive)


def _normalize_skill_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or not SKILL_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="技能名称只能包含字母、数字、点、下划线和横线，且必须以字母或数字开头",
        )
    return name


def _ensure_skill_available(registry: Any, name: str) -> None:
    registry.refresh_if_changed()
    if registry.get_skill(name):
        raise HTTPException(status_code=409, detail=f"技能已存在: {name}")


def _render_skill_md(
    *,
    name: str,
    description: str,
    triggers: list[str],
    content: str,
) -> str:
    frontmatter: dict[str, Any] = {"name": name, "description": description}
    if triggers:
        frontmatter["triggers"] = triggers
    body = content.strip() or f"# {name}"
    return (
        "---\n"
        + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + body
        + "\n"
    )


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _skill_response(registry: Any, name: str) -> dict[str, Any]:
    registry.refresh_if_changed()
    info = registry.get_skill(name)
    if not info:
        raise HTTPException(
            status_code=500,
            detail="技能文件已写入但解析失败，请检查 SKILL.md 内容",
        )
    disabled_skills = runtime_config_store.get_disabled_skills()
    return {
        "name": info["name"],
        "description": str(info.get("description") or "")[:500],
        "source": info.get("source", "learned"),
        "enabled": info["name"] not in disabled_skills,
        "triggers": list(info.get("triggers") or []),
        "ikaros_only": bool(info.get("ikaros_only")),
    }


def _read_zip_entries(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="不是合法的 zip 文件") from exc

    members = [info for info in archive.infolist() if not info.is_dir()]
    if len(members) > _IMPORT_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"zip 内文件数量超过 {_IMPORT_MAX_FILES} 个",
        )

    skill_md_names = [
        info.filename
        for info in members
        if info.filename == "SKILL.md" or info.filename.endswith("/SKILL.md")
    ]
    if not skill_md_names:
        raise HTTPException(status_code=400, detail="zip 中缺少 SKILL.md")
    prefix = min(skill_md_names, key=len)[: -len("SKILL.md")]

    entries: dict[str, bytes] = {}
    for info in members:
        filename = info.filename.replace("\\", "/")
        if not filename.startswith(prefix):
            continue
        rel_path = filename[len(prefix) :]
        parts = [part for part in rel_path.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise HTTPException(
                status_code=400,
                detail=f"zip 包含非法路径: {info.filename}",
            )
        content = archive.read(info)
        if len(content) > _IMPORT_MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"zip 内文件超过 1MB 限制: {info.filename}",
            )
        entries["/".join(parts)] = content

    if "SKILL.md" not in entries:
        raise HTTPException(status_code=400, detail="zip 中缺少可用的 SKILL.md")
    return entries


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
    request: Request,
    admin_user: User = Depends(require_admin),
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
        actor=_actor(admin_user),
        reason="admin_toggle_skill",
    )

    await record_admin_audit(
        {
            "action": "toggle_skill",
            "actor": _actor(admin_user),
            "target": f"skill:{skill_name}",
            "summary": f"{'enabled' if payload.enabled else 'disabled'} {skill_name}",
            "ip": _client_ip(request),
            "status": "success",
        }
    )

    disabled_skills = runtime_config_store.get_disabled_skills()
    return {
        "name": skill_name,
        "enabled": skill_name not in disabled_skills,
    }


@router.post("")
async def create_skill(
    payload: SkillCreateRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    registry = _get_skill_registry()
    name = _normalize_skill_name(payload.name)
    _ensure_skill_available(registry, name)

    description = str(payload.description or "").strip()
    triggers = [
        token
        for token in (str(item).strip() for item in payload.triggers or [])
        if token
    ]
    rendered = _render_skill_md(
        name=name,
        description=description,
        triggers=triggers,
        content=str(payload.content or ""),
    )

    skill_dir = _learned_skills_dir(registry) / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(rendered, encoding="utf-8")
    await record_admin_audit(
        {
            "action": "create_skill",
            "actor": _actor(admin_user),
            "target": f"skill:{name}",
            "summary": f"created learned skill {name}",
            "ip": _client_ip(request),
            "status": "success",
        }
    )
    return _skill_response(registry, name)


@router.post("/import")
async def import_skill(
    request: Request,
    file: UploadFile = File(...),
    admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    registry = _get_skill_registry()
    filename = str(file.filename or "").strip()
    lowered = filename.lower()

    data = await file.read(_IMPORT_MAX_TOTAL_BYTES + 1)
    if len(data) > _IMPORT_MAX_TOTAL_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 8MB 大小限制")

    if lowered.endswith(".zip"):
        entries = _read_zip_entries(data)
    elif lowered.endswith(".md"):
        entries = {"SKILL.md": data}
    else:
        raise HTTPException(status_code=400, detail="仅支持导入 .md 或 .zip 文件")

    try:
        skill_md_text = entries["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="SKILL.md 不是合法的 UTF-8 文本",
        ) from exc

    frontmatter = _parse_frontmatter(skill_md_text)
    fallback_name = Path(filename).stem
    name = _normalize_skill_name(frontmatter.get("name") or fallback_name)
    _ensure_skill_available(registry, name)

    skill_dir = _learned_skills_dir(registry) / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    try:
        for rel_path, content in entries.items():
            target = skill_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        await record_admin_audit(
            {
                "action": "import_skill",
                "actor": _actor(admin_user),
                "target": f"skill:{name}",
                "summary": f"imported learned skill {name} from {filename or 'upload'}",
                "ip": _client_ip(request),
                "status": "success",
            }
        )
        return _skill_response(registry, name)
    except Exception:
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise


@router.get("/{skill_name}/detail")
async def get_skill_detail(
    skill_name: str,
    _: User = Depends(require_operator),
) -> dict[str, Any]:
    registry = _get_skill_registry()
    registry.refresh_if_changed()
    info = registry.get_skill(skill_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    content = ""
    skill_md_path = str(info.get("skill_md_path") or "").strip()
    if skill_md_path:
        try:
            content = Path(skill_md_path).read_text(encoding="utf-8")
        except Exception:
            content = ""

    return {
        "name": info["name"],
        "description": str(info.get("description") or ""),
        "source": info.get("source", ""),
        "triggers": list(info.get("triggers") or []),
        "scripts": list(info.get("scripts") or []),
        "content": content,
    }


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str,
    request: Request,
    admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    registry = _get_skill_registry()
    registry.refresh_if_changed()
    info = registry.get_skill(skill_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    if info.get("source") != "learned":
        raise HTTPException(status_code=400, detail="只有已学习技能可以删除")

    backup_path = _backup_skill_dir(Path(str(info["skill_dir"])), info["name"])
    shutil.rmtree(str(info["skill_dir"]), ignore_errors=True)
    runtime_config_store.set_skill_enabled(
        info["name"],
        True,
        actor=_actor(admin_user),
        reason="admin_delete_skill",
    )
    registry.refresh_if_changed()
    await record_admin_audit(
        {
            "action": "delete_skill",
            "actor": _actor(admin_user),
            "target": f"skill:{skill_name}",
            "summary": f"deleted learned skill {skill_name}"
            + (f", backup: {backup_path}" if backup_path else ""),
            "ip": _client_ip(request),
            "status": "success",
        }
    )
    return {
        "name": info["name"],
        "deleted": True,
        "backup": str(backup_path) if backup_path else "",
    }
