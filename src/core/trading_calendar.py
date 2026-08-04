"""A-share trading day helpers (weekdays + China public holidays)."""

from __future__ import annotations

import datetime
import logging

import httpx

logger = logging.getLogger(__name__)

_HOLIDAY_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"
# year -> (holidays, makeup_workdays)
_YEAR_CACHE: dict[int, tuple[set[datetime.date], set[datetime.date]]] = {}

RUN_CALENDAR_ALWAYS = "always"
RUN_CALENDAR_WEEKDAYS = "weekdays"
RUN_CALENDAR_TRADING_DAYS = "trading_days"
VALID_RUN_CALENDARS = {
    RUN_CALENDAR_ALWAYS,
    RUN_CALENDAR_WEEKDAYS,
    RUN_CALENDAR_TRADING_DAYS,
}


def normalize_run_calendar(value: str | None) -> str:
    text = str(value or RUN_CALENDAR_ALWAYS).strip().lower()
    if text in {"weekday", "workday", "workdays", "工作日"}:
        return RUN_CALENDAR_WEEKDAYS
    if text in {"trading", "trading_day", "market", "交易日"}:
        return RUN_CALENDAR_TRADING_DAYS
    if text in VALID_RUN_CALENDARS:
        return text
    return RUN_CALENDAR_ALWAYS


def is_weekday(day: datetime.date | None = None) -> bool:
    current = day or datetime.date.today()
    return current.weekday() < 5


def _parse_year_calendar(payload: object) -> tuple[set[datetime.date], set[datetime.date]]:
    holidays: set[datetime.date] = set()
    makeups: set[datetime.date] = set()
    if not isinstance(payload, dict):
        return holidays, makeups
    days = payload.get("days")
    if not isinstance(days, list):
        return holidays, makeups
    for item in days:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("date") or "").strip()
        try:
            day = datetime.date.fromisoformat(raw)
        except ValueError:
            continue
        if bool(item.get("isOffDay", True)):
            holidays.add(day)
        else:
            makeups.add(day)
    return holidays, makeups


def _year_special_days(year: int) -> tuple[set[datetime.date], set[datetime.date]]:
    if year in _YEAR_CACHE:
        return _YEAR_CACHE[year]
    holidays: set[datetime.date] = set()
    makeups: set[datetime.date] = set()
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(_HOLIDAY_URL.format(year=year))
            response.raise_for_status()
            holidays, makeups = _parse_year_calendar(response.json())
    except Exception:
        logger.debug("Failed to load CN holiday calendar for %s", year, exc_info=True)
    _YEAR_CACHE[year] = (holidays, makeups)
    return holidays, makeups


def is_a_share_trading_day(day: datetime.date | None = None) -> bool:
    """True for A-share trading days.

    - Normal weekdays that are not public holidays
    - Weekend makeup workdays (调休上班) when the holiday feed is available
    - Falls back to plain weekdays when the holiday feed is empty/unavailable
    """
    current = day or datetime.date.today()
    holidays, makeups = _year_special_days(current.year)
    if current in makeups:
        return True
    if current.weekday() >= 5:
        return False
    if not holidays and not makeups:
        return True
    return current not in holidays


def should_run_on_calendar(
    run_calendar: str | None,
    day: datetime.date | None = None,
) -> bool:
    mode = normalize_run_calendar(run_calendar)
    current = day or datetime.date.today()
    if mode == RUN_CALENDAR_ALWAYS:
        return True
    if mode == RUN_CALENDAR_WEEKDAYS:
        return is_weekday(current)
    if mode == RUN_CALENDAR_TRADING_DAYS:
        return is_a_share_trading_day(current)
    return True


def run_calendar_label(run_calendar: str | None) -> str:
    mode = normalize_run_calendar(run_calendar)
    return {
        RUN_CALENDAR_ALWAYS: "每天",
        RUN_CALENDAR_WEEKDAYS: "仅工作日",
        RUN_CALENDAR_TRADING_DAYS: "仅交易日",
    }.get(mode, "每天")


def clear_trading_calendar_cache() -> None:
    _YEAR_CACHE.clear()


__all__ = [
    "RUN_CALENDAR_ALWAYS",
    "RUN_CALENDAR_TRADING_DAYS",
    "RUN_CALENDAR_WEEKDAYS",
    "VALID_RUN_CALENDARS",
    "clear_trading_calendar_cache",
    "is_a_share_trading_day",
    "is_weekday",
    "normalize_run_calendar",
    "run_calendar_label",
    "should_run_on_calendar",
]
