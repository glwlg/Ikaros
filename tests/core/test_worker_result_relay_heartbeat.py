from __future__ import annotations

import pytest

from manager.relay.result_relay import WorkerResultRelay
from shared.contracts.dispatch import TaskEnvelope


@pytest.mark.asyncio
async def test_heartbeat_delivery_summary_bypasses_model_synthesis(monkeypatch):
    async def fail_generate_text(**_kwargs):
        raise AssertionError("heartbeat delivery should not call model synthesis")

    monkeypatch.setattr(
        "services.openai_adapter.generate_text",
        fail_generate_text,
    )

    relay = WorkerResultRelay()
    task = TaskEnvelope(
        task_id="tsk-hb",
        worker_id="worker-main",
        instruction="heartbeat raw output",
        source="manager_dispatch",
        metadata={
            "session_id": "hb-123",
            "task_goal": "检查今日 heartbeat 结果",
        },
    )
    result = {
        "ok": True,
        "summary": "原始摘要",
        "payload": {
            "text": (
                "## 工具选择策略\n"
                "- 任务: heartbeat 巡检\n\n"
                "## 执行日志\n"
                "- 已完成巡检\n\n"
                "## 最终结果\n"
                "发现 1 条需要关注的更新，请尽快处理。"
            )
        },
    }

    body = await relay._summarize_delivery_body(
        task=task,
        result=result,
        text=str(result["payload"]["text"]),
        files=[],
    )

    assert "需要关注的更新" in body
