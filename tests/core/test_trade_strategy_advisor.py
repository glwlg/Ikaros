from api.models.trade import TradeAccount, TradePosition
from api.services.trade_strategy_advisor import evaluate_trade_advice


def test_cash_constraint_filtering():
    # 1. 账户现金为 0，即便触发加仓信号也拦截并降级为 hold
    acc_no_cash = TradeAccount(id=1, name="招商证券", cash_balance=0.0)
    pos = TradePosition(stock_code="sh600519", stock_name="贵州茅台", quantity=100, cost_price=1500.0)
    quote = {"code": "sh600519", "name": "贵州茅台", "price": 1450.0}

    advice1 = evaluate_trade_advice(
        account=acc_no_cash,
        position=pos,
        stock_quote=quote,
        base_signal="buy",
        total_account_assets=1000000.0,
        max_position_ratio=30.0,
    )
    assert advice1["final_signal"] == "hold"
    assert any("无可用现金" in note for note in advice1["risk_notes"])

    # 2. 现金不足一手，提示观望
    acc_low_cash = TradeAccount(id=1, name="招商证券", cash_balance=500.0)
    advice2 = evaluate_trade_advice(
        account=acc_low_cash,
        position=pos,
        stock_quote=quote,
        base_signal="buy",
        total_account_assets=1000000.0,
        max_position_ratio=30.0,
    )
    assert advice2["final_signal"] == "hold"
    assert any("不足买入一手" in note for note in advice2["risk_notes"])


def test_position_ceiling_filtering():
    # 账户现金充足，但该标的在账户中占比达到 40% (超过 30% 阈值)，限制加仓
    acc = TradeAccount(id=2, name="中信证券", cash_balance=60000.0)
    pos = TradePosition(stock_code="sz000001", stock_name="平安银行", quantity=4000, cost_price=10.0)
    quote = {"code": "sz000001", "name": "平安银行", "price": 10.0}
    total_assets = 100000.0  # 40000 / 100000 = 40%

    advice = evaluate_trade_advice(
        account=acc,
        position=pos,
        stock_quote=quote,
        base_signal="buy",
        total_account_assets=total_assets,
        max_position_ratio=30.0,
    )
    assert advice["final_signal"] == "hold"
    assert any("超过 30% 仓位上限" in note for note in advice["risk_notes"])


def test_normal_advice_pass_through():
    # 现金充足且持仓未超标，买入建议正常通过
    acc = TradeAccount(id=3, name="中信证券", cash_balance=80000.0)
    pos = TradePosition(stock_code="sz000001", stock_name="平安银行", quantity=1000, cost_price=10.0)
    quote = {"code": "sz000001", "name": "平安银行", "price": 10.0}
    total_assets = 90000.0  # 10000 / 90000 = 11.1%

    advice = evaluate_trade_advice(
        account=acc,
        position=pos,
        stock_quote=quote,
        base_signal="buy",
        total_account_assets=total_assets,
        max_position_ratio=30.0,
    )
    assert advice["final_signal"] == "buy"
    assert len(advice["risk_notes"]) == 0
