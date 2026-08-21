from core.tool_access_store import ToolAccessStore


def test_tool_access_groups_and_defaults(tmp_path):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    groups = store.groups_for_tool("read", kind="tool")
    assert "group:fs" in groups
    assert "group:primitives" in groups

    message_delivery_groups = store.groups_for_tool("send_message", kind="tool")
    assert "group:delivery" in message_delivery_groups
    assert "group:fs" not in message_delivery_groups

    bash_groups = store.groups_for_tool("bash", kind="tool")
    assert "group:execution" in bash_groups

    coding_tool_groups = store.groups_for_tool("coding_backend", kind="tool")
    assert "group:coding" in coding_tool_groups

    opencode_groups = store.groups_for_tool("opencode", kind="backend")
    assert "group:coding" in opencode_groups

    generic_skill_groups = store.groups_for_tool("ext_internal_dev_tool", kind="tool")
    assert "group:coding" not in generic_skill_groups

    allowed, detail = store.is_tool_allowed(
        runtime_user_id="subagent::subagent-main::u1",
        platform="subagent_kernel",
        tool_name="ext_web_browser",
        kind="tool",
    )
    assert allowed is True
    assert "group:research" in detail["groups"]
    assert "group:skills" in detail["groups"]


def test_tool_access_dynamic_skill_export_inherits_parent_skill_groups(
    tmp_path,
    monkeypatch,
):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.get_tool_export",
        lambda name: (
            {
                "name": "queue_status",
                "skill_name": "skill_manager",
            }
            if name == "queue_status"
            else None
        ),
    )

    groups = store.groups_for_tool("queue_status", kind="tool")

    assert "group:skills" in groups
    assert "group:skill-admin" in groups


def test_tool_access_ext_skill_prefers_frontmatter_policy_groups(tmp_path, monkeypatch):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.get_skill",
        lambda name: (
            {"policy_groups": ["group:media"]} if name == "download_video" else {}
        ),
    )

    groups = store.groups_for_tool("ext_download_video", kind="tool")

    assert "group:media" in groups


def test_regular_user_runtime_uses_core_ikaros_policy(tmp_path):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    resolved = store.resolve_runtime_policy(
        runtime_user_id="u-plain-user", platform="telegram"
    )
    assert resolved["agent_kind"] == "core-ikaros"

    allowed, detail = store.is_tool_allowed(
        runtime_user_id="u-plain-user",
        platform="telegram",
        tool_name="ext_web_browser",
        kind="tool",
    )
    assert allowed is True
    assert detail["reason"] == "allowed"

    allowed_management, management_detail = store.is_tool_allowed(
        runtime_user_id="u-plain-user",
        platform="telegram",
        tool_name="git_ops",
        kind="tool",
    )
    assert allowed_management is True
    assert "group:management" in management_detail["groups"]

    allowed_primitive, primitive_detail = store.is_tool_allowed(
        runtime_user_id="u-plain-user",
        platform="telegram",
        tool_name="read",
        kind="tool",
    )
    assert allowed_primitive is True
    assert "group:primitives" in primitive_detail["groups"]

    allowed_ikaros_skill, ikaros_skill_detail = store.is_tool_allowed(
        runtime_user_id="u-plain-user",
        platform="telegram",
        tool_name="ext_skill_manager",
        kind="tool",
    )
    assert allowed_ikaros_skill is True
    assert "group:skill-admin" in ikaros_skill_detail["groups"]

    denied_finance_skill, finance_skill_detail = store.is_tool_allowed(
        runtime_user_id="u-plain-user",
        platform="telegram",
        tool_name="ext_stock_watch",
        kind="tool",
    )
    assert denied_finance_skill is False
    assert finance_skill_detail["reason"] == "channel_feature_disabled:stock"


