"""Attendance rules, punch attribution and the daily result calculator.

Rules
-----
* A shift runs work_start..work_end on its work date; ``cross_day`` shifts end on the next
  calendar day (e.g. 22:00-06:00).
* A punch belongs to the work date whose window
  [shift start - window_before, shift end + window_after] contains it. Rules are validated so
  windows of consecutive days never overlap.
* Earliest punch in the window = check-in, latest = check-out. Punches within 60 seconds of an
  existing punch are treated as duplicates (idempotent).
* Late  = check-in  > expected start + grace; Early = check-out < expected end - grace.
* Half-day leave moves the expected start (AM leave) or end (PM leave) to the break boundary.
* Non-workdays (weekend/holiday) are "rest"/"holiday"; full-day leave -> "leave"; approved
  travel -> "travel"; a past workday without punches -> "absent"; a day still in progress
  without a check-out is "pending".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.errors import ValidationFailed
from ..models import (AttendancePunch, AttendanceRecord, AttendanceRule, Employee, OvertimeRequest, TravelRequest)
from . import calendar
from .leave import approved_leave_halves

DUPLICATE_SECONDS = 60


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


@dataclass
class ShiftTimes:
    start: datetime
    end: datetime
    break_start: datetime
    break_end: datetime
    window_start: datetime
    window_end: datetime


def shift_times(rule: AttendanceRule, d: date) -> ShiftTimes:
    start = datetime.combine(d, _t(rule.work_start))
    end = datetime.combine(d + timedelta(days=1 if rule.cross_day else 0), _t(rule.work_end))
    if rule.break_start and rule.break_end:
        bs = datetime.combine(d, _t(rule.break_start))
        if bs < start:
            bs += timedelta(days=1)
        be = datetime.combine(bs.date(), _t(rule.break_end))
        if be < bs:
            be += timedelta(days=1)
    else:
        bs = be = start + (end - start) / 2
    return ShiftTimes(start, end, bs, be, start - timedelta(minutes=rule.window_before_minutes),
                      end + timedelta(minutes=rule.window_after_minutes))


def validate_rule(work_start: str, work_end: str, break_start: str | None, break_end: str | None,
                  cross_day: bool, before: int, after: int) -> None:
    try:
        ws, we = _t(work_start), _t(work_end)
        if break_start or break_end:
            if not (break_start and break_end):
                raise ValueError
            _t(break_start), _t(break_end)
    except (ValueError, AttributeError):
        raise ValidationFailed("时间格式应为 HH:MM", code="INVALID_RULE") from None
    if not cross_day and we <= ws:
        raise ValidationFailed("非跨天班次的下班时间必须晚于上班时间", code="INVALID_RULE")
    if cross_day and we >= ws:
        raise ValidationFailed("跨天班次的下班时间应早于上班时间（次日）", code="INVALID_RULE")
    dummy = AttendanceRule(work_start=work_start, work_end=work_end, break_start=break_start, break_end=break_end,
                           cross_day=cross_day, window_before_minutes=before, window_after_minutes=after)
    st = shift_times(dummy, date(2026, 1, 5))
    if not (st.start <= st.break_start <= st.break_end <= st.end):
        raise ValidationFailed("休息时间必须位于班次内", code="INVALID_RULE")
    if (st.window_end - st.window_start) > timedelta(hours=24):
        raise ValidationFailed("打卡窗口总长不能超过 24 小时，否则相邻两天无法区分", code="INVALID_RULE")


def rule_for(db: Session, employee: Employee) -> AttendanceRule:
    rule = db.get(AttendanceRule, employee.attendance_rule_id) if employee.attendance_rule_id else None
    if rule is None:
        rule = db.scalar(select(AttendanceRule).where(AttendanceRule.is_default.is_(True)))
    if rule is None:
        raise ValidationFailed("未配置默认考勤规则", code="NO_ATTENDANCE_RULE")
    return rule


def attribute_work_date(rule: AttendanceRule, at: datetime) -> date:
    for d in (at.date(), at.date() - timedelta(days=1)):
        st = shift_times(rule, d)
        if st.window_start <= at <= st.window_end:
            return d
    return at.date()


@dataclass
class DayResult:
    status: str
    expected_start: datetime | None
    expected_end: datetime | None
    check_in: datetime | None
    check_out: datetime | None
    late_minutes: int = 0
    early_minutes: int = 0
    leave_hours: int = 0
    is_travel: bool = False


def compute_day(rule: AttendanceRule, d: date, punches: list[datetime], workday: bool, holiday_kind: str | None,
                leave_halves: set[str], is_travel: bool, now: datetime) -> DayResult:
    st = shift_times(rule, d)
    punches = sorted(p for p in punches if st.window_start <= p <= st.window_end)
    if not workday:
        return DayResult("holiday" if holiday_kind == "holiday" else "rest", None, None,
                         punches[0] if punches else None, punches[-1] if len(punches) > 1 else None)
    leave_hours = calendar.HALF_HOURS * len(leave_halves & {"AM", "PM"})
    if leave_halves >= {"AM", "PM"}:
        return DayResult("leave", None, None, None, None, leave_hours=leave_hours)
    if is_travel:
        return DayResult("travel", None, None, punches[0] if punches else None, None, is_travel=True)
    exp_start, exp_end = st.start, st.end
    if "AM" in leave_halves:
        exp_start = st.break_end
    if "PM" in leave_halves:
        exp_end = st.break_start
    res = DayResult("normal", exp_start, exp_end, None, None, leave_hours=leave_hours)
    day_over = now >= exp_end
    if not punches:
        if now < exp_start:
            res.status = "upcoming"
        else:
            res.status = "absent" if day_over else "pending"
        return res
    if len(punches) == 1:
        midpoint = exp_start + (exp_end - exp_start) / 2
        if punches[0] < midpoint or not day_over:
            res.check_in = punches[0]
        else:
            res.check_out = punches[0]
    else:
        res.check_in, res.check_out = punches[0], punches[-1]
    if res.check_in and res.check_in > exp_start + timedelta(minutes=rule.late_grace_minutes):
        res.late_minutes = int((res.check_in - exp_start).total_seconds() // 60)
    if res.check_out and res.check_out < exp_end - timedelta(minutes=rule.early_grace_minutes):
        res.early_minutes = int((exp_end - res.check_out).total_seconds() // 60 + (
            1 if (exp_end - res.check_out).total_seconds() % 60 else 0))
    if res.check_in is None or res.check_out is None:
        if res.check_out is None and not day_over:
            res.status = "late" if res.late_minutes else "pending"
        else:
            res.status = "missing"
        return res
    if res.late_minutes and res.early_minutes:
        res.status = "late_early"
    elif res.late_minutes:
        res.status = "late"
    elif res.early_minutes:
        res.status = "early"
    return res


def _travel_days(db: Session, employee_ids: list[int] | None, start: date, end: date) -> set[tuple[int, date]]:
    stmt = select(TravelRequest).where(TravelRequest.status == "approved", TravelRequest.start_date <= end,
                                       TravelRequest.end_date >= start)
    if employee_ids is not None:
        stmt = stmt.where(TravelRequest.employee_id.in_(employee_ids))
    out = set()
    for t in db.scalars(stmt):
        for d in timeutil.daterange(max(t.start_date, start), min(t.end_date, end)):
            out.add((t.employee_id, d))
    return out


def compute_range(db: Session, employees: list[Employee], start: date, end: date) -> dict[tuple[int, date], DayResult | None]:
    """Pure computation of daily results (no writes). None = future day without leave/travel."""
    out: dict[tuple[int, date], DayResult | None] = {}
    if not employees or end < start:
        return out
    now = timeutil.now()
    today = now.date()
    ids = [e.id for e in employees]
    hmap = calendar.holiday_map(db, start, end)
    halves = approved_leave_halves(db, ids, start, end)
    travel = _travel_days(db, ids, start, end)
    punch_rows = db.execute(select(AttendancePunch.employee_id, AttendancePunch.work_date, AttendancePunch.punched_at)
                            .where(AttendancePunch.employee_id.in_(ids), AttendancePunch.work_date >= start,
                                   AttendancePunch.work_date <= end)).all()
    punches: dict[tuple[int, date], list[datetime]] = {}
    for eid, wd, at in punch_rows:
        punches.setdefault((eid, wd), []).append(at)
    rules: dict[int, AttendanceRule] = {}
    for emp in employees:
        rule = rules.get(emp.attendance_rule_id or 0)
        if rule is None:
            rule = rules[emp.attendance_rule_id or 0] = rule_for(db, emp)
        first = max(start, emp.hire_date)
        last = min(end, emp.resign_date) if emp.resign_date else end
        for d in timeutil.daterange(first, last):
            key = (emp.id, d)
            h = halves.get(key, set())
            is_tr = key in travel
            if d > today and not h and not is_tr:
                out[key] = None
                continue
            out[key] = compute_day(rule, d, punches.get(key, []), calendar.is_workday(d, hmap), hmap.get(d), h,
                                   is_tr, now)
    return out


def rebuild(db: Session, employees: list[Employee], start: date, end: date) -> int:
    """Recompute (upsert) daily records for employees over [start, end]. Idempotent."""
    results = compute_range(db, employees, start, end)
    if not results:
        return 0
    ids = [e.id for e in employees]
    existing = {(r.employee_id, r.work_date): r for r in db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.employee_id.in_(ids), AttendanceRecord.work_date >= start,
                                       AttendanceRecord.work_date <= end))}
    count = 0
    for key, r in results.items():
        rec = existing.get(key)
        if r is None:
            if rec is not None:
                db.delete(rec)
            continue
        if rec is None:
            rec = AttendanceRecord(employee_id=key[0], work_date=key[1])
            db.add(rec)
        rec.status = r.status
        rec.expected_start, rec.expected_end = r.expected_start, r.expected_end
        rec.check_in_at, rec.check_out_at = r.check_in, r.check_out
        rec.late_minutes, rec.early_minutes = r.late_minutes, r.early_minutes
        rec.leave_hours, rec.is_travel = r.leave_hours, r.is_travel
        count += 1
    db.flush()
    return count


def recompute_range(db: Session, employee_id: int, start: date, end: date) -> int:
    emp = db.get(Employee, employee_id)
    return rebuild(db, [emp], start, end) if emp else 0


def punch(db: Session, employee: Employee, at: datetime, source: str, ref_id: int | None = None):
    """Record a punch; returns (punch, record, duplicate)."""
    if employee.status == "resigned":
        raise ValidationFailed("离职员工不能打卡", code="EMPLOYEE_RESIGNED")
    at = timeutil.to_local(at).replace(microsecond=0)
    if at > timeutil.now() + timedelta(minutes=5):
        raise ValidationFailed("不能在未来时间打卡", code="FUTURE_PUNCH")
    dup = db.scalar(select(AttendancePunch).where(
        AttendancePunch.employee_id == employee.id,
        AttendancePunch.punched_at >= at - timedelta(seconds=DUPLICATE_SECONDS),
        AttendancePunch.punched_at <= at + timedelta(seconds=DUPLICATE_SECONDS)))
    rule = rule_for(db, employee)
    if dup is not None:
        rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == employee.id,
                                                       AttendanceRecord.work_date == dup.work_date))
        return dup, rec, True
    wd = attribute_work_date(rule, at)
    if wd < employee.hire_date:
        raise ValidationFailed("打卡日期早于入职日期", code="BEFORE_HIRE_DATE")
    p = AttendancePunch(employee_id=employee.id, punched_at=at, work_date=wd, source=source, ref_id=ref_id)
    db.add(p)
    db.flush()
    rebuild(db, [employee], wd, wd)
    rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == employee.id,
                                                   AttendanceRecord.work_date == wd))
    return p, rec, False


def monthly_summary(db: Session, employees: list[Employee], month: str) -> list[dict]:
    """Read-only monthly statistics computed from punches, leaves, travel and calendar."""
    start, end = timeutil.month_bounds(month)
    upto = min(end, timeutil.today())
    results = compute_range(db, employees, start, upto) if upto >= start else {}
    ids = [e.id for e in employees]
    ot_rows = db.scalars(select(OvertimeRequest).where(
        OvertimeRequest.employee_id.in_(ids), OvertimeRequest.status == "approved",
        OvertimeRequest.start_at >= datetime.combine(start, time()),
        OvertimeRequest.start_at < datetime.combine(end + timedelta(days=1), time()))).all() if ids else []
    hmap = calendar.holiday_map(db, start, end)
    by_emp: dict[int, dict] = {}
    for e in employees:
        first = max(start, e.hire_date)
        last = min(upto, e.resign_date) if e.resign_date else upto
        by_emp[e.id] = {
            "employee_id": e.id, "employee_no": e.employee_no, "name": e.name, "department_id": e.department_id,
            "workdays": calendar.count_workdays(hmap, first, last) if last >= first else 0,
            "normal": 0, "late": 0, "early": 0, "missing": 0, "absent": 0, "leave_hours": 0,
            "travel_days": 0, "late_minutes": 0, "early_minutes": 0, "overtime_hours": 0,
        }
    for (eid, _d), r in results.items():
        if r is None:
            continue
        s = by_emp[eid]
        if r.status == "normal":
            s["normal"] += 1
        if r.status in ("late", "late_early"):
            s["late"] += 1
        if r.status in ("early", "late_early"):
            s["early"] += 1
        if r.status == "missing":
            s["missing"] += 1
        if r.status == "absent":
            s["absent"] += 1
        if r.status == "travel":
            s["travel_days"] += 1
        s["leave_hours"] += r.leave_hours
        s["late_minutes"] += r.late_minutes
        s["early_minutes"] += r.early_minutes
    for o in ot_rows:
        by_emp[o.employee_id]["overtime_hours"] += o.hours
    return list(by_emp.values())


def clear_future_records(db: Session, employee_id: int, after: date) -> None:
    db.execute(delete(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id,
                                              AttendanceRecord.work_date > after))
