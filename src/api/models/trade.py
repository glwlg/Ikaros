from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


class TradeAccount(Base):
    """交易账户模型"""

    __tablename__ = "trade_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    broker: Mapped[str] = mapped_column(String(50), default="通用券商", nullable=False)
    cash_balance: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0.0, nullable=False
    )
    commission_rate: Mapped[float] = mapped_column(
        Numeric(8, 6), default=0.00025, nullable=False
    )  # 佣金率（默认万2.5）
    min_commission: Mapped[float] = mapped_column(
        Numeric(8, 2), default=5.0, nullable=False
    )  # 最低佣金（默认5元）
    stamp_duty_rate: Mapped[float] = mapped_column(
        Numeric(8, 6), default=0.0005, nullable=False
    )  # 印花税率（默认万5，仅卖出）
    transfer_fee_rate: Mapped[float] = mapped_column(
        Numeric(8, 6), default=0.00001, nullable=False
    )  # 过户费率（默认十万分之1）
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    positions: Mapped[list["TradePosition"]] = relationship(
        "TradePosition", back_populates="account", cascade="all, delete-orphan"
    )
    orders: Mapped[list["TradeOrder"]] = relationship(
        "TradeOrder", back_populates="account", cascade="all, delete-orphan"
    )
    cash_flows: Mapped[list["TradeCashFlow"]] = relationship(
        "TradeCashFlow", back_populates="account", cascade="all, delete-orphan"
    )


class TradePosition(Base):
    """账户持仓标的模型"""

    __tablename__ = "trade_positions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "stock_code",
            name="uq_trade_position_account_stock",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("trade_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), default=0.0, nullable=False)
    cost_price: Mapped[float] = mapped_column(
        Numeric(14, 4), default=0.0, nullable=False
    )
    accumulated_pnl: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0.0, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    account: Mapped["TradeAccount"] = relationship("TradeAccount", back_populates="positions")


class TradeOrder(Base):
    """交易订单流水模型（买入/卖出交割记录）"""

    __tablename__ = "trade_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("trade_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # 'buy' or 'sell'
    price: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)  # price * quantity
    commission: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=False
    )
    stamp_duty: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=False
    )
    transfer_fee: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=False
    )
    total_fee: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=False
    )
    net_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )  # 买入: amount + total_fee; 卖出: amount - total_fee
    realized_pnl: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0.0, nullable=False
    )
    cost_price_after: Mapped[float] = mapped_column(
        Numeric(14, 4), default=0.0, nullable=False
    )
    holding_after: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0.0, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transacted_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    account: Mapped["TradeAccount"] = relationship("TradeAccount", back_populates="orders")


class TradeCashFlow(Base):
    """资金流水模型（银证转账、交易出入款）"""

    __tablename__ = "trade_cash_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("trade_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flow_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # 'deposit', 'withdraw', 'trade_buy', 'trade_sell', 'dividend'
    amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )  # 变动金额（流入为正，流出为负）
    balance_after: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    related_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("trade_orders.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transacted_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    account: Mapped["TradeAccount"] = relationship("TradeAccount", back_populates="cash_flows")
