from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.trade import TradeAccount, TradePosition
from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    fetch_stock_quotes,
)


def evaluate_trade_advice(
    account: TradeAccount,
    position: TradePosition | None,
    stock_quote: dict[str, Any],
    base_signal: str = "hold",
    total_account_assets: float = 0.0,
    max_position_ratio: float = 30.0,
) -> dict[str, Any]:
    """
    结合账户真实可用现金约束与单票仓位上限，评估并修正量化建议：
    1. 现金约束过滤：无可用现金或现金不足一手时，限制加仓信号；
    2. 仓位上限风控：单票市值占比超过阈值（默认30%）时，限制加仓评级。
    """
    cur_price = float(stock_quote.get("price") or 0.0)
    cash = float(account.cash_balance)
    qty = float(position.quantity) if position else 0.0
    cost = float(position.cost_price) if position else 0.0
    stock_market_val = round(qty * cur_price, 2)

    current_ratio = (
        round((stock_market_val / total_account_assets) * 100, 2)
        if total_account_assets > 0
        else 0.0
    )

    final_signal = base_signal.lower().strip()
    risk_notes: list[str] = []

    # 若原策略为买入加仓
    if final_signal in {"buy", "加仓", "买入"}:
        # 检查仓位上限
        if current_ratio >= max_position_ratio:
            final_signal = "hold"
            risk_notes.append(
                f"当前单票占比已达 {current_ratio:.1f}%，超过 {max_position_ratio:.0f}% 仓位上限，限制加仓以控制单一标的风控敞口"
            )
        # 检查账户可用现金
        elif cash <= 0:
            final_signal = "hold"
            risk_notes.append("该账户无可用现金，建议维持观望或需先调拨资金")
        elif cur_price > 0 and cash < cur_price * 100:
            final_signal = "hold"
            shortage = round((cur_price * 100) - cash, 2)
            risk_notes.append(f"可用现金 (¥{cash:.2f}) 不足买入一手（差额约 ¥{shortage:.2f}），建议观望")

    # 若原策略为卖出减仓
    elif final_signal in {"sell", "减仓", "卖出"}:
        if qty <= 0:
            final_signal = "hold"
            risk_notes.append("当前账户无此标的持仓，忽略减仓建议")
        elif cost > 0 and cur_price > 0:
            profit_pct = round(((cur_price - cost) / cost) * 100, 2)
            if current_ratio >= max_position_ratio:
                risk_notes.append(f"单票仓位较重 ({current_ratio:.1f}%)，建议分批减仓止盈以平衡组合配置")

    return {
        "stock_code": str(stock_quote.get("code") or ""),
        "stock_name": str(stock_quote.get("name") or ""),
        "account_id": account.id,
        "account_name": account.name,
        "original_signal": base_signal,
        "final_signal": final_signal,
        "current_price": cur_price,
        "cost_price": cost,
        "holding_quantity": qty,
        "position_ratio_percent": current_ratio,
        "available_cash": cash,
        "risk_notes": risk_notes,
    }


async def generate_account_strategy_recommendations(
    session: AsyncSession,
    user_id: int,
    max_position_ratio: float = 30.0,
) -> list[dict[str, Any]]:
    """生成该用户所有账户的量化策略与资金风控联动建议清单"""
    acc_stmt = select(TradeAccount).where(TradeAccount.user_id == user_id)
    accounts = (await session.execute(acc_stmt)).scalars().all()
    if not accounts:
        return []

    # 获取所有持仓
    acc_ids = [a.id for a in accounts]
    pos_stmt = select(TradePosition).where(
        TradePosition.account_id.in_(acc_ids), TradePosition.quantity > 0
    )
    positions = (await session.execute(pos_stmt)).scalars().all()

    codes = list({p.stock_code for p in positions})
    quotes = await fetch_stock_quotes(codes) if codes else []
    quotes_map = {q["code"]: q for q in quotes}

    recommendations = []
    for acc in accounts:
        acc_positions = [p for p in positions if p.account_id == acc.id]
        total_market_val = sum(
            float(p.quantity) * float(quotes_map.get(p.stock_code, {}).get("price") or p.cost_price)
            for p in acc_positions
        )
        total_assets = float(acc.cash_balance) + total_market_val

        for pos in acc_positions:
            q = quotes_map.get(pos.stock_code, {})
            cur_price = float(q.get("price") or pos.cost_price)
            pct_change = float(q.get("percent") or 0.0)

            # 模拟基准策略逻辑（如跌幅大为低吸加仓，涨幅大且估值高为减仓）
            if pct_change <= -2.5:
                base_sig = "buy"
            elif pct_change >= 4.0:
                base_sig = "sell"
            else:
                base_sig = "hold"

            advice = evaluate_trade_advice(
                account=acc,
                position=pos,
                stock_quote={"code": pos.stock_code, "name": pos.stock_name, "price": cur_price},
                base_signal=base_sig,
                total_account_assets=total_assets,
                max_position_ratio=max_position_ratio,
            )
            recommendations.append(advice)

    return recommendations
