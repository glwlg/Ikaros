import pytest

from core.state_paths import SINGLE_USER_SCOPE
from extension.channels.web.adapter import WebAdapter


@pytest.mark.asyncio
async def test_web_scheduler_session_reuses_scheduler_codex_key():
    adapter = WebAdapter()

    ctx = await adapter._build_context(
        {
            "id": "evt-1",
            "type": "message_text",
            "owner_user_id": "web-1",
            "session_id": "scheduler-task-7",
            "payload": {
                "text": "这次定时任务结果要更关注监管新闻",
                "message_id": "msg-1",
                "user_id": "web-1",
            },
        }
    )

    assert ctx.user_data["current_session_id"] == "scheduler-task-7"
    assert ctx.user_data["codex_kernel_session_platform"] == "scheduler"
    assert ctx.user_data["codex_kernel_session_user_id"] == SINGLE_USER_SCOPE

    ctx = await adapter._build_context(
        {
            "id": "evt-2",
            "type": "message_text",
            "owner_user_id": "web-1",
            "session_id": "web-session",
            "payload": {
                "text": "普通 Web 对话",
                "message_id": "msg-2",
                "user_id": "web-1",
            },
        }
    )

    assert ctx.user_data["current_session_id"] == "web-session"
    assert "codex_kernel_session_platform" not in ctx.user_data
    assert "codex_kernel_session_user_id" not in ctx.user_data
