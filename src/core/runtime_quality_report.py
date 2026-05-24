from __future__ import annotations

from collections import Counter
from typing import Any


def build_task_quality_report(tasks: list[Any]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    artifact_delivered = 0
    artifact_failed = 0

    for task in list(tasks or []):
        status = str(getattr(task, "status", "") or "unknown").strip().lower()
        source = str(getattr(task, "source", "") or "unknown").strip().lower()
        status_counts[status or "unknown"] += 1
        source_counts[source or "unknown"] += 1
        for event in list(getattr(task, "events", []) or []):
            if not isinstance(event, dict):
                continue
            if str(event.get("event") or "").strip() != "artifact_delivery":
                continue
            extra = event.get("extra")
            if not isinstance(extra, dict):
                continue
            artifact_delivered += len(extra.get("delivered") or [])
            artifact_failed += len(extra.get("failed") or [])

    recommendations: list[str] = []
    if status_counts.get("failed", 0):
        recommendations.append("把最近失败任务沉淀成回归测试或 skill 文档修正。")
    if artifact_failed:
        recommendations.append("检查附件投递链路和 channel capability。")
    if status_counts.get("waiting_user", 0):
        recommendations.append("复查等待态是否设置了明确过期时间和恢复入口。")
    if not recommendations:
        recommendations.append("近期任务没有明显异常，继续观察。")

    return {
        "total": sum(status_counts.values()),
        "status_counts": dict(status_counts),
        "source_counts": dict(source_counts),
        "artifact_delivered": artifact_delivered,
        "artifact_failed": artifact_failed,
        "recommendations": recommendations,
    }
