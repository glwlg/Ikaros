from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.api.endpoints import channel_access as endpoint
from api.auth.models import User
from api.schemas.channel_access import (
    ChannelAccessUpdateRequest,
    ChannelRemarkUpdateRequest,
    ToolPolicyUpdateRequest,
)
from core.channel_user_store import ChannelUserStore
from core.tool_access_store import ToolAccessStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.channel_user_store.data_dir",
        lambda: tmp_path,
    )
    users = ChannelUserStore()
    tools = ToolAccessStore()
    tools.path = (tmp_path / "tool_access.json").resolve()
    tools._payload = tools._default_payload()
    tools._write_unlocked()
    monkeypatch.setattr(endpoint, "channel_user_store", users)
    monkeypatch.setattr(endpoint, "tool_access_store", tools)
    return users, tools


@pytest.fixture(autouse=True)
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def _record(payload):
        calls.append(dict(payload or {}))
        return payload

    monkeypatch.setattr(endpoint, "record_admin_audit", _record)
    return calls


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/channel-access",
            "headers": [],
            "client": ("127.0.0.1", 8000),
        }
    )


def _admin() -> User:
    return User(id=1, email="admin@example.com")


@pytest.mark.asyncio
async def test_list_channel_users_includes_access_and_tool_policy(stores):
    users, tools = stores
    users.ensure_user(platform="weixin", platform_user_id="guest-1")
    users.set_remark(
        platform="weixin",
        platform_user_id="guest-1",
        remark="张三",
    )
    tools.set_user_override(
        platform="weixin",
        platform_user_id="guest-1",
        allow=["group:media", "group:delivery"],
    )

    payload = await endpoint.list_channel_users(_user=_admin())

    assert payload["group_catalog"]
    assert "chat" in payload["feature_labels"]
    items = payload["items"]
    assert len(items) == 1
    item = items[0]
    assert item["platform"] == "weixin"
    assert item["user_id"] == "guest-1"
    assert item["remark"] == "张三"
    assert item["access"]["chat"] is True
    assert item["tool_policy"] == {
        "allow": ["group:media", "group:delivery"],
        "deny": [],
    }


@pytest.mark.asyncio
async def test_update_channel_user_remark_persists(stores, audit_calls):
    users, _tools = stores
    users.ensure_user(platform="weixin", platform_user_id="guest-1")

    payload = await endpoint.update_channel_user_remark(
        platform="weixin",
        user_id="guest-1",
        payload=ChannelRemarkUpdateRequest(remark="  张三  "),
        request=_request(),
        user=_admin(),
    )

    assert payload["remark"] == "张三"
    assert (
        users.get_profile(
            platform="weixin",
            platform_user_id="guest-1",
            is_admin=False,
        ).remark
        == "张三"
    )
    assert audit_calls[-1]["action"] == "channel_user_remark_update"

    cleared = await endpoint.update_channel_user_remark(
        platform="weixin",
        user_id="guest-1",
        payload=ChannelRemarkUpdateRequest(remark=""),
        request=_request(),
        user=_admin(),
    )
    assert cleared["remark"] == ""


@pytest.mark.asyncio
async def test_update_channel_user_access_persists(stores, audit_calls):
    users, _tools = stores
    users.ensure_user(platform="weixin", platform_user_id="guest-1")

    payload = await endpoint.update_channel_user_access(
        platform="weixin",
        user_id="guest-1",
        payload=ChannelAccessUpdateRequest(
            access={"stock": True, "chat": False, "unknown_feature": True}
        ),
        request=_request(),
        user=_admin(),
    )

    assert payload["access"]["stock"] is True
    assert payload["access"]["chat"] is False
    assert "unknown_feature" not in payload["access"]
    assert users.is_feature_enabled(
        platform="weixin",
        platform_user_id="guest-1",
        feature="stock",
        is_admin=False,
    ) is True
    assert audit_calls[-1]["action"] == "channel_user_access_update"


@pytest.mark.asyncio
async def test_tool_policy_update_and_delete(stores, audit_calls):
    _users, tools = stores

    payload = await endpoint.update_channel_user_tool_policy(
        platform="weixin",
        user_id="guest-1",
        payload=ToolPolicyUpdateRequest(allow=["group:media", "group:delivery"]),
        request=_request(),
        user=_admin(),
    )
    assert payload["tool_policy"]["allow"] == ["group:media", "group:delivery"]

    allowed, _detail = tools.is_tool_allowed(
        runtime_user_id="guest-1",
        platform="weixin",
        tool_name="read",
        kind="tool",
    )
    assert allowed is False
    assert audit_calls[-1]["action"] == "channel_user_tool_policy_update"

    removed = await endpoint.delete_channel_user_tool_policy(
        platform="weixin",
        user_id="guest-1",
        request=_request(),
        user=_admin(),
    )
    assert removed["tool_policy"] is None
    assert (
        tools.get_user_override(platform="weixin", platform_user_id="guest-1")
        is None
    )
    assert audit_calls[-1]["action"] == "channel_user_tool_policy_delete"

    with pytest.raises(HTTPException) as exc_info:
        await endpoint.delete_channel_user_tool_policy(
            platform="weixin",
            user_id="guest-1",
            request=_request(),
            user=_admin(),
        )
    assert exc_info.value.status_code == 404
