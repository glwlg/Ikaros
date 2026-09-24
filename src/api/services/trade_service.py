import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.trade import (
    TradeAccount,
    TradePosition,
    TradeOrder,
    TradeCashFlow,
)


def _round_currency(val: float | Decimal) -> float:
    d = Decimal(str(val))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_price(val: float | Decimal) -> float:
    d = Decimal(str(val))
    return float(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def calculate_fees(
    trade_type: str,
    amount: float,
    account: TradeAccount,
    custom_commission: float | None = None,
    custom_stamp_duty: float | None = None,
    custom_transfer_fee: float | None = None,
) -> dict[str, float]:
    """
    计算交易手续费（买入/卖出）
    A 股标准：
    - 佣金：成交额 * 佣金率，单笔最低佣金限制（默认5元）
    - 印花税：仅卖出收取，成交额 * 印花税率（默认0.05%）
    - 过户费：成交额 * 过户费率（默认0.001%）
    """
    norm_type = trade_type.strip().lower()
    if amount <= 0:
        return {
            "commission": 0.0,
            "stamp_duty": 0.0,
            "transfer_fee": 0.0,
            "total_fee": 0.0,
        }

    if custom_commission is not None:
        commission = _round_currency(custom_commission)
    else:
        raw_commission = amount * float(account.commission_rate)
        commission = _round_currency(max(float(account.min_commission), raw_commission))

    if custom_stamp_duty is not None:
        stamp_duty = _round_currency(custom_stamp_duty)
    else:
        if norm_type == "sell":
            stamp_duty = _round_currency(amount * float(account.stamp_duty_rate))
        else:
            stamp_duty = 0.0

    if custom_transfer_fee is not None:
        transfer_fee = _round_currency(custom_transfer_fee)
    else:
        transfer_fee = _round_currency(amount * float(account.transfer_fee_rate))

    total_fee = _round_currency(commission + stamp_duty + transfer_fee)
    return {
        "commission": commission,
        "stamp_duty": stamp_duty,
        "transfer_fee": transfer_fee,
        "total_fee": total_fee,
    }


def calculate_buy_dilution(
    current_qty: float,
    current_cost: float,
    buy_qty: float,
    buy_price: float,
    buy_fee: float,
) -> tuple[float, float]:
    """
    移动加权计算买入加仓后的持仓与单位成本
    最新成本价 = (原持仓量 * 原成本 + 新买入量 * 买入价 + 手续费) / (原持仓量 + 新买入量)
    """
    if buy_qty <= 0:
        raise ValueError("买入数量必须大于 0")
    if buy_price <= 0:
        raise ValueError("买入单价必须大于 0")

    new_qty = current_qty + buy_qty
    total_cost_basis = (current_qty * current_cost) + (buy_qty * buy_price) + buy_fee
    new_cost_price = _round_price(total_cost_basis / new_qty)
    return new_qty, new_cost_price


def calculate_sell_pnl(
    current_qty: float,
    current_cost: float,
    sell_qty: float,
    sell_price: float,
    sell_fee: float,
) -> dict[str, float]:
    """
    移动加权计算卖出减仓盈亏
    已实现盈亏 = 卖出净回款 (成交金额 - 手续费) - (卖出数量 * 原单位成本)
    """
    if sell_qty <= 0:
        raise ValueError("卖出数量必须大于 0")
    if sell_price <= 0:
        raise ValueError("卖出单价必须大于 0")
    if sell_qty > current_qty:
        raise ValueError(f"卖出数量 ({sell_qty:g}) 超过当前可用持仓 ({current_qty:g})")

    amount = _round_currency(sell_qty * sell_price)
    net_amount = _round_currency(amount - sell_fee)
    cost_basis = sell_qty * current_cost
    realized_pnl = _round_currency(net_amount - cost_basis)
    remaining_qty = current_qty - sell_qty
    cost_price_after = current_cost if remaining_qty > 0 else 0.0

    return {
        "amount": amount,
        "net_amount": net_amount,
        "realized_pnl": realized_pnl,
        "remaining_qty": remaining_qty,
        "cost_price_after": cost_price_after,
    }


def simulate_buy_order(
    account: TradeAccount,
    stock_code: str,
    stock_name: str,
    price: float,
    target_amount: float | None = None,
    quantity: float | None = None,
    current_position: TradePosition | None = None,
    existing_portfolio_market_value: float = 0.0,
) -> dict[str, Any]:
    """
    买入/加仓智能试算器：
    - 若输入 target_amount（如5000元），自动折算整手（100股整数倍）最优买入数量
    - 若输入 quantity，直接使用传入股数
    - 预演加仓后的摊薄成本、所需扣款现金、可用现金缺口、调仓后个股权重占比
    """
    if price <= 0:
        raise ValueError("委托单价必须大于 0")

    if quantity is None and target_amount is None:
        raise ValueError("必须指定拟买入金额 (target_amount) 或拟买入数量 (quantity)")

    if quantity is not None:
        sim_qty = float(quantity)
        if sim_qty <= 0:
            raise ValueError("拟买入数量必须大于 0")
    else:
        assert target_amount is not None
        if target_amount <= 0:
            raise ValueError("拟买入金额必须大于 0")
        # 折算整手（100股为一手）
        # 每手成本约 100 * price
        single_lot_amount = 100 * price
        lots = int(target_amount // single_lot_amount)
        # 尝试由多到少寻找扣除手续费后不超过 target_amount 的最大整手（若一手就超，则保底1手试算并提示超额）
        best_qty = lots * 100
        while best_qty > 0:
            est_amt = best_qty * price
            fees = calculate_fees("buy", est_amt, account)
            if est_amt + fees["total_fee"] <= target_amount:
                break
            best_qty -= 100
        sim_qty = float(best_qty if best_qty > 0 else 100)

    trade_amount = _round_currency(sim_qty * price)
    fees = calculate_fees("buy", trade_amount, account)
    total_fee = fees["total_fee"]
    total_required = _round_currency(trade_amount + total_fee)

    current_cash = float(account.cash_balance)
    is_sufficient = current_cash >= total_required
    cash_shortage = _round_currency(max(0.0, total_required - current_cash))

    cur_qty = float(current_position.quantity) if current_position else 0.0
    cur_cost = float(current_position.cost_price) if current_position else 0.0
    new_qty, new_cost = calculate_buy_dilution(
        cur_qty, cur_cost, sim_qty, price, total_fee
    )

    # 仓位权重试算
    # 新总资产 = (原有持仓市值 + 现有现金) - total_fee（买入为现金转持仓，资产仅扣除损耗手续费）
    new_stock_market_value = _round_currency(new_qty * price)
    new_total_assets = _round_currency(
        existing_portfolio_market_value + current_cash - total_fee
    )
    position_ratio = (
        round((new_stock_market_value / new_total_assets) * 100, 2)
        if new_total_assets > 0
        else 0.0
    )

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "price": price,
        "simulated_quantity": sim_qty,
        "simulated_lots": int(sim_qty // 100),
        "trade_amount": trade_amount,
        "fees": fees,
        "total_required": total_required,
        "current_cash": current_cash,
        "is_sufficient": is_sufficient,
        "cash_shortage": cash_shortage,
        "diluted_cost_price": new_cost,
        "new_quantity": new_qty,
        "new_stock_market_value": new_stock_market_value,
        "new_total_assets": new_total_assets,
        "position_ratio_percent": position_ratio,
    }


async def deposit_cash(
    session: AsyncSession,
    account_id: int,
    amount: float,
    notes: str = "",
    transacted_at: datetime | None = None,
) -> TradeCashFlow:
    """银证转入（现金入金）"""
    if amount <= 0:
        raise ValueError("转入金额必须大于 0")

    account = await session.get(TradeAccount, account_id)
    if not account:
        raise ValueError(f"交易账户不存在 (id={account_id})")

    delta = _round_currency(amount)
    new_balance = _round_currency(float(account.cash_balance) + delta)
    account.cash_balance = new_balance
    now = transacted_at or datetime.utcnow()

    flow = TradeCashFlow(
        account_id=account.id,
        flow_type="deposit",
        amount=delta,
        balance_after=new_balance,
        notes=notes or "银证转入",
        transacted_at=now,
    )
    session.add(flow)
    await session.flush()
    return flow


async def withdraw_cash(
    session: AsyncSession,
    account_id: int,
    amount: float,
    notes: str = "",
    transacted_at: datetime | None = None,
) -> TradeCashFlow:
    """银证转出（现金出金）"""
    if amount <= 0:
        raise ValueError("转出金额必须大于 0")

    account = await session.get(TradeAccount, account_id)
    if not account:
        raise ValueError(f"交易账户不存在 (id={account_id})")

    delta = _round_currency(amount)
    current_cash = float(account.cash_balance)
    if current_cash < delta:
        raise ValueError(
            f"可用现金不足，当前余额 {current_cash:.2f} 元，拟转出 {delta:.2f} 元"
        )

    new_balance = _round_currency(current_cash - delta)
    account.cash_balance = new_balance
    now = transacted_at or datetime.utcnow()

    flow = TradeCashFlow(
        account_id=account.id,
        flow_type="withdraw",
        amount=-delta,
        balance_after=new_balance,
        notes=notes or "银证转出",
        transacted_at=now,
    )
    session.add(flow)
    await session.flush()
    return flow


async def execute_buy_order(
    session: AsyncSession,
    account_id: int,
    stock_code: str,
    stock_name: str,
    price: float,
    quantity: float,
    custom_commission: float | None = None,
    custom_stamp_duty: float | None = None,
    custom_transfer_fee: float | None = None,
    notes: str | None = None,
    transacted_at: datetime | None = None,
) -> TradeOrder:
    """
    执行买入记账：
    1. 计算手续费
    2. 校验账户可用现金 (严格拦截现金不足)
    3. 移动加权摊薄持仓成本
    4. 扣减账户现金并生成流水
    5. 生成交易订单与资金流水
    """
    if price <= 0:
        raise ValueError("买入价格必须大于 0")
    if quantity <= 0:
        raise ValueError("买入数量必须大于 0")

    account = await session.get(TradeAccount, account_id)
    if not account:
        raise ValueError(f"交易账户不存在 (id={account_id})")

    code = stock_code.strip()
    name = stock_name.strip()
    amount = _round_currency(price * quantity)
    fees = calculate_fees(
        "buy",
        amount,
        account,
        custom_commission,
        custom_stamp_duty,
        custom_transfer_fee,
    )
    total_fee = fees["total_fee"]
    net_amount = _round_currency(amount + total_fee)  # 买入总扣款

    current_cash = float(account.cash_balance)
    if current_cash < net_amount:
        shortage = _round_currency(net_amount - current_cash)
        raise ValueError(
            f"账户可用现金不足：需要 {net_amount:.2f} 元（含费用 {total_fee:.2f} 元），"
            f"当前可用 {current_cash:.2f} 元，缺少 {shortage:.2f} 元"
        )

    # 查询当前持仓
    stmt = select(TradePosition).where(
        TradePosition.account_id == account_id,
        TradePosition.stock_code == code,
    )
    pos_res = await session.execute(stmt)
    pos = pos_res.scalar_one_or_none()

    cur_qty = float(pos.quantity) if pos else 0.0
    cur_cost = float(pos.cost_price) if pos else 0.0
    new_qty, new_cost = calculate_buy_dilution(
        cur_qty, cur_cost, quantity, price, total_fee
    )

    now = transacted_at or datetime.utcnow()
    if pos:
        pos.quantity = new_qty
        pos.cost_price = new_cost
        pos.stock_name = name or pos.stock_name
        pos.updated_at = now
    else:
        pos = TradePosition(
            account_id=account.id,
            stock_code=code,
            stock_name=name or code,
            quantity=new_qty,
            cost_price=new_cost,
            accumulated_pnl=0.0,
            updated_at=now,
        )
        session.add(pos)

    # 扣减账户现金
    new_cash = _round_currency(current_cash - net_amount)
    account.cash_balance = new_cash

    order = TradeOrder(
        account_id=account.id,
        stock_code=code,
        stock_name=name or code,
        trade_type="buy",
        price=price,
        quantity=quantity,
        amount=amount,
        commission=fees["commission"],
        stamp_duty=fees["stamp_duty"],
        transfer_fee=fees["transfer_fee"],
        total_fee=total_fee,
        net_amount=net_amount,
        realized_pnl=0.0,
        cost_price_after=new_cost,
        holding_after=new_qty,
        notes=notes,
        transacted_at=now,
    )
    session.add(order)
    await session.flush()

    cash_flow = TradeCashFlow(
        account_id=account.id,
        flow_type="trade_buy",
        amount=-net_amount,
        balance_after=new_cash,
        related_order_id=order.id,
        notes=f"买入 {name}({code}) {quantity:g}股",
        transacted_at=now,
    )
    session.add(cash_flow)
    await session.flush()
    return order


async def execute_sell_order(
    session: AsyncSession,
    account_id: int,
    stock_code: str,
    stock_name: str,
    price: float,
    quantity: float,
    custom_commission: float | None = None,
    custom_stamp_duty: float | None = None,
    custom_transfer_fee: float | None = None,
    notes: str | None = None,
    transacted_at: datetime | None = None,
) -> TradeOrder:
    """
    执行卖出记账：
    1. 校验可用持仓
    2. 计算手续费与已实现盈亏 (Realized PnL)
    3. 扣减持仓数量与更新累计盈亏
    4. 卖出回款增加账户现金
    5. 生成交易订单与资金流水
    """
    if price <= 0:
        raise ValueError("卖出价格必须大于 0")
    if quantity <= 0:
        raise ValueError("卖出数量必须大于 0")

    account = await session.get(TradeAccount, account_id)
    if not account:
        raise ValueError(f"交易账户不存在 (id={account_id})")

    code = stock_code.strip()
    name = stock_name.strip()

    stmt = select(TradePosition).where(
        TradePosition.account_id == account_id,
        TradePosition.stock_code == code,
    )
    pos_res = await session.execute(stmt)
    pos = pos_res.scalar_one_or_none()
    if not pos or float(pos.quantity) < quantity:
        holding = float(pos.quantity) if pos else 0.0
        raise ValueError(
            f"持仓不足：当前可用 {holding:g} 股，拟卖出 {quantity:g} 股"
        )

    cur_qty = float(pos.quantity)
    cur_cost = float(pos.cost_price)
    amount = _round_currency(price * quantity)
    fees = calculate_fees(
        "sell",
        amount,
        account,
        custom_commission,
        custom_stamp_duty,
        custom_transfer_fee,
    )
    total_fee = fees["total_fee"]
    net_amount = _round_currency(amount - total_fee)  # 卖出净回款

    pnl_info = calculate_sell_pnl(cur_qty, cur_cost, quantity, price, total_fee)
    realized_pnl = pnl_info["realized_pnl"]
    remaining_qty = pnl_info["remaining_qty"]
    cost_after = pnl_info["cost_price_after"]

    now = transacted_at or datetime.utcnow()
    pos.quantity = remaining_qty
    pos.cost_price = cost_after
    pos.accumulated_pnl = _round_currency(float(pos.accumulated_pnl) + realized_pnl)
    pos.updated_at = now

    # 现金回款
    current_cash = float(account.cash_balance)
    new_cash = _round_currency(current_cash + net_amount)
    account.cash_balance = new_cash

    order = TradeOrder(
        account_id=account.id,
        stock_code=code,
        stock_name=name or pos.stock_name,
        trade_type="sell",
        price=price,
        quantity=quantity,
        amount=amount,
        commission=fees["commission"],
        stamp_duty=fees["stamp_duty"],
        transfer_fee=fees["transfer_fee"],
        total_fee=total_fee,
        net_amount=net_amount,
        realized_pnl=realized_pnl,
        cost_price_after=cost_after,
        holding_after=remaining_qty,
        notes=notes,
        transacted_at=now,
    )
    session.add(order)
    await session.flush()

    cash_flow = TradeCashFlow(
        account_id=account.id,
        flow_type="trade_sell",
        amount=net_amount,
        balance_after=new_cash,
        related_order_id=order.id,
        notes=f"卖出 {name or pos.stock_name}({code}) {quantity:g}股，盈亏 {realized_pnl:+.2f} 元",
        transacted_at=now,
    )
    session.add(cash_flow)
    await session.flush()
    return order
