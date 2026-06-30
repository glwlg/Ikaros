from extension.skills.learned.stock_watch.scripts.services.stock_service import (
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
