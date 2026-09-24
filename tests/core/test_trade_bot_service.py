import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.auth.models import User
from api.core.database import Base
from api.models.binding import PlatformUserBinding
from api.models.trade import TradeAccount, TradePosition
from api.services.trade_bot_service import (
    parse_trade_instruction,
    execute_bot_trade_action,
)


def test_parse_natural_language_trade():
    # 1. 在中信以 1.662 买入 40 手电网
    p1 = parse_trade_instruction("在中信以 1.662 买入 40 手电网")
    assert p1 is not None
    assert p1["action"] == "buy"
    assert p1["account_keyword"] == "中信"
    assert p1["stock_keyword"] == "电网"
    assert p1["price"] == 1.662
    assert p1["quantity"] == 4000.0  # 40手 = 4000股

    # 2. 在招商证券以 15.0 买入 1000股 浦发银行
    p2 = parse_trade_instruction("在招商证券以 15.0 买入 1000股 浦发银行")
    assert p2 is not None
    assert p2["action"] == "buy"
    assert p2["account_keyword"] == "招商"
    assert p2["stock_keyword"] == "浦发银行"
    assert p2["price"] == 15.0
    assert p2["quantity"] == 1000.0

    # 3. 卖出 500股 浦发银行 16.5
    p3 = parse_trade_instruction("以 16.5 卖出 500股 浦发银行")
    assert p3 is not None
    assert p3["action"] == "sell"
    assert p3["price"] == 16.5
    assert p3["quantity"] == 500.0

    # 4. /stock 结构化指令
    p4 = parse_trade_instruction("/stock buy 中信 sh600519 1650 100")
    assert p4 is not None
    assert p4["action"] == "buy"
    assert p4["account_keyword"] == "中信"
    assert p4["stock_keyword"] == "sh600519"
    assert p4["price"] == 1650.0
    assert p4["quantity"] == 100.0

    # 5. /stock accounts
    p5 = parse_trade_instruction("/stock accounts")
    assert p5 == {"action": "accounts"}

    # 6. 转账出入金
    p6 = parse_trade_instruction("在中信转入 10000 元")
    assert p6 is not None
    assert p6["action"] == "cash_flow"
    assert p6["flow_type"] == "deposit"
    assert p6["account_keyword"] == "中信"
    assert p6["amount"] == 10000.0


@pytest.fixture
async def bot_trade_session(tmp_path, monkeypatch):
    db_path = tmp_path / "bot-trade-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("api.services.trade_bot_service.get_session_maker", lambda: session_maker)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_execute_bot_trade_action_flow(bot_trade_session, monkeypatch):
    # 初始化用户与中信证券账户
    user = User(
        email="bot_trader@example.com",
        hashed_password="dummy",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    bot_trade_session.add(user)
    await bot_trade_session.flush()

    binding = PlatformUserBinding(
        user_id=user.id,
        platform="telegram",
        platform_user_id="tg_12345",
    )
    bot_trade_session.add(binding)

    account = TradeAccount(
        user_id=user.id,
        name="中信证券",
        broker="中信证券",
        cash_balance=20000.0,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    bot_trade_session.add(account)
    await bot_trade_session.commit()

    # Mock 行情与股票搜索
    async def fake_search(kw):
        return [{"code": "sz000001", "name": "平安银行"}]

    monkeypatch.setattr("api.services.trade_bot_service.search_stock_by_name", fake_search)

    # 1. 模拟买入执行
    parsed_buy = {
        "action": "buy",
        "account_keyword": "中信",
        "stock_keyword": "平安银行",
        "price": 12.0,
        "quantity": 1000.0,
    }
    reply = await execute_bot_trade_action("telegram", "tg_12345", parsed_buy)
    assert "买入交割已记账" in reply
    assert "平安银行" in reply
    assert "中信证券" in reply
    assert "最新摊薄成本价" in reply

    # 2. 模拟查看账户
    reply_acc = await execute_bot_trade_action("telegram", "tg_12345", {"action": "accounts"})
    assert "多账户资产全景" in reply_acc
    assert "中信证券" in reply_acc