def test_subagent_runtime_uses_ikaros_policy_without_management_loops(tmp_path):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    resolved = store.resolve_runtime_policy(
        runtime_user_id="subagent::subagent-main::u-1",
        platform="subagent_kernel",
    )
    assert resolved["agent_kind"] == "subagent"

    allowed_dev, _ = store.is_tool_allowed(
        runtime_user_id="subagent::subagent-main::u-1",
        platform="subagent_kernel",
        tool_name="git_ops",
        kind="tool",
    )
    assert allowed_dev is True

    denied_spawn, detail = store.is_tool_allowed(
        runtime_user_id="subagent::subagent-main::u-1",
        platform="subagent_kernel",
        tool_name="spawn_subagent",
        kind="tool",
    )
    assert denied_spawn is True
    assert "group:management" in detail["groups"]


def test_user_override_restricts_tools_to_allow_list(tmp_path, monkeypatch):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    monkeypatch.setattr("core.tool_access_store.is_user_admin", lambda _uid: False)
    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.get_skill",
        lambda name: (
            {"policy_groups": ["media"]}
            if name in {"download_video", "video_to_text"}
            else {}
        ),
    )

    policy = store.set_user_override(
        platform="weixin",
        platform_user_id="guest-1",
        allow=["group:media", "group:delivery"],
    )
    assert policy["tools"]["allow"] == ["group:media", "group:delivery"]

    for allowed_tool in ("download_video", "video_to_text", "send_message"):
        allowed, detail = store.is_tool_allowed(
            runtime_user_id="guest-1",
            platform="weixin",
            tool_name=allowed_tool,
            kind="tool",
        )
        assert allowed is True, allowed_tool
        assert detail["agent_kind"] == "channel-user"

    for blocked_tool in ("read", "write", "bash", "coding_backend", "git_ops"):
        allowed, detail = store.is_tool_allowed(
            runtime_user_id="guest-1",
            platform="weixin",
            tool_name=blocked_tool,
            kind="tool",
        )
        assert allowed is False, blocked_tool
        assert detail["reason"] == "not_in_allow_list"
        assert detail["agent_kind"] == "channel-user"

    reloaded = ToolAccessStore()
    reloaded.path = store.path
    reloaded._payload = reloaded._read()
    allowed_after_reload, _ = reloaded.is_tool_allowed(
        runtime_user_id="guest-1",
        platform="weixin",
        tool_name="bash",
        kind="tool",
    )
    assert allowed_after_reload is False

    other_allowed, other_detail = store.is_tool_allowed(
        runtime_user_id="someone-else",
        platform="weixin",
        tool_name="read",
        kind="tool",
    )
    assert other_allowed is True
    assert other_detail["agent_kind"] == "core-ikaros"


def test_user_override_does_not_apply_to_admin(tmp_path, monkeypatch):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    monkeypatch.setattr(
        "core.tool_access_store.is_user_admin",
        lambda uid: str(uid) == "boss-1",
    )
    store.set_user_override(
        platform="weixin",
        platform_user_id="boss-1",
        allow=["group:media"],
    )

    allowed, detail = store.is_tool_allowed(
        runtime_user_id="boss-1",
        platform="weixin",
        tool_name="read",
        kind="tool",
    )
    assert allowed is True
    assert detail["agent_kind"] == "core-ikaros"


def test_remove_user_override_restores_core_policy(tmp_path, monkeypatch):
    store = ToolAccessStore()
    store.path = (tmp_path / "tool_access.json").resolve()
    store._payload = store._default_payload()
    store._write_unlocked()

    monkeypatch.setattr("core.tool_access_store.is_user_admin", lambda _uid: False)
    store.set_user_override(
        platform="weixin",
        platform_user_id="guest-1",
        allow=["group:media"],
    )

    assert (
        store.remove_user_override(platform="weixin", platform_user_id="guest-1")
        is True
    )
    assert (
        store.remove_user_override(platform="weixin", platform_user_id="guest-1")
        is False
    )

    allowed, detail = store.is_tool_allowed(
        runtime_user_id="guest-1",
        platform="weixin",
        tool_name="read",
        kind="tool",
    )
    assert allowed is True
    assert detail["agent_kind"] == "core-ikaros"
