import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.auth.models import User
from api.core.database import Base
from api.models.trade import (
    TradeAccount,
    TradePosition,
    TradeOrder,
    TradeCashFlow,
)
from api.services.trade_service import (
    calculate_fees,
    calculate_buy_dilution,
    calculate_sell_pnl,
    simulate_buy_order,
    deposit_cash,
    withdraw_cash,
    execute_buy_order,
    execute_sell_order,
)


@pytest.fixture
async def trade_session(tmp_path):
    db_path = tmp_path / "trade-engine-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _setup_account(session, cash: float = 10000.0) -> tuple[User, TradeAccount]:
    user = User(
        email="trader@example.com",
        hashed_password="dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    account = TradeAccount(
        user_id=user.id,
        name="招商证券主账户",
        broker="招商证券",
        cash_balance=cash,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    session.add(account)
    await session.flush()
    return user, account


def test_fee_calculation():
    account = TradeAccount(
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    # 买入 10000 元：佣金 2.5元 -> 保底5元；过户费 0.1元；印花税 0
    buy_fees = calculate_fees("buy", 10000.0, account)
    assert buy_fees["commission"] == 5.0
    assert buy_fees["stamp_duty"] == 0.0
    assert buy_fees["transfer_fee"] == 0.10
    assert buy_fees["total_fee"] == 5.10

    # 卖出 100000 元：佣金 25元；过户费 1元；印花税 50元
    sell_fees = calculate_fees("sell", 100000.0, account)
    assert sell_fees["commission"] == 25.0
    assert sell_fees["stamp_duty"] == 50.0
    assert sell_fees["transfer_fee"] == 1.0
    assert sell_fees["total_fee"] == 76.0


def test_buy_dilution_and_sell_pnl():
    # 首次建仓 1000 股，价格 10.0，手续费 5.1
    qty1, cost1 = calculate_buy_dilution(0, 0, 1000, 10.0, 5.1)
    assert qty1 == 1000
    assert cost1 == 10.0051  # (10000 + 5.1) / 1000

    # 第二次加仓 1000 股，价格 12.0，手续费 5.1
    qty2, cost2 = calculate_buy_dilution(qty1, cost1, 1000, 12.0, 5.1)
    assert qty2 == 2000
    assert cost2 == 11.0051

    # 减仓 500 股，价格 15.0，手续费 8.8
    pnl_res = calculate_sell_pnl(qty2, cost2, 500, 15.0, 8.8)
    assert pnl_res["remaining_qty"] == 1500
    assert pnl_res["cost_price_after"] == 11.0051
    # 净回款 7500 - 8.8 = 7491.20；成本对应额 500 * 11.0051 = 5502.55；盈亏 = 7491.20 - 5502.55 = 1988.65
    assert abs(pnl_res["realized_pnl"] - 1988.65) < 0.05


def test_simulate_buy_order():
    account = TradeAccount(
        cash_balance=8000.0,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    # 拟加仓 5000 元，股价 16.50
    # 100股 = 1650元。300股 = 4950元。加手续费后约 4955.1元 <= 5000
    sim = simulate_buy_order(
        account=account,
        stock_code="sh600519",
        stock_name="贵州茅台",
        price=16.50,
        target_amount=5000.0,
        existing_portfolio_market_value=12000.0,
    )
    assert sim["simulated_quantity"] == 300
    assert sim["simulated_lots"] == 3
    assert sim["is_sufficient"] is True
    assert sim["cash_shortage"] == 0.0
    assert sim["diluted_cost_price"] > 16.50


@pytest.mark.asyncio
async def test_account_cash_flows(trade_session):
    _, account = await _setup_account(trade_session, cash=5000.0)

    # 银证转入 3000
    in_flow = await deposit_cash(trade_session, account.id, 3000.0, "资金注入")
    assert in_flow.amount == 3000.0
    assert in_flow.balance_after == 8000.0
    assert float(account.cash_balance) == 8000.0

    # 银证转出 2000
    out_flow = await withdraw_cash(trade_session, account.id, 2000.0, "资金提取")
    assert out_flow.amount == -2000.0
    assert out_flow.balance_after == 6000.0
    assert float(account.cash_balance) == 6000.0

    # 转出超额拦截
    with pytest.raises(ValueError, match="可用现金不足"):
        await withdraw_cash(trade_session, account.id, 10000.0)


@pytest.mark.asyncio
async def test_order_execution_lifecycle(trade_session):
    _, account = await _setup_account(trade_session, cash=20000.0)

    # 1. 现金不足拦截买入
    with pytest.raises(ValueError, match="账户可用现金不足"):
        await execute_buy_order(
            trade_session,
            account.id,
            "sh600000",
            "浦发银行",
            price=10.0,
            quantity=5000,  # 50000元 > 20000元
        )

    # 2. 正常买入 1000 股 @ 10.0元 (总额 10000 + 费用 5.1 = 10005.1)
    order1 = await execute_buy_order(
        trade_session,
        account.id,
        "sh600000",
        "浦发银行",
        price=10.0,
        quantity=1000,
    )
    assert order1.total_fee == 5.10
    assert order1.net_amount == 10005.10
    assert float(account.cash_balance) == 9994.90

    # 持仓检查
    pos = (
        await trade_session.execute(
            select(TradePosition).where(
                TradePosition.account_id == account.id,
                TradePosition.stock_code == "sh600000",
            )
        )
    ).scalar_one()
    assert float(pos.quantity) == 1000
    assert round(float(pos.cost_price), 4) == 10.0051

    # 3. 加仓 500 股 @ 12.0元 (额 6000 + 费用 5.06 = 6005.06)
    order2 = await execute_buy_order(
        trade_session,
        account.id,
        "sh600000",
        "浦发银行",
        price=12.0,
        quantity=500,
    )
    assert float(pos.quantity) == 1500
    # 新总成本 = 10005.10 + 6005.06 = 16010.16 -> 每股 10.6734
    assert round(float(pos.cost_price), 4) == 10.6734
    assert float(account.cash_balance) == round(9994.90 - 6005.06, 2)

    # 4. 卖出超额拦截
    with pytest.raises(ValueError, match="持仓不足"):
        await execute_sell_order(
            trade_session,
            account.id,
            "sh600000",
            "浦发银行",
            price=15.0,
            quantity=2000,  # 现有 1500
        )

    # 5. 卖出 1000 股 @ 15.0元 (额 15000 - 费用 (佣金5 + 印花税7.5 + 过户0.15 = 12.65) = 净回款 14987.35)
    order3 = await execute_sell_order(
        trade_session,
        account.id,
        "sh600000",
        "浦发银行",
        price=15.0,
        quantity=1000,
    )
    assert float(pos.quantity) == 500
    assert round(float(pos.cost_price), 4) == 10.6734  # 剩余持仓成本不变
    assert order3.realized_pnl > 4300  # 14987.35 - 10673.44 = 4313.91
    assert float(pos.accumulated_pnl) == order3.realized_pnl

    # 验证资金流水与交易订单记录完整性
    orders = (
        (
            await trade_session.execute(
                select(TradeOrder).where(TradeOrder.account_id == account.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(orders) == 3

    flows = (
        (
            await trade_session.execute(
                select(TradeCashFlow).where(TradeCashFlow.account_id == account.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(flows) == 3
    assert flows[0].flow_type == "trade_buy"
    assert flows[1].flow_type == "trade_buy"
    assert flows[2].flow_type == "trade_sell"
