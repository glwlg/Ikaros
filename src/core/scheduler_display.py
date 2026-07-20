from __future__ import annotations

SCHEDULER_INSTRUCTION_PREVIEW_LIMIT = 30


def summarize_scheduler_instruction(
    instruction: str,
    *,
    limit: int = SCHEDULER_INSTRUCTION_PREVIEW_LIMIT,
) -> str:
    text = " ".join(str(instruction or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def format_scheduler_report(instruction: str, response: str) -> str:
    response_text = str(response or "").strip()
    if not response_text:
        return ""
    instruction_preview = summarize_scheduler_instruction(instruction)
    return f"⏰ **定时任务执行报告 ({instruction_preview})**\n\n{response_text}"
