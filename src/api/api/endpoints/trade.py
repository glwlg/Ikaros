import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import User
from api.auth.users import current_active_user
from api.core.database import get_async_session
from api.models.trade import (
    TradeAccount,
    TradeCashFlow,
    TradeOrder,
    TradePosition,
)
from api.services.trade_service import (
    deposit_cash,
    execute_buy_order,
    execute_sell_order,
    simulate_buy_order,
    withdraw_cash,
)
from api.services.trade_strategy_advisor import (
    generate_account_strategy_recommendations,
)
from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    fetch_stock_quotes,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    broker: str = Field("通用券商", max_length=50)
    initial_cash: float = Field(0.0, ge=0.0)
    commission_rate: float = Field(0.00025, ge=0.0, le=0.05)
    min_commission: float = Field(5.0, ge=0.0)
    stamp_duty_rate: float = Field(0.0005, ge=0.0, le=0.05)
    transfer_fee_rate: float = Field(0.00001, ge=0.0, le=0.05)
    notes: str | None = None


class AccountUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    broker: str = Field("通用券商", max_length=50)
    cash_balance: float | None = Field(None, ge=0.0)
    commission_rate: float = Field(0.00025, ge=0.0, le=0.05)
    min_commission: float = Field(5.0, ge=0.0)
    stamp_duty_rate: float = Field(0.0005, ge=0.0, le=0.05)
    transfer_fee_rate: float = Field(0.00001, ge=0.0, le=0.05)
    notes: str | None = None


class CashFlowCreate(BaseModel):
    flow_type: str = Field(..., pattern="^(deposit|withdraw)$")
    amount: float = Field(..., gt=0.0)
    notes: str = ""


class OrderCreate(BaseModel):
    account_id: int
    stock_code: str = Field(..., min_length=1)
    stock_name: str = Field(..., min_length=1)
    trade_type: str = Field(..., pattern="^(buy|sell)$")
    price: float = Field(..., gt=0.0)
    quantity: float = Field(..., gt=0.0)
    custom_commission: float | None = None
    custom_stamp_duty: float | None = None
    custom_transfer_fee: float | None = None
    notes: str | None = None


class SimulateRequest(BaseModel):
    account_id: int
    stock_code: str
    stock_name: str
    price: float = Field(..., gt=0.0)
    target_amount: float | None = None
    quantity: float | None = None


