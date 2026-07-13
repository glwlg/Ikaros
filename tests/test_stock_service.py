from extension.skills.learned.stock_watch.scripts.services.stock_service import (
    _parse_sina_search_results,
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

    assert "大秦铁路 7.88 +1.55% ↑" in message
    assert "平安银行 12.1 -1.63% ↓" in message
    assert "浦发银行 8.0 0%" in message
    assert "浦发银行 8.0 0% →" not in message


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
        '景顺长城纳斯达克科技ETF(QDII),99,1,,,;of159509,22,159509,of159509,'
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
