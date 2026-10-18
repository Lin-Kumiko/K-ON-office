"""Business travel and expense claims."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, cents_str, idempotent, jsonable, paginate, to_cents
from ..core.deps import CurrentUser, PageParams, current_user, employee_scope_filter, ensure_can_view_employee, get_db, require
from ..core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..models import Employee, ExpenseCategory, ExpenseClaim, ExpenseItem, StoredFile, TravelRequest, User
from ..services import attendance
from ..services import documents_flow as flow
from .common import ERRORS, Page

router = APIRouter(prefix="/api", tags=["出差与报销"], responses=ERRORS)


# ================================================================== travel
class TravelIn(BaseModel):
    destination: str = Field(min_length=1, max_length=128)
    start_date: date
    end_date: date
    purpose: str = Field(min_length=1, max_length=500)
    transport: str | None = Field(None, max_length=32)
    estimated_cost: Decimal = Field(Decimal("0"), ge=0, le=Decimal("1000000"))


class TravelOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    destination: str
    start_date: date
    end_date: date
    days: int
    purpose: str
    transport: str | None
    estimated_cost: str
    status: str
    instance_id: int | None
    original_id: int | None
    cancel_reason: str | None
    submitted_at: datetime | None
    created_at: datetime


def travel_out(t: TravelRequest) -> TravelOut:
    return TravelOut(id=t.id, employee_id=t.employee_id, employee_name=t.employee.name, destination=t.destination,
                     start_date=t.start_date, end_date=t.end_date, days=(t.end_date - t.start_date).days + 1,
                     purpose=t.purpose, transport=t.transport, estimated_cost=cents_str(t.estimated_cost_cents),
                     status=t.status, instance_id=t.instance_id, original_id=t.original_id,
                     cancel_reason=t.cancel_reason, submitted_at=t.submitted_at, created_at=t.created_at)


def _travel_apply(t: TravelRequest, body: TravelIn) -> None:
    if body.end_date < body.start_date:
        raise ValidationFailed("结束日期不能早于开始日期", code="INVALID_DATE_RANGE")
    if (body.end_date - body.start_date).days > 90:
        raise ValidationFailed("单次出差不超过 90 天", code="TRAVEL_TOO_LONG")
    t.destination, t.start_date, t.end_date = body.destination, body.start_date, body.end_date
    t.purpose, t.transport = body.purpose, body.transport
    t.estimated_cost_cents = to_cents(body.estimated_cost)


def _travel_overlap(db: Session, t: TravelRequest) -> None:
    q = select(TravelRequest.id).where(TravelRequest.employee_id == t.employee_id, TravelRequest.id != t.id,
                                       TravelRequest.status.in_(("pending", "approved")),
                                       TravelRequest.start_date <= t.end_date, TravelRequest.end_date >= t.start_date)
    if t.original_id:
        q = q.where(TravelRequest.id != t.original_id)
    other = db.scalar(q)
    if other:
        raise Conflict(f"与出差申请 #{other} 时间重叠", code="TRAVEL_OVERLAP")


def _submit_travel(db: Session, cu: CurrentUser, t: TravelRequest) -> None:
    _travel_overlap(db, t)
    emp = db.get(Employee, t.employee_id)
    days = (t.end_date - t.start_date).days + 1
    flow.submit(db, cu, t, business_type="travel",
                title=f"{emp.name}{'的出差变更' if t.original_id else '的出差申请'}：{t.destination}（{days}天）",
                subject_employee_id=emp.id,
                variables={"days": days, "estimated_cost": float(t.estimated_cost_cents) / 100,
                           "department_id": emp.department_id, "is_change": bool(t.original_id)}, label="出差申请")


def _own_travel(db: Session, cu: CurrentUser, tid: int, write: bool = True) -> TravelRequest:
    t = db.get(TravelRequest, tid)
    if t is None:
        raise NotFound("出差申请不存在")
    own = cu.employee is not None and t.employee_id == cu.employee.id
    if not own:
        if write or not cu.has("employee:read"):
            raise Forbidden("只能操作本人的出差申请", code="NOT_OWNER")
        ensure_can_view_employee(db, cu, t.employee)
    return t


@router.get("/travel", response_model=Page[TravelOut], summary="出差记录（mine / all）")
def list_travel(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                q: str | None = Query(None, max_length=64), page: PageParams = Depends(),
                cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(TravelRequest)
    if scope == "mine":
        stmt = stmt.where(TravelRequest.employee_id == (cu.employee.id if cu.employee else -1))
    else:
        if not cu.has("employee:read"):
            raise Forbidden("无权查看他人出差", code="DATA_SCOPE_DENIED")
        f = employee_scope_filter(db, cu, TravelRequest.employee_id)
        if f is not None:
            stmt = stmt.where(f)
    if status:
        stmt = stmt.where(TravelRequest.status == status)
    if q:
        stmt = stmt.where(TravelRequest.destination.ilike(f"%{q}%"))
    return paginate(db, stmt, page, {"id": TravelRequest.id, "start_date": TravelRequest.start_date},
                    TravelRequest.id.desc(), travel_out)


@router.post("/travel", response_model=TravelOut, status_code=201, summary="新建出差申请（submit=true 直接提交）")
def create_travel(body: TravelIn, request: Request, submit: bool = False,
                  cu: CurrentUser = Depends(require("travel:apply")), db: Session = Depends(get_db)):
    emp = cu.require_employee()

    def action():
        t = TravelRequest(employee_id=emp.id, status="draft")
        _travel_apply(t, body)
        db.add(t)
        db.flush()
        if submit:
            _submit_travel(db, cu, t)
        return 201, jsonable(travel_out(t))
    return idempotent(db, cu, request, {"b": body.model_dump(mode="json"), "s": submit}, action)


@router.get("/travel/{tid}", response_model=TravelOut, summary="出差详情")
def get_travel(tid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return travel_out(_own_travel(db, cu, tid, write=False))


@router.put("/travel/{tid}", response_model=TravelOut, summary="修改出差申请（草稿/驳回/撤回）")
def update_travel(tid: int, body: TravelIn, cu: CurrentUser = Depends(require("travel:apply")),
                  db: Session = Depends(get_db)):
    t = _own_travel(db, cu, tid)
    flow.ensure_editable(t, "出差申请")
    _travel_apply(t, body)
    db.commit()
    return travel_out(t)


@router.post("/travel/{tid}/submit", response_model=TravelOut, summary="提交出差审批")
def submit_travel(tid: int, request: Request, cu: CurrentUser = Depends(require("travel:apply")),
                  db: Session = Depends(get_db)):
    t = _own_travel(db, cu, tid)

    def action():
        _submit_travel(db, cu, t)
        return 200, jsonable(travel_out(t))
    return idempotent(db, cu, request, {"id": tid}, action)


@router.post("/travel/{tid}/withdraw", response_model=TravelOut, summary="撤回出差申请")
def withdraw_travel(tid: int, cu: CurrentUser = Depends(require("travel:apply")), db: Session = Depends(get_db)):
    t = _own_travel(db, cu, tid)
    flow.withdraw(db, cu, t, "travel", "出差申请")
    db.commit()
    return travel_out(t)


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


@router.post("/travel/{tid}/cancel", response_model=TravelOut, summary="取消出差（审批中/草稿，或已批准且未开始）")
def cancel_travel(tid: int, body: CancelIn, cu: CurrentUser = Depends(require("travel:apply")),
                  db: Session = Depends(get_db)):
    t = _own_travel(db, cu, tid)
    if t.status == "approved":
        if t.start_date <= timeutil.today():
            raise InvalidState("出差已开始，不能取消", code="TRAVEL_STARTED")
        t.status = "cancelled"
        t.cancel_reason = body.reason
        db.flush()
        attendance.recompute_range(db, t.employee_id, t.start_date, t.end_date)
    else:
        flow.cancel(db, cu, t, "travel", "出差申请")
        t.cancel_reason = body.reason
    audit(db, cu, "cancel_travel", "travel", t.id, {"reason": body.reason})
    db.commit()
    return travel_out(t)


@router.post("/travel/{tid}/change", response_model=TravelOut, status_code=201,
             summary="变更已批准的出差（生成变更单并提交审批，批准后原单标记为已变更）")
def change_travel(tid: int, body: TravelIn, cu: CurrentUser = Depends(require("travel:apply")),
                  db: Session = Depends(get_db)):
    orig = _own_travel(db, cu, tid)
    if orig.status != "approved":
        raise InvalidState("只有已批准的出差可以变更", code="INVALID_STATE")
    if orig.end_date < timeutil.today():
        raise InvalidState("出差已结束，不能变更", code="TRAVEL_FINISHED")
    if db.scalar(select(TravelRequest.id).where(TravelRequest.original_id == orig.id,
                                                TravelRequest.status == "pending")):
        raise Conflict("已有审批中的变更单", code="CHANGE_PENDING")
    t = TravelRequest(employee_id=orig.employee_id, status="draft", original_id=orig.id)
    _travel_apply(t, body)
    db.add(t)
    db.flush()
    _submit_travel(db, cu, t)
    db.commit()
    return travel_out(t)


# ================================================================== expense
class CategoryOut(BaseModel):
    id: int
    code: str
    name: str
    item_limit: str | None
    status: str


@router.get("/expense/categories", response_model=list[CategoryOut], summary="费用分类")
def categories(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [CategoryOut(id=c.id, code=c.code, name=c.name, item_limit=cents_str(c.item_limit_cents), status=c.status)
            for c in db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.id))]


class ItemIn(BaseModel):
    category_id: int
    occurred_on: date
    amount: Decimal = Field(gt=0, le=Decimal("1000000"), max_digits=12, decimal_places=2)
    description: str | None = Field(None, max_length=255)
    receipt_file_id: int | None = None


class ClaimIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    travel_id: int | None = None
    items: list[ItemIn] = Field(min_length=1, max_length=50)


class ItemOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    occurred_on: date
    amount: str
    description: str | None
    receipt_file_id: int | None
    receipt_name: str | None


class ClaimOut(BaseModel):
    id: int
    claim_no: str
    employee_id: int
    employee_name: str
    title: str
    total: str
    travel_id: int | None
    status: str
    instance_id: int | None
    submitted_at: datetime | None
    decided_at: datetime | None
    finance_confirmed_by: str | None
    finance_confirmed_at: datetime | None
    payment_ref: str | None
    archived_at: datetime | None
    created_at: datetime
    items: list[ItemOut]


def claim_out(db: Session, c: ExpenseClaim) -> ClaimOut:
    names = {}
    for it in c.items:
        if it.receipt_file_id:
            f = db.get(StoredFile, it.receipt_file_id)
            names[it.id] = f.original_name if f else None
    fin = db.get(User, c.finance_confirmed_by) if c.finance_confirmed_by else None
    return ClaimOut(id=c.id, claim_no=c.claim_no, employee_id=c.employee_id, employee_name=c.employee.name,
                    title=c.title, total=cents_str(c.total_cents), travel_id=c.travel_id, status=c.status,
                    instance_id=c.instance_id, submitted_at=c.submitted_at, decided_at=c.decided_at,
                    finance_confirmed_by=fin.display_name if fin else None,
                    finance_confirmed_at=c.finance_confirmed_at, payment_ref=c.payment_ref,
                    archived_at=c.archived_at, created_at=c.created_at,
                    items=[ItemOut(id=i.id, category_id=i.category_id, category_name=i.category.name,
                                   occurred_on=i.occurred_on, amount=cents_str(i.amount_cents),
                                   description=i.description, receipt_file_id=i.receipt_file_id,
                                   receipt_name=names.get(i.id)) for i in c.items])


def _claim_apply(db: Session, cu: CurrentUser, c: ExpenseClaim, body: ClaimIn) -> None:
    if body.travel_id is not None:
        t = db.get(TravelRequest, body.travel_id)
        if t is None or t.employee_id != c.employee_id or t.status not in ("approved", "changed"):
            raise ValidationFailed("关联出差不存在或未批准", code="INVALID_TRAVEL")
    cats = {x.id: x for x in db.scalars(select(ExpenseCategory))}
    today = timeutil.today()
    items = []
    for i, it in enumerate(body.items):
        cat = cats.get(it.category_id)
        if cat is None or cat.status != "active":
            raise ValidationFailed(f"第 {i + 1} 行费用分类无效", code="INVALID_CATEGORY")
        if it.occurred_on > today or (today - it.occurred_on).days > 365:
            raise ValidationFailed(f"第 {i + 1} 行发生日期需在近一年内且不晚于今天", code="INVALID_DATE")
        cents = to_cents(it.amount)
        if cat.item_limit_cents and cents > cat.item_limit_cents:
            raise ValidationFailed(f"第 {i + 1} 行超过「{cat.name}」单笔上限 {cents_str(cat.item_limit_cents)}",
                                   code="ITEM_OVER_LIMIT")
        if it.receipt_file_id is not None:
            f = db.get(StoredFile, it.receipt_file_id)
            if f is None or f.uploaded_by != cu.id or f.purpose != "expense_receipt":
                raise ValidationFailed(f"第 {i + 1} 行票据附件无效", code="INVALID_RECEIPT")
        items.append(ExpenseItem(category_id=cat.id, occurred_on=it.occurred_on, amount_cents=cents,
                                 description=it.description, receipt_file_id=it.receipt_file_id))
    c.title, c.travel_id = body.title, body.travel_id
    c.items = items
    c.total_cents = sum(i.amount_cents for i in items)


def _claim_no(db: Session) -> str:
    prefix = f"EXP{timeutil.today():%Y%m%d}"
    n = db.scalar(select(func.count()).select_from(ExpenseClaim).where(ExpenseClaim.claim_no.like(prefix + "%")))
    return f"{prefix}{n + 1:04d}"


def _submit_claim(db: Session, cu: CurrentUser, c: ExpenseClaim) -> None:
    if not c.items or c.total_cents <= 0:
        raise ValidationFailed("报销单至少需要一条明细", code="NO_ITEMS")
    emp = db.get(Employee, c.employee_id)
    flow.submit(db, cu, c, business_type="expense", title=f"{emp.name}的报销：{c.title}（¥{cents_str(c.total_cents)}）",
                subject_employee_id=emp.id,
                variables={"amount": float(Decimal(c.total_cents) / 100), "item_count": len(c.items),
                           "department_id": emp.department_id}, label="报销单")


def _get_claim(db: Session, cu: CurrentUser, cid: int, write: bool = False) -> ExpenseClaim:
    c = db.get(ExpenseClaim, cid)
    if c is None:
        raise NotFound("报销单不存在")
    own = cu.employee is not None and c.employee_id == cu.employee.id
    if write and not own:
        raise Forbidden("只能操作本人的报销单", code="NOT_OWNER")
    if not own and not cu.has("expense:finance"):
        if not cu.has("employee:read"):
            from ..models import WfTask
            if not (c.instance_id and db.scalar(select(WfTask.id).where(WfTask.instance_id == c.instance_id,
                                                                         WfTask.assignee_id == cu.id))):
                raise Forbidden("无权查看该报销单", code="DATA_SCOPE_DENIED")
        else:
            ensure_can_view_employee(db, cu, c.employee)
    return c


@router.get("/expense/claims", response_model=Page[ClaimOut], summary="报销单列表（mine / all / finance）")
def list_claims(scope: str = Query("mine", pattern="^(mine|all|finance)$"), status: str | None = None,
                q: str | None = Query(None, max_length=64), page: PageParams = Depends(),
                cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(ExpenseClaim)
    if scope == "mine":
        stmt = stmt.where(ExpenseClaim.employee_id == (cu.employee.id if cu.employee else -1))
    elif scope == "finance":
        cu.require("expense:finance")
    else:
        if not cu.has("employee:read"):
            raise Forbidden("无权查看他人报销", code="DATA_SCOPE_DENIED")
        f = employee_scope_filter(db, cu, ExpenseClaim.employee_id)
        if f is not None:
            stmt = stmt.where(f)
    if status:
        stmt = stmt.where(ExpenseClaim.status == status)
    if q:
        stmt = stmt.where(ExpenseClaim.title.ilike(f"%{q}%") | ExpenseClaim.claim_no.ilike(f"%{q}%"))
    return paginate(db, stmt, page, {"id": ExpenseClaim.id, "total": ExpenseClaim.total_cents},
                    ExpenseClaim.id.desc(), lambda c: claim_out(db, c))


@router.post("/expense/claims", response_model=ClaimOut, status_code=201, summary="新建报销单（金额服务端精确计算）")
def create_claim(body: ClaimIn, request: Request, submit: bool = False,
                 cu: CurrentUser = Depends(require("expense:apply")), db: Session = Depends(get_db)):
    emp = cu.require_employee()

    def action():
        c = ExpenseClaim(claim_no=_claim_no(db), employee_id=emp.id, status="draft", title=body.title)
        _claim_apply(db, cu, c, body)
        db.add(c)
        db.flush()
        if submit:
            _submit_claim(db, cu, c)
        db.refresh(c)
        return 201, jsonable(claim_out(db, c))
    return idempotent(db, cu, request, {"b": body.model_dump(mode="json"), "s": submit}, action)


@router.get("/expense/claims/{cid}", response_model=ClaimOut, summary="报销单详情")
def get_claim(cid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return claim_out(db, _get_claim(db, cu, cid))


@router.put("/expense/claims/{cid}", response_model=ClaimOut, summary="修改报销单（草稿/驳回/撤回）")
def update_claim(cid: int, body: ClaimIn, cu: CurrentUser = Depends(require("expense:apply")),
                 db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid, write=True)
    flow.ensure_editable(c, "报销单")
    _claim_apply(db, cu, c, body)
    db.commit()
    return claim_out(db, c)


@router.post("/expense/claims/{cid}/submit", response_model=ClaimOut, summary="提交报销审批（按金额分支）")
def submit_claim(cid: int, request: Request, cu: CurrentUser = Depends(require("expense:apply")),
                 db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid, write=True)

    def action():
        _submit_claim(db, cu, c)
        return 200, jsonable(claim_out(db, c))
    return idempotent(db, cu, request, {"id": cid}, action)


@router.post("/expense/claims/{cid}/withdraw", response_model=ClaimOut, summary="撤回报销")
def withdraw_claim(cid: int, cu: CurrentUser = Depends(require("expense:apply")), db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid, write=True)
    flow.withdraw(db, cu, c, "expense", "报销单")
    db.commit()
    return claim_out(db, c)


@router.post("/expense/claims/{cid}/cancel", response_model=ClaimOut, summary="作废报销单")
def cancel_claim(cid: int, cu: CurrentUser = Depends(require("expense:apply")), db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid, write=True)
    flow.cancel(db, cu, c, "expense", "报销单")
    db.commit()
    return claim_out(db, c)


class FinanceIn(BaseModel):
    note: str | None = Field(None, max_length=255)


@router.post("/expense/claims/{cid}/finance-confirm", response_model=ClaimOut,
             summary="模拟财务确认付款（不连接任何真实支付服务）")
def finance_confirm(cid: int, request: Request, body: FinanceIn | None = None,
                    cu: CurrentUser = Depends(require("expense:finance")), db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid)

    def action():
        if c.status != "approved":
            raise InvalidState(f"报销单状态为 {c.status}，只有审批通过的报销单可以财务确认", code="INVALID_STATE",
                               details={"status": c.status})
        if cu.employee and c.employee_id == cu.employee.id:
            raise Forbidden("不能确认本人的报销单", code="SELF_OPERATION")
        c.status = "paid"
        c.finance_confirmed_by = cu.id
        c.finance_confirmed_at = timeutil.now()
        c.payment_ref = f"SIM-{c.claim_no}"
        from ..core.common import notify
        emp = db.get(Employee, c.employee_id)
        notify(db, emp.user_id, "expense", f"报销已确认付款（模拟）：{c.claim_no}", f"金额 ¥{cents_str(c.total_cents)}",
               f"/expense?claim={c.id}", "expense_claim", c.id)
        audit(db, cu, "finance_confirm", "expense_claim", c.id, {"total": c.total_cents,
                                                                 "note": body.note if body else None})
        return 200, jsonable(claim_out(db, c))
    return idempotent(db, cu, request, {"id": cid, "act": "confirm"}, action)


@router.post("/expense/claims/{cid}/archive", response_model=ClaimOut, summary="归档（已确认付款后）")
def archive_claim(cid: int, cu: CurrentUser = Depends(require("expense:finance")), db: Session = Depends(get_db)):
    c = _get_claim(db, cu, cid)
    if c.status != "paid":
        raise InvalidState(f"报销单状态为 {c.status}，只有已确认付款的报销单可以归档", code="INVALID_STATE",
                           details={"status": c.status})
    c.status = "archived"
    c.archived_at = timeutil.now()
    audit(db, cu, "archive_claim", "expense_claim", c.id)
    db.commit()
    return claim_out(db, c)