async def _enrich_positions_with_quotes(
    positions: list[TradePosition],
) -> list[dict[str, Any]]:
    if not positions:
        return []
    codes = [p.stock_code for p in positions if p.stock_code]
    quotes_map: dict[str, dict] = {}
    try:
        quotes = await fetch_stock_quotes(codes)
        for q in quotes:
            quotes_map[q["code"]] = q
    except Exception as exc:
        logger.warning("Failed to fetch quotes for trade positions: %s", exc)

    enriched = []
    for p in positions:
        q = quotes_map.get(p.stock_code, {})
        cur_price = float(q.get("price") or 0.0)
        change = float(q.get("change") or 0.0)
        percent = float(q.get("percent") or 0.0)
        qty = float(p.quantity)
        cost = float(p.cost_price)

        calc_price = cur_price if cur_price > 0 else cost
        market_value = round(qty * calc_price, 2)
        cost_amount = round(qty * cost, 2)
        unrealized_pnl = round(market_value - cost_amount, 2)
        unrealized_pnl_percent = (
            round((unrealized_pnl / cost_amount) * 100, 2) if cost_amount > 0 else 0.0
        )
        today_pnl = round(qty * change, 2) if cur_price > 0 else 0.0

        enriched.append(
            {
                "id": p.id,
                "account_id": p.account_id,
                "stock_code": p.stock_code,
                "stock_name": p.stock_name,
                "quantity": qty,
                "cost_price": cost,
                "accumulated_pnl": float(p.accumulated_pnl),
                "current_price": cur_price,
                "change": change,
                "percent": percent,
                "market_value": market_value,
                "cost_amount": cost_amount,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_percent": unrealized_pnl_percent,
                "today_pnl": today_pnl,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
        )
    return enriched


@router.get("/accounts")
async def list_accounts(
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取当前用户的所有交易账户及其资产指标"""
    stmt = (
        select(TradeAccount)
        .where(TradeAccount.user_id == current_user.id)
        .order_by(TradeAccount.id)
    )
    res = await session.execute(stmt)
    accounts = res.scalars().all()

    account_list = []
    for acc in accounts:
        # 获取该账户持仓
        pos_stmt = select(TradePosition).where(
            TradePosition.account_id == acc.id, TradePosition.quantity > 0
        )
        positions = (await session.execute(pos_stmt)).scalars().all()
        enriched_pos = await _enrich_positions_with_quotes(list(positions))

        market_value = sum(item["market_value"] for item in enriched_pos)
        today_pnl = sum(item["today_pnl"] for item in enriched_pos)
        unrealized_pnl = sum(item["unrealized_pnl"] for item in enriched_pos)
        accumulated_pnl = sum(float(p.accumulated_pnl) for p in positions)
        cash_balance = float(acc.cash_balance)
        total_assets = round(cash_balance + market_value, 2)
        position_ratio = (
            round((market_value / total_assets) * 100, 2) if total_assets > 0 else 0.0
        )

        account_list.append(
            {
                "id": acc.id,
                "name": acc.name,
                "broker": acc.broker,
                "cash_balance": cash_balance,
                "total_assets": total_assets,
                "market_value": market_value,
                "position_ratio_percent": position_ratio,
                "today_pnl": round(today_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "accumulated_pnl": round(accumulated_pnl, 2),
                "commission_rate": float(acc.commission_rate),
                "min_commission": float(acc.min_commission),
                "stamp_duty_rate": float(acc.stamp_duty_rate),
                "transfer_fee_rate": float(acc.transfer_fee_rate),
                "notes": acc.notes,
                "positions_count": len(enriched_pos),
                "created_at": acc.created_at.isoformat() if acc.created_at else None,
            }
        )
    return account_list


@router.post("/accounts")
async def create_account(
    payload: AccountCreate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """创建新交易账户"""
    acc = TradeAccount(
        user_id=current_user.id,
        name=payload.name.strip(),
        broker=payload.broker.strip(),
        cash_balance=payload.initial_cash,
        commission_rate=payload.commission_rate,
        min_commission=payload.min_commission,
        stamp_duty_rate=payload.stamp_duty_rate,
        transfer_fee_rate=payload.transfer_fee_rate,
        notes=payload.notes,
    )
    session.add(acc)
    await session.flush()

    if payload.initial_cash > 0:
        flow = TradeCashFlow(
            account_id=acc.id,
            flow_type="deposit",
            amount=payload.initial_cash,
            balance_after=payload.initial_cash,
            notes="初始账户资金",
            transacted_at=datetime.now(timezone.utc),
        )
        session.add(flow)
        await session.flush()

    return {"success": True, "id": acc.id}


@router.put("/accounts/{account_id}")
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """更新账户配置与费率"""
    acc = await session.get(TradeAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="账户不存在")

    acc.name = payload.name.strip()
    acc.broker = payload.broker.strip()
    acc.commission_rate = payload.commission_rate
    acc.min_commission = payload.min_commission
    acc.stamp_duty_rate = payload.stamp_duty_rate
    acc.transfer_fee_rate = payload.transfer_fee_rate
    acc.notes = payload.notes
    if payload.cash_balance is not None:
        new_cash = round(payload.cash_balance, 2)
        old_cash = float(acc.cash_balance)
        diff = round(new_cash - old_cash, 2)
        if abs(diff) > 0.001:
            acc.cash_balance = new_cash
            flow = TradeCashFlow(
                account_id=acc.id,
                flow_type="adjust",
                amount=diff,
                balance_after=new_cash,
                notes=f"校正可用现金：¥{old_cash:.2f} → ¥{new_cash:.2f}",
                transacted_at=datetime.now(timezone.utc),
            )
            session.add(flow)
    return {"success": True}


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """删除账户"""
    acc = await session.get(TradeAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="账户不存在")

    await session.delete(acc)
    return {"success": True}


@router.post("/accounts/{account_id}/cash-flow")
async def handle_cash_flow(
    account_id: int,
    payload: CashFlowCreate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """银证转入/转出出入金"""
    acc = await session.get(TradeAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="账户不存在")

    try:
        if payload.flow_type == "deposit":
            flow = await deposit_cash(
                session, account_id, payload.amount, notes=payload.notes
            )
        else:
            flow = await withdraw_cash(
                session, account_id, payload.amount, notes=payload.notes
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "flow_id": flow.id,
        "balance_after": float(acc.cash_balance),
    }


@router.get("/accounts/{account_id}/cash-flows")
async def get_cash_flows(
    account_id: int,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取指定账户的资金流水明细"""
    acc = await session.get(TradeAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="账户不存在")

    stmt = (
        select(TradeCashFlow)
        .where(TradeCashFlow.account_id == account_id)
        .order_by(desc(TradeCashFlow.transacted_at))
    )
    res = await session.execute(stmt)
    flows = res.scalars().all()
    return [
        {
            "id": f.id,
            "flow_type": f.flow_type,
            "amount": float(f.amount),
            "balance_after": float(f.balance_after),
            "notes": f.notes,
            "transacted_at": f.transacted_at.isoformat() if f.transacted_at else None,
        }
        for f in flows
    ]


@router.get("/accounts/{account_id}/positions")
async def get_account_positions(
    account_id: int,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取指定账户的持仓列表（含实时行情与盈亏计算）"""
    acc = await session.get(TradeAccount, account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="账户不存在")

    stmt = select(TradePosition).where(
        TradePosition.account_id == account_id, TradePosition.quantity > 0
    )
    positions = (await session.execute(stmt)).scalars().all()
    enriched = await _enrich_positions_with_quotes(list(positions))

    # 计算在账户中的持仓占比
    total_market_val = sum(p["market_value"] for p in enriched)
    total_assets = float(acc.cash_balance) + total_market_val
    for p in enriched:
        p["weight_percent"] = (
            round((p["market_value"] / total_assets) * 100, 2)
            if total_assets > 0
            else 0.0
        )

    return enriched


@router.get("/summary")
async def get_multi_accounts_summary(
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """多账户全景资产看板汇总"""
    stmt = select(TradeAccount).where(TradeAccount.user_id == current_user.id)
    accounts = (await session.execute(stmt)).scalars().all()

    total_cash = sum(float(a.cash_balance) for a in accounts)

    acc_ids = [a.id for a in accounts]
    if not acc_ids:
        return {
            "total_assets": 0.0,
            "total_market_value": 0.0,
            "total_cash": 0.0,
            "total_today_pnl": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_accumulated_pnl": 0.0,
            "position_ratio_percent": 0.0,
            "accounts_count": 0,
            "positions_count": 0,
            "asset_distribution": [],
        }

    pos_stmt = select(TradePosition).where(
        TradePosition.account_id.in_(acc_ids), TradePosition.quantity > 0
    )
    all_positions = (await session.execute(pos_stmt)).scalars().all()
    enriched_positions = await _enrich_positions_with_quotes(list(all_positions))

    total_market_value = sum(p["market_value"] for p in enriched_positions)
    total_today_pnl = sum(p["today_pnl"] for p in enriched_positions)
    total_unrealized_pnl = sum(p["unrealized_pnl"] for p in enriched_positions)
    total_accumulated_pnl = sum(float(p.accumulated_pnl) for p in all_positions)
    total_assets = round(total_cash + total_market_value, 2)
    global_position_ratio = (
        round((total_market_value / total_assets) * 100, 2) if total_assets > 0 else 0.0
    )

    # 汇总各标的在全市场的合并市值分布
    stock_distribution: dict[str, dict[str, Any]] = {}
    for p in enriched_positions:
        code = p["stock_code"]
        if code not in stock_distribution:
            stock_distribution[code] = {
                "stock_code": code,
                "stock_name": p["stock_name"],
                "total_quantity": 0.0,
                "total_market_value": 0.0,
            }
        stock_distribution[code]["total_quantity"] += p["quantity"]
        stock_distribution[code]["total_market_value"] += p["market_value"]

    distribution_list = []
    # 现金作为一项分布
    distribution_list.append(
        {
            "label": "可用现金",
            "category": "cash",
            "amount": round(total_cash, 2),
            "ratio_percent": (
                round((total_cash / total_assets) * 100, 2) if total_assets > 0 else 0.0
            ),
        }
    )
    for item in sorted(
        stock_distribution.values(), key=lambda x: x["total_market_value"], reverse=True
    ):
        distribution_list.append(
            {
                "label": f"{item['stock_name']}({item['stock_code']})",
                "category": "stock",
                "amount": round(item["total_market_value"], 2),
                "ratio_percent": (
                    round((item["total_market_value"] / total_assets) * 100, 2)
                    if total_assets > 0
                    else 0.0
                ),
            }
        )

    return {
        "total_assets": total_assets,
        "total_market_value": round(total_market_value, 2),
        "total_cash": round(total_cash, 2),
        "total_today_pnl": round(total_today_pnl, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_accumulated_pnl": round(total_accumulated_pnl, 2),
        "position_ratio_percent": global_position_ratio,
        "accounts_count": len(accounts),
        "positions_count": len(enriched_positions),
        "asset_distribution": distribution_list,
    }


@router.post("/orders")
async def create_trade_order(
    payload: OrderCreate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """录入买入或卖出交易订单"""
    acc = await session.get(TradeAccount, payload.account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="交易账户不存在")

    try:
        if payload.trade_type == "buy":
            order = await execute_buy_order(
                session=session,
                account_id=acc.id,
                stock_code=payload.stock_code,
                stock_name=payload.stock_name,
                price=payload.price,
                quantity=payload.quantity,
                custom_commission=payload.custom_commission,
                custom_stamp_duty=payload.custom_stamp_duty,
                custom_transfer_fee=payload.custom_transfer_fee,
                notes=payload.notes,
                transacted_at=datetime.now(timezone.utc),
            )
        else:
            order = await execute_sell_order(
                session=session,
                account_id=acc.id,
                stock_code=payload.stock_code,
                stock_name=payload.stock_name,
                price=payload.price,
                quantity=payload.quantity,
                custom_commission=payload.custom_commission,
                custom_stamp_duty=payload.custom_stamp_duty,
                custom_transfer_fee=payload.custom_transfer_fee,
                notes=payload.notes,
                transacted_at=datetime.now(timezone.utc),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "order_id": order.id,
        "trade_type": order.trade_type,
        "net_amount": float(order.net_amount),
        "total_fee": float(order.total_fee),
        "realized_pnl": float(order.realized_pnl),
        "holding_after": float(order.holding_after),
        "cost_price_after": float(order.cost_price_after),
    }


@router.get("/orders")
async def list_trade_orders(
    account_id: int | None = Query(None),
    stock_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """查询历史交易订单流水明细"""
    stmt = (
        select(TradeOrder)
        .join(TradeAccount, TradeOrder.account_id == TradeAccount.id)
        .where(TradeAccount.user_id == current_user.id)
    )
    if account_id:
        stmt = stmt.where(TradeOrder.account_id == account_id)
    if stock_code:
        stmt = stmt.where(TradeOrder.stock_code == stock_code.strip())
    stmt = stmt.order_by(desc(TradeOrder.transacted_at)).limit(limit)

    orders = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": o.id,
            "account_id": o.account_id,
            "stock_code": o.stock_code,
            "stock_name": o.stock_name,
            "trade_type": o.trade_type,
            "price": float(o.price),
            "quantity": float(o.quantity),
            "amount": float(o.amount),
            "commission": float(o.commission),
            "stamp_duty": float(o.stamp_duty),
            "transfer_fee": float(o.transfer_fee),
            "total_fee": float(o.total_fee),
            "net_amount": float(o.net_amount),
            "realized_pnl": float(o.realized_pnl),
            "cost_price_after": float(o.cost_price_after),
            "holding_after": float(o.holding_after),
            "notes": o.notes,
            "transacted_at": o.transacted_at.isoformat() if o.transacted_at else None,
        }
        for o in orders
    ]


@router.post("/simulate")
async def simulate_order(
    payload: SimulateRequest,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """加仓/调仓资金校验与影响预演"""
    acc = await session.get(TradeAccount, payload.account_id)
    if not acc or acc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="交易账户不存在")

    # 查询当前持仓
    stmt = select(TradePosition).where(
        TradePosition.account_id == acc.id,
        TradePosition.stock_code == payload.stock_code.strip(),
    )
    pos = (await session.execute(stmt)).scalar_one_or_none()

    # 查询该账户其他持仓市值
    all_pos_stmt = select(TradePosition).where(
        TradePosition.account_id == acc.id, TradePosition.quantity > 0
    )
    all_pos = (await session.execute(all_pos_stmt)).scalars().all()
    enriched = await _enrich_positions_with_quotes(list(all_pos))
    portfolio_market_val = sum(p["market_value"] for p in enriched)

    try:
        res = simulate_buy_order(
            account=acc,
            stock_code=payload.stock_code.strip(),
            stock_name=payload.stock_name.strip(),
            price=payload.price,
            target_amount=payload.target_amount,
            quantity=payload.quantity,
            current_position=pos,
            existing_portfolio_market_value=portfolio_market_val,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 若现金不足，查找该用户其他有剩余可用现金的账户，给出调拨建议
    if not res["is_sufficient"]:
        other_acc_stmt = select(TradeAccount).where(
            TradeAccount.user_id == current_user.id,
            TradeAccount.id != acc.id,
            TradeAccount.cash_balance > 0,
        )
        other_accounts = (await session.execute(other_acc_stmt)).scalars().all()
        transfer_suggestions = [
            {
                "account_id": a.id,
                "name": a.name,
                "available_cash": float(a.cash_balance),
                "can_cover_fully": float(a.cash_balance) >= res["cash_shortage"],
            }
            for a in other_accounts
        ]
        res["transfer_suggestions"] = transfer_suggestions
    else:
        res["transfer_suggestions"] = []

    return res


@router.get("/recommendations")
async def get_strategy_recommendations(
    max_position_ratio: float = Query(30.0, ge=5.0, le=100.0),
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取基于账户可用现金约束与仓位上限风控的量化策略调仓指引"""
    return await generate_account_strategy_recommendations(
        session=session,
        user_id=current_user.id,
        max_position_ratio=max_position_ratio,
    )
