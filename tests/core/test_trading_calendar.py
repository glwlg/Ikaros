import datetime

from core.trading_calendar import (
    clear_trading_calendar_cache,
    is_a_share_trading_day,
    normalize_run_calendar,
    should_run_on_calendar,
)


def test_normalize_run_calendar_aliases():
    assert normalize_run_calendar("工作日") == "weekdays"
    assert normalize_run_calendar("交易日") == "trading_days"
    assert normalize_run_calendar("always") == "always"
    assert normalize_run_calendar("weird") == "always"


def test_should_run_weekdays_skips_weekend():
    saturday = datetime.date(2026, 8, 1)  # Saturday
    monday = datetime.date(2026, 8, 3)
    assert should_run_on_calendar("weekdays", saturday) is False
    assert should_run_on_calendar("weekdays", monday) is True
    assert should_run_on_calendar("always", saturday) is True


def test_trading_day_uses_holiday_feed(monkeypatch):
    clear_trading_calendar_cache()
    national_day = datetime.date(2026, 10, 1)

    monkeypatch.setattr(
        "core.trading_calendar._year_special_days",
        lambda year: ({national_day}, set()),
    )
    assert is_a_share_trading_day(national_day) is False
    assert is_a_share_trading_day(datetime.date(2026, 10, 9)) is True
    assert should_run_on_calendar("trading_days", national_day) is False
