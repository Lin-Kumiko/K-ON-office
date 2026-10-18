"""Attendance: punches, daily records, rules, monthly statistics, corrections and overtime."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, idempotent, jsonable, paginate
from ..core.deps import (CurrentUser, PageParams, current_user, department_subtree, employee_scope_filter,
                         ensure_can_view_employee, get_db, require)
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import (AttendanceCorrection, AttendancePunch, AttendanceRecord, AttendanceRule, Employee,
                      OvertimeRequest)
from ..services import attendance as svc
from ..services import calendar
from ..services import documents_flow as flow
from ..services import org
from ..services.leave import approved_leave_halves
from .common import ERRORS, CommentIn, Msg, Page

router = APIRouter(prefix="/api/attendance", tags=["考勤"], responses=ERRORS)


class RecordOut(BaseModel):
    id: int | None
    employee_id: int
    employee_name: str | None = None
    work_date: date
    status: str
    expected_start: datetime | None
    expected_end: datetime | None
    check_in_at: datetime | None
    check_out_at: datetime | None
    late_minutes: int
    early_minutes: int
    leave_hours: int
    is_travel: bool


def rec_out(r: AttendanceRecord | None, names: dict | None = None) -> RecordOut | None:
    if r is None:
        return None
    return RecordOut(id=r.id, employee_id=r.employee_id, employee_name=(names or {}).get(r.employee_id),
                     work_date=r.work_date, status=r.status, expected_start=r.expected_start,
                     expected_end=r.expected_end, check_in_at=r.check_in_at, check_out_at=r.check_out_at,
                     late_minutes=r.late_minutes, early_minutes=r.early_minutes, leave_hours=r.leave_hours,
                     is_travel=r.is_travel)


class PunchIn(BaseModel):
    punch_time: datetime | None = Field(None, description="模拟打卡时间；为空则取服务器当前时间")


class PunchOut(BaseModel):
    punch_id: int
    punched_at: datetime
    work_date: date
    duplicate: bool
    source: str
    record: RecordOut | None


@router.post("/punch", response_model=PunchOut, summary="打卡（支持模拟时间；60 秒内重复打卡视为同一次）")
def do_punch(body: PunchIn, request: Request, cu: CurrentUser = Depends(require("attendance:punch")),
             db: Session = Depends(get_db)):
    emp = cu.require_employee()
    simulated = body.punch_time is not None
    if simulated and not (request.app.state.settings.simulation_mode or cu.has("attendance:manage")):
        raise Forbidden("当前环境不允许模拟打卡", code="SIMULATION_DISABLED")
    at = body.punch_time or timeutil.now()
    p, rec, dup = svc.punch(db, emp, at, "simulated" if simulated else "web")
    db.commit()
    return PunchOut(punch_id=p.id, punched_at=p.punched_at, work_date=p.work_date, duplicate=dup, source=p.source,
                    record=rec_out(rec))


def _target(db: Session, cu: CurrentUser, employee_id: int | None) -> Employee:
    if employee_id is None or (cu.employee and cu.employee.id == employee_id):
        return cu.require_employee()
    if not (cu.has("attendance:manage") or cu.has("employee:read")):
        raise Forbidden("无权查看他人考勤", code="DATA_SCOPE_DENIED")
    emp = org.get_employee(db, employee_id)
    ensure_can_view_employee(db, cu, emp)
    return emp


@router.get("/records", response_model=list[RecordOut], summary="个人日考勤（默认本人；按规则实时计算，含无打卡的缺勤日）")
def records(start: date, end: date, employee_id: int | None = None, cu: CurrentUser = Depends(current_user),
            db: Session = Depends(get_db)):
    if end < start or (end - start).days > 62:
        raise ValidationFailed("查询区间需在 62 天内", code="INVALID_RANGE")
    emp = _target(db, cu, employee_id)
    return day_records(db, emp, start, end)


def day_records(db: Session, emp: Employee, start: date, end: date) -> list[RecordOut]:
    persisted = {r.work_date: r.id for r in db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.employee_id == emp.id, AttendanceRecord.work_date >= start, AttendanceRecord.work_date <= end))}
    out = []
    for (eid, d), r in sorted(svc.compute_range(db, [emp], start, end).items(), key=lambda kv: kv[0][1]):
        if r is None:
            continue
        out.append(RecordOut(id=persisted.get(d), employee_id=eid, employee_name=emp.name, work_date=d, status=r.status,
                             expected_start=r.expected_start, expected_end=r.expected_end, check_in_at=r.check_in,
                             check_out_at=r.check_out, late_minutes=r.late_minutes, early_minutes=r.early_minutes,
                             leave_hours=r.leave_hours, is_travel=r.is_travel))
    return out


class PunchRow(BaseModel):
    id: int
    punched_at: datetime
    work_date: date
    source: str


@router.get("/punches", response_model=list[PunchRow], summary="打卡流水")
def punches(start: date, end: date, employee_id: int | None = None, cu: CurrentUser = Depends(current_user),
            db: Session = Depends(get_db)):
    emp = _target(db, cu, employee_id)
    rows = db.scalars(select(AttendancePunch).where(AttendancePunch.employee_id == emp.id,
                                                    AttendancePunch.work_date >= start,
                                                    AttendancePunch.work_date <= end).order_by(AttendancePunch.punched_at))
    return [PunchRow(id=p.id, punched_at=p.punched_at, work_date=p.work_date, source=p.source) for p in rows]


def _scoped_employees(db: Session, cu: CurrentUser, department_id: int | None) -> list[Employee]:
    stmt = select(Employee)
    if not cu.has("attendance:manage"):
        if not cu.has("employee:read"):
            stmt = stmt.where(Employee.id == (cu.employee.id if cu.employee else -1))
        else:
            f = employee_scope_filter(db, cu, Employee.id)
            if f is not None:
                stmt = stmt.where(f)
    if department_id:
        stmt = stmt.where(Employee.department_id.in_(department_subtree(db, department_id)))
    return list(db.scalars(stmt.order_by(Employee.employee_no)))


class MonthlyOut(BaseModel):
    employee_id: int
    employee_no: str
    name: str
    department_id: int
    workdays: int
    normal: int
    late: int
    early: int
    missing: int
    absent: int
    leave_hours: int
    travel_days: int
    late_minutes: int
    early_minutes: int
    overtime_hours: int


@router.get("/monthly", response_model=list[MonthlyOut], summary="月度统计（迟到/早退/缺卡/缺勤/请假/出差/加班）")
def monthly(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), department_id: int | None = None,
            cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    emps = _scoped_employees(db, cu, department_id)
    return svc.monthly_summary(db, emps, month)


class RebuildIn(BaseModel):
    start: date
    end: date
    department_id: int | None = None


@router.post("/rebuild", response_model=Msg, summary="重算考勤结果（幂等）")
def rebuild(body: RebuildIn, cu: CurrentUser = Depends(require("attendance:manage")), db: Session = Depends(get_db)):
    if body.end < body.start or (body.end - body.start).days > 92:
        raise ValidationFailed("重算区间需在 92 天内", code="INVALID_RANGE")
    emps = [e for e in _scoped_employees(db, cu, body.department_id)]
    n = svc.rebuild(db, emps, body.start, min(body.end, timeutil.today()))
    audit(db, cu, "rebuild_attendance", "attendance", None, {"start": str(body.start), "end": str(body.end), "n": n})
    db.commit()
    return Msg(message=f"已重算 {n} 条日考勤")


@router.get("/team", response_model=list[RecordOut], summary="团队某日考勤（按数据权限）")
def team_day(day: date, department_id: int | None = None, cu: CurrentUser = Depends(current_user),
             db: Session = Depends(get_db)):
    emps = _scoped_employees(db, cu, department_id)
    names = {e.id: e.name for e in emps}
    rows = db.scalars(select(AttendanceRecord).where(AttendanceRecord.employee_id.in_(list(names)),
                                                     AttendanceRecord.work_date == day)).all()
    return [rec_out(r, names) for r in rows]


# ------------------------------------------------------------------ rules
class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    work_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    work_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    break_start: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    break_end: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    cross_day: bool = False
    late_grace_minutes: int = Field(0, ge=0, le=120)
    early_grace_minutes: int = Field(0, ge=0, le=120)
    window_before_minutes: int = Field(240, ge=0, le=720)
    window_after_minutes: int = Field(360, ge=0, le=720)
    is_default: bool = False


class RuleOut(RuleIn):
    id: int


@router.get("/rules", response_model=list[RuleOut], summary="考勤规则")
def list_rules(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [RuleOut.model_validate(r, from_attributes=True) for r in db.scalars(select(AttendanceRule))]


def _save_rule(db: Session, r: AttendanceRule, body: RuleIn) -> None:
    svc.validate_rule(body.work_start, body.work_end, body.break_start, body.break_end, body.cross_day,
                      body.window_before_minutes, body.window_after_minutes)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    if body.is_default:
        for other in db.scalars(select(AttendanceRule).where(AttendanceRule.is_default.is_(True))):
            if other is not r:
                other.is_default = False


@router.post("/rules", response_model=RuleOut, status_code=201, summary="新增考勤规则")
def create_rule(body: RuleIn, cu: CurrentUser = Depends(require("attendance:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(AttendanceRule.id).where(AttendanceRule.name == body.name)):
        raise Conflict("规则名称已存在", code="RULE_EXISTS")
    r = AttendanceRule()
    _save_rule(db, r, body)
    db.add(r)
    db.flush()
    audit(db, cu, "create_attendance_rule", "attendance_rule", r.id)
    db.commit()
    return RuleOut.model_validate(r, from_attributes=True)


@router.put("/rules/{rule_id}", response_model=RuleOut, summary="修改考勤规则（不自动重算历史）")
def update_rule(rule_id: int, body: RuleIn, cu: CurrentUser = Depends(require("attendance:manage")),
                db: Session = Depends(get_db)):
    r = db.get(AttendanceRule, rule_id)
    if r is None:
        raise NotFound("规则不存在")
    if r.is_default and not body.is_default:
        raise ValidationFailed("必须保留一个默认规则", code="DEFAULT_RULE_REQUIRED")
    _save_rule(db, r, body)
    audit(db, cu, "update_attendance_rule", "attendance_rule", r.id)
    db.commit()
    return RuleOut.model_validate(r, from_attributes=True)


# ------------------------------------------------------------------ corrections
class CorrectionIn(BaseModel):
    work_date: date
    kind: str = Field(pattern="^(in|out)$")
    corrected_time: datetime
    reason: str = Field(min_length=1, max_length=255)


class CorrectionOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    work_date: date
    kind: str
    corrected_time: datetime
    reason: str
    status: str
    instance_id: int | None
    created_at: datetime


def corr_out(db: Session, c: AttendanceCorrection) -> CorrectionOut:
    return CorrectionOut(id=c.id, employee_id=c.employee_id, employee_name=db.get(Employee, c.employee_id).name,
                         work_date=c.work_date, kind=c.kind, corrected_time=c.corrected_time, reason=c.reason,
                         status=c.status, instance_id=c.instance_id, created_at=c.created_at)


def _validate_correction(db: Session, emp: Employee, body: CorrectionIn, exclude_id: int | None = None) -> None:
    ct = timeutil.to_local(body.corrected_time)
    if body.work_date > timeutil.today():
        raise ValidationFailed("不能为未来日期补卡", code="FUTURE_CORRECTION")
    if ct > timeutil.now():
        raise ValidationFailed("补卡时间不能晚于当前时间", code="FUTURE_CORRECTION")
    if body.work_date < emp.hire_date:
        raise ValidationFailed("补卡日期早于入职日期", code="BEFORE_HIRE_DATE")
    if (timeutil.today() - body.work_date).days > 31:
        raise ValidationFailed("只能补 31 天内的卡", code="CORRECTION_TOO_OLD")
    rule = svc.rule_for(db, emp)
    if svc.attribute_work_date(rule, ct) != body.work_date:
        raise ValidationFailed("补卡时间不在该工作日的打卡窗口内", code="OUT_OF_WINDOW")
    hmap = calendar.holiday_map(db, body.work_date, body.work_date)
    if not calendar.is_workday(body.work_date, hmap):
        raise ValidationFailed("非工作日无需补卡", code="NOT_WORKDAY")
    halves = approved_leave_halves(db, [emp.id], body.work_date, body.work_date).get((emp.id, body.work_date), set())
    if halves >= {"AM", "PM"}:
        raise ValidationFailed("当天为全天请假，不能补卡", code="DAY_ON_LEAVE")
    dup = db.scalar(select(AttendanceCorrection.id).where(
        AttendanceCorrection.employee_id == emp.id, AttendanceCorrection.work_date == body.work_date,
        AttendanceCorrection.kind == body.kind, AttendanceCorrection.status.in_(("pending", "approved")),
        AttendanceCorrection.id != (exclude_id or -1)))
    if dup:
        raise Conflict("该日已有同类型补卡申请", code="DUPLICATE_CORRECTION")


@router.get("/corrections", response_model=Page[CorrectionOut], summary="补卡申请列表（mine / all）")
def list_corrections(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                     page: PageParams = Depends(), cu: CurrentUser = Depends(current_user),
                     db: Session = Depends(get_db)):
    stmt = select(AttendanceCorrection)
    if scope == "mine":
        stmt = stmt.where(AttendanceCorrection.employee_id == (cu.employee.id if cu.employee else -1))
    else:
        if not (cu.has("attendance:manage") or cu.has("employee:read")):
            raise Forbidden("无权查看", code="DATA_SCOPE_DENIED")
        f = employee_scope_filter(db, cu, AttendanceCorrection.employee_id)
        if f is not None:
            stmt = stmt.where(f)
    if status:
        stmt = stmt.where(AttendanceCorrection.status == status)
    return paginate(db, stmt, page, None, AttendanceCorrection.id.desc(), lambda c: corr_out(db, c))


def _own_correction(db: Session, cu: CurrentUser, cid: int) -> AttendanceCorrection:
    c = db.get(AttendanceCorrection, cid)
    if c is None:
        raise NotFound("补卡申请不存在")
    if not cu.employee or c.employee_id != cu.employee.id:
        raise Forbidden("只能操作本人的申请", code="NOT_OWNER")
    return c


@router.post("/corrections", response_model=CorrectionOut, status_code=201, summary="提交补卡申请（直接发起审批）")
def create_correction(body: CorrectionIn, request: Request, cu: CurrentUser = Depends(require("attendance:punch")),
                      db: Session = Depends(get_db)):
    emp = cu.require_employee()

    def action():
        _validate_correction(db, emp, body)
        c = AttendanceCorrection(employee_id=emp.id, work_date=body.work_date, kind=body.kind,
                                 corrected_time=timeutil.to_local(body.corrected_time), reason=body.reason)
        db.add(c)
        db.flush()
        flow.submit(db, cu, c, business_type="attendance_correction",
                    title=f"{emp.name}的补卡申请（{body.work_date} {'上班' if body.kind == 'in' else '下班'}）",
                    subject_employee_id=emp.id, variables={"department_id": emp.department_id}, label="补卡申请")
        return 201, jsonable(corr_out(db, c))
    return idempotent(db, cu, request, body.model_dump(mode="json"), action)


@router.post("/corrections/{cid}/withdraw", response_model=CorrectionOut, summary="撤回补卡申请")
def withdraw_correction(cid: int, body: CommentIn | None = None, cu: CurrentUser = Depends(current_user),
                        db: Session = Depends(get_db)):
    c = _own_correction(db, cu, cid)
    flow.withdraw(db, cu, c, "attendance_correction", "补卡申请")
    db.commit()
    return corr_out(db, c)


@router.post("/corrections/{cid}/resubmit", response_model=CorrectionOut, summary="修改后重新提交")
def resubmit_correction(cid: int, body: CorrectionIn, cu: CurrentUser = Depends(current_user),
                        db: Session = Depends(get_db)):
    c = _own_correction(db, cu, cid)
    flow.ensure_editable(c, "补卡申请")
    emp = cu.require_employee()
    _validate_correction(db, emp, body, exclude_id=c.id)
    c.work_date, c.kind, c.corrected_time, c.reason = (body.work_date, body.kind,
                                                       timeutil.to_local(body.corrected_time), body.reason)
    flow.submit(db, cu, c, business_type="attendance_correction", title=f"{emp.name}的补卡申请（{c.work_date}）",
                subject_employee_id=emp.id, variables={"department_id": emp.department_id}, label="补卡申请")
    db.commit()
    return corr_out(db, c)


# ------------------------------------------------------------------ overtime
class OvertimeIn(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: str = Field(min_length=1, max_length=255)
    compensation: str = Field("leave", pattern="^(leave|pay)$")


class OvertimeOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    start_at: datetime
    end_at: datetime
    hours: int
    reason: str
    compensation: str
    status: str
    instance_id: int | None
    created_at: datetime


def ot_out(db: Session, o: OvertimeRequest) -> OvertimeOut:
    return OvertimeOut(id=o.id, employee_id=o.employee_id, employee_name=db.get(Employee, o.employee_id).name,
                       start_at=o.start_at, end_at=o.end_at, hours=o.hours, reason=o.reason,
                       compensation=o.compensation, status=o.status, instance_id=o.instance_id,
                       created_at=o.created_at)


def _ot_hours(db: Session, emp: Employee, body: OvertimeIn, exclude_id: int | None = None) -> int:
    s, e = timeutil.to_local(body.start_at), timeutil.to_local(body.end_at)
    if e <= s:
        raise ValidationFailed("结束时间必须晚于开始时间", code="INVALID_TIME_RANGE")
    hours = int((e - s).total_seconds() // 3600)
    if hours < 1 or hours > 12:
        raise ValidationFailed("单次加班需为 1-12 小时（按整小时计）", code="INVALID_OVERTIME_HOURS")
    overlap = db.scalar(select(OvertimeRequest.id).where(
        OvertimeRequest.employee_id == emp.id, OvertimeRequest.status.in_(("pending", "approved")),
        OvertimeRequest.start_at < e, OvertimeRequest.end_at > s, OvertimeRequest.id != (exclude_id or -1)))
    if overlap:
        raise Conflict("与已有加班申请时间重叠", code="OVERTIME_OVERLAP")
    return hours


@router.get("/overtime", response_model=Page[OvertimeOut], summary="加班申请列表（mine / all）")
def list_overtime(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                  page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(OvertimeRequest)
    if scope == "mine":
        stmt = stmt.where(OvertimeRequest.employee_id == (cu.employee.id if cu.employee else -1))
    else:
        if not (cu.has("attendance:manage") or cu.has("employee:read")):
            raise Forbidden("无权查看", code="DATA_SCOPE_DENIED")
        f = employee_scope_filter(db, cu, OvertimeRequest.employee_id)
        if f is not None:
            stmt = stmt.where(f)
    if status:
        stmt = stmt.where(OvertimeRequest.status == status)
    return paginate(db, stmt, page, None, OvertimeRequest.id.desc(), lambda o: ot_out(db, o))


@router.post("/overtime", response_model=OvertimeOut, status_code=201, summary="提交加班申请（审批通过后可转调休）")
def create_overtime(body: OvertimeIn, request: Request, cu: CurrentUser = Depends(require("attendance:punch")),
                    db: Session = Depends(get_db)):
    emp = cu.require_employee()

    def action():
        hours = _ot_hours(db, emp, body)
        o = OvertimeRequest(employee_id=emp.id, start_at=timeutil.to_local(body.start_at),
                            end_at=timeutil.to_local(body.end_at), hours=hours, reason=body.reason,
                            compensation=body.compensation)
        db.add(o)
        db.flush()
        flow.submit(db, cu, o, business_type="overtime", title=f"{emp.name}的加班申请（{hours} 小时）",
                    subject_employee_id=emp.id, variables={"hours": hours, "department_id": emp.department_id},
                    label="加班申请")
        return 201, jsonable(ot_out(db, o))
    return idempotent(db, cu, request, body.model_dump(mode="json"), action)


@router.post("/overtime/{oid}/withdraw", response_model=OvertimeOut, summary="撤回加班申请")
def withdraw_overtime(oid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    o = db.get(OvertimeRequest, oid)
    if o is None:
        raise NotFound("加班申请不存在")
    if not cu.employee or o.employee_id != cu.employee.id:
        raise Forbidden("只能操作本人的申请", code="NOT_OWNER")
    flow.withdraw(db, cu, o, "overtime", "加班申请")
    db.commit()
    return ot_out(db, o)


@router.post("/overtime/{oid}/resubmit", response_model=OvertimeOut, summary="修改后重新提交")
def resubmit_overtime(oid: int, body: OvertimeIn, cu: CurrentUser = Depends(current_user),
                      db: Session = Depends(get_db)):
    o = db.get(OvertimeRequest, oid)
    if o is None:
        raise NotFound("加班申请不存在")
    if not cu.employee or o.employee_id != cu.employee.id:
        raise Forbidden("只能操作本人的申请", code="NOT_OWNER")
    flow.ensure_editable(o, "加班申请")
    emp = cu.employee
    o.hours = _ot_hours(db, emp, body, exclude_id=o.id)
    o.start_at, o.end_at = timeutil.to_local(body.start_at), timeutil.to_local(body.end_at)
    o.reason, o.compensation = body.reason, body.compensation
    flow.submit(db, cu, o, business_type="overtime", title=f"{emp.name}的加班申请（{o.hours} 小时）",
                subject_employee_id=emp.id, variables={"hours": o.hours, "department_id": emp.department_id},
                label="加班申请")
    db.commit()
    return ot_out(db, o)
