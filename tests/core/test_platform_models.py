from datetime import datetime

import pytest

from core.platform.models import (
    Chat,
    MessageType,
    PlatformCapabilities,
    UnifiedContext,
    UnifiedMessage,
    User,
)


def test_platform_capabilities_reply_kind_lookup():
    capabilities = PlatformCapabilities(reply_video=False)

    assert capabilities.supports_reply_kind("photo") is True
    assert capabilities.supports_reply_kind("video") is False
    assert capabilities.supports_reply_kind("unknown") is True


@pytest.mark.asyncio
async def test_unified_context_run_skill_blocks_disabled_skill(monkeypatch):
    monkeypatch.setattr(
        "extension.skills.registry.skill_registry.is_skill_enabled",
        lambda _skill_name: False,
    )

    ctx = UnifiedContext(
        message=UnifiedMessage(
            id="msg-1",
            platform="telegram",
            user=User(id="u-1"),
            chat=Chat(id="c-1", type="private"),
            date=datetime.now(),
            type=MessageType.TEXT,
            text="test",
        ),
        platform_ctx=None,
    )

    result = await ctx.run_skill("disabled_demo", {})

    assert result["success"] is False
    assert "disabled" in result["error"]
