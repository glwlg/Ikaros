from __future__ import annotations

from typing import Any

from core.config import is_user_admin
from core.platform.registry import adapter_manager


def _usage_text() -> str:
    return (
        "用法:\n"
        "`/wxbind qr` - 生成新的微信绑定二维码\n"
        "`/wxbind list` - 查看已绑定微信用户\n"
        "`/wxbind help` - 查看帮助"
    )


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_subcommand(text: str) -> str:
    raw = _safe_text(text)
    if not raw:
        return "help"
    parts = raw.split(maxsplit=2)
    if not parts or not parts[0].startswith("/wxbind"):
        return "help"
    if len(parts) == 1:
        return "help"
    return _safe_text(parts[1]).lower() or "help"


async def weixin_bind_command(ctx) -> None:
    user = getattr(getattr(ctx, "message", None), "user", None)
    user_id = _safe_text(getattr(user, "id", ""))
    if not is_user_admin(user_id):
        await ctx.reply("⛔ 仅管理员可使用 `/wxbind`。")
        return

    adapter = adapter_manager.get_adapter("weixin")
    if adapter is None:
        await ctx.reply("⛔ 微信适配器未启用，无法使用 `/wxbind`。")
        return

    message = getattr(ctx, "message", None)
    action = _parse_subcommand(getattr(message, "text", ""))
    if action in {"help", "h", "?"}:
        await ctx.reply(_usage_text())
        return

    if action == "list":
        rows = adapter.list_bound_users()
        if not rows:
            await ctx.reply("当前没有已记录的微信绑定用户。")
            return
        lines = ["已绑定微信用户：", ""]
        for item in rows:
            lines.append(
                f"- `{item.get('user_id')}` | {item.get('status') or 'active'} | "
                f"bot={item.get('account_id') or '-'} | "
                f"{item.get('source') or '-'} | {item.get('bound_at') or '-'}"
            )
        await ctx.reply("\n".join(lines))
        return

    if action == "qr":
        requester_platform = _safe_text(getattr(message, "platform", "")).lower()
        requester_chat_id = _safe_text(getattr(getattr(message, "chat", None), "id", ""))
        requester_account_id = _safe_text(
            ((getattr(message, "raw_data", None) or {}).get("to_user_id") or "")
        )
        payload = await adapter.start_additional_binding(
            requester_user_id=user_id,
            requester_account_id=requester_account_id,
            notification_platform=requester_platform,
            notification_chat_id=requester_chat_id or user_id,
        )
        qr_content = _safe_text(payload.get("qr_content") or payload.get("qr_url"))
        caption = (
            "请让对方扫码完成微信绑定。\n"
            "扫码成功后，我会自动把该微信加入 allow-list，并回消息通知你。"
        )
        if not qr_content:
            await ctx.reply("❌ 未能生成二维码，请稍后重试。")
            return

        qr_png = b""
        render_qr_png = getattr(adapter, "render_qr_png", None)
        if callable(render_qr_png):
            qr_png = bytes(render_qr_png(qr_content) or b"")

        if qr_png:
            try:
                await ctx.reply_photo(
                    qr_png,
                    caption=caption,
                    filename="weixin-bind-qr.png",
                )
                return
            except Exception:
                pass
        await ctx.reply(f"{caption}\n\n二维码链接：{qr_content}")
        return

    await ctx.reply(_usage_text())
