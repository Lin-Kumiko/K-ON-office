"""Workbench summary and statistical reports (all computed from live data)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.deps import CurrentUser, get_db, require, scope_department_ids
from ..core.permissions import MENUS
from ..models import (Announcement, AnnouncementRead, Department, Employee, ExpenseCategory,
                      ExpenseClaim, ExpenseItem, LeaveBalance, LeaveRequest, LeaveType, MeetingBooking, MeetingRoom,
                      Notification, PerformanceReview, Schedule, WfInstance, WfTask)
from ..services import attendance
from ..workflow import registry
from .common import ERRORS

router = APIRouter(prefix="/api", tags=["工作台与报表"], responses=ERRORS)


def _months_back(n: int) -> list[str]:
    t = timeutil.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(f"{t:%Y-%m}")
        t = (t - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


@router.get("/dashboard/summary", summary="企业工作台汇总")
def summary(cu: CurrentUser = Depends(require("dashboard:view")), db: Session = Depends(get_db)):
    now = timeutil.now()
    today = now.date()
    pending = db.scalars(select(WfTask).where(WfTask.assignee_id == cu.id, WfTask.status == "pending")
                         .order_by(WfTask.id.desc())).all()
    todo = []
    for t in pending[:6]:
        inst = db.get(WfInstance, t.instance_id)
        todo.append({"task_id": t.id, "instance_id": inst.id, "title": inst.title, "node_name": t.node_name,
                     "business_type": inst.business_type, "created_at": t.created_at})
    mine = db.scalars(select(WfInstance).where(WfInstance.initiator_id == cu.id).order_by(WfInstance.id.desc())
                      .limit(6)).all()
    my_apps = [{"instance_id": i.id, "title": i.title, "status": i.status, "business_type": i.business_type,
                "started_at": i.started_at} for i in mine]
    running_mine = db.scalar(select(func.count()).select_from(WfInstance).where(
        WfInstance.initiator_id == cu.id, WfInstance.status == "running"))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == cu.id,
                                                                            Notification.read_at.is_(None)))
    # latest announcements visible to the user
    from .oa_misc import _visible_to_member
    reads = set(db.scalars(select(AnnouncementRead.announcement_id).where(AnnouncementRead.user_id == cu.id)))
    anns = [a for a in db.scalars(select(Announcement).where(Announcement.status == "published")
                                  .order_by(Announcement.pinned.desc(), Announcement.published_at.desc()))
            if _visible_to_member(db, cu, a)]
    announcements = [{"id": a.id, "title": a.title, "pinned": a.pinned, "published_at": a.published_at,
                      "read": a.id in reads} for a in anns[:5]]
    recent_att, balance = [], None
    if cu.employee:
        from .attendance import day_records
        recs = [r for r in day_records(db, cu.employee, today - timedelta(days=13), today)
                if r.status not in ("rest", "holiday", "upcoming")][-7:]
        recent_att = [{"work_date": r.work_date, "status": r.status, "check_in_at": r.check_in_at,
                       "check_out_at": r.check_out_at, "late_minutes": r.late_minutes} for r in reversed(recs)]
        b = db.scalar(select(LeaveBalance).join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id).where(
            LeaveBalance.employee_id == cu.employee.id, LeaveBalance.year == today.year, LeaveType.code == "annual"))
        if b:
            balance = {"total_hours": b.total_hours, "used_hours": b.used_hours, "pending_hours": b.pending_hours,
                       "available_hours": b.total_hours - b.used_hours - b.pending_hours}
    horizon = now + timedelta(days=7)
    reminders = [{"kind": "schedule", "id": s.id, "title": s.title, "start_at": s.start_at, "end_at": s.end_at}
                 for s in db.scalars(select(Schedule).where(Schedule.user_id == cu.id, Schedule.end_at >= now,
                                                            Schedule.start_at <= horizon).order_by(Schedule.start_at))]
    for b in db.scalars(select(MeetingBooking).where(MeetingBooking.status == "approved", MeetingBooking.end_at >= now,
                                                     MeetingBooking.start_at <= horizon)):
        if b.organizer_id == cu.id or cu.id in (b.attendee_ids or []):
            room = db.get(MeetingRoom, b.room_id)
            reminders.append({"kind": "meeting", "id": b.id, "title": f"{b.subject}（{room.name}）",
                              "start_at": b.start_at, "end_at": b.end_at})
    reminders.sort(key=lambda x: x["start_at"])
    # trend of my / company applications in the last 6 months
    months = _months_back(6)
    start = datetime.combine(date.fromisoformat(months[0] + "-01"), time())
    stmt = select(WfInstance.business_type, WfInstance.started_at).where(WfInstance.started_at >= start)
    company_view = cu.has("workflow:monitor") or cu.has("report:view")
    if not company_view:
        stmt = stmt.where(WfInstance.initiator_id == cu.id)
    trend: dict[str, dict[str, int]] = {}
    for bt, at in db.execute(stmt):
        trend.setdefault(bt, {m: 0 for m in months})[f"{at:%Y-%m}"] = trend.get(bt, {}).get(f"{at:%Y-%m}", 0) + 1
    series = [{"business_type": bt, "name": registry.BUSINESS_TYPES.get(bt, {}).get("name", bt),
               "data": [v.get(m, 0) for m in months]} for bt, v in sorted(trend.items())]
    stats = {"pending_tasks": len(pending), "running_applications": running_mine, "unread_notifications": unread,
             "unread_announcements": sum(1 for a in anns if a.id not in reads)}
    if company_view:
        depts = scope_department_ids(db, cu)
        emp_stmt = select(func.count()).select_from(Employee).where(Employee.status != "resigned")
        if depts is not None:
            emp_stmt = emp_stmt.where(Employee.department_id.in_(depts))
        stats["headcount"] = db.scalar(emp_stmt)
        stats["probation"] = db.scalar(select(func.count()).select_from(Employee).where(Employee.status == "probation"))
        stats["on_leave_today"] = db.scalar(select(func.count()).select_from(LeaveRequest).where(
            LeaveRequest.status == "approved", LeaveRequest.start_date <= today, LeaveRequest.end_date >= today))
        stats["running_instances"] = db.scalar(select(func.count()).select_from(WfInstance).where(
            WfInstance.status == "running"))
    quick = [m for m in MENUS if cu.has(m["perm"]) and m["key"] in
             ("leave", "expense", "attendance", "meeting", "travel", "documents", "approvals")]
    return {"user": {"name": cu.user.display_name, "employee_name": cu.employee.name if cu.employee else None},
            "stats": stats, "todo": todo, "my_applications": my_apps, "announcements": announcements,
            "recent_attendance": recent_att, "annual_leave": balance, "reminders": reminders[:8],
            "quick_entries": quick, "trend": {"months": months, "series": series}, "company_view": company_view}


@router.get("/reports/overview", summary="统计报表（按数据权限）")
def reports(month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            cu: CurrentUser = Depends(require("report:view")), db: Session = Depends(get_db)):
    month = month or f"{timeutil.today():%Y-%m}"
    depts = scope_department_ids(db, cu)
    emp_stmt = select(Employee)
    if depts is not None:
        emp_stmt = emp_stmt.where(Employee.department_id.in_(depts))
    emps = list(db.scalars(emp_stmt))
    ids = [e.id for e in emps]
    dnames = dict(db.execute(select(Department.id, Department.name)).all())
    headcount: dict[str, int] = {}
    status: dict[str, int] = {}
    for e in emps:
        status[e.status] = status.get(e.status, 0) + 1
        if e.status != "resigned":
            headcount[dnames.get(e.department_id, "?")] = headcount.get(dnames.get(e.department_id, "?"), 0) + 1
    months = _months_back(6)
    hires = {m: 0 for m in months}
    for e in emps:
        k = f"{e.hire_date:%Y-%m}"
        if k in hires:
            hires[k] += 1
    # leave by type (approved, last 6 months)
    lt = dict(db.execute(select(LeaveType.id, LeaveType.name)).all())
    leave_by_type: dict[str, int] = {}
    first = date.fromisoformat(months[0] + "-01")
    for r in db.scalars(select(LeaveRequest).where(LeaveRequest.status == "approved", LeaveRequest.start_date >= first,
                                                   LeaveRequest.employee_id.in_(ids))):
        leave_by_type[lt[r.leave_type_id]] = leave_by_type.get(lt[r.leave_type_id], 0) + r.hours
    # expense by category & month (approved/paid/archived)
    cats = dict(db.execute(select(ExpenseCategory.id, ExpenseCategory.name)).all())
    exp_by_cat: dict[str, int] = {}
    exp_by_month = {m: 0 for m in months}
    rows = db.execute(select(ExpenseItem.category_id, ExpenseItem.amount_cents, ExpenseClaim.submitted_at)
                      .join(ExpenseClaim, ExpenseClaim.id == ExpenseItem.claim_id)
                      .where(ExpenseClaim.status.in_(("approved", "paid", "archived")),
                             ExpenseClaim.employee_id.in_(ids))).all()
    for cid, cents, sub in rows:
        exp_by_cat[cats[cid]] = exp_by_cat.get(cats[cid], 0) + cents
        if sub and f"{sub:%Y-%m}" in exp_by_month:
            exp_by_month[f"{sub:%Y-%m}"] += cents
    # attendance for the month by department
    att = attendance.monthly_summary(db, [e for e in emps if e.status != "resigned"], month)
    att_by_dept: dict[str, dict] = {}
    for s in att:
        d = att_by_dept.setdefault(dnames.get(s["department_id"], "?"),
                                   {"late": 0, "early": 0, "absent": 0, "missing": 0, "leave_hours": 0, "workdays": 0})
        for k in d:
            d[k] += s[k]
    # workflow statistics
    wf_stmt = select(WfInstance)
    if depts is not None:
        wf_stmt = wf_stmt.where(WfInstance.subject_employee_id.in_(ids))
    wf_status: dict[str, int] = {}
    durations: dict[str, list[float]] = {}
    for i in db.scalars(wf_stmt):
        wf_status[i.status] = wf_status.get(i.status, 0) + 1
        if i.ended_at and i.status == "approved":
            durations.setdefault(i.business_type, []).append((i.ended_at - i.started_at).total_seconds() / 3600)
    wf_avg = [{"business_type": registry.BUSINESS_TYPES.get(k, {}).get("name", k), "count": len(v),
               "avg_hours": round(sum(v) / len(v), 2)} for k, v in sorted(durations.items())]
    grades: dict[str, int] = {}
    for g, in db.execute(select(PerformanceReview.grade).where(PerformanceReview.status == "confirmed",
                                                                PerformanceReview.employee_id.in_(ids))):
        grades[g] = grades.get(g, 0) + 1
    return {"month": month, "scope": "all" if depts is None else "department",
            "headcount_by_department": headcount, "employee_status": status,
            "hires_by_month": {"months": months, "data": [hires[m] for m in months]},
            "leave_hours_by_type": leave_by_type,
            "expense_by_category": {k: round(v / 100, 2) for k, v in exp_by_cat.items()},
            "expense_by_month": {"months": months, "data": [round(exp_by_month[m] / 100, 2) for m in months]},
            "attendance_by_department": att_by_dept, "workflow_status": wf_status, "workflow_avg_duration": wf_avg,
            "performance_grades": grades}
