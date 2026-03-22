from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.platform.models import UnifiedContext
from core.skill_menu import make_callback, parse_callback
from core.skill_cli import (
    add_common_arguments,
    merge_params,
    prepare_default_env,
    run_execute_cli,
)

prepare_default_env(REPO_ROOT)

from core.state_store import add_scheduled_task, delete_task, get_all_active_tasks
import logging

logger = logging.getLogger(__name__)
SCHEDULE_MENU_NS = "schm"


def _parse_schedule_subcommand(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "menu", ""

    parts = raw.split(maxsplit=2)
    if not parts:
        return "list", ""
    if not parts[0].startswith("/schedule"):
        return "help", ""
    if len(parts) == 1:
        return "menu", ""

    sub = str(parts[1] or "").strip().lower()
    args = str(parts[2] if len(parts) >= 3 else "").strip()

    if sub in {"menu", "home", "start"}:
        return "menu", ""
    if sub in {"list", "ls", "show"}:
        return "list", ""
    if sub in {"delete", "del", "rm", "remove"}:
        return "delete", args
    if sub in {"help", "h", "?"}:
        return "help", ""
    return "help", ""


def _schedule_usage_text() -> str:
    return (
        "用法:\n"
        "`/schedule`\n"
        "`/schedule list`\n"
        "`/schedule delete <task_id>`\n"
        "`/schedule help`\n\n"
        "新增任务请直接告诉我任务内容，或通过技能参数创建。"
    )


def _schedule_menu_ui() -> dict:
    return {
        "actions": [
            [
                {"text": "📋 任务列表", "callback_data": make_callback(SCHEDULE_MENU_NS, "list")},
                {"text": "❌ 删除任务", "callback_data": make_callback(SCHEDULE_MENU_NS, "delete")},
            ],
            [
                {"text": "➕ 新建说明", "callback_data": make_callback(SCHEDULE_MENU_NS, "addhelp")},
                {"text": "ℹ️ 帮助", "callback_data": make_callback(SCHEDULE_MENU_NS, "help")},
            ],
        ]
    }


async def show_schedule_menu(ctx: UnifiedContext) -> dict:
    tasks = await get_all_active_tasks()
    return {
        "text": (
            "⏰ **定时任务管理**\n\n"
            f"当前活跃任务：{len(tasks)}\n\n"
            "删除任务可直接用 `/schedule delete <task_id>`。\n"
            "新增任务建议直接告诉我执行频率和内容，或走技能参数创建。"
        ),
        "ui": _schedule_menu_ui(),
    }


def _schedule_add_help_response() -> dict:
    return {
        "text": (
            "➕ **新增定时任务**\n\n"
            "这个命令入口当前只负责查看和删除。\n"
            "如果你想新建任务，建议直接描述需求，例如：\n"
            "• 每天早上 9 点提醒我看日报\n"
            "• 每小时检查一次 RSS\n\n"
            "如果要手动删除，直接发 `/schedule delete <task_id>`。"
        ),
        "ui": {
            "actions": [
                [
                    {"text": "🏠 返回首页", "callback_data": make_callback(SCHEDULE_MENU_NS, "home")},
                    {"text": "📋 查看任务", "callback_data": make_callback(SCHEDULE_MENU_NS, "list")},
                ]
            ]
        },
    }


async def execute(ctx: UnifiedContext, params: dict, runtime=None) -> dict:
    """
    Execute scheduler management operations.
    """
    action = params.get("action", "list")
    user_id = ctx.message.user.id if ctx.message and ctx.message.user else "0"
    platform = (
        ctx.message.platform if ctx.message and ctx.message.platform else "telegram"
    )

    if action == "add":
        crontab = params.get("crontab")
        instruction = params.get("instruction")
        # Default True if not specified as 'false' string
        push_param = str(params.get("push", "true")).lower()
        need_push = push_param == "true" or push_param == "1"

        if not instruction:
            return {"text": "❌ 请提供 `instruction`"}

        try:
            task_id = await add_scheduled_task(
                crontab, instruction, user_id, platform, need_push
            )

            # 立即触发 Scheduler 重载
            from core.scheduler import reload_scheduler_jobs

            await reload_scheduler_jobs()

            return {
                "text": (
                    f"✅ 定时任务已添加 (ID: {task_id})\n"
                    f"Cron: `{crontab}`\n"
                    f"Instruction: `{instruction}`\n"
                    f"Push: `{'Yes' if need_push else 'No'}`\n"
                    f"状态: 已立即生效"
                )
            }
        except Exception as e:
            return {"text": f"❌ 添加失败: {e}"}

    elif action == "list":
        return await list_tasks_command(ctx)

    elif action == "delete":
        task_id = params.get("task_id")
        if not task_id:
            return {"text": "❌ 请提供 `task_id`"}

        try:
            await delete_task(int(task_id))
            from core.scheduler import reload_scheduler_jobs

            await reload_scheduler_jobs()
            return {"text": f"✅ 任务 {task_id} 已删除并立即生效。"}
        except Exception as e:
            return {"text": f"❌ 删除失败: {e}"}

    return {"text": f"❌ 未知操作: {action}"}


def register_handlers(adapter_manager):
    """注册 Scheduler 二级命令和 Callback"""
    from core.config import is_user_allowed

    async def cmd_schedule(ctx):
        if not await is_user_allowed(ctx.message.user.id):
            return

        sub, args = _parse_schedule_subcommand(ctx.message.text or "")
        if sub == "menu":
            return await show_schedule_menu(ctx)
        if sub == "list":
            return await list_tasks_command(ctx, include_menu_nav=True)

        if sub == "delete":
            task_id_raw = args.strip()
            if not task_id_raw:
                return await show_delete_menu(ctx, include_menu_nav=True)
            try:
                task_id = int(task_id_raw)
            except ValueError:
                return "❌ 任务 ID 必须是数字。"

            try:
                await delete_task(task_id)
                from core.scheduler import reload_scheduler_jobs

                await reload_scheduler_jobs()
                return f"✅ 任务 {task_id} 已删除。"
            except Exception as exc:
                return f"❌ 删除失败: {exc}"

        return _schedule_usage_text()

    adapter_manager.on_command("schedule", cmd_schedule, description="管理定时任务")

    # Callbacks
    adapter_manager.on_callback_query("^sch_del_", handle_task_delete_callback)
    adapter_manager.on_callback_query("^schm_", handle_task_delete_callback)


async def list_tasks_command(
    ctx: UnifiedContext,
    *,
    include_menu_nav: bool = False,
):
    """处理 schedule 列表展示，显示带按钮的任务列表"""
    tasks = await get_all_active_tasks()

    if not tasks:
        # return {"text": "📭 当前没有活跃的定时任务。", "ui": {}}
        # Skill execute return expectation can be str or dict with text/ui
        # But here we are called by execute or cmd_tasks.
        # execute handles dict return nicely? execute implementation above returns directly.
        # Let's return dict format which is supported by unified_adapter for skills usually,
        # but check how cmd handles it.
        # The adapter generally handles str or dict.
        return {
            "text": "📭 当前没有活跃的定时任务。",
            "ui": _schedule_menu_ui() if include_menu_nav else {},
        }

    msg = "📋 **定时任务列表**\n\n"
    all_sorted = list(tasks)

    for t in all_sorted:
        msg += f"🕒 **ID: {t['id']}**\n"
        msg += f"   Cron: `{t['crontab']}`\n"
        msg += f"   Desc: `{t['instruction']}`\n"
        msg += f"   Push: {t.get('need_push', True)}\n\n"

    # Actions: Create delete buttons for own tasks (or all if admin?)
    # Assuming user can delete any task for now as per previous logic "trust SkillAgent"
    # But for UI clutter, maybe just first few or allow all.
    # Let's create actions for ALL tasks for now.

    actions = []
    temp_row = []
    for t in all_sorted:
        # Label: "❌ {id} {instruction[:5]}"
        instr_short = (
            t["instruction"][:8] + ".."
            if len(t["instruction"]) > 8
            else t["instruction"]
        )
        btn_text = f"❌ {t['id']} {instr_short}"
        btn_data = f"sch_del_{t['id']}"

        temp_row.append({"text": btn_text, "callback_data": btn_data})
        if len(temp_row) == 2:
            actions.append(temp_row)
            temp_row = []

    if temp_row:
        actions.append(temp_row)

    if include_menu_nav:
        actions.append(
            [
                {"text": "➕ 新建说明", "callback_data": make_callback(SCHEDULE_MENU_NS, "addhelp")},
                {"text": "🏠 返回首页", "callback_data": make_callback(SCHEDULE_MENU_NS, "home")},
            ]
        )

    return {"text": msg, "ui": {"actions": actions}}


async def show_delete_menu(
    ctx: UnifiedContext,
    *,
    include_menu_nav: bool = False,
):
    """显示删除菜单"""
    return await list_tasks_command(ctx, include_menu_nav=include_menu_nav)


async def handle_task_delete_callback(ctx: UnifiedContext):
    """处理删除按钮回调"""
    data = ctx.callback_data
    if not data:
        return

    action, _parts = parse_callback(data, SCHEDULE_MENU_NS)
    if action:
        await ctx.answer_callback()
        if action == "home":
            payload = await show_schedule_menu(ctx)
        elif action == "list":
            payload = await list_tasks_command(ctx, include_menu_nav=True)
        elif action == "delete":
            payload = await show_delete_menu(ctx, include_menu_nav=True)
        elif action == "addhelp":
            payload = _schedule_add_help_response()
        elif action == "help":
            payload = {
                "text": _schedule_usage_text(),
                "ui": {
                    "actions": [
                        [
                            {"text": "🏠 返回首页", "callback_data": make_callback(SCHEDULE_MENU_NS, "home")},
                            {"text": "📋 查看任务", "callback_data": make_callback(SCHEDULE_MENU_NS, "list")},
                        ]
                    ]
                },
            }
        else:
            payload = {"text": "❌ 未知操作。", "ui": _schedule_menu_ui()}
        await ctx.edit_message(ctx.message.id, payload["text"], ui=payload.get("ui"))
        return

    await ctx.answer_callback()

    try:
        task_id = int(data.replace("sch_del_", ""))
    except ValueError:
        return "❌ 无效的操作。"

    try:
        await delete_task(task_id)
        from core.scheduler import reload_scheduler_jobs

        await reload_scheduler_jobs()

        payload = await list_tasks_command(ctx, include_menu_nav=True)
        text = f"✅ 任务 {task_id} 已删除。\n\n{payload['text']}"
        await ctx.edit_message(ctx.message.id, text, ui=payload.get("ui"))
        return None
    except Exception as e:
        return f"❌ 删除失败: {e}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scheduler manager skill CLI bridge.",
    )
    add_common_arguments(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Create a scheduled task")
    add_parser.add_argument("--crontab", required=True, help="Cron expression")
    add_parser.add_argument(
        "--instruction",
        required=True,
        help="Instruction to run on schedule",
    )
    add_parser.add_argument(
        "--push",
        choices=("true", "false"),
        default="true",
        help="Whether to push task results",
    )

    subparsers.add_parser("list", help="List active tasks")

    delete_parser = subparsers.add_parser("delete", help="Delete a task")
    delete_parser.add_argument("task_id", help="Task id to delete")
    return parser


def _params_from_args(args: argparse.Namespace) -> dict:
    command = str(args.command or "").strip().lower()
    if command == "add":
        return merge_params(
            args,
            {
                "action": "add",
                "crontab": str(args.crontab or "").strip(),
                "instruction": str(args.instruction or "").strip(),
                "push": str(args.push or "true").strip().lower(),
            },
        )
    if command == "list":
        return merge_params(args, {"action": "list"})
    if command == "delete":
        return merge_params(
            args,
            {"action": "delete", "task_id": str(args.task_id or "").strip()},
        )
    raise SystemExit(f"unsupported command: {command}")


async def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return await run_execute_cli(execute, args=args, params=_params_from_args(args))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
