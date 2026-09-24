import logging
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.accounting import Account, Record
from api.models.trade import TradeAccount, TradePosition
from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    fetch_stock_quotes,
)

logger = logging.getLogger(__name__)


async def calculate_current_account_balance(
    session: AsyncSession, account_id: int, initial_balance: float
) -> float:
    """计算记账账户当前的实际余额（初始余额 + 历史收支及转账净额）"""
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Record.type == "收入", Record.amount),
                        (Record.type == "支出", -Record.amount),
                        (
                            Record.type == "转账",
                            case(
                                (Record.target_account_id == account_id, Record.amount),
                                (Record.account_id == account_id, -Record.amount),
                                else_=literal(0),
                            ),
                        ),
                        else_=literal(0),
                    )
                ),
                literal(0),
            )
        ).where(
            or_(
                Record.account_id == account_id,
                Record.target_account_id == account_id,
            )
        )
    )
    net_sum = float(result.scalar() or 0.0)
    return round(initial_balance + net_sum, 2)


async def get_trade_account_total_assets(
    session: AsyncSession, trade_account_id: int
) -> tuple[float, str]:
    """获取股票账户最新总资产（可用现金 + 持仓市值）"""
    trade_acc = await session.get(TradeAccount, trade_account_id)
    if not trade_acc:
        raise ValueError(f"关联的股票交易账户不存在 (id={trade_account_id})")

    cash = float(trade_acc.cash_balance)
    stmt = select(TradePosition).where(
        TradePosition.account_id == trade_account_id, TradePosition.quantity > 0
    )
    positions = (await session.execute(stmt)).scalars().all()

    if not positions:
        return round(cash, 2), trade_acc.name

    codes = [p.stock_code for p in positions]
    quotes_map: dict[str, dict] = {}
    try:
        quotes = await fetch_stock_quotes(codes)
        for q in quotes:
            quotes_map[q["code"]] = q
    except Exception as exc:
        logger.warning("获取对齐行情失败: %s", exc)

    market_val = 0.0
    for p in positions:
        q = quotes_map.get(p.stock_code, {})
        cur_price = float(q.get("price") or 0.0)
        price = cur_price if cur_price > 0 else float(p.cost_price)
        market_val += float(p.quantity) * price

    total_assets = round(cash + market_val, 2)
    return total_assets, trade_acc.name


async def sync_account_with_trade_assets(
    session: AsyncSession,
    account_id: int,
    creator_id: int,
) -> dict[str, Any]:
    """
    将记账账户与关联的股票账户资金对齐：
    - 计算股票账户总资产与记账账户当前余额的差额
    - 若有差额，新增一笔收入（增值）或支出（亏损）记录
    - 不修改历史记录，保持资产走势连续
    """
    acc = await session.get(Account, account_id)
    if not acc:
        raise ValueError(f"记账账户不存在 (id={account_id})")
    if not acc.trade_account_id:
        raise ValueError(f"记账账户「{acc.name}」尚未关联任何股票交易账户")

    target_assets, trade_name = await get_trade_account_total_assets(
        session, acc.trade_account_id
    )
    current_balance = await calculate_current_account_balance(
        session, acc.id, float(acc.balance)
    )
    diff = round(target_assets - current_balance, 2)

    record = None
    now = datetime.now(timezone.utc)
    if diff > 0.01:
        record = Record(
            book_id=acc.book_id,
            type="收入",
            amount=diff,
            account_id=acc.id,
            target_account_id=None,
            category_id=None,
            record_time=now,
            payee="",
            remark=f"股票收盘自动对齐收益：{trade_name}",
            exclude_from_budget=True,
            creator_id=creator_id,
        )
        session.add(record)
        await session.flush()
    elif diff < -0.01:
        record = Record(
            book_id=acc.book_id,
            type="支出",
            amount=abs(diff),
            account_id=acc.id,
            target_account_id=None,
            category_id=None,
            record_time=now,
            payee="",
            remark=f"股票收盘自动对齐亏损：{trade_name}",
            exclude_from_budget=True,
            creator_id=creator_id,
        )
        session.add(record)
        await session.flush()

    new_balance = round(current_balance + diff, 2)
    return {
        "account_id": acc.id,
        "account_name": acc.name,
        "trade_account_name": trade_name,
        "previous_balance": current_balance,
        "target_assets": target_assets,
        "diff": diff,
        "record_id": record.id if record else None,
        "record_type": record.type if record else None,
        "new_balance": new_balance,
    }


async def sync_all_trade_accounts_at_market_close(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """收盘自动巡检：对所有关联了股票账户的记账账户执行自动对齐"""
    stmt = select(Account).where(Account.trade_account_id.isnot(None))
    accounts = (await session.execute(stmt)).scalars().all()
    results = []
    for acc in accounts:
        try:
            res = await sync_account_with_trade_assets(
                session=session,
                account_id=acc.id,
                creator_id=1,  # 系统管理员或默认用户
            )
            results.append(res)
        except Exception as exc:
            logger.error("对齐记账账户 %s 失败: %s", acc.id, exc)
    await session.commit()
    return results
