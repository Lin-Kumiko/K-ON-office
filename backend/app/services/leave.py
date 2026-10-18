"""Leave balances, ledger and the leave business handler.

Balance model (hours, integers): available = total - used - pending.
* submit   -> freeze   (pending += h)
* approve  -> consume  (pending -= h, used += h)
* reject / withdraw / cancel -> unfreeze (pending -= h)
Each movement writes a ledger row keyed by (ref_type, ref_id, seq, change_type) which is
UNIQUE, so the same submission can never be frozen, consumed or released twice.
A CHECK constraint (used + pending <= total) rejects any overdraw at the database level.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.errors import AppError, Conflict, InvalidState, NotFound, ValidationFailed
from ..models import Employee, LeaveBalance, LeaveLedger, LeaveRequest, LeaveType
from ..workflow import registry
from . import calendar


class BalanceInsufficient(AppError):
    status_code = 409
    code = "LEAVE_BALANCE_INSUFFICIENT"


def get_balance(db: Session, employee_id: int, leave_type_id: int, year: int, create: bool = False) -> LeaveBalance | None:
    bal = db.scalar(select(LeaveBalance).where(LeaveBalance.employee_id == employee_id,
                                               LeaveBalance.leave_type_id == leave_type_id,
                                               LeaveBalance.year == year))
    if bal is None and create:
        bal = LeaveBalance(employee_id=employee_id, leave_type_id=leave_type_id, year=year, total_hours=0,
                           used_hours=0, pending_hours=0)
        db.add(bal)
        db.flush()
    return bal


def _ledger(db: Session, bal: LeaveBalance, change_type: str, hours: int, *, ref_type: str | None = None,
            ref_id: int | None = None, seq: int = 0, operator_id: int | None = None, remark: str | None = None):
    try:
        with db.begin_nested():
            db.add(LeaveLedger(balance_id=bal.id, employee_id=bal.employee_id, leave_type_id=bal.leave_type_id,
                               year=bal.year, change_type=change_type, hours=hours, total_after=bal.total_hours,
                               used_after=bal.used_hours, pending_after=bal.pending_hours, ref_type=ref_type,
                               ref_id=ref_id, seq=seq, operator_id=operator_id, remark=remark))
            db.flush()
    except IntegrityError as exc:
        msg = str(exc.orig)
        if "not_overdrawn" in msg or "non_negative" in msg or "CHECK" in msg:
            raise BalanceInsufficient("假期余额不足") from exc
        raise Conflict("该业务的余额变动已执行过，已拒绝重复扣减", code="DUPLICATE_BALANCE_CHANGE") from exc


def available(bal: LeaveBalance | None) -> int:
    if bal is None:
        return 0
    return bal.total_hours - bal.used_hours - bal.pending_hours


def grant(db: Session, employee_id: int, leave_type_id: int, year: int, hours: int, operator_id: int | None,
          remark: str, change_type: str = "grant", ref_type: str | None = None, ref_id: int | None = None):
    bal = get_balance(db, employee_id, leave_type_id, year, create=True)
    if bal.total_hours + hours < bal.used_hours + bal.pending_hours or bal.total_hours + hours < 0:
        raise BalanceInsufficient("调整后额度将低于已使用与冻结的时长")
    bal.total_hours += hours
    _ledger(db, bal, change_type, hours, ref_type=ref_type, ref_id=ref_id, seq=1 if ref_id else 0,
            operator_id=operator_id, remark=remark)
    return bal


def freeze(db: Session, req: LeaveRequest, operator_id: int) -> None:
    lt = db.get(LeaveType, req.leave_type_id)
    if not lt.requires_balance:
        return
    bal = get_balance(db, req.employee_id, req.leave_type_id, req.start_date.year)
    if available(bal) < req.hours:
        raise BalanceInsufficient(f"{lt.name}余额不足：可用 {available(bal) / 8:g} 天，申请 {req.hours / 8:g} 天",
                                  details={"available_hours": available(bal), "requested_hours": req.hours})
    bal.pending_hours += req.hours
    _ledger(db, bal, "freeze", -req.hours, ref_type="leave_request", ref_id=req.id, seq=req.submit_seq,
            operator_id=operator_id, remark="提交请假冻结额度")


def _release(db: Session, req: LeaveRequest, operator_id: int | None, consume: bool) -> None:
    lt = db.get(LeaveType, req.leave_type_id)
    if not lt.requires_balance:
        return
    bal = get_balance(db, req.employee_id, req.leave_type_id, req.start_date.year)
    if bal is None:
        raise InvalidState("余额记录缺失，无法处理", code="BALANCE_MISSING")
    bal.pending_hours -= req.hours
    if consume:
        bal.used_hours += req.hours
    _ledger(db, bal, "consume" if consume else "unfreeze", -req.hours if consume else req.hours,
            ref_type="leave_request", ref_id=req.id, seq=req.submit_seq, operator_id=operator_id,
            remark="审批通过扣减" if consume else "流程结束释放冻结额度")


def check_overlap(db: Session, req: LeaveRequest) -> None:
    mine = set(calendar.leave_slots(req.start_date, req.start_half, req.end_date, req.end_half))
    others = db.scalars(select(LeaveRequest).where(
        LeaveRequest.employee_id == req.employee_id, LeaveRequest.id != req.id,
        LeaveRequest.status.in_(("pending", "approved")),
        LeaveRequest.start_date <= req.end_date, LeaveRequest.end_date >= req.start_date))
    for o in others:
        if mine & set(calendar.leave_slots(o.start_date, o.start_half, o.end_date, o.end_half)):
            raise Conflict(f"与已有请假单 #{o.id} 时间重叠", code="LEAVE_OVERLAP", details={"leave_id": o.id})


def compute_hours(db: Session, req: LeaveRequest) -> int:
    hours, _ = calendar.calc_leave_hours_db(db, req.start_date, req.start_half, req.end_date, req.end_half)
    if hours <= 0:
        raise ValidationFailed("所选时段不包含工作日", code="NO_WORKDAY_IN_RANGE")
    return hours


class LeaveHandler:
    business_type = "leave"

    def _load(self, db: Session, inst) -> LeaveRequest:
        req = db.get(LeaveRequest, inst.business_id)
        if req is None:
            raise NotFound("请假单不存在")
        if req.status != "pending":
            raise InvalidState(f"请假单状态为 {req.status}，与流程不一致", code="BUSINESS_STATE_MISMATCH")
        req.instance_id = inst.id
        return req

    def on_approved(self, db: Session, inst, actor_id):
        from . import attendance  # local import to avoid cycle
        req = self._load(db, inst)
        _release(db, req, actor_id, consume=True)
        req.status = "approved"
        req.decided_at = timeutil.now()
        db.flush()
        attendance.recompute_range(db, req.employee_id, req.start_date, req.end_date)

    def _close(self, db, inst, actor_id, status):
        req = self._load(db, inst)
        _release(db, req, actor_id, consume=False)
        req.status = status
        req.decided_at = timeutil.now()

    def on_rejected(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "rejected")

    def on_withdrawn(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "withdrawn")

    def on_cancelled(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "cancelled")


registry.register(LeaveHandler())


def approved_leave_halves(db: Session, employee_ids: list[int] | None, start: date, end: date) -> dict:
    """{(employee_id, date): set('AM','PM')} for approved leaves overlapping the range."""
    stmt = select(LeaveRequest).where(LeaveRequest.status == "approved", LeaveRequest.start_date <= end,
                                      LeaveRequest.end_date >= start)
    if employee_ids is not None:
        stmt = stmt.where(LeaveRequest.employee_id.in_(employee_ids))
    out: dict = {}
    for r in db.scalars(stmt):
        for d, half in calendar.leave_slots(r.start_date, r.start_half, r.end_date, r.end_half):
            if start <= d <= end:
                out.setdefault((r.employee_id, d), set()).add(half)
    return out


def ensure_year_balances(db: Session, employee: Employee, year: int, operator_id: int | None) -> int:
    """Grant default yearly quota for every balance-type leave the employee lacks. Idempotent."""
    created = 0
    for lt in db.scalars(select(LeaveType).where(LeaveType.requires_balance.is_(True), LeaveType.status == "active")):
        if get_balance(db, employee.id, lt.id, year) is None:
            bal = get_balance(db, employee.id, lt.id, year, create=True)
            if lt.default_hours:
                bal.total_hours = lt.default_hours
                _ledger(db, bal, "grant", lt.default_hours, operator_id=operator_id, remark=f"{year} 年度额度发放")
            created += 1
    return created
