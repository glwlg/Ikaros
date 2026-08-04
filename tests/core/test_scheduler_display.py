from types import SimpleNamespace

import pytest

from core.scheduler_display import (
    format_scheduler_report,
    summarize_scheduler_instruction,
    summarize_scheduler_instruction_for_ui,
)
from extension.skills.builtin.scheduler_manager.scripts import (
    execute as scheduler_execute,
)


def test_scheduler_instruction_preview_keeps_at_most_thirty_characters():
    instruction = "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三"

    assert summarize_scheduler_instruction(instruction) == instruction[:30] + "..."


def test_scheduler_instruction_preview_does_not_truncate_thirty_characters():
    instruction = "定" * 30

    assert summarize_scheduler_instruction(instruction) == instruction


def test_scheduler_instruction_preview_collapses_whitespace_before_truncating():
    instruction = "用 article_publisher\n\n写一篇办公效率文章"

    assert summarize_scheduler_instruction(instruction) == (
        "用 article_publisher 写一篇办公效率文章"
    )


def test_scheduler_report_uses_instruction_preview_but_keeps_full_response():
    instruction = "任务说明" * 20
    response = "这是完整的任务执行结果。"

    report = format_scheduler_report(instruction, response)

    assert f"({instruction[:30]}...)" in report
    assert response in report
    assert instruction not in report


def test_scheduler_ui_preview_is_longer_than_chat_preview():
    instruction = "用 article_publisher 写一篇" + ("很长的提示词内容" * 20)

    ui_preview = summarize_scheduler_instruction_for_ui(instruction)
    chat_preview = summarize_scheduler_instruction(instruction)

    assert ui_preview.endswith("...")
    assert len(ui_preview) > len(chat_preview)
    assert len(ui_preview) <= 99


@pytest.mark.asyncio
async def test_scheduler_list_uses_instruction_preview(monkeypatch):
    instruction = "完整定时任务内容" * 10

    async def fake_get_all_active_tasks():
        return [
            {
                "id": 7,
                "crontab": "0 8 * * *",
                "instruction": instruction,
                "need_push": True,
                "platform": "weixin",
                "chat_id": "user-1",
            }
        ]

    monkeypatch.setattr(
        scheduler_execute,
        "get_all_active_tasks",
        fake_get_all_active_tasks,
    )
    ctx = SimpleNamespace()

    result = await scheduler_execute.list_tasks_command(ctx)

    assert f"Desc: `{instruction[:30]}...`" in result["text"]
    assert instruction not in result["text"]
