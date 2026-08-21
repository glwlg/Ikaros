from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth.models import User
from api.auth.router import require_admin
from api.schemas.channel_access import (
    ChannelAccessUpdateRequest,
    ChannelRemarkUpdateRequest,
    ToolPolicyUpdateRequest,
)
from api.services.admin_audit import record_admin_audit
from core.channel_access import FEATURE_LABELS
from core.channel_user_store import channel_user_store
from core.tool_access_store import tool_access_store

router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is None:
        return ""
    return str(request.client.host or "").strip()


def _actor(user: User) -> str:
    return f"{user.id}:{user.email}"


def _profile_payload(profile: Any) -> dict[str, Any]:
    override = tool_access_store.get_user_override(
        platform=profile.platform,
        platform_user_id=profile.platform_user_id,
    )
    tools = dict((override or {}).get("tools") or {})
    return {
        "platform": profile.platform,
        "user_id": profile.platform_user_id,
        "status": profile.status,
        "role": profile.role,
        "remark": profile.remark,
        "access": dict(profile.access or {}),
        "tool_policy": (
            {
                "allow": list(tools.get("allow") or []),
                "deny": list(tools.get("deny") or []),
            }
            if override is not None
            else None
        ),
    }


@router.get("/users")
async def list_channel_users(
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    return {
        "items": [
            _profile_payload(profile) for profile in channel_user_store.list_users()
        ],
        "feature_labels": dict(FEATURE_LABELS),
        "group_catalog": tool_access_store.get_group_catalog(),
    }


@router.put("/users/{platform}/{user_id}/access")
async def update_channel_user_access(
    platform: str,
    user_id: str,
    payload: ChannelAccessUpdateRequest,
    request: Request,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    profile = channel_user_store.set_access(
        platform=platform,
        platform_user_id=user_id,
        access=payload.access,
    )
    await record_admin_audit(
        {
            "actor": _actor(user),
            "action": "channel_user_access_update",
            "target": f"{profile.platform}:{profile.platform_user_id}",
            "detail": {"access": dict(profile.access or {})},
            "ip": _client_ip(request),
        }
    )
    return _profile_payload(profile)


@router.put("/users/{platform}/{user_id}/remark")
async def update_channel_user_remark(
    platform: str,
    user_id: str,
    payload: ChannelRemarkUpdateRequest,
    request: Request,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    profile = channel_user_store.set_remark(
        platform=platform,
        platform_user_id=user_id,
        remark=payload.remark,
    )
    await record_admin_audit(
        {
            "actor": _actor(user),
            "action": "channel_user_remark_update",
            "target": f"{profile.platform}:{profile.platform_user_id}",
            "detail": {"remark": profile.remark},
            "ip": _client_ip(request),
        }
    )
    return _profile_payload(profile)


@router.put("/users/{platform}/{user_id}/tool-policy")
async def update_channel_user_tool_policy(
    platform: str,
    user_id: str,
    payload: ToolPolicyUpdateRequest,
    request: Request,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    policy = tool_access_store.set_user_override(
        platform=platform,
        platform_user_id=user_id,
        allow=payload.allow,
        deny=payload.deny,
    )
    await record_admin_audit(
        {
            "actor": _actor(user),
            "action": "channel_user_tool_policy_update",
            "target": f"{platform.strip().lower()}:{user_id.strip()}",
            "detail": dict((policy or {}).get("tools") or {}),
            "ip": _client_ip(request),
        }
    )
    tools = dict((policy or {}).get("tools") or {})
    return {
        "tool_policy": {
            "allow": list(tools.get("allow") or []),
            "deny": list(tools.get("deny") or []),
        }
    }


@router.delete("/users/{platform}/{user_id}/tool-policy")
async def delete_channel_user_tool_policy(
    platform: str,
    user_id: str,
    request: Request,
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    removed = tool_access_store.remove_user_override(
        platform=platform,
        platform_user_id=user_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="该用户没有自定义工具策略")
    await record_admin_audit(
        {
            "actor": _actor(user),
            "action": "channel_user_tool_policy_delete",
            "target": f"{platform.strip().lower()}:{user_id.strip()}",
            "detail": {},
            "ip": _client_ip(request),
        }
    )
    return {"tool_policy": None}
