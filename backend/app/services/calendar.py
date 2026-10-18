"""Working calendar: weekends, configurable holidays and make-up workdays."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import ValidationFailed
from ..core.timeutil import daterange
from ..models import Holiday

HALF_HOURS = 4
DAY_HOURS = 8


def holiday_map(db: Session, start: date, end: date) -> dict[date, str]:
    rows = db.execute(select(Holiday.day, Holiday.kind).where(Holiday.day >= start, Holiday.day <= end)).all()
    return {d: k for d, k in rows}


def is_workday(d: date, hmap: dict[date, str]) -> bool:
    kind = hmap.get(d)
    if kind == "holiday":
        return False
    if kind == "workday":
        return True
    return d.weekday() < 5


def leave_slots(start_date: date, start_half: str, end_date: date, end_half: str) -> list[tuple[date, str]]:
    """All half-day slots covered by a leave range, ignoring the calendar."""
    out = []
    for d in daterange(start_date, end_date):
        for half in ("AM", "PM"):
            if d == start_date and start_half == "PM" and half == "AM":
                continue
            if d == end_date and end_half == "AM" and half == "PM":
                continue
            out.append((d, half))
    return out


def validate_range(start_date: date, start_half: str, end_date: date, end_half: str, max_days: int = 60) -> None:
    if start_half not in ("AM", "PM") or end_half not in ("AM", "PM"):
        raise ValidationFailed("半天标识只能是 AM 或 PM", code="INVALID_HALF")
    if end_date < start_date:
        raise ValidationFailed("结束日期不能早于开始日期", code="INVALID_DATE_RANGE")
    if start_date == end_date and start_half == "PM" and end_half == "AM":
        raise ValidationFailed("同一天内结束时段不能早于开始时段", code="INVALID_DATE_RANGE")
    if start_date.year != end_date.year:
        raise ValidationFailed("请假不能跨自然年，请按年度拆分申请", code="CROSS_YEAR_LEAVE")
    if (end_date - start_date).days > max_days:
        raise ValidationFailed(f"单次请假跨度不能超过 {max_days} 天", code="LEAVE_TOO_LONG")


def calc_leave_hours(hmap: dict[date, str], start_date: date, start_half: str, end_date: date,
                     end_half: str) -> tuple[int, dict[date, int]]:
    """Hours = 4 per working half-day slot. Weekends/holidays are excluded, make-up workdays included."""
    validate_range(start_date, start_half, end_date, end_half)
    per_day: dict[date, int] = {}
    for d, _half in leave_slots(start_date, start_half, end_date, end_half):
        if is_workday(d, hmap):
            per_day[d] = per_day.get(d, 0) + HALF_HOURS
    total = sum(per_day.values())
    return total, per_day


def calc_leave_hours_db(db: Session, start_date: date, start_half: str, end_date: date, end_half: str):
    hmap = holiday_map(db, start_date, end_date + timedelta(days=0))
    return calc_leave_hours(hmap, start_date, start_half, end_date, end_half)


def count_workdays(hmap: dict[date, str], start: date, end: date) -> int:
    return sum(1 for d in daterange(start, end) if is_workday(d, hmap))
