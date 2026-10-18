"""Recruitment (requisitions, candidates, interviews, offers), onboarding, regularization and transfer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, cents_str, idempotent, jsonable, paginate, to_cents
from ..core.deps import (CurrentUser, PageParams, current_user, employee_scope_filter, ensure_can_view_employee,
                         get_db, require, require_any)
from ..core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..core.security import mask_phone
from ..models import (Candidate, Department, Employee, Interview, JobRequisition, OnboardingRequest, OnboardingTask,
                      Offer, Position, RegularizationRequest, Role, StoredFile, TransferRequest, User)
from ..services import documents_flow as flow
from ..services import org
from .common import ERRORS, Page

router = APIRouter(prefix="/api", tags=["招聘·入职·转正·调岗"], responses=ERRORS)


def _names(db: Session):
    return (dict(db.execute(select(Department.id, Department.name)).all()),
            dict(db.execute(select(Position.id, Position.name)).all()),
            dict(db.execute(select(Employee.id, Employee.name)).all()),
            dict(db.execute(select(User.id, User.display_name)).all()))


# ================================================================== requisitions
class RequisitionIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    department_id: int
    position_id: int | None = None
    headcount: int = Field(1, ge=1, le=100)
    description: str | None = Field(None, max_length=5000)


class RequisitionOut(BaseModel):
    id: int
    title: str
    department_id: int
    department_name: str | None
    position_id: int | None
    position_name: str | None
    headcount: int
    hired_count: int
    description: str | None
    status: str
    candidate_count: int
    created_at: datetime


def req_out(db: Session, r: JobRequisition) -> RequisitionOut:
    d, p, _, _ = _names(db)
    n = db.scalar(select(func.count()).select_from(Candidate).where(Candidate.requisition_id == r.id))
    return RequisitionOut(id=r.id, title=r.title, department_id=r.department_id, department_name=d.get(r.department_id),
                          position_id=r.position_id, position_name=p.get(r.position_id), headcount=r.headcount,
                          hired_count=r.hired_count, description=r.description, status=r.status, candidate_count=n,
                          created_at=r.created_at)


@router.get("/recruitment/requisitions", response_model=Page[RequisitionOut], summary="招聘需求")
def list_requisitions(status: str | None = None, page: PageParams = Depends(),
                      cu: CurrentUser = Depends(require("recruit:manage")), db: Session = Depends(get_db)):
    stmt = select(JobRequisition)
    if status:
        stmt = stmt.where(JobRequisition.status == status)
    return paginate(db, stmt, page, None, JobRequisition.id.desc(), lambda r: req_out(db, r))


@router.post("/recruitment/requisitions", response_model=RequisitionOut, status_code=201, summary="新建招聘需求")
def create_requisition(body: RequisitionIn, cu: CurrentUser = Depends(require("recruit:manage")),
                       db: Session = Depends(get_db)):
    org.get_department(db, body.department_id)
    org.get_position(db, body.position_id)
    r = JobRequisition(**body.model_dump(), created_by=cu.id)
    db.add(r)
    db.flush()
    audit(db, cu, "create_requisition", "requisition", r.id)
    db.commit()
    return req_out(db, r)


@router.put("/recruitment/requisitions/{rid}", response_model=RequisitionOut, summary="修改招聘需求")
def update_requisition(rid: int, body: RequisitionIn, cu: CurrentUser = Depends(require("recruit:manage")),
                       db: Session = Depends(get_db)):
    r = db.get(JobRequisition, rid)
    if r is None:
        raise NotFound("招聘需求不存在")
    if body.headcount < r.hired_count:
        raise ValidationFailed("招聘人数不能少于已录用人数", code="INVALID_HEADCOUNT")
    org.get_department(db, body.department_id)
    org.get_position(db, body.position_id)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return req_out(db, r)


class ReqStatusIn(BaseModel):
    status: str = Field(pattern="^(open|closed)$")


@router.post("/recruitment/requisitions/{rid}/status", response_model=RequisitionOut, summary="开启/关闭招聘需求")
def requisition_status(rid: int, body: ReqStatusIn, cu: CurrentUser = Depends(require("recruit:manage")),
                       db: Session = Depends(get_db)):
    r = db.get(JobRequisition, rid)
    if r is None:
        raise NotFound("招聘需求不存在")
    r.status = body.status
    db.commit()
    return req_out(db, r)


# ================================================================== candidates
class CandidateIn(BaseModel):
    requisition_id: int | None = None
    name: str = Field(min_length=1, max_length=64)
    gender: str | None = Field(None, pattern="^(女|男|其他)$")
    phone: str | None = Field(None, pattern=r"^[0-9+\- ]{6,20}$")
    email: str | None = Field(None, max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    source: str | None = Field(None, max_length=32)
    resume_file_id: int | None = None
    note: str | None = Field(None, max_length=5000)


class CandidateOut(BaseModel):
    id: int
    requisition_id: int | None
    requisition_title: str | None
    name: str
    gender: str | None
    phone: str | None
    email: str | None
    source: str | None
    resume_file_id: int | None
    note: str | None
    status: str
    interview_count: int
    created_at: datetime


def cand_out(db: Session, c: Candidate) -> CandidateOut:
    req = db.get(JobRequisition, c.requisition_id) if c.requisition_id else None
    n = db.scalar(select(func.count()).select_from(Interview).where(Interview.candidate_id == c.id))
    return CandidateOut(id=c.id, requisition_id=c.requisition_id, requisition_title=req.title if req else None,
                        name=c.name, gender=c.gender, phone=c.phone, email=c.email, source=c.source,
                        resume_file_id=c.resume_file_id, note=c.note, status=c.status, interview_count=n,
                        created_at=c.created_at)


def _cand_check(db: Session, body: CandidateIn) -> None:
    if body.requisition_id:
        r = db.get(JobRequisition, body.requisition_id)
        if r is None or r.status != "open":
            raise ValidationFailed("招聘需求不存在或已关闭", code="REQUISITION_CLOSED")
    if body.resume_file_id:
        f = db.get(StoredFile, body.resume_file_id)
        if f is None or f.purpose != "resume":
            raise ValidationFailed("简历附件无效", code="INVALID_RESUME")


@router.get("/recruitment/candidates", response_model=Page[CandidateOut], summary="候选人档案")
def list_candidates(requisition_id: int | None = None, status: str | None = None,
                    q: str | None = Query(None, max_length=64), page: PageParams = Depends(),
                    cu: CurrentUser = Depends(require("recruit:manage")), db: Session = Depends(get_db)):
    stmt = select(Candidate)
    if requisition_id:
        stmt = stmt.where(Candidate.requisition_id == requisition_id)
    if status:
        stmt = stmt.where(Candidate.status == status)
    if q:
        stmt = stmt.where(Candidate.name.ilike(f"%{q}%"))
    return paginate(db, stmt, page, None, Candidate.id.desc(), lambda c: cand_out(db, c))


@router.post("/recruitment/candidates", response_model=CandidateOut, status_code=201, summary="新建候选人")
def create_candidate(body: CandidateIn, cu: CurrentUser = Depends(require("recruit:manage")),
                     db: Session = Depends(get_db)):
    _cand_check(db, body)
    if body.email and db.scalar(select(Candidate.id).where(func.lower(Candidate.email) == body.email.lower(),
                                                           Candidate.status.not_in(("rejected", "hired")))):
        raise Conflict("该邮箱已有进行中的候选人档案", code="CANDIDATE_EXISTS")
    c = Candidate(**body.model_dump())
    db.add(c)
    db.flush()
    audit(db, cu, "create_candidate", "candidate", c.id)
    db.commit()
    return cand_out(db, c)


@router.get("/recruitment/candidates/{cid}", response_model=CandidateOut, summary="候选人详情")
def get_candidate(cid: int, cu: CurrentUser = Depends(require("recruit:manage")), db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if c is None:
        raise NotFound("候选人不存在")
    return cand_out(db, c)


@router.put("/recruitment/candidates/{cid}", response_model=CandidateOut, summary="修改候选人")
def update_candidate(cid: int, body: CandidateIn, cu: CurrentUser = Depends(require("recruit:manage")),
                     db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if c is None:
        raise NotFound("候选人不存在")
    if c.status in ("hired", "onboarding"):
        raise InvalidState("候选人已进入入职流程，不能修改", code="INVALID_STATE")
    _cand_check(db, body)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return cand_out(db, c)


@router.post("/recruitment/candidates/{cid}/reject", response_model=CandidateOut, summary="淘汰候选人")
def reject_candidate(cid: int, cu: CurrentUser = Depends(require("recruit:manage")), db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if c is None:
        raise NotFound("候选人不存在")
    if c.status in ("hired", "onboarding", "offer_pending"):
        raise InvalidState(f"候选人状态为 {c.status}，不能淘汰", code="INVALID_STATE")
    c.status = "rejected"
    db.commit()
    return cand_out(db, c)


class InterviewIn(BaseModel):
    interviewer_id: int
    scheduled_at: datetime
    round: int = Field(1, ge=1, le=10)


class InterviewResultIn(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=1, max_length=5000)
    result: str = Field(pattern="^(pass|fail)$")


class InterviewOut(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    round: int
    interviewer_id: int
    interviewer_name: str | None
    scheduled_at: datetime
    score: int | None
    feedback: str | None
    result: str


def iv_out(db: Session, i: Interview) -> InterviewOut:
    u = db.get(User, i.interviewer_id)
    return InterviewOut(id=i.id, candidate_id=i.candidate_id, candidate_name=db.get(Candidate, i.candidate_id).name,
                        round=i.round, interviewer_id=i.interviewer_id, interviewer_name=u.display_name if u else None,
                        scheduled_at=i.scheduled_at, score=i.score, feedback=i.feedback, result=i.result)


@router.get("/recruitment/interviews", response_model=list[InterviewOut], summary="面试记录（HR 看全部，面试官看自己的）")
def list_interviews(candidate_id: int | None = None, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    stmt = select(Interview)
    if not cu.has("recruit:manage"):
        stmt = stmt.where(Interview.interviewer_id == cu.id)
    if candidate_id:
        stmt = stmt.where(Interview.candidate_id == candidate_id)
    return [iv_out(db, i) for i in db.scalars(stmt.order_by(Interview.scheduled_at))]


@router.post("/recruitment/candidates/{cid}/interviews", response_model=InterviewOut, status_code=201, summary="安排面试")
def schedule_interview(cid: int, body: InterviewIn, cu: CurrentUser = Depends(require("recruit:manage")),
                       db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if c is None:
        raise NotFound("候选人不存在")
    if c.status not in ("new", "interviewing"):
        raise InvalidState(f"候选人状态为 {c.status}，不能安排面试", code="INVALID_STATE")
    u = db.get(User, body.interviewer_id)
    if u is None or u.status != "active":
        raise ValidationFailed("面试官不存在或已停用", code="INVALID_INTERVIEWER")
    i = Interview(candidate_id=c.id, interviewer_id=u.id, scheduled_at=timeutil.to_local(body.scheduled_at),
                  round=body.round)
    db.add(i)
    c.status = "interviewing"
    db.flush()
    from ..core.common import notify
    notify(db, u.id, "interview", f"面试安排：{c.name}（第 {body.round} 轮）", f"{i.scheduled_at:%m-%d %H:%M}",
           "/recruitment?tab=interviews", "interview", i.id)
    db.commit()
    return iv_out(db, i)


@router.post("/recruitment/interviews/{iid}/result", response_model=InterviewOut, summary="登记面试结果（面试官或 HR）")
def interview_result(iid: int, body: InterviewResultIn, cu: CurrentUser = Depends(current_user),
                     db: Session = Depends(get_db)):
    i = db.get(Interview, iid)
    if i is None:
        raise NotFound("面试不存在")
    if i.interviewer_id != cu.id and not cu.has("recruit:manage"):
        raise Forbidden("只有面试官或 HR 可以登记结果", code="NOT_INTERVIEWER")
    if i.result != "pending":
        raise InvalidState("面试结果已登记", code="INVALID_STATE")
    i.score, i.feedback, i.result = body.score, body.feedback, body.result
    db.commit()
    return iv_out(db, i)


# ================================================================== offers
class OfferIn(BaseModel):
    candidate_id: int
    department_id: int
    position_id: int | None = None
    salary: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)
    hire_date: date
    note: str | None = Field(None, max_length=255)


class OfferOut(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    department_id: int
    department_name: str | None
    position_id: int | None
    position_name: str | None
    salary: str
    hire_date: date
    note: str | None
    status: str
    instance_id: int | None
    created_at: datetime


def offer_out(db: Session, o: Offer) -> OfferOut:
    d, p, _, _ = _names(db)
    return OfferOut(id=o.id, candidate_id=o.candidate_id, candidate_name=db.get(Candidate, o.candidate_id).name,
                    department_id=o.department_id, department_name=d.get(o.department_id), position_id=o.position_id,
                    position_name=p.get(o.position_id), salary=cents_str(o.salary_cents), hire_date=o.hire_date,
                    note=o.note, status=o.status, instance_id=o.instance_id, created_at=o.created_at)


@router.get("/recruitment/offers", response_model=Page[OfferOut], summary="录用审批单")
def list_offers(status: str | None = None, page: PageParams = Depends(),
                cu: CurrentUser = Depends(require("recruit:manage")), db: Session = Depends(get_db)):
    stmt = select(Offer)
    if status:
        stmt = stmt.where(Offer.status == status)
    return paginate(db, stmt, page, None, Offer.id.desc(), lambda o: offer_out(db, o))


@router.post("/recruitment/offers", response_model=OfferOut, status_code=201, summary="发起录用审批（需至少一轮面试通过）")
def create_offer(body: OfferIn, request: Request, cu: CurrentUser = Depends(require("recruit:manage")),
                 db: Session = Depends(get_db)):
    def action():
        c = db.get(Candidate, body.candidate_id)
        if c is None:
            raise NotFound("候选人不存在")
        if c.status != "interviewing":
            raise InvalidState(f"候选人状态为 {c.status}，需处于面试中才能发起录用", code="INVALID_STATE")
        if not db.scalar(select(Interview.id).where(Interview.candidate_id == c.id, Interview.result == "pass")):
            raise InvalidState("候选人尚无通过的面试记录", code="NO_PASSED_INTERVIEW")
        if body.hire_date < timeutil.today():
            raise ValidationFailed("入职日期不能早于今天", code="INVALID_DATE")
        org.get_department(db, body.department_id)
        org.get_position(db, body.position_id)
        o = Offer(candidate_id=c.id, department_id=body.department_id, position_id=body.position_id,
                  salary_cents=to_cents(body.salary), hire_date=body.hire_date, note=body.note, created_by=cu.id)
        db.add(o)
        db.flush()
        c.status = "offer_pending"
        flow.submit(db, cu, o, business_type="offer", title=f"录用审批：{c.name}", subject_employee_id=None,
                    variables={"salary": float(body.salary), "department_id": body.department_id}, label="录用审批")
        return 201, jsonable(offer_out(db, o))
    return idempotent(db, cu, request, body.model_dump(mode="json"), action)


# ================================================================== onboarding
class OnboardingIn(BaseModel):
    candidate_id: int | None = None
    name: str = Field(min_length=1, max_length=64)
    gender: str | None = Field(None, pattern="^(女|男|其他)$")
    phone: str | None = Field(None, pattern=r"^[0-9+\- ]{6,20}$")
    email: str = Field(max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department_id: int
    position_id: int | None = None
    manager_id: int | None = None
    hire_date: date
    probation_months: int = Field(3, ge=0, le=6)
    create_account: bool = True
    username: str | None = Field(None, min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    role_codes: list[str] = Field(default_factory=lambda: ["employee"])
    base_salary: Decimal | None = Field(None, gt=0, le=Decimal("1000000"), decimal_places=2)


class OnboardingOut(BaseModel):
    id: int
    candidate_id: int | None
    name: str
    email: str
    phone: str | None
    department_id: int
    department_name: str | None
    position_id: int | None
    position_name: str | None
    manager_id: int | None
    manager_name: str | None
    hire_date: date
    probation_months: int
    create_account: bool
    username: str | None
    role_codes: list[str]
    base_salary: str | None
    status: str
    instance_id: int | None
    employee_id: int | None
    user_id: int | None
    account_linked: bool
    created_at: datetime


def onb_out(db: Session, o: OnboardingRequest) -> OnboardingOut:
    d, p, e, _ = _names(db)
    return OnboardingOut(id=o.id, candidate_id=o.candidate_id, name=o.name, email=o.email, phone=mask_phone(o.phone),
                         department_id=o.department_id, department_name=d.get(o.department_id),
                         position_id=o.position_id, position_name=p.get(o.position_id), manager_id=o.manager_id,
                         manager_name=e.get(o.manager_id), hire_date=o.hire_date, probation_months=o.probation_months,
                         create_account=o.create_account, username=o.username, role_codes=o.role_codes or [],
                         base_salary=cents_str(o.base_salary_cents), status=o.status, instance_id=o.instance_id,
                         employee_id=o.employee_id, user_id=o.user_id, account_linked=o.account_linked,
                         created_at=o.created_at)


def _onb_apply(db: Session, cu: CurrentUser, o: OnboardingRequest, body: OnboardingIn) -> None:
    if body.candidate_id:
        c = db.get(Candidate, body.candidate_id)
        if c is None:
            raise NotFound("候选人不存在")
        if c.status not in ("offered", "onboarding") or (c.status == "onboarding" and o.candidate_id != c.id):
            raise InvalidState("候选人需已通过录用审批", code="CANDIDATE_NOT_OFFERED")
        dup = db.scalar(select(OnboardingRequest.id).where(
            OnboardingRequest.candidate_id == c.id, OnboardingRequest.id != (o.id or -1),
            OnboardingRequest.status.in_(("draft", "pending", "approved"))))
        if dup:
            raise Conflict("该候选人已有入职申请", code="ONBOARDING_EXISTS")
    org.get_department(db, body.department_id)
    org.get_position(db, body.position_id)
    if body.manager_id:
        org.check_manager(db, None, body.manager_id)
    roles = set(db.scalars(select(Role.code)))
    if set(body.role_codes) - roles:
        raise ValidationFailed("角色不存在", code="ROLE_NOT_FOUND")
    if "admin" in body.role_codes:
        raise ValidationFailed("入职流程不能直接授予管理员角色", code="ROLE_NOT_ALLOWED")
    if body.create_account and body.username and db.scalar(
            select(Employee.id).join(User, User.id == Employee.user_id).where(
                func.lower(User.username) == body.username.lower())):
        raise Conflict("用户名已被在册员工使用", code="USERNAME_EXISTS")
    data = body.model_dump(exclude={"base_salary"})
    for k, v in data.items():
        setattr(o, k, v)
    o.base_salary_cents = to_cents(body.base_salary) if body.base_salary else None


@router.get("/onboarding", response_model=Page[OnboardingOut], summary="入职申请列表")
def list_onboarding(status: str | None = None, page: PageParams = Depends(),
                    cu: CurrentUser = Depends(require("onboarding:manage")), db: Session = Depends(get_db)):
    stmt = select(OnboardingRequest)
    if status:
        stmt = stmt.where(OnboardingRequest.status == status)
    return paginate(db, stmt, page, None, OnboardingRequest.id.desc(), lambda o: onb_out(db, o))


@router.post("/onboarding", response_model=OnboardingOut, status_code=201, summary="创建入职申请（submit=true 直接发起流程）")
def create_onboarding(body: OnboardingIn, request: Request, submit: bool = False,
                      cu: CurrentUser = Depends(require("onboarding:manage")), db: Session = Depends(get_db)):
    def action():
        o = OnboardingRequest(status="draft", created_by=cu.id)
        _onb_apply(db, cu, o, body)
        db.add(o)
        db.flush()
        if o.candidate_id:
            db.get(Candidate, o.candidate_id).status = "onboarding"
        if submit:
            _submit_onb(db, cu, o)
        return 201, jsonable(onb_out(db, o))
    return idempotent(db, cu, request, {"b": body.model_dump(mode="json"), "s": submit}, action)


def _submit_onb(db: Session, cu: CurrentUser, o: OnboardingRequest) -> None:
    flow.submit(db, cu, o, business_type="onboarding", title=f"入职审批：{o.name}", subject_employee_id=None,
                variables={"department_id": o.department_id, "probation_months": o.probation_months},
                label="入职申请")


def _get_onb(db: Session, oid: int) -> OnboardingRequest:
    o = db.get(OnboardingRequest, oid)
    if o is None:
        raise NotFound("入职申请不存在")
    return o


@router.get("/onboarding/{oid}", response_model=OnboardingOut, summary="入职申请详情")
def get_onboarding(oid: int, cu: CurrentUser = Depends(require("onboarding:manage")), db: Session = Depends(get_db)):
    return onb_out(db, _get_onb(db, oid))


@router.put("/onboarding/{oid}", response_model=OnboardingOut, summary="修改入职申请")
def update_onboarding(oid: int, body: OnboardingIn, cu: CurrentUser = Depends(require("onboarding:manage")),
                      db: Session = Depends(get_db)):
    o = _get_onb(db, oid)
    flow.ensure_editable(o, "入职申请")
    _onb_apply(db, cu, o, body)
    db.commit()
    return onb_out(db, o)


@router.post("/onboarding/{oid}/submit", response_model=OnboardingOut, summary="提交入职审批")
def submit_onboarding(oid: int, request: Request, cu: CurrentUser = Depends(require("onboarding:manage")),
                      db: Session = Depends(get_db)):
    o = _get_onb(db, oid)

    def action():
        _submit_onb(db, cu, o)
        return 200, jsonable(onb_out(db, o))
    return idempotent(db, cu, request, {"id": oid}, action)


@router.post("/onboarding/{oid}/withdraw", response_model=OnboardingOut, summary="撤回入职审批")
def withdraw_onboarding(oid: int, cu: CurrentUser = Depends(require("onboarding:manage")),
                        db: Session = Depends(get_db)):
    o = _get_onb(db, oid)
    from ..models import WfInstance
    from ..workflow import engine
    inst = db.scalar(select(WfInstance).where(WfInstance.business_type == "onboarding", WfInstance.business_id == o.id,
                                              WfInstance.status == "running"))
    if inst is None:
        raise InvalidState("没有进行中的流程", code="INSTANCE_NOT_RUNNING")
    if inst.initiator_id == cu.id:
        engine.withdraw(db, inst.id, cu.id)
    else:  # another HR member stops it: cancel (terminal)
        engine.cancel(db, inst.id, cu.id, True)
    db.commit()
    return onb_out(db, o)


class OnbTaskOut(BaseModel):
    id: int
    onboarding_id: int
    employee_id: int
    employee_name: str
    title: str
    assignee_id: int
    assignee_name: str | None
    due_date: date
    status: str
    done_at: datetime | None


def task_out(db: Session, t: OnboardingTask) -> OnbTaskOut:
    u = db.get(User, t.assignee_id)
    return OnbTaskOut(id=t.id, onboarding_id=t.onboarding_id, employee_id=t.employee_id,
                      employee_name=db.get(Employee, t.employee_id).name, title=t.title, assignee_id=t.assignee_id,
                      assignee_name=u.display_name if u else None, due_date=t.due_date, status=t.status,
                      done_at=t.done_at)


@router.get("/onboarding-tasks", response_model=list[OnbTaskOut], summary="入职待办（mine 我的 / all 全部）")
def onboarding_tasks(scope: str = Query("mine", pattern="^(mine|all)$"), onboarding_id: int | None = None,
                     cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(OnboardingTask)
    if scope == "mine":
        stmt = stmt.where(OnboardingTask.assignee_id == cu.id)
    else:
        cu.require("onboarding:manage")
    if onboarding_id:
        stmt = stmt.where(OnboardingTask.onboarding_id == onboarding_id)
    return [task_out(db, t) for t in db.scalars(stmt.order_by(OnboardingTask.due_date, OnboardingTask.id))]


@router.post("/onboarding-tasks/{tid}/done", response_model=OnbTaskOut, summary="完成入职待办")
def complete_task(tid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(OnboardingTask, tid)
    if t is None:
        raise NotFound("待办不存在")
    if t.assignee_id != cu.id and not cu.has("onboarding:manage"):
        raise Forbidden("只能完成分配给自己的待办", code="NOT_ASSIGNEE")
    if t.status == "done":
        raise InvalidState("待办已完成", code="INVALID_STATE")
    t.status = "done"
    t.done_at = timeutil.now()
    db.commit()
    return task_out(db, t)


# ================================================================== regularization
class RegIn(BaseModel):
    employee_id: int | None = None
    planned_date: date
    self_review: str = Field(min_length=1, max_length=5000)


class RegOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    department_name: str | None
    hire_date: date
    probation_end_date: date | None
    planned_date: date
    self_review: str
    manager_evaluation: str | None
    manager_score: int | None
    hr_comment: str | None
    status: str
    instance_id: int | None
    created_at: datetime


def reg_out(db: Session, r: RegularizationRequest) -> RegOut:
    e = db.get(Employee, r.employee_id)
    d = db.get(Department, e.department_id)
    return RegOut(id=r.id, employee_id=e.id, employee_name=e.name, department_name=d.name if d else None,
                  hire_date=e.hire_date, probation_end_date=e.probation_end_date, planned_date=r.planned_date,
                  self_review=r.self_review, manager_evaluation=r.manager_evaluation, manager_score=r.manager_score,
                  hr_comment=r.hr_comment, status=r.status, instance_id=r.instance_id, created_at=r.created_at)


class ProbationOut(BaseModel):
    id: int
    employee_no: str
    name: str
    department_id: int
    hire_date: date
    probation_end_date: date | None
    manager_id: int | None
    has_open_request: bool


@router.get("/regularization/probation-employees", response_model=list[ProbationOut], summary="试用期员工（按数据权限）")
def probation_employees(cu: CurrentUser = Depends(require_any("regularization:manage", "employee:read")),
                        db: Session = Depends(get_db)):
    stmt = select(Employee).where(Employee.status == "probation")
    f = employee_scope_filter(db, cu, Employee.id)
    if f is not None and not cu.has("regularization:manage"):
        stmt = stmt.where(f)
    open_ids = set(db.scalars(select(RegularizationRequest.employee_id).where(
        RegularizationRequest.status.in_(("draft", "pending")))))
    return [ProbationOut(id=e.id, employee_no=e.employee_no, name=e.name, department_id=e.department_id,
                         hire_date=e.hire_date, probation_end_date=e.probation_end_date, manager_id=e.manager_id,
                         has_open_request=e.id in open_ids) for e in db.scalars(stmt.order_by(Employee.hire_date))]


def _reg_target(db: Session, cu: CurrentUser, employee_id: int | None) -> Employee:
    if employee_id is None or (cu.employee and cu.employee.id == employee_id):
        cu.require("regularization:apply")
        return cu.require_employee()
    cu.require("regularization:manage")
    return org.get_employee(db, employee_id)


@router.get("/regularization", response_model=Page[RegOut], summary="转正申请（mine / all）")
def list_regularization(scope: str = Query("mine", pattern="^(mine|all)$"), status: str | None = None,
                        page: PageParams = Depends(), cu: CurrentUser = Depends(current_user),
                        db: Session = Depends(get_db)):
    stmt = select(RegularizationRequest)
    if scope == "mine":
        stmt = stmt.where(RegularizationRequest.employee_id == (cu.employee.id if cu.employee else -1))
    else:
        if not cu.has("regularization:manage"):
            f = employee_scope_filter(db, cu, RegularizationRequest.employee_id)
            cu.require("employee:read")
            if f is not None:
                stmt = stmt.where(f)
    if status:
        stmt = stmt.where(RegularizationRequest.status == status)
    return paginate(db, stmt, page, None, RegularizationRequest.id.desc(), lambda r: reg_out(db, r))


@router.post("/regularization", response_model=RegOut, status_code=201,
             summary="创建转正申请（本人，或 HR 代发；submit=true 直接发起）")
def create_regularization(body: RegIn, request: Request, submit: bool = False,
                          cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    emp = _reg_target(db, cu, body.employee_id)

    def action():
        if emp.status != "probation":
            raise InvalidState("只有试用期员工可以申请转正", code="NOT_ON_PROBATION")
        if db.scalar(select(RegularizationRequest.id).where(RegularizationRequest.employee_id == emp.id,
                                                            RegularizationRequest.status.in_(("draft", "pending")))):
            raise Conflict("已有进行中的转正申请", code="REGULARIZATION_EXISTS")
        if body.planned_date < emp.hire_date:
            raise ValidationFailed("转正日期不能早于入职日期", code="INVALID_DATE")
        r = RegularizationRequest(employee_id=emp.id, planned_date=body.planned_date, self_review=body.self_review,
                                  created_by=cu.id)
        db.add(r)
        db.flush()
        if submit:
            _submit_reg(db, cu, r, emp)
        return 201, jsonable(reg_out(db, r))
    return idempotent(db, cu, request, {"b": body.model_dump(mode="json"), "s": submit}, action)


def _submit_reg(db: Session, cu: CurrentUser, r: RegularizationRequest, emp: Employee) -> None:
    if emp.status != "probation":
        raise InvalidState("员工已不是试用期", code="NOT_ON_PROBATION")
    r.manager_score = r.manager_evaluation = r.hr_comment = None
    flow.submit(db, cu, r, business_type="regularization", title=f"{emp.name}的转正申请",
                subject_employee_id=emp.id, variables={"department_id": emp.department_id}, label="转正申请")


def _get_reg(db: Session, cu: CurrentUser, rid: int, write: bool = False) -> RegularizationRequest:
    r = db.get(RegularizationRequest, rid)
    if r is None:
        raise NotFound("转正申请不存在")
    own = cu.employee is not None and r.employee_id == cu.employee.id
    if not own and not cu.has("regularization:manage"):
        if write:
            raise Forbidden("无权操作该转正申请", code="NOT_OWNER")
        cu.require("employee:read")
        ensure_can_view_employee(db, cu, db.get(Employee, r.employee_id))
    return r


@router.get("/regularization/{rid}", response_model=RegOut, summary="转正申请详情")
def get_regularization(rid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return reg_out(db, _get_reg(db, cu, rid))


@router.post("/regularization/{rid}/submit", response_model=RegOut, summary="提交转正审批")
def submit_regularization(rid: int, request: Request, cu: CurrentUser = Depends(current_user),
                          db: Session = Depends(get_db)):
    r = _get_reg(db, cu, rid, write=True)

    def action():
        _submit_reg(db, cu, r, db.get(Employee, r.employee_id))
        return 200, jsonable(reg_out(db, r))
    return idempotent(db, cu, request, {"id": rid}, action)


@router.post("/regularization/{rid}/withdraw", response_model=RegOut, summary="撤回转正申请")
def withdraw_regularization(rid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    r = _get_reg(db, cu, rid, write=True)
    flow.withdraw(db, cu, r, "regularization", "转正申请")
    db.commit()
    return reg_out(db, r)


class RegUpdate(BaseModel):
    planned_date: date
    self_review: str = Field(min_length=1, max_length=5000)


@router.put("/regularization/{rid}", response_model=RegOut, summary="修改转正申请")
def update_regularization(rid: int, body: RegUpdate, cu: CurrentUser = Depends(current_user),
                          db: Session = Depends(get_db)):
    r = _get_reg(db, cu, rid, write=True)
    flow.ensure_editable(r, "转正申请")
    r.planned_date, r.self_review = body.planned_date, body.self_review
    db.commit()
    return reg_out(db, r)


# ================================================================== transfer
class TransferIn(BaseModel):
    employee_id: int
    to_department_id: int
    to_position_id: int | None = None
    to_manager_id: int | None = None
    effective_date: date
    reason: str = Field(min_length=1, max_length=500)


class TransferOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    from_department_id: int
    from_department_name: str | None
    to_department_id: int
    to_department_name: str | None
    from_position_name: str | None
    to_position_id: int | None
    to_position_name: str | None
    to_manager_id: int | None
    to_manager_name: str | None
    effective_date: date
    reason: str
    status: str
    instance_id: int | None
    created_at: datetime


def tr_out(db: Session, t: TransferRequest) -> TransferOut:
    d, p, e, _ = _names(db)
    return TransferOut(id=t.id, employee_id=t.employee_id, employee_name=e.get(t.employee_id, "?"),
                       from_department_id=t.from_department_id, from_department_name=d.get(t.from_department_id),
                       to_department_id=t.to_department_id, to_department_name=d.get(t.to_department_id),
                       from_position_name=p.get(t.from_position_id), to_position_id=t.to_position_id,
                       to_position_name=p.get(t.to_position_id), to_manager_id=t.to_manager_id,
                       to_manager_name=e.get(t.to_manager_id), effective_date=t.effective_date, reason=t.reason,
                       status=t.status, instance_id=t.instance_id, created_at=t.created_at)


@router.get("/transfers", response_model=Page[TransferOut], summary="调岗申请")
def list_transfers(status: str | None = None, employee_id: int | None = None, page: PageParams = Depends(),
                   cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(TransferRequest)
    if not cu.has("transfer:manage"):
        stmt = stmt.where(TransferRequest.employee_id == (cu.employee.id if cu.employee else -1))
    if status:
        stmt = stmt.where(TransferRequest.status == status)
    if employee_id:
        stmt = stmt.where(TransferRequest.employee_id == employee_id)
    return paginate(db, stmt, page, None, TransferRequest.id.desc(), lambda t: tr_out(db, t))


@router.post("/transfers", response_model=TransferOut, status_code=201, summary="发起调岗（HR；调出/调入部门并行会审）")
def create_transfer(body: TransferIn, request: Request, cu: CurrentUser = Depends(require("transfer:manage")),
                    db: Session = Depends(get_db)):
    def action():
        emp = org.get_employee(db, body.employee_id)
        if emp.status == "resigned":
            raise InvalidState("离职员工不能调岗", code="EMPLOYEE_RESIGNED")
        if body.to_department_id == emp.department_id and body.to_position_id == emp.position_id:
            raise ValidationFailed("调岗前后部门与岗位相同", code="NO_CHANGE")
        org.get_department(db, body.to_department_id)
        org.get_position(db, body.to_position_id)
        org.check_manager(db, emp.id, body.to_manager_id)
        if db.scalar(select(TransferRequest.id).where(TransferRequest.employee_id == emp.id,
                                                      TransferRequest.status.in_(("draft", "pending")))):
            raise Conflict("该员工已有进行中的调岗申请", code="TRANSFER_EXISTS")
        t = TransferRequest(employee_id=emp.id, from_department_id=emp.department_id, to_department_id=body.to_department_id,
                            from_position_id=emp.position_id, to_position_id=body.to_position_id,
                            to_manager_id=body.to_manager_id, effective_date=body.effective_date, reason=body.reason,
                            created_by=cu.id)
        db.add(t)
        db.flush()
        flow.submit(db, cu, t, business_type="transfer", title=f"{emp.name}的调岗申请", subject_employee_id=emp.id,
                    variables={"from_department_id": emp.department_id, "to_department_id": body.to_department_id},
                    label="调岗申请")
        return 201, jsonable(tr_out(db, t))
    return idempotent(db, cu, request, body.model_dump(mode="json"), action)


@router.get("/transfers/{tid}", response_model=TransferOut, summary="调岗详情")
def get_transfer(tid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(TransferRequest, tid)
    if t is None:
        raise NotFound("调岗申请不存在")
    if not cu.has("transfer:manage") and not (cu.employee and cu.employee.id == t.employee_id):
        raise Forbidden("无权查看", code="DATA_SCOPE_DENIED")
    return tr_out(db, t)


@router.post("/transfers/{tid}/cancel", response_model=TransferOut, summary="取消调岗")
def cancel_transfer(tid: int, cu: CurrentUser = Depends(require("transfer:manage")), db: Session = Depends(get_db)):
    t = db.get(TransferRequest, tid)
    if t is None:
        raise NotFound("调岗申请不存在")
    if t.status == "pending":
        from ..workflow import engine
        engine.withdraw_for_business(db, "transfer", t.id, cu.id, cancel_instead=True, can_monitor=True)
    else:
        flow.cancel(db, cu, t, "transfer", "调岗申请")
    db.commit()
    return tr_out(db, t)
