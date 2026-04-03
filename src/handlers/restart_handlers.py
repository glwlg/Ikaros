from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from core.app_paths import data_dir, project_root
from core.config import is_user_admin
from core.platform.models import UnifiedContext

from .base_handlers import check_permission_unified

logger = logging.getLogger(__name__)
_RESTART_LOG_FILE = "restart-command.out.log"


def _parse_subcommand(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "run", "all"
    parts = raw.split(maxsplit=1)
    if not parts or not parts[0].startswith("/restart"):
        return "run", "all"
    if len(parts) == 1:
        return "run", "all"

    arg = parts[1].strip().lower()
    if arg in {"help", "-h", "--help", "h", "?"}:
        return "help", ""
    if arg == "status":
        return "status", ""
    if arg in {"all", "*"}:
        return "run", "all"
    if arg in {"ikaros", "core"}:
        return "run", "ikaros"
    if arg in {"api", "ikaros-api"}:
        return "run", "api"
    return "help", ""


def _restart_usage_text() -> str:
    return (
        "用法:\n"
        "`/restart`\n"
        "`/restart all`\n"
        "`/restart ikaros`\n"
        "`/restart api`\n"
        "`/restart status`\n"
        "`/restart help`\n\n"
        "说明:\n"
        "- 默认重启 `ikaros-api` 后再重启 `ikaros`\n"
        "- 脚本会优先识别 `systemd/launchd`，识别不到时按 `nohup` 处理\n"
        "- 如包含 `ikaros`，当前会话可能短暂中断"
    )


def _restart_script_path() -> Path:
    return (project_root() / "scripts" / "restart_services.sh").resolve()


def _restart_log_path() -> Path:
    return (data_dir() / "logs" / _RESTART_LOG_FILE).resolve()


def _project_cwd() -> str:
    return str(project_root())


def _trim_output(text: str, limit: int = 3000) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


async def _collect_restart_status(script_path: Path) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "bash",
        str(script_path),
        "status",
        cwd=_project_cwd(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    text = output.decode("utf-8", errors="replace").strip()
    return int(process.returncode or 0), text


def _spawn_restart(script_path: Path, target: str, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            ["bash", str(script_path), target],
            cwd=_project_cwd(),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    return int(process.pid)


def _target_label(target: str) -> str:
    if target == "api":
        return "ikaros-api"
    if target == "ikaros":
        return "ikaros"
    return "ikaros-api + ikaros"


async def restart_command(ctx: UnifiedContext) -> None:
    """管理员重启入口: /restart [all|ikaros|api|status|help]"""
    if not await check_permission_unified(ctx):
        return
    if not is_user_admin(ctx.message.user.id):
        await ctx.reply("❌ 只有管理员可以执行此操作")
        return

    action, target = _parse_subcommand(ctx.message.text or "")
    if action == "help":
        await ctx.reply(_restart_usage_text())
        return

    script_path = _restart_script_path()
    if not script_path.exists():
        await ctx.reply(f"❌ 重启脚本不存在：`{script_path}`")
        return

    if action == "status":
        try:
            returncode, output = await _collect_restart_status(script_path)
        except Exception as exc:
            logger.error("Failed to read restart status: %s", exc, exc_info=True)
            await ctx.reply(f"❌ 获取重启状态失败：`{exc}`")
            return

        prefix = "✅ Restart 状态" if returncode == 0 else "❌ Restart 状态"
        safe_output = _trim_output(output or "未返回任何状态信息。")
        await ctx.reply(f"{prefix}\n\n```\n{safe_output}\n```")
        return

    log_path = _restart_log_path()
    try:
        pid = _spawn_restart(script_path, target, log_path)
    except Exception as exc:
        logger.error("Failed to spawn restart script: %s", exc, exc_info=True)
        await ctx.reply(f"❌ 触发重启失败：`{exc}`")
        return

    lines = [
        f"🔄 已触发重启：`{_target_label(target)}`",
        "",
        f"- 后台进程 PID：`{pid}`",
        f"- 脚本：`{script_path}`",
        f"- 日志：`{log_path}`",
    ]
    if target != "api":
        lines.extend(
            [
                "",
                "如果本次包含 `ikaros`，当前会话可能在几十秒内短暂中断。",
            ]
        )
    await ctx.reply("\n".join(lines))
