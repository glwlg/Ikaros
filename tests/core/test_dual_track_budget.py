from datetime import UTC, datetime
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.api.accounting_router as accounting_router_module
from api.auth.models import User
from api.core.database import Base
from api.models.accounting import Book, Record, Budget, Category

@pytest.fixture
async def accounting_session(tmp_path):
    db_path = tmp_path / "dual-track-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()

async def _setup_user_and_book(session):
    user = User(
        email="budget-test@example.com",
        hashed_password="dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    book = Book(name="家庭账本", owner_id=user.id)
    session.add(book)
    await session.flush()
    return user, book

@pytest.mark.asyncio
async def test_dual_track_budget_summary_and_exclusion(accounting_session):
    user, book = await _setup_user_and_book(accounting_session)

    # 1. 设置常规月度预算 7800 元
    await accounting_router_module.create_or_update_budget(
        book.id,
        accounting_router_module.BudgetUpdate(
            month="2026-09",
            period_key="2026-09",
            budget_type="monthly",
            total_amount=7800.0,
        ),
        user=user,
        session=accounting_session,
    )

    # 2. 设置年度大额专项资金池 60000 元，月度计划计提 5000 元
    await accounting_router_module.create_or_update_budget(
        book.id,
        accounting_router_module.BudgetUpdate(
            month="2026",
            period_key="2026",
            budget_type="annual_pool",
            total_amount=60000.0,
            monthly_provision=5000.0,
            pool_name="年度大额专项池",
        ),
        user=user,
        session=accounting_session,
    )

    # 3. 记录常规生活支出 (3450 元)
    rec_routine = await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=3450.0,
            category_name="餐饮美食",
            account_name="微信",
            record_time="2026-09-05T12:00:00",
            is_large_expense=False,
        ),
    )

    # 4. 记录年度大额专项支出（房租 6600 元，打标 is_large_expense=True）
    rec_large = await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=6600.0,
            category_name="房租",
            account_name="招商银行",
            record_time="2026-09-10T10:00:00",
            is_large_expense=True,
        ),
    )

    # 5. 查询 dual-track-summary
    summary = await accounting_router_module.get_dual_track_summary(
        book.id,
        year=2026,
        month=9,
        user=user,
        session=accounting_session,
    )

    # 验证常规月度预算：已支出 3450，不包含 6600 房租
    routine = summary["routine_budget"]
    assert routine["budget_amount"] == 7800.0
    assert routine["spent_amount"] == 3450.0
    assert routine["remaining_amount"] == 4350.0
    assert routine["usage_percent"] == 44.23

    # 验证年度大额专项资金池：截至 9 月累计计提 45000 (5000*9)，已核销 6600，当前结余 38400
    pool = summary["annual_pool"]
    assert pool["annual_budget_limit"] == 60000.0
    assert pool["monthly_provision"] == 5000.0
    assert pool["accumulated_provision"] == 45000.0
    assert pool["spent_total"] == 6600.0
    assert pool["current_balance"] == 38400.0
    assert pool["usage_percent"] == 11.0
    assert len(pool["records"]) == 1
    assert pool["records"][0]["id"] == rec_large.id

@pytest.mark.asyncio
async def test_batch_large_expense_organize(accounting_session):
    user, book = await _setup_user_and_book(accounting_session)

    r1 = await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=2000.0,
            category_name="车位费",
            record_time="2026-05-01T12:00:00",
            is_large_expense=False,
        ),
    )
    r2 = await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=50.0,
            category_name="餐饮",
            record_time="2026-05-02T12:00:00",
            is_large_expense=False,
        ),
    )

    res = await accounting_router_module.batch_update_large_expense(
        book.id,
        accounting_router_module.BatchLargeExpenseUpdate(
            is_large_expense=True,
            min_amount=1500.0,
            year=2026,
        ),
        user=user,
        session=accounting_session,
    )

    assert res["updated_count"] == 1
    updated_r1 = await accounting_session.get(Record, r1.id)
    updated_r2 = await accounting_session.get(Record, r2.id)
    assert updated_r1.is_large_expense is True
    assert updated_r2.is_large_expense is False

@pytest.mark.asyncio
async def test_get_records_amount_filter(accounting_session):
    user, book = await _setup_user_and_book(accounting_session)
    await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=200.0,
            category_name="日常",
        ),
    )
    await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=2000.0,
            category_name="大额",
        ),
    )
    records = await accounting_router_module.get_records(
        book.id,
        min_amount=1000.0,
        user=user,
        session=accounting_session,
    )
    assert len(records) == 1
    assert records[0]["amount"] == 2000.0


@pytest.mark.asyncio
async def test_exclude_from_budget_not_counted_in_routine_or_pool(accounting_session):
    user, book = await _setup_user_and_book(accounting_session)

    # 设置月度常规预算 10,000 元
    await accounting_router_module.create_or_update_budget(
        book.id,
        accounting_router_module.BudgetUpdate(
            month="2026-09",
            period_key="2026-09",
            budget_type="monthly",
            total_amount=10000.0,
        ),
        user=user,
        session=accounting_session,
    )

    # 1. 记一笔普通日常支出 300 元
    await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=300.0,
            category_name="餐饮",
            record_time="2026-09-10T12:00:00",
            is_large_expense=False,
            exclude_from_budget=False,
        ),
    )

    # 2. 记一笔股票对齐亏损 5917.2 元，标记为 exclude_from_budget=True
    stock_loss_rec = await accounting_router_module._create_record_entity(
        accounting_session,
        book_id=book.id,
        creator_id=user.id,
        data=accounting_router_module.RecordCreate(
            type="支出",
            amount=5917.2,
            category_name="未分类",
            remark="股票收盘自动对齐亏损：中信证券",
            record_time="2026-09-23T15:10:00",
            is_large_expense=False,
            exclude_from_budget=True,
        ),
    )

    # 3. 获取预算概览
    overview = await accounting_router_module.get_dual_track_summary(
        book.id,
        year=2026,
        month=9,
        user=user,
        session=accounting_session,
    )
    # 常规月度预算只计入 300 元，5917.2 元完全被排除！
    assert overview["routine_budget"]["spent_amount"] == 300.0
    assert overview["annual_pool"]["spent_total"] == 0.0

    # 4. 测试更新：如果取消不计入预算
    await accounting_router_module.update_record(
        stock_loss_rec.id,
        book.id,
        data=accounting_router_module.RecordUpdate(exclude_from_budget=False),
        user=user,
        session=accounting_session,
    )
    overview2 = await accounting_router_module.get_dual_track_summary(
        book.id,
        year=2026,
        month=9,
        user=user,
        session=accounting_session,
    )
    assert overview2["routine_budget"]["spent_amount"] == 6217.2

    # 5. 再次标记为不计入预算
    await accounting_router_module.update_record(
        stock_loss_rec.id,
        book.id,
        data=accounting_router_module.RecordUpdate(exclude_from_budget=True),
        user=user,
        session=accounting_session,
    )
    overview3 = await accounting_router_module.get_dual_track_summary(
        book.id,
        year=2026,
        month=9,
        user=user,
        session=accounting_session,
    )
    assert overview3["routine_budget"]["spent_amount"] == 300.0
