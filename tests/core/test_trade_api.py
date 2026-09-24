import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.api.endpoints import trade as trade_api
from api.auth.models import User
from api.core.database import Base
from api.models.trade import TradeAccount, TradePosition


@pytest.fixture
async def trade_api_session(tmp_path):
    db_path = tmp_path / "trade-api-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_test_user(session, email="trade_api_user@test.com") -> User:
    user = User(
        email=email,
        hashed_password="hashed_dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_trade_account_crud_and_cash_flow(trade_api_session):
    user = await _create_test_user(trade_api_session)

    # 1. 创建账户
    create_res = await trade_api.create_account(
        trade_api.AccountCreate(
            name="中信证券机动账户",
            broker="中信证券",
            initial_cash=50000.0,
            commission_rate=0.0002,
            min_commission=5.0,
            stamp_duty_rate=0.0005,
            transfer_fee_rate=0.00001,
            notes="测试账户",
        ),
        current_user=user,
        session=trade_api_session,
    )
    assert create_res["success"] is True
    acc_id = create_res["id"]

    # 2. 查账户列表
    acc_list = await trade_api.list_accounts(
        current_user=user,
        session=trade_api_session,
    )
    assert len(acc_list) == 1
    assert acc_list[0]["name"] == "中信证券机动账户"
    assert acc_list[0]["cash_balance"] == 50000.0
    assert acc_list[0]["total_assets"] == 50000.0

    # 3. 银证转入与转出
    cf1 = await trade_api.handle_cash_flow(
        acc_id,
        trade_api.CashFlowCreate(flow_type="deposit", amount=10000.0, notes="追加资金"),
        current_user=user,
        session=trade_api_session,
    )
    assert cf1["balance_after"] == 60000.0

    cf2 = await trade_api.handle_cash_flow(
        acc_id,
        trade_api.CashFlowCreate(flow_type="withdraw", amount=5000.0, notes="取现"),
        current_user=user,
        session=trade_api_session,
    )
    assert cf2["balance_after"] == 55000.0

    # 4. 查资金流水列表
    flows = await trade_api.get_cash_flows(
        acc_id,
        current_user=user,
        session=trade_api_session,
    )
    assert len(flows) == 3  # 初始入金 + deposit + withdraw

    # 5. 直接修改校正可用现金
    update_res = await trade_api.update_account(
        acc_id,
        trade_api.AccountUpdate(
            name="中信证券机动账户",
            broker="中信证券",
            cash_balance=88888.0,
        ),
        current_user=user,
        session=trade_api_session,
    )
    assert update_res["success"] is True

    acc_after = await trade_api.list_accounts(current_user=user, session=trade_api_session)
    assert acc_after[0]["cash_balance"] == 88888.0

    flows_after = await trade_api.get_cash_flows(acc_id, current_user=user, session=trade_api_session)
    assert len(flows_after) == 4
    assert flows_after[0]["flow_type"] == "adjust"
    assert flows_after[0]["balance_after"] == 88888.0


@pytest.mark.asyncio
async def test_trade_orders_and_summary(trade_api_session, monkeypatch):
    user = await _create_test_user(trade_api_session, "user2@test.com")

    # Mock 行情
    async def fake_quotes(codes):
        return [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 8.0,
                "change": 0.2,
                "percent": 2.56,
            }
        ]

    monkeypatch.setattr(trade_api, "fetch_stock_quotes", fake_quotes)

    # 创建两个账户
    a1 = await trade_api.create_account(
        trade_api.AccountCreate(
            name="账户A",
            broker="券商A",
            initial_cash=20000.0,
        ),
        current_user=user,
        session=trade_api_session,
    )
    a2 = await trade_api.create_account(
        trade_api.AccountCreate(
            name="账户B",
            broker="券商B",
            initial_cash=30000.0,
        ),
        current_user=user,
        session=trade_api_session,
    )

    # 账户A 买入 1000 股大秦铁路 @ 7.50
    order_res = await trade_api.create_trade_order(
        trade_api.OrderCreate(
            account_id=a1["id"],
            stock_code="sh601006",
            stock_name="大秦铁路",
            trade_type="buy",
            price=7.50,
            quantity=1000,
        ),
        current_user=user,
        session=trade_api_session,
    )
    assert order_res["success"] is True
    assert order_res["holding_after"] == 1000

    # 账户A 持仓查询
    positions = await trade_api.get_account_positions(
        a1["id"],
        current_user=user,
        session=trade_api_session,
    )
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "sh601006"
    assert positions[0]["current_price"] == 8.0
    assert positions[0]["market_value"] == 8000.0
    assert positions[0]["unrealized_pnl"] > 0

    # 全景资产汇总看板
    summary = await trade_api.get_multi_accounts_summary(
        current_user=user,
        session=trade_api_session,
    )
    assert summary["accounts_count"] == 2
    assert summary["positions_count"] == 1
    assert summary["total_market_value"] == 8000.0
    assert len(summary["asset_distribution"]) == 2  # 现金 + 大秦铁路

    # 调仓加仓试算
    sim = await trade_api.simulate_order(
        trade_api.SimulateRequest(
            account_id=a1["id"],
            stock_code="sh601006",
            stock_name="大秦铁路",
            price=8.0,
            target_amount=5000.0,
        ),
        current_user=user,
        session=trade_api_session,
    )
    assert sim["simulated_quantity"] == 600  # 600 * 8 = 4800 <= 5000
    assert sim["is_sufficient"] is True
    assert sim["cash_shortage"] == 0.0
