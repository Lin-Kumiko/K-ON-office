"""Company-local time helpers.

All business datetimes are stored as naive datetimes in the company timezone
(default Asia/Shanghai). Incoming aware datetimes are converted; naive ones are
taken as company-local.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_TZ_NAME = "Asia/Shanghai"
_TZ = ZoneInfo(_TZ_NAME)
# Tests may freeze "now" by assigning a callable here.
_now_override = None


def configure(tz_name: str) -> None:
    global _TZ, _TZ_NAME
    _TZ_NAME = tz_name
    _TZ = ZoneInfo(tz_name)


def tz() -> ZoneInfo:
    return _TZ


def set_fixed_now(value: datetime | None) -> None:
    """Freeze the business clock (tests / reproducible demos only)."""
    global _now_override
    _now_override = (lambda: value) if value is not None else None


def now() -> datetime:
    if _now_override is not None:
        return _now_override()
    return datetime.now(_TZ).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def to_local(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(_TZ).replace(tzinfo=None)
    return value.replace(microsecond=0)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(x) for x in month.split("-"))
    start = date(year, mon, 1)
    nxt = date(year + (mon // 12), mon % 12 + 1, 1)
    return start, nxt - timedelta(days=1)
