import pytest

from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    _display_width,
    _parse_sina_search_results,
    _parse_tencent_quote_content,
    fetch_stock_quotes,
    format_stock_message,
)


def test_format_stock_message_keeps_existing_output_without_previous_prices():
    message = format_stock_message(
        [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 7.88,
                "change": 0.12,
                "percent": 1.55,
            }
        ]
    )

    assert "大秦铁路 7.88 +1.55%" in message
    assert "↑" not in message
    assert "↓" not in message


def test_format_stock_message_adds_direction_against_previous_push_prices():
    message = format_stock_message(
        [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 7.88,
                "change": 0.12,
                "percent": 1.55,
            },
            {
                "code": "sz000001",
                "name": "平安银行",
                "price": 12.10,
                "change": -0.20,
                "percent": -1.63,
            },
            {
                "code": "sh600000",
                "name": "浦发银行",
                "price": 8.00,
                "change": 0,
                "percent": 0,
            },
        ],
        {
            "sh601006": 7.80,
            "sz000001": 12.50,
            "sh600000": 8.00,
        },
    )

    assert "大秦铁路 7.88 +1.55%↑" in message
    assert "平安银行 12.1 -1.63%↓" in message
    assert "浦发银行 8 0%" in message
    assert "浦发银行 8 0%→" not in message


def test_format_stock_message_includes_daily_and_holding_profit():
    message = format_stock_message(
        [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 8.0,
                "change": 0.2,
                "percent": 2.56,
            },
            {
                "code": "sz000001",
                "name": "平安银行",
                "price": 10.0,
                "change": -0.1,
                "percent": -0.99,
            },
            {
                "code": "sh601398",
                "name": "工商银行",
                "price": 8.0,
                "change": -0.02,
                "percent": -0.25,
            },
            {
                "code": "sz000002",
                "name": "红太阳",
                "price": 4.65,
                "change": 0.03,
                "percent": 0.65,
            },
        ],
        positions=[
            {
                "stock_code": "sh601006",
                "position_quantity": 100,
                "cost_price": 7.5,
            },
            {
                "stock_code": "sz000001",
                "position_quantity": 200,
                "cost_price": 11.0,
            },
            {
                "stock_code": "sh601398",
                "position_quantity": 800,
                "cost_price": 0.0001,
            },
            {
                "stock_code": "sz000002",
                "position_quantity": 3000,
                "cost_price": 7.025,
            },
        ],
    )

    assert "今日盈亏：+74.00元" in message
    assert "持仓盈亏：" in message
    assert "1手 今+20 浮+50(+6.7%)" in message
    assert "2手 今-20 浮-200(-9.1%)" in message
    assert "8手 今-16 浮+6400(+8万倍)" in message
    assert "30手 今+90 浮-7125(-34%)" in message
    assert "大秦铁路 8 +2.56%" in message
    assert "平安银行 10 -0.99%" in message
    assert "红太阳　" in message
    assert "**🔴大秦铁路 8 +2.56%**" in message
    assert "**🟢平安银行 10 -0.99%**" not in message

    quote_line = next(
        line for line in message.splitlines() if "大秦铁路" in line and "平安银行" in line
    )
    detail_line = next(
        line
        for line in message.splitlines()
        if "1手 今+20 浮+50(+6.7%)" in line and "2手 今-20 浮-200(-9.1%)" in line
    )
    second_quote = next(
        line for line in message.splitlines() if "工商银行" in line and "红太阳" in line
    )
    second_detail = next(
        line
        for line in message.splitlines()
        if "8手 今-16 浮+6400(+8万倍)" in line and "30手 今+90 浮-7125(-34%)" in line
    )
    assert quote_line.index("大秦铁路") < quote_line.index("平安银行")
    assert detail_line.index("1手") < detail_line.index("2手")

    def visible_index(line: str, token: str) -> int:
        raw = line.index(token)
        return _display_width(line[:raw])

    assert abs(visible_index(quote_line, "平安银行") - visible_index(second_quote, "红太阳")) <= 2
    assert abs(visible_index(detail_line, "2手") - visible_index(second_detail, "30手")) <= 2


