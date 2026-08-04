"""
任务调度模块 - 处理定时提醒
"""

import logging
import datetime
import contextlib
import dateutil.parser
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from core.background_delivery import push_background_text
from core.heartbeat_store import heartbeat_store
from core.platform.registry import adapter_manager
from core.platform.models import UnifiedContext
from core.proactive_delivery import resolve_proactive_target
from core.runtime_v2 import runtime_event_bus, runtime_v2
from core.scheduler_display import format_scheduler_report
from core.state_paths import SINGLE_USER_SCOPE
from core.trading_calendar import (
    RUN_CALENDAR_ALWAYS,
    normalize_run_calendar,
    should_run_on_calendar,
)
from shared.contracts.proactive_delivery_target import normalize_proactive_platform

from extension.skills.learned.reminder.scripts.store import (
    add_reminder,
    delete_reminder,
    get_pending_reminders,
)
from extension.skills.builtin.scheduler_manager.scripts.store import (
    get_all_active_tasks,
    scheduler_task_session_id,
)

logger = logging.getLogger(__name__)
SCHEDULER_SESSION_CALLBACK_NS = "schsess"
RUNTIME_V2_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}
RUNTIME_V2_WAITING_STATUSES = {"waiting_user", "waiting_external"}

# Global Scheduler Instance
scheduler = AsyncIOScheduler()
_scheduler_store_revision: int | None = None
SCHEDULER_TEMPLATE_RE = re.compile(
    r"\{\{\s*(?P<name>date|today|now|datetime)"
    r"(?P<offset>[+-]\d+)?"
    r"(?::(?P<fmt>[^{}]+))?\s*\}\}"
)


def _scheduled_tasks_store_revision() -> int:
    try:
        return int(runtime_v2.scheduler_jobs_revision())
    except Exception:
        logger.debug("Failed to read scheduler task store revision.", exc_info=True)
        return 0


def render_scheduler_instruction_template(
    instruction: str,
    *,
    now: datetime.datetime | None = None,
) -> str:
    """Render safe time placeholders in a scheduled task instruction."""
    raw = str(instruction or "")
    if "{{" not in raw:
        return raw

    base_now = now or datetime.datetime.now().astimezone()
    if base_now.tzinfo is None:
        base_now = base_now.astimezone()

    def _replace(match: re.Match[str]) -> str:
        name = str(match.group("name") or "").strip().lower()
        offset = int(str(match.group("offset") or "0"))
        fmt = str(match.group("fmt") or "").strip()
        target = base_now + datetime.timedelta(days=offset)
        if name in {"date", "today"}:
            return target.strftime(fmt) if fmt else target.date().isoformat()
        return target.strftime(fmt) if fmt else target.isoformat(timespec="seconds")

    return SCHEDULER_TEMPLATE_RE.sub(_replace, raw)


async def reconcile_scheduler_jobs() -> None:
    global _scheduler_store_revision
    current_revision = _scheduled_tasks_store_revision()
    if _scheduler_store_revision == current_revision:
        return
    logger.info("Scheduler task store changed; reconciling runtime jobs.")
    await reload_scheduler_jobs()


async def _resolve_proactive_delivery_target(
    user_id: int | str,
    platform: str,
    metadata: dict[str, object] | None = None,
) -> tuple[str, str]:
    return await resolve_proactive_target(
        owner_user_id=str(user_id or "").strip(),
        platform=platform,
        metadata=metadata,
    )


async def _remember_proactive_delivery_target(
    user_id: int | str,
    platform: str,
    chat_id: str,
    session_id: str = "",
) -> None:
    target_platform = normalize_proactive_platform(platform)
    target_chat_id = str(chat_id or "").strip()
    if not target_platform or not target_chat_id:
        return
    try:
        await heartbeat_store.set_delivery_target(
            str(user_id or "").strip(),
            target_platform,
            target_chat_id,
            session_id=session_id,
        )
    except Exception:
        logger.debug("Failed to remember proactive delivery target.", exc_info=True)


