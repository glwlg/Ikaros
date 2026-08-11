from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.requests import Request

from api.api.endpoints import skills as skills_endpoint
from api.api.endpoints.skills import SkillCreateRequest, SkillEnabledPatch
from api.auth.models import User
from extension.skills.registry import SkillRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    instance = SkillRegistry(skills_dir=str(tmp_path))
    monkeypatch.setattr(skills_endpoint, "_get_skill_registry", lambda: instance)
    return instance


@pytest.fixture(autouse=True)
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def _record(payload):
        calls.append(dict(payload or {}))
        return payload

    monkeypatch.setattr(skills_endpoint, "record_admin_audit", _record)
    return calls


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/skills",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }
    )


def _admin() -> User:
    return User(id=1, email="admin@example.com")


def _upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=filename)


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_create_skill_writes_learned_skill(registry):
    result = await skills_endpoint.create_skill(
        SkillCreateRequest(
            name="daily_brief",
            description="生成每日简报",
            triggers=["每日简报", "brief"],
            content="# 步骤\n\n1. 汇总数据",
        ),
        _request(),
        _admin(),
    )

    assert result["name"] == "daily_brief"
    assert result["source"] == "learned"
    assert result["enabled"] is True
    assert result["triggers"] == ["每日简报", "brief"]

    skill_md = registry.skills_dir + "/learned/daily_brief/SKILL.md"
    with open(skill_md, encoding="utf-8") as handle:
        content = handle.read()
    assert "name: daily_brief" in content
    assert "汇总数据" in content
    assert registry.get_skill("daily_brief")


@pytest.mark.asyncio
async def test_create_skill_rejects_duplicate(registry):
    await skills_endpoint.create_skill(
        SkillCreateRequest(name="dup_skill"), _request(), _admin()
    )

    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.create_skill(
            SkillCreateRequest(name="dup_skill"), _request(), _admin()
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_skill_rejects_invalid_name(registry):
    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.create_skill(
            SkillCreateRequest(name="bad/name"), _request(), _admin()
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_import_skill_from_markdown(registry):
    payload = b"---\nname: imported_md\ndescription: hello\n---\n\n# body\n"

    result = await skills_endpoint.import_skill(
        _request(), _upload(payload, "whatever.md"), _admin()
    )

    assert result["name"] == "imported_md"
    assert result["description"] == "hello"
    assert registry.get_skill("imported_md")


@pytest.mark.asyncio
async def test_import_skill_from_zip_extracts_full_directory(registry):
    payload = _zip_bytes(
        {
            "demo-skill/SKILL.md": "---\nname: zip_skill\n---\n\n# zip\n",
            "demo-skill/scripts/run.py": "print('ok')\n",
        }
    )

    result = await skills_endpoint.import_skill(
        _request(), _upload(payload, "demo.zip"), _admin()
    )

    assert result["name"] == "zip_skill"
    extracted = registry.skills_dir + "/learned/zip_skill/scripts/run.py"
    with open(extracted, encoding="utf-8") as handle:
        assert "print('ok')" in handle.read()


@pytest.mark.asyncio
async def test_import_zip_requires_skill_md(registry):
    payload = _zip_bytes({"readme.txt": "no skill here"})

    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.import_skill(
            _request(), _upload(payload, "demo.zip"), _admin()
        )

    assert exc.value.status_code == 400
    assert "SKILL.md" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_import_zip_rejects_path_traversal(registry):
    payload = _zip_bytes(
        {
            "SKILL.md": "---\nname: zip_safe\n---\n",
            "../evil.md": "bad",
        }
    )

    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.import_skill(
            _request(), _upload(payload, "demo.zip"), _admin()
        )

    assert exc.value.status_code == 400
    assert registry.get_skill("zip_safe") is None


@pytest.mark.asyncio
async def test_skill_detail_returns_content_and_scripts(registry):
    await skills_endpoint.import_skill(
        _request(),
        _upload(
            _zip_bytes(
                {
                    "demo/SKILL.md": "---\nname: detail_skill\ndescription: d\n---\n\n# body\n",
                    "demo/scripts/run.py": "print('x')\n",
                }
            ),
            "demo.zip",
        ),
        _admin(),
    )

    detail = await skills_endpoint.get_skill_detail("detail_skill")

    assert detail["name"] == "detail_skill"
    assert detail["source"] == "learned"
    assert detail["scripts"] == ["run.py"]
    assert "# body" in detail["content"]


@pytest.mark.asyncio
async def test_toggle_skill_records_audit(registry, monkeypatch, audit_calls):
    class _StubConfigStore:
        def __init__(self):
            self.disabled: list[str] = []

        def get_disabled_skills(self):
            return list(self.disabled)

        def set_skill_enabled(self, name, enabled, *, actor, reason):
            if enabled:
                self.disabled = [item for item in self.disabled if item != name]
            elif name not in self.disabled:
                self.disabled.append(name)

    monkeypatch.setattr(skills_endpoint, "runtime_config_store", _StubConfigStore())
    await skills_endpoint.create_skill(
        SkillCreateRequest(name="toggle_me"), _request(), _admin()
    )

    result = await skills_endpoint.patch_skill_enabled(
        "toggle_me", SkillEnabledPatch(enabled=False), _request(), _admin()
    )

    assert result == {"name": "toggle_me", "enabled": False}
    toggle_call = audit_calls[-1]
    assert toggle_call["action"] == "toggle_skill"
    assert toggle_call["actor"] == "1:admin@example.com"
    assert toggle_call["target"] == "skill:toggle_me"
    assert toggle_call["summary"] == "disabled toggle_me"
    assert toggle_call["ip"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_delete_skill_removes_learned_skill(
    registry, tmp_path, monkeypatch, audit_calls
):
    backup_root = tmp_path / "backups"
    monkeypatch.setattr(skills_endpoint, "_skill_backup_dir", lambda: backup_root)
    await skills_endpoint.create_skill(
        SkillCreateRequest(name="to_delete"), _request(), _admin()
    )
    assert registry.get_skill("to_delete")

    result = await skills_endpoint.delete_skill("to_delete", _request(), _admin())

    assert result["name"] == "to_delete"
    assert result["deleted"] is True
    assert registry.get_skill("to_delete") is None

    backup = Path(result["backup"])
    assert backup.parent == backup_root
    assert backup.name.startswith("to_delete-")
    with zipfile.ZipFile(backup) as archive:
        assert "SKILL.md" in archive.namelist()

    actions = [call["action"] for call in audit_calls]
    assert actions == ["create_skill", "delete_skill"]
    delete_call = audit_calls[-1]
    assert delete_call["actor"] == "1:admin@example.com"
    assert delete_call["target"] == "skill:to_delete"
    assert delete_call["ip"] == "127.0.0.1"
    assert "backup:" in delete_call["summary"]


@pytest.mark.asyncio
async def test_delete_skill_rejects_builtin(registry, tmp_path):
    builtin_dir = tmp_path / "builtin" / "sys_skill"
    builtin_dir.mkdir(parents=True)
    (builtin_dir / "SKILL.md").write_text(
        "---\nname: sys_skill\n---\n", encoding="utf-8"
    )

    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.delete_skill("sys_skill", _request(), _admin())

    assert exc.value.status_code == 400
    assert (builtin_dir / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_delete_skill_missing_returns_404(registry):
    with pytest.raises(HTTPException) as exc:
        await skills_endpoint.delete_skill("missing_skill", _request(), _admin())

    assert exc.value.status_code == 404
