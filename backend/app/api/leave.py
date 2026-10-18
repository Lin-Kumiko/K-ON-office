"""Leave types, balances, ledger and leave requests."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, idempotent, jsonable, paginate
from ..core.deps import (CurrentUser, PageParams, current_user, employee_scope_filter, ensure_can_view_employee,
                         get_db, require)
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import Employee, LeaveBalance, LeaveLedger, LeaveRequest, LeaveType, User
from ..services import calendar
from ..services import documents_flow as flow
from ..services import leave as svc
from ..services import org
from .common import ERRORS, CommentIn, Msg, Page

router = APIRouter(prefix="/api/leave", tags=["请假与假期"], responses=ERRORS)


class LeaveTypeOut(BaseModel):
    id: int
    code: str
    name: str
    paid: bool
    requires_balance: bool
    default_hours: int
    description: str | None
    status: str


class LeaveTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    name: str = Field(min_length=1, max_length=32)
    paid: bool = True
    requires_balance: bool = True
    default_hours: int = Field(0, ge=0, le=2400)
    description: str | None = Field(None, max_length=255)
    status: str = Field("active", pattern="^(active|disabled)$")


@router.get("/types", response_model=list[LeaveTypeOut], summary="假期类型")
def list_types(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [LeaveTypeOut.model_validate(t, from_attributes=True) for t in db.scalars(select(LeaveType).order_by(LeaveType.id))]


@router.post("/types", response_model=LeaveTypeOut, status_code=201, summary="新增假期类型")
def create_type(body: LeaveTypeIn, cu: CurrentUser = Depends(require("leave:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(LeaveType.id).where(LeaveType.code == body.code)):
        raise Conflict("假期类型编码已存在", code="LEAVE_TYPE_EXISTS")
    t = LeaveType(**body.model_dump())
    db.add(t)
    db.flush()
    audit(db, cu, "create_leave_type", "leave_type", t.id)
    db.commit()
    return LeaveTypeOut.model_validate(t, from_attributes=True)


@router.put("/types/{type_id}", response_model=LeaveTypeOut, summary="修改假期类型")
def update_type(type_id: int, body: LeaveTypeIn, cu: CurrentUser = Depends(require("leave:manage")),
                db: Session = Depends(get_db)):
    t = db.get(LeaveType, type_id)
    if t is None:
        raise NotFound("假期类型不存在")
    if body.code != t.code:
        raise ValidationFailed("假期类型编码不可修改", code="IMMUTABLE_FIELD")
    if body.requires_balance != t.requires_balance and db.scalar(
            select(LeaveRequest.id).where(LeaveRequest.leave_type_id == t.id, LeaveRequest.status == "pending")):
        raise Conflict("存在审批中的该类请假，不能修改是否扣余额", code="LEAVE_TYPE_IN_USE")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    audit(db, cu, "update_leave_type", "leave_type", t.id)
    db.commit()
    return LeaveTypeOut.model_validate(t, from_attributes=True)


# ------------------------------------------------------------------ balances
class BalanceOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    leave_type_id: int
    leave_type_code: str
    leave_type_name: str
    year: int
    total_hours: int
    used_hours: int
    pending_hours: int
    available_hours: int


def _resolve_employee(db: Session, cu: CurrentUser, employee_id: int | None) -> Employee:
    if employee_id is None or (cu.employee and employee_id == cu.employee.id):
        return cu.require_employee()
    emp = org.get_employee(db, employee_id)
    if not (cu.has("leave:manage") or cu.has("employee:read")):
        raise Forbidden("无权查看他人假期", code="DATA_SCOPE_DENIED")
    ensure_can_view_employee(db, cu, emp)
    return emp


@router.get("/balances", response_model=list[BalanceOut], summary="假期余额（默认本人）")
def balances(employee_id: int | None = None, year: int | None = Query(None, ge=2000, le=2100),
             cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    emp = _resolve_employee(db, cu, employee_id)
    year = year or timeutil.today().year
    rows = db.scalars(select(LeaveBalance).where(LeaveBalance.employee_id == emp.id, LeaveBalance.year == year)
                      .order_by(LeaveBalance.leave_type_id)).all()
    return [BalanceOut(id=b.id, employee_id=emp.id, employee_name=emp.name, leave_type_id=b.leave_type_id,
                       leave_type_code=b.leave_type.code, leave_type_name=b.leave_type.name, year=b.year,
                       total_hours=b.total_hours, used_hours=b.used_hours, pending_hours=b.pending_hours,
                       available_hours=svc.available(b)) for b in rows]


class AdjustIn(BaseModel):
    employee_id: int
    leave_type_id: int
    year: int = Field(ge=2000, le=2100)
    hours: int = Field(ge=-2400, le=2400)
    remark: str = Field(min_length=1, max_length=255)


@router.post("/balances/adjust", response_model=BalanceOut, summary="调整额度（正数增加，负数扣减）")
def adjust_balance(body: AdjustIn, cu: CurrentUser = Depends(require("leave:manage")), db: Session = Depends(get_db)):
    if body.hours == 0:
        raise ValidationFailed("调整时长不能为 0", code="INVALID_HOURS")
    emp = org.get_employee(db, body.employee_id)
    lt = db.get(LeaveType, body.leave_type_id)
    if lt is None or not lt.requires_balance:
        raise ValidationFailed("该假期类型不使用余额", code="LEAVE_TYPE_NO_BALANCE")
    b = svc.grant(db, emp.id, lt.id, body.year, body.hours, cu.id, body.remark, change_type="adjust")
    audit(db, cu, "adjust_leave_balance", "leave_balance", b.id, body.model_dump())
    db.commit()
    return BalanceOut(id=b.id, employee_id=emp.id, employee_name=emp.name, leave_type_id=lt.id, leave_type_code=lt.code,
                      leave_type_name=lt.name, year=b.year, total_hours=b.total_hours, used_hours=b.used_hours,
                      pending_hours=b.pending_hours, available_hours=svc.available(b))


class GrantIn(BaseModel):
    year: int = Field(ge=2000, le=2100)


@router.post("/balances/grant-annual", response_model=Msg, summary="为在职员工发放年度额度（幂等）")
def grant_annual(body: GrantIn, cu: CurrentUser = Depends(require("leave:manage")), db: Session = Depends(get_db)):
    created = 0
    for emp in db.scalars(select(Employee).where(Employee.status != "resigned")):
        created += svc.ensure_year_balances(db, emp, body.year, cu.id)
    audit(db, cu, "grant_annual_leave", "leave_balance", None, {"year": body.year, "created": created})
    db.commit()
    return Msg(message=f"已新建 {created} 条余额记录")


class LedgerOut(BaseModel):
    id: int
    leave_type_name: str
    year: int
    change_type: str
    hours: int
    total_after: int
    used_after: int
    pending_after: int
    ref_type: str | None
    ref_id: int | None
    operator_name: str | None
    remark: str | None
    created_at: datetime


@router.get("/ledger", response_model=Page[LedgerOut], summary="余额流水")
def ledger(employee_id: int | None = None, year: int | None = None, leave_type_id: int | None = None,
           page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    emp = _resolve_employee(db, cu, employee_id)
    stmt = select(LeaveLedger).where(LeaveLedger.employee_id == emp.id)
    if year:
        stmt = stmt.where(LeaveLedger.year == year)
    if leave_type_id:
        stmt = stmt.where(LeaveLedger.leave_type_id == leave_type_id)
    types = dict(db.execute(select(LeaveType.id, LeaveType.name)).all())
    users = dict(db.execute(select(User.id, User.display_name)).all())
    return paginate(db, stmt, page, {"id": LeaveLedger.id}, LeaveLedger.id.desc(),
                    lambda r: LedgerOut(id=r.id, leave_type_name=types.get(r.leave_type_id, "?"), year=r.year,
                                        change_type=r.change_type, hours=r.hours, total_after=r.total_after,
                                        used_after=r.used_after, pending_after=r.pending_after, ref_type=r.ref_type,
                                        ref_id=r.ref_id, operator_name=users.get(r.operator_id), remark=r.remark,
                                        created_at=r.created_at))


# ------------------------------------------------------------------ requests
class CalcIn(BaseModel):
    start_date: date
    start_half: str = Field("AM", pattern="^(AM|PM)$")
    end_date: date
    end_half: str = Field("PM", pattern="^(AM|PM)$")


class CalcOut(BaseModel):
    hours: int
    days: float
    per_day: dict[str, int]


@router.post("/calculate", response_model=CalcOut, summary="计算请假时长（排除周末节假日）")
def calculate(body: CalcIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    hours, per_day = calendar.calc_leave_hours_db(db, body.start_date, body.start_half, body.end_date, body.end_half)
    return CalcOut(hours=hours, days=hours / 8, per_day={str(k): v for k, v in per_day.items()})


class LeaveIn(CalcIn):
    leave_type_id: int
    reason: str = Field(min_length=1, max_length=500)


class LeaveOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    leave_type_id: int
    leave_type_name: str
    start_date: date
    start_half: str
    end_date: date
    end_half: str
    hours: int
    days: float
    reason: str
    status: str
    instance_id: int | None
    submitted_at: datetime | None
    decided_at: datetime | None
    created_at: datetime


def leave_out(r: LeaveRequest) -> LeaveOut:
    return LeaveOut(id=r.id, employee_id=r.employee_id, employee_name=r.employee.name, leave_type_id=r.leave_type_id,
                    leave_type_name=r.leave_type.name, start_date=r.start_date, start_half=r.start_half,
                    end_date=r.end_date, end_half=r.end_half, hours=r.hours, days=r.hours / 8, reason=r.reason,
                    status=r.status, instance_id=r.instance_id, submitted_at=r.submitted_at,
                    decided_at=r.decided_at, created_at=r.created_at)


def _apply(db: Session, r: LeaveRequest, body: LeaveIn) -> None:
    lt = db.get(LeaveType, body.leave_type_id)
    if lt is None or lt.status != "active":
        raise ValidationFailed("假期类型不存在或已停用", code="INVALID_LEAVE_TYPE")
    r.leave_type_id = lt.id
    r.start_date, r.start_half, r.end_date, r.end_half = body.start_date, body.start_half, body.end_date, body.end_half
    r.reason = body.reason
    r.hours = svc.compute_hours(db, r)


@router.get("/requests", response_model=Page[LeaveOut], summary="请假单列表（scope=mine|all）")
def list_requests(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                  employee_id: int | None = None, start: date | None = None, end: date | None = None,
                  page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(LeaveRequest)
    if scope == "mine":
        stmt = stmt.where(LeaveRequest.employee_id == (cu.employee.id if cu.employee else -1))
    else:
        if not (cu.has("leave:manage") or cu.has("employee:read")):
            raise Forbidden("无权查看他人请假单", code="DATA_SCOPE_DENIED")
        f = employee_scope_filter(db, cu, LeaveRequest.employee_id)
        if f is not None:
            stmt = stmt.where(f)
        if employee_id:
            stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if start:
        stmt = stmt.where(LeaveRequest.end_date >= start)
    if end:
        stmt = stmt.where(LeaveRequest.start_date <= end)
    return paginate(db, stmt, page, {"id": LeaveRequest.id, "start_date": LeaveRequest.start_date},
                    LeaveRequest.id.desc(), leave_out)


def _get_own(db: Session, cu: CurrentUser, req_id: int, write: bool = False) -> LeaveRequest:
    r = db.get(LeaveRequest, req_id)
    if r is None:
        raise NotFound("请假单不存在")
    own = cu.employee is not None and r.employee_id == cu.employee.id
    if write and not own:
        raise Forbidden("只能操作本人的请假单", code="NOT_OWNER")
    if not own:
        if not (cu.has("leave:manage") or cu.has("employee:read")):
            raise Forbidden("无权查看他人请假单", code="DATA_SCOPE_DENIED")
        ensure_can_view_employee(db, cu, r.employee)
    return r


@router.post("/requests", response_model=LeaveOut, status_code=201, summary="创建请假单（草稿，可带 submit=true 直接提交）")
def create_request(body: LeaveIn, request: Request, submit: bool = False,
                   cu: CurrentUser = Depends(require("leave:apply")), db: Session = Depends(get_db)):
    emp = cu.require_employee()

    def action():
        r = LeaveRequest(employee_id=emp.id, status="draft")
        _apply(db, r, body)
        db.add(r)
        db.flush()
        if submit:
            _submit(db, cu, r)
        db.refresh(r)
        return 201, jsonable(leave_out(r))

    return idempotent(db, cu, request, {"body": body.model_dump(mode="json"), "submit": submit}, action)


@router.get("/requests/{req_id}", response_model=LeaveOut, summary="请假单详情")
def get_request(req_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return leave_out(_get_own(db, cu, req_id))


@router.put("/requests/{req_id}", response_model=LeaveOut, summary="修改请假单（草稿/驳回/撤回状态）")
def update_request(req_id: int, body: LeaveIn, cu: CurrentUser = Depends(require("leave:apply")),
                   db: Session = Depends(get_db)):
    r = _get_own(db, cu, req_id, write=True)
    flow.ensure_editable(r, "请假单")
    _apply(db, r, body)
    db.commit()
    return leave_out(r)


def _submit(db: Session, cu: CurrentUser, r: LeaveRequest) -> None:
    flow.ensure_editable(r, "请假单")
    r.hours = svc.compute_hours(db, r)
    svc.check_overlap(db, r)
    emp = db.get(Employee, r.employee_id)
    if emp.status == "resigned":
        raise ValidationFailed("离职员工不能请假", code="EMPLOYEE_RESIGNED")
    r.submit_seq += 1
    svc.freeze(db, r, cu.id)
    lt = db.get(LeaveType, r.leave_type_id)
    flow.submit(db, cu, r, business_type="leave",
                title=f"{emp.name}的{lt.name}申请（{r.hours / 8:g}天）", subject_employee_id=emp.id,
                variables={"days": r.hours / 8, "hours": r.hours, "leave_type": lt.code,
                           "department_id": emp.department_id}, label="请假单")


@router.post("/requests/{req_id}/submit", response_model=LeaveOut, summary="提交审批（冻结余额并发起流程）")
def submit_request(req_id: int, request: Request, cu: CurrentUser = Depends(require("leave:apply")),
                   db: Session = Depends(get_db)):
    r = _get_own(db, cu, req_id, write=True)

    def action():
        _submit(db, cu, r)
        db.refresh(r)
        return 200, jsonable(leave_out(r))

    return idempotent(db, cu, request, {"id": req_id}, action)


@router.post("/requests/{req_id}/withdraw", response_model=LeaveOut, summary="撤回（释放冻结额度）")
def withdraw_request(req_id: int, body: CommentIn | None = None, cu: CurrentUser = Depends(require("leave:apply")),
                     db: Session = Depends(get_db)):
    r = _get_own(db, cu, req_id, write=True)
    flow.withdraw(db, cu, r, "leave", "请假单")
    db.commit()
    return leave_out(r)


@router.post("/requests/{req_id}/cancel", response_model=LeaveOut, summary="取消（终止，不可再提交）")
def cancel_request(req_id: int, cu: CurrentUser = Depends(require("leave:apply")), db: Session = Depends(get_db)):
    r = _get_own(db, cu, req_id, write=True)
    flow.cancel(db, cu, r, "leave", "请假单")
    db.commit()
    return leave_out(r)


@router.delete("/requests/{req_id}", response_model=Msg, summary="删除草稿")
def delete_request(req_id: int, cu: CurrentUser = Depends(require("leave:apply")), db: Session = Depends(get_db)):
    r = _get_own(db, cu, req_id, write=True)
    if r.status != "draft" or r.submit_seq:
        raise Conflict("只有从未提交过的草稿可以删除", code="INVALID_STATE")
    db.delete(r)
    db.commit()
    return Msg(message="已删除")
