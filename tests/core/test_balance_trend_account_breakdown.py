from datetime import datetime
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.api.accounting_router as accounting_router_module
from api.auth.models import User
from api.core.database import Base
from api.models.accounting import Account, Book, Record
from api.models.trade import TradeAccount  # noqa: F401


@pytest.fixture
async def trend_session(tmp_path):
    db_path = tmp_path / "trend-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_balance_trend_returns_account_breakdown(trend_session):
    user = User(
        email="trend_user@example.com",
        hashed_password="dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    trend_session.add(user)
    await trend_session.flush()

    book = Book(name="资产趋势账本", owner_id=user.id)
    trend_session.add(book)
    await trend_session.flush()

    acc1 = Account(
        book_id=book.id,
        name="招商银行",
        type="储蓄卡",
        balance=10000.0,
        include_in_assets=True,
    )
    acc2 = Account(
        book_id=book.id,
        name="中信证券",
        type="股票",
        balance=20000.0,
        include_in_assets=True,
    )
    trend_session.add_all([acc1, acc2])
    await trend_session.flush()

    # 在 2026-08 月份：
    # acc1 收入 5000
    # acc2 支出 2000
    r1 = Record(
        book_id=book.id,
        type="收入",
        amount=5000.0,
        account_id=acc1.id,
        record_time=datetime(2026, 8, 10, 10, 0, 0),
        creator_id=user.id,
    )
    r2 = Record(
        book_id=book.id,
        type="支出",
        amount=2000.0,
        account_id=acc2.id,
        record_time=datetime(2026, 8, 15, 14, 0, 0),
        creator_id=user.id,
    )
    # 在 2026-09 月份：
    # acc1 转账 3000 到 acc2
    r3 = Record(
        book_id=book.id,
        type="转账",
        amount=3000.0,
        account_id=acc1.id,
        target_account_id=acc2.id,
        record_time=datetime(2026, 9, 5, 9, 30, 0),
        creator_id=user.id,
    )
    trend_session.add_all([r1, r2, r3])
    await trend_session.commit()

    # 查询月度趋势
    rows = await accounting_router_module.get_balance_trend(
        book_id=book.id,
        start_date="2026-08-01",
        end_date="2026-10-01",
        granularity="month",
        scope="net",
        user=user,
        session=trend_session,
    )

    assert len(rows) == 2
    row_aug = next(r for r in rows if r["period"] == "2026-08")
    row_sep = next(r for r in rows if r["period"] == "2026-09")

    # 验证 8 月总变动与各账户细分
    # 8月：acc1 +5000，acc2 -2000，净变动 +3000
    assert row_aug["change"] == 3000.0
    aug_acc_map = {item["account_id"]: item for item in row_aug["account_changes"]}
    assert aug_acc_map[acc1.id]["change"] == 5000.0
    assert aug_acc_map[acc1.id]["end_balance"] == 15000.0
    assert aug_acc_map[acc2.id]["change"] == -2000.0
    assert aug_acc_map[acc2.id]["end_balance"] == 18000.0

    # 验证 9 月总变动与各账户细分
    # 9月：内部转账 3000，净资产总变动 0
    # acc1 -3000，acc2 +3000
    assert row_sep["change"] == 0.0
    sep_acc_map = {item["account_id"]: item for item in row_sep["account_changes"]}
    assert sep_acc_map[acc1.id]["change"] == -3000.0
    assert sep_acc_map[acc1.id]["end_balance"] == 12000.0
    assert sep_acc_map[acc2.id]["change"] == 3000.0
    assert sep_acc_map[acc2.id]["end_balance"] == 21000.0
