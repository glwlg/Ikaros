from __future__ import annotations

from core.config import is_user_admin
from core.platform.models import UnifiedContext
from core.platform.registry import adapter_manager


def _parse_subcommand(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "help", ""
    parts = raw.split(maxsplit=2)
    if not parts or not parts[0].startswith("/wxbind"):
        return "help", ""
    if len(parts) == 1:
        return "help", ""
    sub = str(parts[1] or "").strip().lower()
    args = str(parts[2] if len(parts) >= 3 else "").strip()
    return sub, args


def _usage_text() -> str:
    return (
        "用法:\n"
        "`/wxbind qr` - 生成新的微信绑定二维码\n"
        "`/wxbind list` - 查看已绑定微信用户\n"
        "`/wxbind help` - 查看帮助"
    )


async def weixin_bind_command(ctx: UnifiedContext) -> None:
    user_id = str(ctx.message.user.id or "").strip()
    if not is_user_admin(user_id):
        await ctx.reply("⛔ 仅管理员可使用 `/wxbind`。")
        return

    try:
        adapter = adapter_manager.get_adapter("weixin")
    except Exception:
        await ctx.reply("⛔ 微信适配器未启用，无法使用 `/wxbind`。")
        return

    sub, _args = _parse_subcommand(ctx.message.text or "")
    if sub in {"help", "h", "?"}:
        await ctx.reply(_usage_text())
        return

    if sub == "list":
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

    if sub == "qr":
        requester_platform = str(getattr(ctx.message, "platform", "") or "").strip().lower()
        requester_chat_id = str(getattr(getattr(ctx.message, "chat", None), "id", "") or "").strip()
        requester_account_id = str(
            ((getattr(ctx.message, "raw_data", None) or {}).get("to_user_id") or "")
        ).strip()
        payload = await adapter.start_additional_binding(
            requester_user_id=user_id,
            requester_account_id=requester_account_id,
            notification_platform=requester_platform,
            notification_chat_id=requester_chat_id or user_id,
        )
        qr_content = str(
            payload.get("qr_content") or payload.get("qr_url") or ""
        ).strip()
        caption = (
            "请让对方扫码完成微信绑定。\n"
            "扫码成功后，我会自动把该微信加入 allow-list，并回消息通知你。"
        )
        if qr_content:
            qr_png = b""
            render_qr_png = getattr(adapter, "render_qr_png", None)
            if callable(render_qr_png):
                qr_png = bytes(render_qr_png(qr_content) or b"")
            try:
                if qr_png:
                    await ctx.reply_photo(
                        qr_png,
                        caption=caption,
                        filename="weixin-bind-qr.png",
                    )
                else:
                    raise ValueError("qr_png_empty")
            except Exception:
                await ctx.reply(f"{caption}\n\n二维码链接：{qr_content}")
            return
        await ctx.reply("❌ 未能生成二维码，请稍后重试。")
        return

    await ctx.reply(_usage_text())