async def send_via_adapter(
    chat_id: int | str,
    text: str,
    platform: str = "telegram",
    parse_mode: str = "Markdown",
    user_id: int | str = "",
    session_id: str = "",
    record_history: bool = False,
    ui: dict[str, object] | None = None,
    runtime_session_id: str = "",
    runtime_turn_id: str = "",
    runtime_source: str = "scheduler",
    **kwargs,
):
    """Helper to send message via available adapters"""
    _ = (parse_mode, kwargs)
    push_kwargs = {
        "platform": str(platform or "telegram"),
        "chat_id": str(chat_id or ""),
        "text": str(text or ""),
        "filename_prefix": "background",
    }
    if record_history and str(user_id or "").strip():
        push_kwargs.update(
            {
                "record_history": True,
                "history_user_id": str(user_id or "").strip(),
                "history_session_id": str(session_id or "").strip(),
            }
        )
    if ui:
        push_kwargs["ui"] = ui
    if runtime_session_id:
        push_kwargs.update(
            {
                "runtime_session_id": str(runtime_session_id or "").strip(),
                "runtime_turn_id": str(runtime_turn_id or "").strip(),
                "runtime_source": str(runtime_source or "scheduler").strip(),
            }
        )
    ok = await push_background_text(
        **push_kwargs,
    )
    if not ok:
        logger.warning("Background push failed platform=%s chat=%s", platform, chat_id)
    return bool(ok)


def _safe_runtime_turn_status(turn_id: str) -> str:
    safe_turn_id = str(turn_id or "").strip()
    if not safe_turn_id:
        return ""
    try:
        return str(runtime_v2.get_turn(safe_turn_id).get("status") or "").strip()
    except Exception:
        logger.debug("Failed to read Runtime v2 turn status.", exc_info=True)
        return ""


