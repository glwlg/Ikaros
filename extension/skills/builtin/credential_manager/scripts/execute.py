from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.platform.models import UnifiedContext
from core.skill_menu import cache_items, get_cached_item, make_callback, parse_callback
from core.skill_cli import (
    add_common_arguments,
    merge_params,
    prepare_default_env,
    run_execute_cli,
)

prepare_default_env(REPO_ROOT)

from extension.skills.builtin.credential_manager.scripts.store import (
    add_credential,
    delete_credential,
    get_credential,
    list_credentials,
)

try:
    import pyotp
except ImportError:
    pyotp = None


CREDENTIAL_MENU_NS = "credm"


async def execute(ctx: UnifiedContext, params: dict, runtime=None) -> dict:
    """执行凭据管理"""
    action = params.get("action", "list")
    service = params.get("service", "").lower().strip()
    data_raw = params.get("data", "")

    # Intelligence: If only service is provided and action is default/unknown, assume 'get'
    # But intent router usually sets action.
    # If using regex skill trigger: "凭据 github" -> action='default'? Need better extraction.
    # Assuming params extraction works well or we fallback.

    user_id = ctx.message.user.id

    if action in ["list", "list_all"]:
        credentials = await list_credentials(user_id)
        if not credentials:
            return {"text": "📭 您还没有保存任何凭据。"}

        msg = "📋 **已保存的凭据**：\n\n"
        for credential in credentials:
            msg += f"• `{credential}`\n"
        msg += "\n发送 `/credential <名称>` 查看详情。"
        # In a real app we might return markup buttons here
        return {"text": msg}

    if action == "get":
        if not service:
            # Try to guess service from data or leftovers
            # But for strictness:
            return {"text": "❌ 请指定要查看的服务名称 (例如: /credential github)"}

        credential = await get_credential(user_id, service)
        if not credential:
            return {"text": f"❌ 未找到服务 `{service}` 的凭据信息。"}

        # Format output
        msg = f"🔐 **{service}**\n\n"
        mfa_code = ""

        for k, v in credential.items():
            if k == "mfa_secret":
                # Generate TOTP if pyotp is available
                if pyotp and v:
                    try:
                        totp = pyotp.TOTP(v.replace(" ", ""))
                        mfa_code = totp.now()
                        msg += f"**MFA Code**: `{mfa_code}` (有效期 30s)\n"
                    except Exception as e:
                        msg += f"**MFA Secret**: `{v}` (生成失败: {e})\n"
                else:
                    msg += f"**{k}**: `{v}`\n"
            else:
                msg += f"**{k}**: `{v}`\n"

        # Auto-copyable version for MFA
        if mfa_code:
            msg += f"\n点击复制 MFA: `{mfa_code}`"

        return {"text": msg}

    if action == "add":
        if not service:
            return {"text": "❌ 请指定服务名称 (service=xxx)"}
        if not data_raw:
            return {"text": "❌ 请提供凭据数据 (data=... 或 key=value)"}

        # Parse data
        # Support JSON or key=value string
        import json

        parsed_data = {}
        try:
            parsed_data = json.loads(data_raw)
        except Exception:
            # Try key=value parsing
            pairs = data_raw.split()
            for p in pairs:
                if "=" in p:
                    k, v = p.split("=", 1)
                    parsed_data[k] = v
                else:
                    # Treat as raw note?
                    parsed_data["note"] = data_raw
                    break

        if not parsed_data:
            return {"text": "❌ 数据格式无法解析，请使用 key=value 格式。"}

        success = await add_credential(user_id, service, parsed_data)
        if success:
            return {"text": f"✅ 凭据 `{service}` 已保存。"}
        else:
            return {"text": "❌ 保存失败。"}

    if action == "remove":
        if not service:
            return {"text": "❌ 请指定要删除的服务名称。"}

        success = await delete_credential(user_id, service)
        if success:
            return {"text": f"🗑️ 凭据 `{service}` 已删除。"}
        else:
            return {"text": "❌ 删除失败。"}

    return {"text": f"❌ 未知操作: {action}"}


