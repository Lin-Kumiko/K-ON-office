"""Performance management and simulated payroll (no real payment / tax filing)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, cents_str, idempotent, jsonable, notify, paginate, to_cents
from ..core.deps import CurrentUser, PageParams, get_db, require
from ..core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..models import (Department, Employee, LeaveRequest, LeaveType, PayrollAdjustment, PayrollRun, Payslip,
                      PerformanceCycle, PerformanceIndicator, PerformanceReview, SalaryStructure)
from ..services import attendance, calendar
from .common import ERRORS, Msg, Page

router = APIRouter(prefix="/api", tags=["绩效与模拟薪资"], responses=ERRORS)


# ================================================================== performance
class IndicatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    weight: int = Field(ge=1, le=100)
    description: str | None = Field(None, max_length=255)


class CycleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date
    indicators: list[IndicatorIn] = Field(min_length=1, max_length=20)


class IndicatorOut(IndicatorIn):
    id: int


class CycleOut(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    status: str
    indicators: list[IndicatorOut]
    review_total: int
    review_confirmed: int


def cycle_out(db: Session, c: PerformanceCycle) -> CycleOut:
    total = db.scalar(select(func.count()).select_from(PerformanceReview).where(PerformanceReview.cycle_id == c.id))
    done = db.scalar(select(func.count()).select_from(PerformanceReview).where(
        PerformanceReview.cycle_id == c.id, PerformanceReview.status == "confirmed"))
    return CycleOut(id=c.id, name=c.name, start_date=c.start_date, end_date=c.end_date, status=c.status,
                    indicators=[IndicatorOut.model_validate(i, from_attributes=True) for i in c.indicators],
                    review_total=total, review_confirmed=done)


def _check_cycle(body: CycleIn) -> None:
    if body.end_date < body.start_date:
        raise ValidationFailed("结束日期不能早于开始日期", code="INVALID_DATE_RANGE")
    if sum(i.weight for i in body.indicators) != 100:
        raise ValidationFailed("指标权重之和必须为 100", code="INVALID_WEIGHTS")
    if len({i.name for i in body.indicators}) != len(body.indicators):
        raise ValidationFailed("指标名称不能重复", code="DUPLICATE_INDICATOR")


@router.get("/performance/cycles", response_model=list[CycleOut], summary="考核周期")
def list_cycles(cu: CurrentUser = Depends(require("performance:self")), db: Session = Depends(get_db)):
    stmt = select(PerformanceCycle).order_by(PerformanceCycle.start_date.desc())
    if not cu.has("performance:manage"):
        stmt = stmt.where(PerformanceCycle.status != "draft")
    return [cycle_out(db, c) for c in db.scalars(stmt)]


@router.post("/performance/cycles", response_model=CycleOut, status_code=201, summary="创建考核周期与指标")
def create_cycle(body: CycleIn, cu: CurrentUser = Depends(require("performance:manage")), db: Session = Depends(get_db)):
    _check_cycle(body)
    if db.scalar(select(PerformanceCycle.id).where(PerformanceCycle.name == body.name)):
        raise Conflict("周期名称已存在", code="CYCLE_EXISTS")
    c = PerformanceCycle(name=body.name, start_date=body.start_date, end_date=body.end_date,
                         indicators=[PerformanceIndicator(**i.model_dump()) for i in body.indicators])
    db.add(c)
    db.flush()
    audit(db, cu, "create_perf_cycle", "performance_cycle", c.id)
    db.commit()
    return cycle_out(db, c)


@router.put("/performance/cycles/{cid}", response_model=CycleOut, summary="修改考核周期（仅草稿）")
def update_cycle(cid: int, body: CycleIn, cu: CurrentUser = Depends(require("performance:manage")),
                 db: Session = Depends(get_db)):
    c = db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound("周期不存在")
    if c.status != "draft":
        raise InvalidState("只有草稿周期可以修改", code="INVALID_STATE")
    _check_cycle(body)
    c.name, c.start_date, c.end_date = body.name, body.start_date, body.end_date
    c.indicators = [PerformanceIndicator(**i.model_dump()) for i in body.indicators]
    db.commit()
    return cycle_out(db, c)


@router.post("/performance/cycles/{cid}/activate", response_model=CycleOut, summary="启动周期（为在职员工生成考核表）")
def activate_cycle(cid: int, cu: CurrentUser = Depends(require("performance:manage")), db: Session = Depends(get_db)):
    c = db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound("周期不存在")
    if c.status != "draft":
        raise InvalidState("周期已启动或已关闭", code="INVALID_STATE")
    c.status = "active"
    for e in db.scalars(select(Employee).where(Employee.status != "resigned", Employee.hire_date <= c.end_date)):
        db.add(PerformanceReview(cycle_id=c.id, employee_id=e.id, reviewer_employee_id=e.manager_id))
        notify(db, e.user_id, "performance", f"绩效自评：{c.name}", "请完成本周期自评", "/performance", "performance_cycle",
               c.id)
    audit(db, cu, "activate_perf_cycle", "performance_cycle", c.id)
    db.commit()
    return cycle_out(db, c)


@router.post("/performance/cycles/{cid}/close", response_model=CycleOut, summary="关闭周期（需全部确认）")
def close_cycle(cid: int, cu: CurrentUser = Depends(require("performance:manage")), db: Session = Depends(get_db)):
    c = db.get(PerformanceCycle, cid)
    if c is None:
        raise NotFound("周期不存在")
    if c.status != "active":
        raise InvalidState("只有进行中的周期可以关闭", code="INVALID_STATE")
    left = db.scalar(select(func.count()).select_from(PerformanceReview).where(
        PerformanceReview.cycle_id == c.id, PerformanceReview.status != "confirmed"))
    if left:
        raise Conflict(f"仍有 {left} 份考核未确认", code="REVIEWS_PENDING")
    c.status = "closed"
    db.commit()
    return cycle_out(db, c)


class ReviewOut(BaseModel):
    id: int
    cycle_id: int
    cycle_name: str
    employee_id: int
    employee_name: str
    department_name: str | None
    reviewer_employee_id: int | None
    reviewer_name: str | None
    status: str
    self_scores: dict | None
    self_comment: str | None
    manager_scores: dict | None
    manager_comment: str | None
    final_score: float | None
    grade: str | None
    confirmed_at: datetime | None
    indicators: list[IndicatorOut]


def review_out(db: Session, r: PerformanceReview) -> ReviewOut:
    c = db.get(PerformanceCycle, r.cycle_id)
    e = db.get(Employee, r.employee_id)
    rv = db.get(Employee, r.reviewer_employee_id) if r.reviewer_employee_id else None
    d = db.get(Department, e.department_id)
    return ReviewOut(id=r.id, cycle_id=c.id, cycle_name=c.name, employee_id=e.id, employee_name=e.name,
                     department_name=d.name if d else None, reviewer_employee_id=r.reviewer_employee_id,
                     reviewer_name=rv.name if rv else None, status=r.status, self_scores=r.self_scores,
                     self_comment=r.self_comment, manager_scores=r.manager_scores, manager_comment=r.manager_comment,
                     final_score=r.final_score, grade=r.grade, confirmed_at=r.confirmed_at,
                     indicators=[IndicatorOut.model_validate(i, from_attributes=True) for i in c.indicators])


@router.get("/performance/reviews", response_model=Page[ReviewOut], summary="考核表（mine / team / all）")
def list_reviews(scope: str = Query("mine", pattern="^(mine|team|all)$"), cycle_id: int | None = None,
                 status: str | None = None, page: PageParams = Depends(),
                 cu: CurrentUser = Depends(require("performance:self")), db: Session = Depends(get_db)):
    stmt = select(PerformanceReview)
    own = cu.employee.id if cu.employee else -1
    if scope == "mine":
        stmt = stmt.where(PerformanceReview.employee_id == own)
    elif scope == "team":
        stmt = stmt.where(PerformanceReview.reviewer_employee_id == own)
    else:
        cu.require("performance:manage")
    if cycle_id:
        stmt = stmt.where(PerformanceReview.cycle_id == cycle_id)
    if status:
        stmt = stmt.where(PerformanceReview.status == status)
    return paginate(db, stmt, page, None, PerformanceReview.id.desc(), lambda r: review_out(db, r))


def _get_review(db: Session, rid: int) -> PerformanceReview:
    r = db.get(PerformanceReview, rid)
    if r is None:
        raise NotFound("考核表不存在")
    return r


@router.get("/performance/reviews/{rid}", response_model=ReviewOut, summary="考核表详情")
def get_review(rid: int, cu: CurrentUser = Depends(require("performance:self")), db: Session = Depends(get_db)):
    r = _get_review(db, rid)
    own = cu.employee.id if cu.employee else -1
    if r.employee_id != own and r.reviewer_employee_id != own and not cu.has("performance:manage"):
        raise Forbidden("无权查看该考核表", code="DATA_SCOPE_DENIED")
    return review_out(db, r)


class ScoreIn(BaseModel):
    scores: dict[str, int]
    comment: str = Field(min_length=1, max_length=5000)


def _validate_scores(db: Session, r: PerformanceReview, scores: dict[str, int]) -> dict[str, int]:
    c = db.get(PerformanceCycle, r.cycle_id)
    if c.status != "active":
        raise InvalidState("考核周期未在进行中", code="CYCLE_NOT_ACTIVE")
    ids = {str(i.id) for i in c.indicators}
    if set(scores) != ids:
        raise ValidationFailed("需为每个指标打分", code="INCOMPLETE_SCORES", details={"expected": sorted(ids)})
    for v in scores.values():
        if not isinstance(v, int) or not 0 <= v <= 100:
            raise ValidationFailed("评分需为 0-100 的整数", code="INVALID_SCORE")
    return scores


def weighted(c: PerformanceCycle, scores: dict[str, int]) -> Decimal:
    total = sum(Decimal(scores[str(i.id)]) * i.weight for i in c.indicators) / 100
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def grade_of(score: Decimal) -> str:
    for g, low in (("A", 90), ("B", 80), ("C", 70), ("D", 60)):
        if score >= low:
            return g
    return "E"


@router.post("/performance/reviews/{rid}/self", response_model=ReviewOut, summary="员工自评")
def self_review(rid: int, body: ScoreIn, cu: CurrentUser = Depends(require("performance:self")),
                db: Session = Depends(get_db)):
    r = _get_review(db, rid)
    if not cu.employee or r.employee_id != cu.employee.id:
        raise Forbidden("只能填写本人的自评", code="NOT_OWNER")
    if r.status != "self_pending":
        raise InvalidState("当前不在自评阶段", code="INVALID_STATE", details={"status": r.status})
    r.self_scores = _validate_scores(db, r, body.scores)
    r.self_comment = body.comment
    r.status = "manager_pending"
    if r.reviewer_employee_id:
        rv = db.get(Employee, r.reviewer_employee_id)
        notify(db, rv.user_id, "performance", f"待评价：{cu.employee.name}的绩效", None, "/performance?tab=team",
               "performance_review", r.id)
    db.commit()
    return review_out(db, r)


@router.post("/performance/reviews/{rid}/manager", response_model=ReviewOut, summary="主管评价（计算加权得分与等级）")
def manager_review(rid: int, body: ScoreIn, cu: CurrentUser = Depends(require("performance:self")),
                   db: Session = Depends(get_db)):
    r = _get_review(db, rid)
    own = cu.employee.id if cu.employee else -1
    if r.employee_id == own:
        raise Forbidden("不能评价自己", code="SELF_OPERATION")
    if r.reviewer_employee_id != own and not (r.reviewer_employee_id is None and cu.has("performance:manage")):
        raise Forbidden("只有直属主管可以评价", code="NOT_REVIEWER")
    if r.status != "manager_pending":
        raise InvalidState("当前不在主管评价阶段", code="INVALID_STATE", details={"status": r.status})
    c = db.get(PerformanceCycle, r.cycle_id)
    r.manager_scores = _validate_scores(db, r, body.scores)
    r.manager_comment = body.comment
    final = (weighted(c, r.self_scores) * Decimal("0.3") + weighted(c, r.manager_scores) * Decimal("0.7")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    r.final_score = float(final)
    r.grade = grade_of(final)
    r.status = "confirm_pending"
    db.commit()
    return review_out(db, r)


class ConfirmIn(BaseModel):
    action: str = Field("confirm", pattern="^(confirm|return)$")
    comment: str | None = Field(None, max_length=1000)


@router.post("/performance/reviews/{rid}/confirm", response_model=ReviewOut, summary="HR 审批确认（或退回主管）")
def confirm_review(rid: int, body: ConfirmIn, cu: CurrentUser = Depends(require("performance:manage")),
                   db: Session = Depends(get_db)):
    r = _get_review(db, rid)
    if cu.employee and r.employee_id == cu.employee.id:
        raise Forbidden("不能确认本人的绩效", code="SELF_OPERATION")
    if r.status != "confirm_pending":
        raise InvalidState("当前不在确认阶段", code="INVALID_STATE", details={"status": r.status})
    e = db.get(Employee, r.employee_id)
    if body.action == "return":
        r.status = "manager_pending"
        r.final_score = r.grade = None
    else:
        r.status = "confirmed"
        r.confirmed_by = cu.id
        r.confirmed_at = timeutil.now()
        notify(db, e.user_id, "performance", f"绩效结果已确认：{r.grade}", body.comment, "/performance",
               "performance_review", r.id)
    db.commit()
    return review_out(db, r)


class PerfStatsOut(BaseModel):
    cycle_id: int
    total: int
    by_status: dict[str, int]
    by_grade: dict[str, int]
    avg_by_department: list[dict]


@router.get("/performance/stats", response_model=PerfStatsOut, summary="绩效统计分析")
def perf_stats(cycle_id: int, cu: CurrentUser = Depends(require("performance:manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(PerformanceReview).where(PerformanceReview.cycle_id == cycle_id)).all()
    by_status: dict[str, int] = {}
    by_grade: dict[str, int] = {}
    dept_scores: dict[int, list[float]] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.status == "confirmed":
            by_grade[r.grade] = by_grade.get(r.grade, 0) + 1
            dept_scores.setdefault(db.get(Employee, r.employee_id).department_id, []).append(r.final_score)
    names = dict(db.execute(select(Department.id, Department.name)).all())
    return PerfStatsOut(cycle_id=cycle_id, total=len(rows), by_status=by_status, by_grade=by_grade,
                        avg_by_department=[{"department": names.get(d, "?"), "avg": round(sum(v) / len(v), 2),
                                            "count": len(v)} for d, v in sorted(dept_scores.items())])


# ================================================================== payroll
class StructureIn(BaseModel):
    employee_id: int
    base: Decimal = Field(ge=0, le=Decimal("1000000"), decimal_places=2)
    allowance: Decimal = Field(Decimal("0"), ge=0, le=Decimal("1000000"), decimal_places=2)
    social_rate_bp: int = Field(1050, ge=0, le=5000)
    effective_from: date
    note: str | None = Field(None, max_length=255)


class StructureOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    base: str
    allowance: str
    social_rate_bp: int
    effective_from: date
    note: str | None
    created_at: datetime


def struct_out(db: Session, s: SalaryStructure) -> StructureOut:
    return StructureOut(id=s.id, employee_id=s.employee_id, employee_name=db.get(Employee, s.employee_id).name,
                        base=cents_str(s.base_cents), allowance=cents_str(s.allowance_cents),
                        social_rate_bp=s.social_rate_bp, effective_from=s.effective_from, note=s.note,
                        created_at=s.created_at)


@router.get("/payroll/structures", response_model=list[StructureOut], summary="薪酬结构（含历史）")
def list_structures(employee_id: int | None = None, cu: CurrentUser = Depends(require("payroll:manage")),
                    db: Session = Depends(get_db)):
    stmt = select(SalaryStructure).order_by(SalaryStructure.employee_id, SalaryStructure.effective_from.desc())
    if employee_id:
        stmt = stmt.where(SalaryStructure.employee_id == employee_id)
    return [struct_out(db, s) for s in db.scalars(stmt)]


@router.post("/payroll/structures", response_model=StructureOut, status_code=201, summary="设定薪酬结构（新生效记录）")
def create_structure(body: StructureIn, cu: CurrentUser = Depends(require("payroll:manage")),
                     db: Session = Depends(get_db)):
    e = db.get(Employee, body.employee_id)
    if e is None:
        raise NotFound("员工不存在")
    if db.scalar(select(SalaryStructure.id).where(SalaryStructure.employee_id == e.id,
                                                  SalaryStructure.effective_from == body.effective_from)):
        raise Conflict("该生效日已有薪酬记录", code="STRUCTURE_EXISTS")
    s = SalaryStructure(employee_id=e.id, base_cents=to_cents(body.base), allowance_cents=to_cents(body.allowance),
                        social_rate_bp=body.social_rate_bp, effective_from=body.effective_from, note=body.note,
                        created_by=cu.id)
    db.add(s)
    db.flush()
    audit(db, cu, "create_salary_structure", "salary_structure", s.id, {"employee_id": e.id})
    db.commit()
    return struct_out(db, s)


class RunIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class RunOut(BaseModel):
    id: int
    month: str
    status: str
    calc_version: int
    calculated_at: datetime | None
    confirmed_at: datetime | None
    payslip_count: int
    total_net: str


def run_out(db: Session, r: PayrollRun) -> RunOut:
    rows = db.execute(select(func.count(), func.coalesce(func.sum(Payslip.net_cents), 0)).where(
        Payslip.run_id == r.id, Payslip.is_current.is_(True))).one()
    return RunOut(id=r.id, month=r.month, status=r.status, calc_version=r.calc_version, calculated_at=r.calculated_at,
                  confirmed_at=r.confirmed_at, payslip_count=rows[0], total_net=cents_str(rows[1]))


@router.get("/payroll/runs", response_model=list[RunOut], summary="薪资批次")
def list_runs(cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    return [run_out(db, r) for r in db.scalars(select(PayrollRun).order_by(PayrollRun.month.desc()))]


@router.post("/payroll/runs", response_model=RunOut, status_code=201, summary="创建月度薪资批次")
def create_run(body: RunIn, cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(PayrollRun.id).where(PayrollRun.month == body.month)):
        raise Conflict("该月份批次已存在", code="RUN_EXISTS")
    r = PayrollRun(month=body.month, created_by=cu.id)
    db.add(r)
    db.commit()
    return run_out(db, r)


def _get_run(db: Session, rid: int, editable: bool = False) -> PayrollRun:
    r = db.get(PayrollRun, rid)
    if r is None:
        raise NotFound("薪资批次不存在")
    if editable and r.status == "confirmed":
        raise InvalidState("批次已确认，不能修改", code="RUN_CONFIRMED")
    return r


class AdjustmentIn(BaseModel):
    employee_id: int
    kind: str = Field(pattern="^(bonus|deduction)$")
    amount: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)
    reason: str = Field(min_length=1, max_length=255)


class AdjustmentOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    kind: str
    amount: str
    reason: str


@router.get("/payroll/runs/{rid}/adjustments", response_model=list[AdjustmentOut], summary="奖金与扣款明细")
def list_adjustments(rid: int, cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    _get_run(db, rid)
    return [AdjustmentOut(id=a.id, employee_id=a.employee_id, employee_name=db.get(Employee, a.employee_id).name,
                          kind=a.kind, amount=cents_str(a.amount_cents), reason=a.reason)
            for a in db.scalars(select(PayrollAdjustment).where(PayrollAdjustment.run_id == rid))]


@router.post("/payroll/runs/{rid}/adjustments", response_model=AdjustmentOut, status_code=201, summary="添加模拟奖金/扣款")
def add_adjustment(rid: int, body: AdjustmentIn, cu: CurrentUser = Depends(require("payroll:manage")),
                   db: Session = Depends(get_db)):
    r = _get_run(db, rid, editable=True)
    e = db.get(Employee, body.employee_id)
    if e is None:
        raise NotFound("员工不存在")
    a = PayrollAdjustment(run_id=r.id, employee_id=e.id, kind=body.kind, amount_cents=to_cents(body.amount),
                          reason=body.reason, created_by=cu.id)
    db.add(a)
    if r.status == "calculated":
        r.status = "draft"  # needs recalculation
    db.commit()
    return AdjustmentOut(id=a.id, employee_id=e.id, employee_name=e.name, kind=a.kind, amount=cents_str(a.amount_cents),
                         reason=a.reason)


@router.delete("/payroll/adjustments/{aid}", response_model=Msg, summary="删除奖金/扣款")
def delete_adjustment(aid: int, cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    a = db.get(PayrollAdjustment, aid)
    if a is None:
        raise NotFound("记录不存在")
    r = _get_run(db, a.run_id, editable=True)
    db.delete(a)
    if r.status == "calculated":
        r.status = "draft"
    db.commit()
    return Msg(message="已删除")


TAX_BRACKETS = [(300000, 3, 0), (1200000, 10, 21000), (2500000, 20, 141000), (3500000, 25, 266000),
                (5500000, 30, 441000), (8000000, 35, 716000), (None, 45, 1516000)]  # cents, simulated monthly table
TAX_THRESHOLD = 500000
DAYS_PER_MONTH = Decimal("21.75")


def simulated_tax(taxable_cents: int) -> int:
    if taxable_cents <= 0:
        return 0
    for limit, rate, quick in TAX_BRACKETS:
        if limit is None or taxable_cents <= limit:
            return max(0, int((Decimal(taxable_cents) * rate / 100 - quick).quantize(Decimal("1"), ROUND_HALF_UP)))
    return 0  # pragma: no cover


def calc_payslip(db: Session, run: PayrollRun, e: Employee, stats: dict, unpaid_hours: int,
                 adjustments: list[PayrollAdjustment]) -> dict | None:
    start, end = timeutil.month_bounds(run.month)
    s = db.scalar(select(SalaryStructure).where(SalaryStructure.employee_id == e.id,
                                                SalaryStructure.effective_from <= end)
                  .order_by(SalaryStructure.effective_from.desc()))
    if s is None:
        return None
    hmap = calendar.holiday_map(db, start, end)
    month_days = calendar.count_workdays(hmap, start, end)
    first = max(start, e.hire_date)
    last = min(end, e.resign_date) if e.resign_date else end
    employed_days = calendar.count_workdays(hmap, first, last) if last >= first else 0
    base = int((Decimal(s.base_cents) * employed_days / month_days).quantize(Decimal("1"), ROUND_HALF_UP)) \
        if month_days else 0
    allowance = s.allowance_cents if employed_days else 0
    daily = Decimal(s.base_cents) / DAYS_PER_MONTH
    absence = int((daily * stats.get("absent", 0)).quantize(Decimal("1"), ROUND_HALF_UP))
    unpaid = int((daily / 8 * unpaid_hours).quantize(Decimal("1"), ROUND_HALF_UP))
    bonus = sum(a.amount_cents for a in adjustments if a.kind == "bonus")
    deduction = sum(a.amount_cents for a in adjustments if a.kind == "deduction")
    gross = max(0, base + allowance + bonus - deduction - absence - unpaid)
    social = int((Decimal(base) * s.social_rate_bp / 10000).quantize(Decimal("1"), ROUND_HALF_UP))
    social = min(social, gross)
    tax = simulated_tax(gross - social - TAX_THRESHOLD)
    return {"base_cents": base, "allowance_cents": allowance, "bonus_cents": bonus, "deduction_cents": deduction,
            "absence_deduction_cents": absence, "unpaid_leave_deduction_cents": unpaid, "gross_cents": gross,
            "social_insurance_cents": social, "tax_cents": tax, "net_cents": gross - social - tax,
            "detail": {"month_workdays": month_days, "employed_workdays": employed_days,
                       "absent_days": stats.get("absent", 0), "unpaid_leave_hours": unpaid_hours,
                       "structure_id": s.id, "social_rate_bp": s.social_rate_bp, "note": "模拟计算，不代表真实发薪或个税"}}


class PayslipOut(BaseModel):
    id: int
    run_id: int
    month: str
    employee_id: int
    employee_name: str
    calc_version: int
    is_current: bool
    base: str
    allowance: str
    bonus: str
    deduction: str
    absence_deduction: str
    unpaid_leave_deduction: str
    gross: str
    social_insurance: str
    tax: str
    net: str
    detail: dict | None
    created_at: datetime


def slip_out(db: Session, p: Payslip) -> PayslipOut:
    run = db.get(PayrollRun, p.run_id)
    return PayslipOut(id=p.id, run_id=p.run_id, month=run.month, employee_id=p.employee_id,
                      employee_name=db.get(Employee, p.employee_id).name, calc_version=p.calc_version,
                      is_current=p.is_current, base=cents_str(p.base_cents), allowance=cents_str(p.allowance_cents),
                      bonus=cents_str(p.bonus_cents), deduction=cents_str(p.deduction_cents),
                      absence_deduction=cents_str(p.absence_deduction_cents),
                      unpaid_leave_deduction=cents_str(p.unpaid_leave_deduction_cents), gross=cents_str(p.gross_cents),
                      social_insurance=cents_str(p.social_insurance_cents), tax=cents_str(p.tax_cents),
                      net=cents_str(p.net_cents), detail=p.detail, created_at=p.created_at)


@router.post("/payroll/runs/{rid}/calculate", response_model=RunOut, summary="计算工资（生成新版本，保留历史）")
def calculate_run(rid: int, cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    r = _get_run(db, rid, editable=True)
    start, end = timeutil.month_bounds(r.month)
    emps = list(db.scalars(select(Employee).where(Employee.hire_date <= end).where(
        (Employee.resign_date.is_(None)) | (Employee.resign_date >= start))))
    stats = {s["employee_id"]: s for s in attendance.monthly_summary(db, emps, r.month)}
    personal = db.scalar(select(LeaveType.id).where(LeaveType.code == "personal"))
    unpaid: dict[int, int] = {}
    if personal:
        for lr in db.scalars(select(LeaveRequest).where(LeaveRequest.leave_type_id == personal,
                                                        LeaveRequest.status == "approved",
                                                        LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)):
            _, per_day = calendar.calc_leave_hours(calendar.holiday_map(db, lr.start_date, lr.end_date), lr.start_date,
                                                   lr.start_half, lr.end_date, lr.end_half)
            unpaid[lr.employee_id] = unpaid.get(lr.employee_id, 0) + sum(
                h for d, h in per_day.items() if start <= d <= end)
    adjs: dict[int, list] = {}
    for a in db.scalars(select(PayrollAdjustment).where(PayrollAdjustment.run_id == r.id)):
        adjs.setdefault(a.employee_id, []).append(a)
    r.calc_version += 1
    db.execute(update(Payslip).where(Payslip.run_id == r.id, Payslip.is_current.is_(True)).values(is_current=False))
    count = 0
    for e in emps:
        data = calc_payslip(db, r, e, stats.get(e.id, {}), unpaid.get(e.id, 0), adjs.get(e.id, []))
        if data is None:
            continue
        db.add(Payslip(run_id=r.id, employee_id=e.id, calc_version=r.calc_version, is_current=True, **data))
        count += 1
    r.status = "calculated"
    r.calculated_at = timeutil.now()
    audit(db, cu, "calculate_payroll", "payroll_run", r.id, {"version": r.calc_version, "count": count})
    db.commit()
    return run_out(db, r)


@router.post("/payroll/runs/{rid}/confirm", response_model=RunOut, summary="确认工资单（模拟，不发放）")
def confirm_run(rid: int, request: Request, cu: CurrentUser = Depends(require("payroll:manage")),
                db: Session = Depends(get_db)):
    r = _get_run(db, rid)

    def action():
        if r.status != "calculated":
            raise InvalidState(f"批次状态为 {r.status}，需先完成计算", code="INVALID_STATE", details={"status": r.status})
        r.status = "confirmed"
        r.confirmed_at = timeutil.now()
        r.confirmed_by = cu.id
        for p in db.scalars(select(Payslip).where(Payslip.run_id == r.id, Payslip.is_current.is_(True))):
            notify(db, db.get(Employee, p.employee_id).user_id, "payroll", f"{r.month} 工资单已生成（模拟）", None,
                   "/payroll", "payslip", p.id)
        audit(db, cu, "confirm_payroll", "payroll_run", r.id)
        return 200, jsonable(run_out(db, r))
    return idempotent(db, cu, request, {"id": rid, "act": "confirm"}, action)


@router.get("/payroll/runs/{rid}/payslips", response_model=list[PayslipOut], summary="批次工资单（当前版本）")
def run_payslips(rid: int, cu: CurrentUser = Depends(require("payroll:manage")), db: Session = Depends(get_db)):
    _get_run(db, rid)
    return [slip_out(db, p) for p in db.scalars(select(Payslip).where(Payslip.run_id == rid, Payslip.is_current.is_(True))
                                                .order_by(Payslip.employee_id))]


@router.get("/payroll/runs/{rid}/history", response_model=list[PayslipOut], summary="计算历史（全部版本）")
def run_history(rid: int, employee_id: int | None = None, cu: CurrentUser = Depends(require("payroll:manage")),
                db: Session = Depends(get_db)):
    _get_run(db, rid)
    stmt = select(Payslip).where(Payslip.run_id == rid)
    if employee_id:
        stmt = stmt.where(Payslip.employee_id == employee_id)
    return [slip_out(db, p) for p in db.scalars(stmt.order_by(Payslip.employee_id, Payslip.calc_version.desc()))]


@router.get("/payroll/my-payslips", response_model=list[PayslipOut], summary="我的工资单（仅已确认批次）")
def my_payslips(cu: CurrentUser = Depends(require("payroll:self")), db: Session = Depends(get_db)):
    emp = cu.require_employee()
    stmt = select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.run_id).where(
        Payslip.employee_id == emp.id, Payslip.is_current.is_(True), PayrollRun.status == "confirmed") \
        .order_by(PayrollRun.month.desc())
    return [slip_out(db, p) for p in db.scalars(stmt)]
