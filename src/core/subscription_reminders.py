from __future__ import annotations

import datetime
import logging
from typing import Any

from core.background_delivery import push_background_text
from core.proactive_delivery import resolve_proactive_target
from core.subscription_store import (
    init_subscription_store,
    list_due_subscriptions,
    mark_subscription_reminded,
)

logger = logging.getLogger(__name__)


def _cycle_label(months: int) -> str:
    labels = {1: "每月", 3: "每季度", 6: "每半年", 12: "每年"}
    return labels.get(int(months), f"每 {int(months)} 个月")


def format_subscription_reminder(
    subscription: dict[str, Any],
    *,
    today: datetime.date | None = None,
) -> str:
    current_date = today or datetime.date.today()
    expiry = datetime.date.fromisoformat(str(subscription["expiry_date"]))
    remaining = (expiry - current_date).days
    if remaining == 0:
        remaining_text = "今天到期"
    else:
        remaining_text = f"还有 {remaining} 天到期"

    lines = [
        "🔔 **订阅续期提醒**",
        "",
        f"**{subscription['name']}** {remaining_text}，到期日为 **{expiry.isoformat()}**。",
        f"- 类别：{subscription.get('category') or '其他'}",
        f"- 周期：{_cycle_label(int(subscription.get('cycle_months') or 0))}",
    ]
    provider = str(subscription.get("provider") or "").strip()
    if provider:
        lines.append(f"- 服务商：{provider}")
    lines.extend(
        [
            "",
            "请确认是否续期；如果服务商给出的日期不同，可在 Ikaros 的订阅管理中手动调整到期日。",
        ]
    )
    return "\n".join(lines)


async def check_subscription_reminders(
    *,
    today: datetime.date | None = None,
) -> dict[str, int]:
    current_date = today or datetime.date.today()
    due = await list_due_subscriptions(today=current_date)
    result = {"due": len(due), "sent": 0, "skipped": 0, "failed": 0}

    for subscription in due:
        platform = str(subscription.get("delivery_platform") or "").strip().lower()
        delivery_user_id = str(subscription.get("delivery_user_id") or "").strip()
        if not platform or not delivery_user_id:
            result["skipped"] += 1
            logger.warning(
                "Subscription reminder skipped without delivery binding id=%s",
                subscription.get("id"),
            )
            continue

        target_platform, target_chat_id = await resolve_proactive_target(
            owner_user_id=delivery_user_id,
            platform=platform,
        )
        if not target_platform or not target_chat_id:
            target_platform, target_chat_id = platform, delivery_user_id

        sent = await push_background_text(
            platform=target_platform,
            chat_id=target_chat_id,
            text=format_subscription_reminder(subscription, today=current_date),
            filename_prefix="subscription-reminder",
            record_history=True,
            history_user_id=delivery_user_id,
            runtime_source="subscription_reminder",
        )
        if not sent:
            result["failed"] += 1
            continue

        marked = await mark_subscription_reminded(
            int(subscription["id"]),
            str(subscription["expiry_date"]),
        )
        if marked:
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result


async def start_subscription_reminder_scheduler(scheduler: Any) -> None:
    await init_subscription_store()
    scheduler.add_job(
        check_subscription_reminders,
        "date",
        run_date=datetime.datetime.now().astimezone() + datetime.timedelta(seconds=60),
        id="subscription_reminder_initial_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        check_subscription_reminders,
        "interval",
        minutes=15,
        id="subscription_reminder_scan",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )


__all__ = [
    "check_subscription_reminders",
    "format_subscription_reminder",
    "start_subscription_reminder_scheduler",
]
