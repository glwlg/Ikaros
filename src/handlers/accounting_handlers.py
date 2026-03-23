import logging

from sqlalchemy import select

from core.accounting_store import get_active_book_id, set_active_book_id
from core.platform.models import UnifiedContext
from core.skill_menu import cache_items, get_cached_item, make_callback, parse_callback
from api.core.database import get_session_maker
from api.models.accounting import Book
from api.models.binding import PlatformUserBinding
from .base_handlers import (
    check_permission_unified,
    edit_callback_message,
    get_effective_user_id,
    require_feature_access,
)

logger = logging.getLogger(__name__)
ACCOUNTING_MENU_NS = "accu"


def _parse_subcommand(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "help", ""
    parts = raw.split(maxsplit=2)
    if not parts:
        return "help", ""
    if not parts[0].startswith("/acc"):
        return "help", ""
    if len(parts) == 1:
        return "info", ""
    cmd = parts[1].strip().lower()
    args = parts[2].strip() if len(parts) >= 3 else ""
    return cmd, args


def _accounting_usage_text() -> str:
    return (
        "📊 记账助手用法:\n\n"
        "`/acc info` - 查看当前记账账本和简要统计\n"
        "`/acc list` - 列出你名下的所有账本\n"
        "`/acc use <账本ID/名称>` - 切换默认记账账本\n"
        "`/acc record <文字/发图>` - 快捷记账支持\n"
        "`/acc help` - 帮助\n\n"
        "💡 Tip: 也可以直接发送带有消费信息的图片或文字，Bot会自动帮你记账。"
    )


def _accounting_menu_ui() -> dict:
    return {
        "actions": [
            [
                {"text": "📈 当前账本", "callback_data": make_callback(ACCOUNTING_MENU_NS, "info")},
                {"text": "📚 账本列表", "callback_data": make_callback(ACCOUNTING_MENU_NS, "list")},
            ],
            [
                {"text": "🧾 记账说明", "callback_data": make_callback(ACCOUNTING_MENU_NS, "record")},
                {"text": "ℹ️ 帮助", "callback_data": make_callback(ACCOUNTING_MENU_NS, "help")},
            ],
        ]
    }


async def _get_user_id_from_binding(platform: str, platform_user_id: str) -> int | None:
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(PlatformUserBinding).where(
            PlatformUserBinding.platform == platform,
            PlatformUserBinding.platform_user_id == platform_user_id,
        )
        binding = (await session.execute(stmt)).scalars().first()
        if binding:
            return binding.user_id
        return None


async def _list_books_for_user(user_id: int) -> list[Book]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(Book).where(Book.owner_id == user_id)
        return list((await session.execute(stmt)).scalars().all())


async def _resolve_bound_user_id(ctx: UnifiedContext) -> tuple[int | None, str, str]:
    platform = ctx.message.platform or "telegram"
    platform_user_id = get_effective_user_id(ctx)
    user_id = await _get_user_id_from_binding(platform, platform_user_id)
    return user_id, platform, platform_user_id


async def _build_accounting_info_payload(
    ctx: UnifiedContext,
    *,
    prefix: str = "",
) -> tuple[str, dict]:
    user_id, platform, platform_user_id = await _resolve_bound_user_id(ctx)
    if not user_id:
        return (
            f"❌ 您还未绑定网页端账号。请先绑定。您的 ID：`{platform_user_id}`, 平台：`{platform}`",
            _accounting_menu_ui(),
        )

    books = await _list_books_for_user(user_id)
    if not books:
        return ("❌ 您还未创建任何账本，请先在系统内创建一个账本。", _accounting_menu_ui())

    active_book_id = await get_active_book_id(user_id)
    book = next((b for b in books if b.id == active_book_id), None)
    if not book:
        book = books[0]
        await set_active_book_id(user_id, book.id)

    cache_items(
        ctx,
        ACCOUNTING_MENU_NS,
        "books",
        [{"id": int(item.id), "name": str(item.name)} for item in books],
    )

    lines: list[str] = []
    if prefix:
        lines.extend([prefix.strip(), ""])
    lines.extend(
        [
            "📈 记账助手",
            "",
            f"当前账本：**{book.name}**",
            f"账本 ID：`{book.id}`",
            f"账本总数：`{len(books)}`",
            "",
            "也支持直接发消费文字或截图，Bot 会自动尝试记账。",
        ]
    )
    return "\n".join(lines), _accounting_menu_ui()


async def _build_accounting_list_payload(
    ctx: UnifiedContext,
    *,
    prefix: str = "",
) -> tuple[str, dict]:
    user_id, platform, platform_user_id = await _resolve_bound_user_id(ctx)
    if not user_id:
        return (
            f"❌ 您还未绑定网页端账号。请先绑定。您的 ID：`{platform_user_id}`, 平台：`{platform}`",
            _accounting_menu_ui(),
        )

    books = await _list_books_for_user(user_id)
    if not books:
        return ("❌ 您还未创建任何账本，请先在系统内创建一个账本。", _accounting_menu_ui())

    active_book_id = await get_active_book_id(user_id)
    if active_book_id is None:
        active_book_id = books[0].id
        await set_active_book_id(user_id, books[0].id)

    payload_books = [{"id": int(item.id), "name": str(item.name)} for item in books]
    cache_items(ctx, ACCOUNTING_MENU_NS, "books", payload_books)

    lines: list[str] = []
    if prefix:
        lines.extend([prefix.strip(), ""])
    lines.append("📚 您的账本列表：")
    for item in payload_books:
        marker = "👉" if int(item["id"]) == int(active_book_id) else "  "
        lines.append(f"{marker} `{item['id']}` | **{item['name']}**")
    lines.append("")
    lines.append("点击按钮可直接切换账本。")

    actions: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for index, item in enumerate(payload_books):
        prefix_text = "✅ " if int(item["id"]) == int(active_book_id) else ""
        row.append(
            {
                "text": f"{prefix_text}{str(item['name'])[:14]}",
                "callback_data": make_callback(ACCOUNTING_MENU_NS, "use", index),
            }
        )
        if len(row) == 2:
            actions.append(row)
            row = []
    if row:
        actions.append(row)
    actions.append(
        [
            {"text": "📈 当前账本", "callback_data": make_callback(ACCOUNTING_MENU_NS, "info")},
            {"text": "ℹ️ 帮助", "callback_data": make_callback(ACCOUNTING_MENU_NS, "help")},
        ]
    )
    return "\n".join(lines), {"actions": actions}


async def _switch_book_payload(
    ctx: UnifiedContext,
    target: str,
) -> tuple[str, dict]:
    user_id, platform, platform_user_id = await _resolve_bound_user_id(ctx)
    if not user_id:
        return (
            f"❌ 您还未绑定网页端账号。请先绑定。您的 ID：`{platform_user_id}`, 平台：`{platform}`",
            _accounting_menu_ui(),
        )

    books = await _list_books_for_user(user_id)
    if not books:
        return ("❌ 您还未创建任何账本，请先在系统内创建一个账本。", _accounting_menu_ui())

    found_book = None
    if target.isdigit():
        found_book = next((b for b in books if b.id == int(target)), None)
    if not found_book:
        found_book = next((b for b in books if b.name == target), None)
    if not found_book:
        return (f"❌ 找不到名为或 ID 为 `{target}` 的账本。", _accounting_menu_ui())

    await set_active_book_id(user_id, found_book.id)
    return await _build_accounting_list_payload(
        ctx,
        prefix=f"✅ 当前记账账本已切换为：**{found_book.name}**",
    )


async def accounting_command(ctx: UnifiedContext) -> None:
    if not await check_permission_unified(ctx):
        return
    if not await require_feature_access(ctx, "accounting"):
        return

    text = ctx.message.text or ""

    sub, args = _parse_subcommand(text)

    if sub in {"help", "h", "?"}:
        await ctx.reply(_accounting_usage_text(), ui=_accounting_menu_ui())
        return

    if sub in {"info", "i"}:
        payload, ui = await _build_accounting_info_payload(ctx)
        await ctx.reply(payload, ui=ui)
        return

    if sub in {"list", "ls"}:
        payload, ui = await _build_accounting_list_payload(ctx)
        await ctx.reply(payload, ui=ui)
        return

    if sub == "use":
        target = args.strip()
        if not target:
            await ctx.reply("用法: `/acc use <账本ID或名称>`")
            return
        payload, ui = await _switch_book_payload(ctx, target)
        await ctx.reply(payload, ui=ui)
        return

    if sub == "record":
        # Using dispatch_tools directly via quick_accounting could be done here,
        # but the request itself is typically sent using normal interaction to trigger it.
        # Alternatively, let the orchestration handle it. Let's just encourage simple reply if empty.
        if not args:
            await ctx.reply("直接在后面输入信息即可，或发送带有收支金额的截图。")
        else:
            await ctx.reply(
                "提示: 此指令可以配合大模型智能截取参数。对于强制单步记录，请使用普通的语言描述。您甚至无需加 `/acc record`。"
            )
        return

    await ctx.reply(_accounting_usage_text(), ui=_accounting_menu_ui())


async def handle_accounting_callback(ctx: UnifiedContext) -> None:
    if not await require_feature_access(ctx, "accounting"):
        return
    data = ctx.callback_data
    if not data:
        return

    action, parts = parse_callback(data, ACCOUNTING_MENU_NS)
    if not action:
        return

    if action == "info":
        payload, ui = await _build_accounting_info_payload(ctx)
    elif action == "list":
        payload, ui = await _build_accounting_list_payload(ctx)
    elif action == "record":
        payload = (
            "🧾 **快捷记账说明**\n\n"
            "直接发送消费描述或票据截图即可，例如：\n"
            "• 午饭 32 元\n"
            "• 打车 18.5\n"
            "• 发送小票照片\n\n"
            "也可以用 `/acc record <文字>` 查看说明。"
        )
        ui = _accounting_menu_ui()
    elif action == "help":
        payload = _accounting_usage_text()
        ui = _accounting_menu_ui()
    elif action == "use":
        cached = get_cached_item(ctx, ACCOUNTING_MENU_NS, "books", parts[0] if parts else "")
        if not cached:
            payload, ui = await _build_accounting_list_payload(ctx, prefix="❌ 账本列表已过期，请重新选择。")
        else:
            payload, ui = await _switch_book_payload(ctx, str(cached.get("id") or ""))
    else:
        payload = _accounting_usage_text()
        ui = _accounting_menu_ui()

    await edit_callback_message(ctx, payload, ui=ui)