def _mark_scheduler_runtime_turn_running(
    turn_id: str,
    *,
    scheduled_task_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    safe_turn_id = str(turn_id or "").strip()
    if not safe_turn_id:
        return
    current_status = _safe_runtime_turn_status(safe_turn_id)
    if current_status in RUNTIME_V2_TERMINAL_STATUSES:
        return
    if current_status == "running":
        return
    try:
        runtime_v2.update_turn_status(
            safe_turn_id,
            "running",
            metadata={
                "scheduled_task_id": str(scheduled_task_id or "").strip(),
                **dict(metadata or {}),
            },
        )
    except Exception:
        logger.debug("Failed to mark scheduler Runtime v2 turn running.", exc_info=True)


def _close_scheduler_runtime_turn(
    turn_id: str,
    *,
    scheduled_task_id: str,
    status: str,
    error: str = "",
    metadata: dict[str, object] | None = None,
) -> str:
    safe_turn_id = str(turn_id or "").strip()
    if not safe_turn_id:
        return ""
    current_status = _safe_runtime_turn_status(safe_turn_id)
    if current_status in RUNTIME_V2_TERMINAL_STATUSES | RUNTIME_V2_WAITING_STATUSES:
        return current_status
    if current_status == "queued":
        _mark_scheduler_runtime_turn_running(
            safe_turn_id,
            scheduled_task_id=scheduled_task_id,
            metadata={"entered_scheduler_runtime": True},
        )
    try:
        closed = runtime_v2.update_turn_status(
            safe_turn_id,
            status,
            error=error,
            metadata={
                "scheduled_task_id": str(scheduled_task_id or "").strip(),
                **dict(metadata or {}),
            },
        )
        return str(closed.get("status") or "").strip()
    except Exception:
        logger.debug("Failed to close scheduler Runtime v2 turn.", exc_info=True)
        return _safe_runtime_turn_status(safe_turn_id)


def scheduler_report_session_ui(scheduled_task_id: int | str) -> dict[str, object] | None:
    safe_task_id = str(scheduled_task_id or "").strip()
    if not safe_task_id:
        return None
    return {
        "actions": [
            [
                {
                    "text": "进入会话",
                    "callback_data": f"{SCHEDULER_SESSION_CALLBACK_NS}_enter_{safe_task_id}",
                }
            ]
        ]
    }


async def send_reminder_job(
    reminder_id: int,
    user_id: int,
    chat_id: int,
    message: str,
    platform: str = "telegram",
):
    """发送提醒的工作任务"""
    logger.info(f"Triggering reminder {reminder_id} for chat {chat_id} on {platform}")

    try:
        await send_via_adapter(
            chat_id=chat_id,
            text=f"⏰ **提醒**\n\n{message}",
            platform=platform,
            user_id=user_id,
            record_history=True,
        )
    except Exception as e:
        logger.error(f"Failed to send reminder {reminder_id}: {e}")
    finally:
        await delete_reminder(reminder_id, user_id=user_id)


async def schedule_reminder(
    user_id: int,
    chat_id: int,
    message: str,
    trigger_time: datetime.datetime,
    platform: str = "telegram",
) -> bool:
    """安排一个新的提醒任务"""
    now = datetime.datetime.now().astimezone()

    # Update: If trigger_time is naiive, make it aware (local)
    if trigger_time.tzinfo is None:
        trigger_time = trigger_time.replace(tzinfo=now.tzinfo)

    # 落盘到文件存储
    reminder_id = await add_reminder(
        user_id, chat_id, message, trigger_time.isoformat(), platform=platform
    )

    # 加入 Scheduler
    scheduler.add_job(
        send_reminder_job,
        "date",
        run_date=trigger_time,
        args=[reminder_id, user_id, chat_id, message, platform],
        id=f"reminder_{reminder_id}",
        replace_existing=True,
    )
    return True


async def load_jobs_from_db():
    """从文件存储加载未执行的提醒任务（Bot 启动时调用）"""
    logger.info("Loading pending reminders from filesystem store...")
    reminders = await get_pending_reminders()

    count = 0
    now = datetime.datetime.now().astimezone()

    for row in reminders:
        reminder_id = row["id"]
        trigger_time_str = row["trigger_time"]
        platform = row.get("platform", "telegram")

        try:
            # 解析时间
            trigger_time = dateutil.parser.isoparse(trigger_time_str)

            # 确保此时区意识到 (aware)
            if trigger_time.tzinfo is None:
                trigger_time = trigger_time.replace(tzinfo=now.tzinfo)

            # 如果错过了时间，稍微延迟一点立即执行
            run_time = trigger_time
            delay = (trigger_time - now).total_seconds()
            if delay < 0:
                run_time = now + datetime.timedelta(seconds=5)

            scheduler.add_job(
                send_reminder_job,
                "date",
                run_date=run_time,
                args=[
                    reminder_id,
                    SINGLE_USER_SCOPE,
                    row["chat_id"],
                    row["message"],
                    platform,
                ],
                id=f"reminder_{reminder_id}",
                replace_existing=True,
            )
            count += 1

        except Exception as e:
            logger.error(f"Failed to load reminder {reminder_id}: {e}")

    logger.info(f"Loaded {count} pending reminders.")


# --- 动态 Skill 调度 ---


async def run_skill_cron_job(
    instruction: str,
    user_id: int | str = 0,
    platform: str = "telegram",
    need_push: bool = False,
    chat_id: str = "",
    session_id: str = "",
    scheduled_task_id: int | str = "",
    run_calendar: str = RUN_CALENDAR_ALWAYS,
):
    """
    通用 Skill 定时任务执行器
    """
    user_id_text = str(user_id or "").strip()
    if not user_id_text:
        user_id_text = "0"
    scheduled_task_id_text = str(scheduled_task_id or "").strip()
    run_session_id = (
        scheduler_task_session_id(scheduled_task_id_text)
        if scheduled_task_id_text
        else str(session_id or "").strip()
    )
    run_now = datetime.datetime.now().astimezone()
    run_date_iso = run_now.date().isoformat()
    calendar_mode = normalize_run_calendar(run_calendar)
    if not should_run_on_calendar(calendar_mode, run_now.date()):
        logger.info(
            "[Cron] Skip task %s on %s (run_calendar=%s)",
            scheduled_task_id_text or instruction[:40],
            run_date_iso,
            calendar_mode,
        )
        return
    original_instruction = str(instruction or "")
    rendered_instruction = render_scheduler_instruction_template(
        original_instruction,
        now=run_now,
    )
    template_rendered = rendered_instruction != original_instruction
    if not rendered_instruction:
        rendered_instruction = "Execute scheduled maintenance/run_cron task."

    if run_session_id:
        runtime_v2.ensure_session(
            session_id=run_session_id,
            kind="scheduled_task",
            platform="scheduler",
            platform_user_id=user_id_text,
            title=rendered_instruction[:80],
            metadata={
                "scheduled_task_id": scheduled_task_id_text,
                "delivery_platform": str(platform or "").strip(),
                "delivery_chat_id": str(chat_id or "").strip(),
                "run_date": run_date_iso,
                "original_instruction": original_instruction,
                "template_rendered": template_rendered,
            },
        )
        runtime_turn = runtime_v2.create_turn(
            session_id=run_session_id,
            source="scheduler",
            input_text=rendered_instruction,
            kernel_provider="agents_sdk",
            metadata={
                "scheduled_task_id": scheduled_task_id_text,
                "original_instruction": original_instruction,
                "template_rendered": template_rendered,
            },
        )
        runtime_turn_id = str(runtime_turn.get("id") or "").strip()
        runtime_event_bus.publish(
            session_id=run_session_id,
            turn_id=runtime_turn_id,
            event_type="scheduler_triggered",
            payload={
                "scheduled_task_id": scheduled_task_id_text,
                "instruction": rendered_instruction,
                "original_instruction": original_instruction,
                "platform": platform,
            },
        )
        _mark_scheduler_runtime_turn_running(
            runtime_turn_id,
            scheduled_task_id=scheduled_task_id_text,
            metadata={
                "instruction": rendered_instruction[:500],
                "original_instruction": original_instruction[:500],
                "template_rendered": template_rendered,
            },
        )
    else:
        runtime_turn_id = ""

    logger.info(
        "[Cron] Executing scheduled skill: '%s' for user %s on %s session=%s",
        rendered_instruction,
        user_id_text,
        platform,
        run_session_id,
    )

    try:
        from core.agent_input import (
            MAX_INLINE_IMAGE_INPUTS,
            build_agent_message_history,
        )
        from core.platform.models import UnifiedMessage, User, Chat, MessageType
        from core.agent_orchestrator import agent_orchestrator
        from core.state_store import create_chat_session, save_message

        mock_user = User(id=user_id_text, username="Cron User", is_bot=False)
        mock_chat = Chat(id=run_session_id or user_id_text, type="private")
        cron_task_id = (
            f"cron-{scheduled_task_id_text}-{int(run_now.timestamp())}"
            if scheduled_task_id_text
            else f"cron-{int(run_now.timestamp())}"
        )
        mock_message = UnifiedMessage(
            id=cron_task_id,
            platform=platform,
            user=mock_user,
            chat=mock_chat,
            text=rendered_instruction,
            date=run_now,
            type=MessageType.TEXT,
            raw_data={
                "source": "scheduler",
                "scheduled_task_id": scheduled_task_id_text,
                "session_id": run_session_id,
                "delivery_platform": str(platform or "").strip(),
                "delivery_chat_id": str(chat_id or "").strip(),
                "run_date": run_date_iso,
                "original_instruction": original_instruction,
                "template_rendered": template_rendered,
            },
        )

        adapter = None
        try:
            adapter = adapter_manager.get_adapter(platform)
        except Exception:
            adapter = None

        ctx = UnifiedContext(
            message=mock_message,
            platform_ctx=None,
            _adapter=adapter,
            user=mock_user,
        )
        if run_session_id:
            ctx.user_data["current_session_id"] = run_session_id
            ctx.user_data["runtime_v2_session_id"] = run_session_id
            if runtime_turn_id:
                ctx.user_data["runtime_v2_turn_id"] = runtime_turn_id
        ctx.user_data["runtime_task_id"] = cron_task_id
        ctx.user_data["scheduler_run_date"] = run_date_iso
        ctx.user_data["scheduler_instruction"] = original_instruction
        ctx.user_data["scheduler_rendered_instruction"] = rendered_instruction
        ctx.user_data["routing_context"] = (
            f"定时任务原始描述：{original_instruction}\n"
            f"定时任务本次描述：{rendered_instruction}"
        )
        if scheduled_task_id_text:
            ctx.user_data["scheduled_task_id"] = scheduled_task_id_text

        final_output = []

        prompt_text = (
            f"[CRON TASK id={cron_task_id}]\n"
            f"source=cron\n"
            f"本次执行时间：{run_now.isoformat(timespec='seconds')}\n"
            f"【系统级别最高指令】：你当前正在“执行”一个已被触发的系统定时任务！\n"
            f"请从以下目标描述中提取需要真实执行的查询、分析等动作并**立刻执行它**。\n"
            f"如果目标描述中包含日期/时间模板表达式，它们已经按本次执行时间渲染完成；请以渲染后的目标描述为准。\n"
            f"如果目标描述里带有“每天/每小时/定时”等字眼，请直接忽略这些时间修饰词，只执行里面提到的查天气、看新闻等实际动作！\n"
            f"**绝对禁止**调用 scheduler_manager 去再次添加、创建新的定时任务（那会导致无限套娃循环）！\n\n"
            f"目标任务描述：{rendered_instruction}"
        )
        if template_rendered:
            prompt_text += f"\n\n原始任务描述：{original_instruction}"
        prepared_input = await build_agent_message_history(
            ctx,
            user_message=prompt_text,
            inline_input_source_texts=[rendered_instruction],
            strip_refs_from_user_message=False,
            max_inline_inputs=MAX_INLINE_IMAGE_INPUTS,
        )
        if run_session_id:
            await create_chat_session(user_id_text, run_session_id)
            await save_message(
                user_id_text,
                "user",
                (
                    f"[定时任务 #{scheduled_task_id_text}] {rendered_instruction}"
                    if scheduled_task_id_text
                    else f"[定时任务] {rendered_instruction}"
                ),
                run_session_id,
            )

        if prepared_input.detected_refs and not prepared_input.has_inline_inputs:
            full_response = "❌ 检测到图片链接或本地图片路径，但没有成功加载任何图片。请检查链接或路径后重试。"
        else:
            message_history = list(prepared_input.message_history)

            if prepared_input.truncated_inline_count:
                final_output.append(
                    f"⚠️ 检测到超过 {MAX_INLINE_IMAGE_INPUTS} 张图片，本次仅使用前 {MAX_INLINE_IMAGE_INPUTS} 张。\n\n"
                )
            if prepared_input.errors and prepared_input.has_inline_inputs:
                final_output.append(
                    f"⚠️ 有 {len(prepared_input.errors)} 张图片加载失败，先按成功加载的图片继续分析。\n\n"
                )

            # Execute via Agent Brain
            async for chunk in agent_orchestrator.handle_message(ctx, message_history):
                if chunk and chunk.strip():
                    final_output.append(chunk)

            full_response = "".join(final_output).strip()
        report_text = format_scheduler_report(rendered_instruction, full_response)
        if run_session_id and report_text:
            await save_message(user_id_text, "model", report_text, run_session_id)
        if run_session_id and runtime_turn_id:
            _close_scheduler_runtime_turn(
                runtime_turn_id,
                scheduled_task_id=scheduled_task_id_text,
                status="succeeded" if full_response else "failed",
                error="" if full_response else "scheduled task produced no output",
                metadata={"report_length": len(report_text)},
            )
            runtime_event_bus.publish(
                session_id=run_session_id,
                turn_id=runtime_turn_id,
                event_type="assistant_message_final",
                payload={"text": full_response, "source": "scheduler"},
            )
        # Push Notification Logic
        if need_push and user_id_text not in {"", "0"}:
            if full_response:
                metadata = (
                    {
                        "resource_binding": {
                            "platform": str(platform or "telegram"),
                            "chat_id": str(chat_id or "").strip(),
                        }
                    }
                    if str(chat_id or "").strip()
                    else None
                )
                (
                    target_platform,
                    target_chat_id,
                ) = await _resolve_proactive_delivery_target(
                    user_id_text,
                    platform,
                    metadata=metadata,
                )
                if not target_platform or not target_chat_id:
                    logger.warning(
                        "[Cron] Push skipped: no delivery target for user=%s on %s",
                        user_id_text,
                        platform,
                    )
                else:
                    logger.info(
                        f"[Cron] Pushing result to {user_id_text} on {target_platform}"
                    )
                    await send_via_adapter(
                        chat_id=target_chat_id,
                        text=report_text,
                        platform=target_platform,
                        user_id=user_id_text,
                        session_id=run_session_id,
                        record_history=False,
                        ui=scheduler_report_session_ui(scheduled_task_id_text),
                        runtime_session_id=run_session_id,
                        runtime_turn_id=runtime_turn_id,
                        runtime_source="scheduler_report",
                    )
                    if run_session_id and runtime_turn_id:
                        runtime_event_bus.publish(
                            session_id=run_session_id,
                            turn_id=runtime_turn_id,
                            event_type="scheduler_report_pushed",
                            payload={
                                "platform": target_platform,
                                "chat_id": target_chat_id,
                                "scheduled_task_id": scheduled_task_id_text,
                            },
                        )
                    await _remember_proactive_delivery_target(
                        user_id_text,
                        target_platform,
                        target_chat_id,
                        session_id=run_session_id,
                    )
            else:
                logger.info(f"[Cron] No output to push for {instruction}")

    except Exception as e:
        if run_session_id and runtime_turn_id:
            with contextlib.suppress(Exception):
                _close_scheduler_runtime_turn(
                    runtime_turn_id,
                    scheduled_task_id=scheduled_task_id_text,
                    status="failed",
                    error=str(e),
                )
                runtime_event_bus.publish(
                    session_id=run_session_id,
                    turn_id=runtime_turn_id,
                    event_type="scheduler_failed",
                    payload={"error": str(e), "scheduled_task_id": scheduled_task_id_text},
                )
        logger.error(f"[Cron] Failed to run skill {instruction}: {e}", exc_info=True)


async def reload_scheduler_jobs():
    """
    重新加载文件存储中的定时任务 (全量刷新)
    """
    global _scheduler_store_revision
    logger.info("Reloading scheduler jobs from Runtime v2 store...")

    # 1. Clear existing dynamic jobs to handle deletions/updates
    # We identify them by ID prefix "cron_db_"
    # Note: scheduler.get_jobs() returns a list
    start_time = datetime.datetime.now()
    removed_count = 0
    for job in scheduler.get_jobs():
        if job.id.startswith("cron_db_"):
            try:
                job.remove()
                removed_count += 1
            except Exception:
                pass

    if removed_count > 0:
        logger.info(f"Removed {removed_count} existing dynamic jobs.")

    # 2. Load from store
    tasks = await get_all_active_tasks()
    count = 0
    active_task_ids: set[str] = set()
    for task in tasks:
        task_id = task["id"]
        active_task_ids.add(str(task_id))
        crontab = task["crontab"]
        instruction = task["instruction"]
        platform = task.get("platform", "telegram")
        chat_id = str(task.get("chat_id") or "").strip()
        need_push = bool(task.get("need_push", True))
        run_calendar = normalize_run_calendar(task.get("run_calendar"))
        session_id = scheduler_task_session_id(task_id)
        existing_session = runtime_v2.get_session(session_id)
        user_id = (
            str(task.get("user_id") or "").strip()
            or str(existing_session.get("platform_user_id") or "").strip()
            or str(SINGLE_USER_SCOPE)
        )
        runtime_v2.ensure_session(
            session_id=session_id,
            kind="scheduled_task",
            platform="scheduler",
            platform_user_id=str(user_id),
            title=str(instruction or "")[:80],
            metadata={"scheduled_task_id": str(task_id)},
        )
        runtime_v2.upsert_scheduler_job(
            job_id=str(task_id),
            session_id=session_id,
            crontab=crontab,
            instruction=instruction,
            platform=platform,
            chat_id=chat_id,
            enabled=True,
            metadata={"need_push": need_push, "run_calendar": run_calendar},
        )

        try:
            parts = crontab.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )

                scheduler.add_job(
                    run_skill_cron_job,
                    trigger,
                    id=f"cron_db_{task_id}",
                    args=[
                        instruction,
                        user_id,
                        platform,
                        need_push,
                        chat_id,
                        session_id,
                        task_id,
                        run_calendar,
                    ],
                    replace_existing=True,
                )
                count += 1
            else:
                logger.warning(
                    f"Invalid crontab format for task {instruction}: {crontab}"
                )
        except Exception as e:
            logger.error(f"Failed to register cron for task {instruction}: {e}")

    disabled_count = runtime_v2.disable_scheduler_jobs_except(active_task_ids)
    if disabled_count:
        logger.info("Disabled %s stale Runtime v2 scheduler jobs.", disabled_count)

    logger.info(
        f"Reloaded {count} jobs from Runtime v2 store in {(datetime.datetime.now() - start_time).total_seconds()}s."
    )
    _scheduler_store_revision = _scheduled_tasks_store_revision()


def start_dynamic_skill_scheduler():
    """
    启动动态 Skill 调度器 (Initial Load)
    """
    scheduler.add_job(
        reload_scheduler_jobs,
        "date",
        run_date=datetime.datetime.now() + datetime.timedelta(seconds=5),
        id="scheduler_initial_reload",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        reconcile_scheduler_jobs,
        "interval",
        seconds=30,
        id="scheduler_store_reconcile",
        replace_existing=True,
        misfire_grace_time=30,
        coalesce=True,
        max_instances=1,
    )