def _parse_credential_subcommand(text: str) -> tuple[str, str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "menu", "", ""

    parts = raw.split(maxsplit=3)
    if not parts or not parts[0].startswith("/credential"):
        return "help", "", ""
    if len(parts) == 1:
        return "menu", "", ""

    sub = str(parts[1] or "").strip().lower()
    if sub in {"menu", "home", "start"}:
        return "menu", "", ""
    if sub in {"help", "h", "?"}:
        return "help", "", ""
    if sub in {"list", "ls", "show"}:
        return "list", "", ""
    if sub in {"get", "view"}:
        return "get", str(parts[2] if len(parts) >= 3 else "").strip(), ""
    if sub in {"remove", "rm", "del", "delete"}:
        return "remove", str(parts[2] if len(parts) >= 3 else "").strip(), ""
    if sub in {"add", "set", "save"}:
        return (
            "add",
            str(parts[2] if len(parts) >= 3 else "").strip(),
            str(parts[3] if len(parts) >= 4 else "").strip(),
        )
    return "get", str(parts[1] or "").strip(), ""


def _credential_usage_text() -> str:
    return (
        "用法:\n"
        "`/credential`\n"
        "`/credential list`\n"
        "`/credential <service>`\n"
        "`/credential get <service>`\n"
        "`/credential add <service> <key=value ...>`\n"
        "`/credential remove <service>`"
    )


def _credential_menu_ui() -> dict:
    return {
        "actions": [
            [
                {"text": "📋 凭据列表", "callback_data": make_callback(CREDENTIAL_MENU_NS, "list")},
                {"text": "➕ 添加说明", "callback_data": make_callback(CREDENTIAL_MENU_NS, "addhelp")},
            ],
            [
                {"text": "ℹ️ 帮助", "callback_data": make_callback(CREDENTIAL_MENU_NS, "help")},
            ],
        ]
    }


async def show_credential_menu(ctx: UnifiedContext) -> dict:
    credentials = await list_credentials(ctx.message.user.id)
    cache_items(ctx, CREDENTIAL_MENU_NS, "services", credentials)
    preview = "、".join(
        str(item or "").strip() for item in credentials[:4] if str(item or "").strip()
    )
    if len(credentials) > 4:
        preview += " 等"
    if not preview:
        preview = "暂无已保存凭据"
    return {
        "text": (
            "🔐 **凭据管理**\n\n"
            f"已保存凭据：{len(credentials)}\n"
            f"当前列表：{preview}\n\n"
            "查看详情可直接发 `/credential <service>`。"
        ),
        "ui": _credential_menu_ui(),
    }


def _credential_add_help_response() -> dict:
    return {
        "text": (
            "➕ **添加凭据**\n\n"
            "直接发送：\n"
            "• `/credential add github username=alice token=xxx`\n"
            "• `/credential add google {\"username\":\"alice\",\"password\":\"secret\"}`\n\n"
            "支持 JSON 和空格分隔的 `key=value`。"
        ),
        "ui": {
            "actions": [
                [
                    {"text": "🏠 返回首页", "callback_data": make_callback(CREDENTIAL_MENU_NS, "home")},
                    {"text": "📋 凭据列表", "callback_data": make_callback(CREDENTIAL_MENU_NS, "list")},
                ]
            ]
        },
    }


async def _build_credential_list_response(ctx: UnifiedContext) -> dict:
    credentials = await list_credentials(ctx.message.user.id)
    cache_items(ctx, CREDENTIAL_MENU_NS, "services", credentials)
    if not credentials:
        return {"text": "📭 您还没有保存任何凭据。", "ui": _credential_menu_ui()}

    lines = ["📋 **已保存的凭据**：", ""]
    for index, service in enumerate(credentials, start=1):
        lines.append(f"{index}. `{service}`")
    lines.append("")
    lines.append("点按钮查看详情，或直接发 `/credential <service>`。")

    actions = []
    row = []
    for index, service in enumerate(credentials):
        row.append(
            {
                "text": str(service)[:18],
                "callback_data": make_callback(CREDENTIAL_MENU_NS, "show", index),
            }
        )
        if len(row) == 2:
            actions.append(row)
            row = []
    if row:
        actions.append(row)
    actions.append(
        [
            {"text": "➕ 添加说明", "callback_data": make_callback(CREDENTIAL_MENU_NS, "addhelp")},
            {"text": "🏠 返回首页", "callback_data": make_callback(CREDENTIAL_MENU_NS, "home")},
        ]
    )
    return {"text": "\n".join(lines), "ui": {"actions": actions}}


async def _build_credential_detail_response(
    ctx: UnifiedContext,
    service_index: str | int | None,
) -> dict:
    service = get_cached_item(ctx, CREDENTIAL_MENU_NS, "services", service_index)
    if service is None:
        credentials = await list_credentials(ctx.message.user.id)
        cache_items(ctx, CREDENTIAL_MENU_NS, "services", credentials)
        service = get_cached_item(ctx, CREDENTIAL_MENU_NS, "services", service_index)
    if service is None:
        return {"text": "❌ 凭据缓存已过期，请返回列表重试。", "ui": _credential_menu_ui()}

    payload = await execute(
        ctx,
        {
            "action": "get",
            "service": str(service),
        },
    )
    ui = {
        "actions": [
            [
                {"text": "🗑️ 删除凭据", "callback_data": make_callback(CREDENTIAL_MENU_NS, "confirmdel", service_index)},
            ],
            [
                {"text": "📋 返回列表", "callback_data": make_callback(CREDENTIAL_MENU_NS, "list")},
                {"text": "🏠 返回首页", "callback_data": make_callback(CREDENTIAL_MENU_NS, "home")},
            ],
        ]
    }
    return {"text": payload.get("text", "❌ 获取凭据失败。"), "ui": ui}


async def handle_credential_menu_callback(ctx: UnifiedContext):
    data = ctx.callback_data
    if not data:
        return

    action, parts = parse_callback(data, CREDENTIAL_MENU_NS)
    if not action:
        return

    await ctx.answer_callback()
    arg = parts[0] if parts else ""

    if action == "home":
        payload = await show_credential_menu(ctx)
    elif action == "list":
        payload = await _build_credential_list_response(ctx)
    elif action == "addhelp":
        payload = _credential_add_help_response()
    elif action == "help":
        payload = {
            "text": _credential_usage_text(),
            "ui": {
                "actions": [
                    [
                        {"text": "🏠 返回首页", "callback_data": make_callback(CREDENTIAL_MENU_NS, "home")},
                        {"text": "📋 凭据列表", "callback_data": make_callback(CREDENTIAL_MENU_NS, "list")},
                    ]
                ]
            },
        }
    elif action == "show":
        payload = await _build_credential_detail_response(ctx, arg)
    elif action == "confirmdel":
        service = get_cached_item(ctx, CREDENTIAL_MENU_NS, "services", arg)
        if service is None:
            payload = await _build_credential_list_response(ctx)
        else:
            payload = {
                "text": f"⚠️ 确认删除凭据 `{service}`？",
                "ui": {
                    "actions": [
                        [
                            {"text": "🗑️ 确认删除", "callback_data": make_callback(CREDENTIAL_MENU_NS, "del", arg)},
                            {"text": "↩️ 返回详情", "callback_data": make_callback(CREDENTIAL_MENU_NS, "show", arg)},
                        ]
                    ]
                },
            }
    elif action == "del":
        service = get_cached_item(ctx, CREDENTIAL_MENU_NS, "services", arg)
        if service is None:
            payload = await _build_credential_list_response(ctx)
        else:
            delete_payload = await execute(
                ctx,
                {
                    "action": "remove",
                    "service": str(service),
                },
            )
            list_payload = await _build_credential_list_response(ctx)
            payload = {
                "text": f"{delete_payload.get('text', '❌ 删除失败。')}\n\n{list_payload['text']}",
                "ui": list_payload.get("ui", {}),
            }
    else:
        payload = {"text": "❌ 未知操作。", "ui": _credential_menu_ui()}

    await ctx.edit_message(ctx.message.id, payload["text"], ui=payload.get("ui"))


def register_handlers(adapter_manager):
    from core.config import is_user_allowed

    async def cmd_credential(ctx):
        if not await is_user_allowed(ctx.message.user.id):
            return

        action, service, data = _parse_credential_subcommand(ctx.message.text or "")
        if action == "menu":
            return await show_credential_menu(ctx)
        if action == "list":
            return await _build_credential_list_response(ctx)
        if action == "get":
            if not service:
                return {"text": "用法: `/credential <service>`", "ui": _credential_menu_ui()}
            return await execute(ctx, {"action": "get", "service": service})
        if action == "add":
            if not service or not data:
                return _credential_add_help_response()
            return await execute(ctx, {"action": "add", "service": service, "data": data})
        if action == "remove":
            if not service:
                return {"text": "用法: `/credential remove <service>`", "ui": _credential_menu_ui()}
            return await execute(ctx, {"action": "remove", "service": service})
        return {"text": _credential_usage_text(), "ui": _credential_menu_ui()}

    adapter_manager.on_command("credential", cmd_credential, description="第三方账号凭据管理")
    adapter_manager.on_callback_query("^credm_", handle_credential_menu_callback)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Credential manager skill CLI bridge.",
    )
    add_common_arguments(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List saved credentials")

    get_parser = subparsers.add_parser("get", help="Show credential details")
    get_parser.add_argument("service", help="Service name")

    add_parser = subparsers.add_parser("add", help="Add or update a credential")
    add_parser.add_argument("service", help="Service name")
    add_parser.add_argument(
        "--data",
        required=True,
        help="JSON string or key=value pairs separated by spaces",
    )

    remove_parser = subparsers.add_parser("remove", help="Delete a credential")
    remove_parser.add_argument("service", help="Service name")
    return parser


def _params_from_args(args: argparse.Namespace) -> dict:
    command = str(args.command or "").strip().lower()
    if command == "list":
        return merge_params(args, {"action": "list"})
    if command == "get":
        return merge_params(
            args,
            {"action": "get", "service": str(args.service or "").strip()},
        )
    if command == "add":
        return merge_params(
            args,
            {
                "action": "add",
                "service": str(args.service or "").strip(),
                "data": str(args.data or "").strip(),
            },
        )
    if command == "remove":
        return merge_params(
            args,
            {"action": "remove", "service": str(args.service or "").strip()},
        )
    raise SystemExit(f"unsupported command: {command}")


async def _run() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return await run_execute_cli(execute, args=args, params=_params_from_args(args))


from core.extension_base import SkillExtension


class CredentialManagerSkillExtension(SkillExtension):
    name = "credential_manager_extension"
    skill_name = "credential_manager"

    def register(self, runtime) -> None:
        register_handlers(runtime.adapter_manager)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
