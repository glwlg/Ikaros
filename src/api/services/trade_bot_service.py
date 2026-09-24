import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import User
from api.core.database import get_session_maker
from api.models.binding import PlatformUserBinding
from api.models.trade import TradeAccount, TradePosition
from api.services.trade_service import (
    deposit_cash,
    execute_buy_order,
    execute_sell_order,
    simulate_buy_order,
    withdraw_cash,
)
from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    fetch_stock_quotes,
    search_stock_by_name,
)
from extension.skills.learned.stock_watch.scripts.store import add_watchlist_stock


async def resolve_user_id(session: AsyncSession, platform: str, platform_uid: str) -> int | None:
    """从平台用户 ID 解析出系统 User ID"""
    stmt = select(PlatformUserBinding.user_id).where(
        PlatformUserBinding.platform == platform.lower().strip(),
        PlatformUserBinding.platform_user_id == str(platform_uid).strip(),
    )
    res = await session.execute(stmt)
    uid = res.scalar_one_or_none()
    if uid:
        return uid

    # 回落：若未绑定，返回系统活跃用户
    user_stmt = select(User.id).where(User.is_active == True).order_by(User.id).limit(1)  # noqa: E712
    res2 = await session.execute(user_stmt)
    return res2.scalar_one_or_none()


def parse_trade_instruction(text: str) -> dict[str, Any] | None:
    """
    解析交易意图与指令：
    支持自然语言与命令语法：
    - 在中信以 1.662 买入 40 手电网
    - 在招商以 15.0 买入 1000 股浦发银行
    - 卖出 500 股浦发银行 16.0
    - /stock buy 中信 600519 1650 100
    - /stock sell 招商 600000 15 500
    - /stock accounts / 账户资产 / 我的账户
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    # 1. 资产看板查询
    if re.search(r"^(?:/stock\s+)?(?:accounts?|assets?|账户|资产|持仓全景|资产看板)$", raw, re.I):
        return {"action": "accounts"}

    # 2. 结构化命令: /stock buy [account] <stock> <price> <qty/lots>
    cmd_match = re.match(
        r"^/stock\s+(buy|sell|加仓|买入|减仓|卖出)(?:\s+(\S+))?\s+(\S+)\s+([0-9.]+)\s+([0-9]+(?:手|股)?)$",
        raw,
        re.I,
    )
    if cmd_match:
        direction = "buy" if cmd_match.group(1).lower() in {"buy", "加仓", "买入"} else "sell"
        account_kw = cmd_match.group(2) or ""
        stock_kw = cmd_match.group(3)
        price = float(cmd_match.group(4))
        raw_qty = cmd_match.group(5)
        if raw_qty.endswith("手"):
            quantity = float(raw_qty[:-1]) * 100
        elif raw_qty.endswith("股"):
            quantity = float(raw_qty[:-1])
        else:
            quantity = float(raw_qty)
        return {
            "action": direction,
            "account_keyword": account_kw,
            "stock_keyword": stock_kw,
            "price": price,
            "quantity": quantity,
        }

    # 3. 自然语言模式：如“在[中信]以 1.662 买入 40 手电网”或“以 15.0 买入 1000股 浦发银行”
    nl_buy = re.search(
        r"(?:在\s*([\u4e00-\u9fa5A-Za-z0-9_-]+?)(?:证券|账户)?\s*)?(?:以\s*([0-9.]+)\s*(?:元)?\s*)?(?:买入|加仓|建仓)\s*([0-9]+(?:\.[0-9]+)?)\s*(手|股)?(?:的)?\s*([\u4e00-\u9fa5A-Za-z0-9]+)(?:\s*以\s*([0-9.]+))?",
        raw,
    )
    if nl_buy and ("买入" in raw or "加仓" in raw or "建仓" in raw):
        acc_kw = nl_buy.group(1) or ""
        p1 = nl_buy.group(2)
        p2 = nl_buy.group(6)
        price = float(p1 or p2 or 0.0)
        num = float(nl_buy.group(3))
        unit = nl_buy.group(4) or ""
        stock_kw = nl_buy.group(5)
        quantity = num * 100 if unit == "手" else num
        return {
            "action": "buy",
            "account_keyword": acc_kw,
            "stock_keyword": stock_kw,
            "price": price,
            "quantity": quantity,
        }

    # 4. 自然语言卖出：如“在[中信]以 16.5 卖出 20手 电网”
    nl_sell = re.search(
        r"(?:在\s*([\u4e00-\u9fa5A-Za-z0-9_-]+?)(?:证券|账户)?\s*)?(?:以\s*([0-9.]+)\s*(?:元)?\s*)?(?:卖出|减仓|平仓)\s*([0-9]+(?:\.[0-9]+)?)\s*(手|股)?(?:的)?\s*([\u4e00-\u9fa5A-Za-z0-9]+)(?:\s*以\s*([0-9.]+))?",
        raw,
    )
    if nl_sell and ("卖出" in raw or "减仓" in raw or "平仓" in raw):
        acc_kw = nl_sell.group(1) or ""
        p1 = nl_sell.group(2)
        p2 = nl_sell.group(6)
        price = float(p1 or p2 or 0.0)
        num = float(nl_sell.group(3))
        unit = nl_sell.group(4) or ""
        stock_kw = nl_sell.group(5)
        quantity = num * 100 if unit == "手" else num
        return {
            "action": "sell",
            "account_keyword": acc_kw,
            "stock_keyword": stock_kw,
            "price": price,
            "quantity": quantity,
        }

    # 5. 银证出入金指令：在[中信]转入/入金 10000元
    cf_match = re.search(
        r"(?:在\s*([\u4e00-\u9fa5A-Za-z0-9_-]+?)(?:证券|账户)?\s*)?(入金|转入|出金|转出|提现)\s*([0-9.]+)\s*(?:元)?",
        raw,
    )
    if cf_match:
        acc_kw = cf_match.group(1) or ""
        op = cf_match.group(2)
        amt = float(cf_match.group(3))
        flow_type = "deposit" if op in {"入金", "转入"} else "withdraw"
        return {
            "action": "cash_flow",
            "flow_type": flow_type,
            "account_keyword": acc_kw,
            "amount": amt,
        }

    return None


async def execute_bot_trade_action(
    platform: str,
    platform_uid: str,
    parsed: dict[str, Any],
) -> str:
    """处理并执行 Bot 端的交易与资产操作，返回面向用户的回复文本"""
    session_maker = get_session_maker()
    async with session_maker() as session:
        user_id = await resolve_user_id(session, platform, platform_uid)
        if not user_id:
            return "⚠️ 未找到已绑定的系统账号，请先在网页端绑定平台账号。"

        action = parsed.get("action")

        # 1. 资产全景看板
        if action == "accounts":
            stmt = select(TradeAccount).where(TradeAccount.user_id == user_id)
            accounts = (await session.execute(stmt)).scalars().all()
            if not accounts:
                return "💼 **交易资产概览**\n\n暂未创建任何交易账户，请先在网页端添加券商账户。"

            lines = ["💼 **多账户资产全景**\n"]
            total_cash = 0.0
            for acc in accounts:
                cash = float(acc.cash_balance)
                total_cash += cash
                # 查持仓数量
                pos_stmt = select(TradePosition).where(
                    TradePosition.account_id == acc.id, TradePosition.quantity > 0
                )
                positions = (await session.execute(pos_stmt)).scalars().all()
                lines.append(
                    f"• **{acc.name}** ({acc.broker})\n"
                    f"   可用现金：¥ {cash:,.2f} | 持仓标的：{len(positions)} 只\n"
                )
            lines.append(f"全局可用现金合计：**¥ {total_cash:,.2f}**")
            return "\n".join(lines)

        # 2. 匹配账户
        acc_kw = str(parsed.get("account_keyword") or "").strip().lower()
        acc_stmt = select(TradeAccount).where(TradeAccount.user_id == user_id)
        all_accounts = (await session.execute(acc_stmt)).scalars().all()
        if not all_accounts:
            return "⚠️ 尚未创建任何交易账户，请先在网页端添加账户。"

        target_acc = None
        if acc_kw:
            for a in all_accounts:
                if acc_kw in a.name.lower() or acc_kw in a.broker.lower():
                    target_acc = a
                    break
            if not target_acc:
                names = "、".join(a.name for a in all_accounts)
                return f"⚠️ 未找到匹配的账户「{acc_kw}」，当前可用账户：{names}"
        else:
            if len(all_accounts) == 1:
                target_acc = all_accounts[0]
            else:
                names = "、".join(a.name for a in all_accounts)
                return f"⚠️ 您拥有多个交易账户，请指明账户名称（如「在中信买入...」）。当前账户：{names}"

        # 3. 银证出入金
        if action == "cash_flow":
            flow_type = parsed.get("flow_type")
            amount = float(parsed.get("amount") or 0)
            try:
                if flow_type == "deposit":
                    await deposit_cash(session, target_acc.id, amount, notes="Bot 快捷入金")
                    await session.commit()
                    return (
                        f"✅ **银证转入成功**\n\n"
                        f"账户：{target_acc.name}\n"
                        f"转入金额：¥ {amount:,.2f}\n"
                        f"最新可用现金：**¥ {float(target_acc.cash_balance):,.2f}**"
                    )
                else:
                    await withdraw_cash(session, target_acc.id, amount, notes="Bot 快捷出金")
                    await session.commit()
                    return (
                        f"✅ **银证转出成功**\n\n"
                        f"账户：{target_acc.name}\n"
                        f"转出金额：¥ {amount:,.2f}\n"
                        f"最新可用现金：**¥ {float(target_acc.cash_balance):,.2f}**"
                    )
            except ValueError as exc:
                return f"⚠️ 操作失败：{exc}"

        # 4. 买入或卖出记账
        stock_kw = str(parsed.get("stock_keyword") or "").strip()
        price = float(parsed.get("price") or 0.0)
        quantity = float(parsed.get("quantity") or 0.0)

        # 补全股票行情与代码
        stock_code = stock_kw
        stock_name = stock_kw
        if not re.match(r"^(?:sh|sz|bj)?[0-9]{6}$", stock_kw, re.I):
            candidates = await search_stock_by_name(stock_kw)
            if not candidates:
                return f"⚠️ 未能识别股票标的「{stock_kw}」，请提供有效代码或全称。"
            stock_code = candidates[0]["code"]
            stock_name = candidates[0]["name"]

        # 若未指定价格，拉取当前最新市价
        if price <= 0:
            quotes = await fetch_stock_quotes([stock_code])
            if quotes and quotes[0].get("price"):
                price = float(quotes[0]["price"])
            else:
                return f"⚠️ 无法自动获取 **{stock_name}** 最新行情价格，请手动指定成交单价（如「以 12.5 买入...」）。"

        if action == "buy":
            try:
                order = await execute_buy_order(
                    session=session,
                    account_id=target_acc.id,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=price,
                    quantity=quantity,
                    notes="Bot 快捷买入记账",
                )
                await session.commit()
                # 同步加入全局自选池
                try:
                    await add_watchlist_stock(platform_uid, stock_code, stock_name, platform=platform)
                except Exception:
                    pass

                lots = int(quantity // 100)
                return (
                    f"✅ **买入交割已记账**\n\n"
                    f"标的：**{stock_name}** ({stock_code})\n"
                    f"归属账户：{target_acc.name}\n"
                    f"成交价：¥ {price:.3f}\n"
                    f"成交量：{quantity:g} 股 ({lots} 手)\n"
                    f"扣除手续费：¥ {float(order.total_fee):.2f}\n"
                    f"实际扣款：¥ {float(order.net_amount):,.2f}\n"
                    f"最新摊薄成本价：**¥ {float(order.cost_price_after):.4f}**\n"
                    f"账户剩余可用现金：**¥ {float(target_acc.cash_balance):,.2f}**"
                )
            except ValueError as exc:
                return f"⚠️ 买入记账被拦截：{exc}"

        elif action == "sell":
            try:
                order = await execute_sell_order(
                    session=session,
                    account_id=target_acc.id,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=price,
                    quantity=quantity,
                    notes="Bot 快捷卖出记账",
                )
                await session.commit()
                lots = int(quantity // 100)
                pnl_str = f"+{float(order.realized_pnl):.2f}" if float(order.realized_pnl) >= 0 else f"{float(order.realized_pnl):.2f}"
                return (
                    f"✅ **卖出交割已记账**\n\n"
                    f"标的：**{stock_name}** ({stock_code})\n"
                    f"归属账户：{target_acc.name}\n"
                    f"成交价：¥ {price:.3f}\n"
                    f"卖出量：{quantity:g} 股 ({lots} 手)\n"
                    f"扣除手续费：¥ {float(order.total_fee):.2f}\n"
                    f"回款金额：¥ {float(order.net_amount):,.2f}\n"
                    f"本次已实现盈亏：**{pnl_str} 元**\n"
                    f"剩余持仓量：{float(order.holding_after):g} 股\n"
                    f"账户最新可用现金：**¥ {float(target_acc.cash_balance):,.2f}**"
                )
            except ValueError as exc:
                return f"⚠️ 卖出记账被拦截：{exc}"

        return "⚠️ 无法识别该交易操作。"