def test_format_stock_message_ignores_incomplete_position_data():
    message = format_stock_message(
        [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 7.88,
                "change": 0.12,
                "percent": 1.55,
            }
        ],
        positions=[
            {
                "stock_code": "sh601006",
                "position_quantity": 100,
            }
        ],
    )

    assert "今日盈亏" not in message
    assert "持仓盈亏" not in message


def test_parse_sina_search_results_keeps_a_share_results():
    results = _parse_sina_search_results(
        'var suggestvalue="仙鹤股份,11,603733,sh603733,仙鹤股份,,仙鹤股份,99,1,,,";'
    )

    assert results == [
        {"code": "sh603733", "name": "仙鹤股份", "market": "沪A"},
    ]


def test_parse_sina_search_results_normalizes_etf_to_quote_code():
    results = _parse_sina_search_results(
        'var suggestvalue="of159509,25,159509,of159509,景顺长城纳斯达克科技ETF(QDII),,'
        "景顺长城纳斯达克科技ETF(QDII),99,1,,,;of159509,22,159509,of159509,"
        '纳指科技ETF景顺,,纳指科技ETF景顺,99,1,,,";'
    )

    assert results == [
        {"code": "sz159509", "name": "纳指科技ETF景顺", "market": "ETF"},
    ]


def test_parse_sina_search_results_normalizes_shanghai_etf_to_quote_code():
    results = _parse_sina_search_results(
        'var suggestvalue="of510300,22,510300,of510300,沪深300ETF华泰柏瑞,,'
        '沪深300ETF华泰柏瑞,99,1,,,";'
    )

    assert results == [
        {"code": "sh510300", "name": "沪深300ETF华泰柏瑞", "market": "ETF"},
    ]


def test_parse_tencent_quote_content_maps_core_fields():
    # Minimal Tencent payload with required ~-separated fields.
    parts = [""] * 53
    parts[1] = "大秦铁路"
    parts[3] = "7.88"
    parts[4] = "7.76"
    parts[5] = "7.80"
    parts[31] = "0.12"
    parts[32] = "1.55"
    parts[33] = "7.90"
    parts[34] = "7.75"
    parts[39] = "12.3"
    parts[46] = "1.1"
    payload = "~".join(parts)
    content = f'v_sh601006="{payload}";'

    rows = _parse_tencent_quote_content(content)
    assert len(rows) == 1
    assert rows[0]["code"] == "sh601006"
    assert rows[0]["name"] == "大秦铁路"
    assert rows[0]["price"] == 7.88
    assert rows[0]["percent"] == 1.55
    assert rows[0]["source"] == "tencent"
    assert rows[0]["pe_ttm"] == 12.3


@pytest.mark.asyncio
async def test_fetch_stock_quotes_falls_back_to_tencent(monkeypatch):
    async def empty_sina(_codes):
        return []

    async def tencent_rows(codes):
        assert codes == ["sh601006"]
        return [
            {
                "code": "sh601006",
                "name": "大秦铁路",
                "price": 7.88,
                "change": 0.12,
                "percent": 1.55,
                "open": 7.8,
                "high": 7.9,
                "low": 7.75,
                "yesterday_close": 7.76,
                "source": "tencent",
                "pe_ttm": 0,
                "pb": 0,
            }
        ]

    monkeypatch.setattr(
        "extension.skills.learned.stock_watch.scripts.services.stock_service._fetch_sina_quotes",
        empty_sina,
    )
    monkeypatch.setattr(
        "extension.skills.learned.stock_watch.scripts.services.stock_service._fetch_tencent_quotes",
        tencent_rows,
    )

    rows = await fetch_stock_quotes(["sh601006"])
    assert rows[0]["source"] == "tencent"
    assert rows[0]["price"] == 7.88
