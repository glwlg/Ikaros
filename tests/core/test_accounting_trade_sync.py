import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.api.accounting_router as accounting_router_module
from api.auth.models import User
from api.core.database import Base
from api.models.accounting import Account, Book, Record
from api.models.trade import TradeAccount, TradePosition
from api.services.accounting_trade_sync import sync_account_with_trade_assets


@pytest.fixture
async def sync_session(tmp_path):
    db_path = tmp_path / "acc-trade-sync-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_accounting_account_bind_and_close_market_sync(sync_session, monkeypatch):
    # 1. 准备用户、账本与记账账户 (初始余额 10,000 元)
    user = User(
        email="investor@example.com",
        hashed_password="dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    sync_session.add(user)
    await sync_session.flush()

    book = Book(name="个人主账本", owner_id=user.id)
    sync_session.add(book)
    await sync_session.flush()

    acc = Account(
        book_id=book.id,
        name="中信证券股票账户",
        type="股票",
        balance=10000.0,
        include_in_assets=True,
    )
    sync_session.add(acc)
    await sync_session.flush()

    # 2. 准备股票交易账户 (现金 5,000 元，持仓 1000 股大秦铁路)
    trade_acc = TradeAccount(
        user_id=user.id,
        name="中信证券主账户",
        broker="中信证券",
        cash_balance=5000.0,
    )
    sync_session.add(trade_acc)
    await sync_session.flush()

    pos = TradePosition(
        account_id=trade_acc.id,
        stock_code="sh601006",
        stock_name="大秦铁路",
        quantity=1000,
        cost_price=7.0,
    )
    sync_session.add(pos)
    await sync_session.commit()

    # 3. 关联绑定
    bind_res = await accounting_router_module.bind_trade_account(
        account_id=acc.id,
        data=accounting_router_module.BindTradeAccountRequest(trade_account_id=trade_acc.id),
        user=user,
        session=sync_session,
    )
    assert bind_res["success"] is True
    assert bind_res["trade_account_id"] == trade_acc.id

    # 4. Mock 行情：大秦铁路现价 8.0 元 -> 股票总资产 = 5000 + 1000 * 8.0 = 13,000 元
    async def fake_quotes(codes):
        return [{"code": "sh601006", "price": 8.0}]

    monkeypatch.setattr(
        "api.services.accounting_trade_sync.fetch_stock_quotes",
        fake_quotes,
    )

    # 5. 执行收盘对齐（差额 = 13000 - 10000 = +3000）
    sync_res = await sync_account_with_trade_assets(sync_session, acc.id, user.id)
    assert sync_res["diff"] == 3000.0
    assert sync_res["record_type"] == "收入"
    assert sync_res["new_balance"] == 13000.0
    await sync_session.commit()

    # 查生成的账单记录
    records = (
        await sync_session.execute(
            select(Record).where(Record.account_id == acc.id)
        )
    ).scalars().all()
    assert len(records) == 1
    assert records[0].type == "收入"
    assert float(records[0].amount) == 3000.0
    assert "股票收盘自动对齐" in records[0].remark

    # 6. 再次对齐（差额为 0，不再重复插入）
    sync_res_again = await sync_account_with_trade_assets(sync_session, acc.id, user.id)
    assert sync_res_again["diff"] == 0.0
    assert sync_res_again["record_id"] is None

    # 7. 模拟次日股票下跌：大秦铁路跌至 6.0 元 -> 股票总资产 = 5000 + 1000 * 6.0 = 11,000 元
    async def fake_quotes_down(codes):
        return [{"code": "sh601006", "price": 6.0}]

    monkeypatch.setattr(
        "api.services.accounting_trade_sync.fetch_stock_quotes",
        fake_quotes_down,
    )

    sync_res_loss = await sync_account_with_trade_assets(sync_session, acc.id, user.id)
    assert sync_res_loss["diff"] == -2000.0  # 亏损 2000 元
    assert sync_res_loss["record_type"] == "支出"
    assert sync_res_loss["new_balance"] == 11000.0
    await sync_session.commit()

    records2 = (
        await sync_session.execute(
            select(Record).where(Record.account_id == acc.id)
        )
    ).scalars().all()
    assert len(records2) == 2
    assert records2[1].type == "支出"
    assert float(records2[1].amount) == 2000.0
