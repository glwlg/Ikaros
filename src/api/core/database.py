"""
SQLite 数据库连接管理模块
"""

from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

from api.core.config import settings

Base = declarative_base()

_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def _resolve_sqlite_path() -> Path:
    raw = str(settings.sqlite.database or "").strip()
    if not raw:
        raise RuntimeError("sqlite database path is empty")
    return Path(raw).expanduser().resolve()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = f"sqlite+aiosqlite:///{_resolve_sqlite_path()}"
        _engine = create_async_engine(
            db_url,
            echo=False,
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _async_session_maker
    if _async_session_maker is None:
        engine = get_engine()
        _async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    engine = get_engine()
    from api.auth.models import User, OAuthAccount  # noqa: F401
    from api.models.binding import PlatformUserBinding  # noqa: F401
    from api.models.camera import Camera  # noqa: F401
    from api.models.accounting import (  # noqa: F401
        Book,
        Account,
        AccountAlias,
        Category,
        Record,
        Budget,
        ScheduledTask,
        DebtOrReimbursement,
        StatsPanel,
        OperationLog,
    )
    from api.models.trade import (  # noqa: F401
        TradeAccount,
        TradePosition,
        TradeOrder,
        TradeCashFlow,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLite migrations for existing accounting tables
        def _run_sqlite_migrations(sync_conn):
            from sqlalchemy import text
            try:
                rec_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(accounting_records)"))}
                if rec_cols and "is_large_expense" not in rec_cols:
                    sync_conn.execute(text("ALTER TABLE accounting_records ADD COLUMN is_large_expense BOOLEAN NOT NULL DEFAULT 0"))
                if rec_cols and "exclude_from_budget" not in rec_cols:
                    sync_conn.execute(text("ALTER TABLE accounting_records ADD COLUMN exclude_from_budget BOOLEAN NOT NULL DEFAULT 0"))
                    sync_conn.execute(text("UPDATE accounting_records SET exclude_from_budget = 1 WHERE remark LIKE '股票收盘自动对齐%'"))
            except Exception:
                pass
            try:
                bgt_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(accounting_budgets)"))}
                if bgt_cols:
                    if "budget_type" not in bgt_cols:
                        sync_conn.execute(text("ALTER TABLE accounting_budgets ADD COLUMN budget_type VARCHAR(20) NOT NULL DEFAULT 'monthly'"))
                    if "period_key" not in bgt_cols:
                        sync_conn.execute(text("ALTER TABLE accounting_budgets ADD COLUMN period_key VARCHAR(10) NOT NULL DEFAULT ''"))
                        sync_conn.execute(text("UPDATE accounting_budgets SET period_key = month WHERE period_key = '' OR period_key IS NULL"))
                    if "monthly_provision" not in bgt_cols:
                        sync_conn.execute(text("ALTER TABLE accounting_budgets ADD COLUMN monthly_provision NUMERIC(12, 2) NOT NULL DEFAULT 0"))
                    if "pool_name" not in bgt_cols:
                        sync_conn.execute(text("ALTER TABLE accounting_budgets ADD COLUMN pool_name VARCHAR(50) NOT NULL DEFAULT ''"))
            except Exception:
                pass
            try:
                acc_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(accounting_accounts)"))}
                if acc_cols and "trade_account_id" not in acc_cols:
                    sync_conn.execute(text("ALTER TABLE accounting_accounts ADD COLUMN trade_account_id INTEGER REFERENCES trade_accounts(id) ON DELETE SET NULL"))
            except Exception:
                pass
        try:
            await conn.run_sync(_run_sqlite_migrations)
        except Exception:
            pass
