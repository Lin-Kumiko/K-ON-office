"""Workflow handlers for every workflow-backed business document (except leave, see leave.py)."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import notify
from ..core.errors import Conflict, InvalidState, ValidationFailed
from ..core.security import unusable_password
from ..models import (AttendanceCorrection, Candidate, Department, Employee, ExpenseClaim, JobRequisition, LeaveType,
                      MeetingBooking, Offer, OnboardingRequest, OnboardingTask, OvertimeRequest,
                      RegularizationRequest, Role, SalaryStructure, TransferRequest, TravelRequest, User)
from ..workflow import engine, registry
from . import attendance, leave, org
from .documents_flow import DocHandler


def _add_months(d, months: int):
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    import calendar as _cal
    return d.replace(year=y, month=m, day=min(d.day, _cal.monthrange(y, m)[1]))


class TravelHandler(DocHandler):
    model = TravelRequest
    business_type = "travel"
    label = "出差申请"

    def after_approved(self, db, doc, inst, actor_id):
        if doc.original_id:
            orig = db.get(TravelRequest, doc.original_id)
            if orig is None or orig.status != "approved":
                raise InvalidState("原出差申请已不是已批准状态，变更无法生效", code="ORIGINAL_NOT_APPROVED")
            orig.status = "changed"
            orig.decided_at = timeutil.now()
            db.flush()
            attendance.recompute_range(db, orig.employee_id, orig.start_date, orig.end_date)
        attendance.recompute_range(db, doc.employee_id, doc.start_date, doc.end_date)


class ExpenseHandler(DocHandler):
    model = ExpenseClaim
    business_type = "expense"
    label = "报销单"

    def after_approved(self, db, doc, inst, actor_id):
        from ..workflow.engine import _role_users
        for uid in _role_users(db, "finance"):
            notify(db, uid, "expense_finance", f"待财务确认：{doc.claim_no}",
                   f"{doc.title} 已审批通过，等待财务确认", f"/expense?claim={doc.id}", "expense_claim", doc.id)


class MeetingHandler(DocHandler):
    model = MeetingBooking
    business_type = "meeting"
    label = "会议室预约"

    def after_approved(self, db, doc, inst, actor_id):
        for uid in doc.attendee_ids or []:
            notify(db, uid, "meeting", f"会议邀请：{doc.subject}",
                   f"{doc.start_at:%m-%d %H:%M}-{doc.end_at:%H:%M}", f"/meeting?booking={doc.id}",
                   "meeting_booking", doc.id)


class OfferHandler(DocHandler):
    model = Offer
    business_type = "offer"
    label = "录用审批"

    def after_approved(self, db, doc, inst, actor_id):
        cand = db.get(Candidate, doc.candidate_id)
        cand.status = "offered"

    def after_closed(self, db, doc, inst, actor_id, status):
        cand = db.get(Candidate, doc.candidate_id)
        if cand.status == "offer_pending":
            cand.status = "interviewing"


ONBOARDING_TASKS = [
    ("签署劳动合同与保密协议", "hr"),
    ("准备工位与乐器（办公设备）", "manager"),
    ("开通系统账号并设置初始密码", "admin"),
    ("参加新人茶话会（入职培训）", "self"),
]


class OnboardingHandler(DocHandler):
    model = OnboardingRequest
    business_type = "onboarding"
    label = "入职申请"

    def after_approved(self, db: Session, doc: OnboardingRequest, inst, actor_id):
        if doc.employee_id:
            raise InvalidState("该入职申请已生成员工档案", code="ALREADY_ONBOARDED")
        dept = org.get_department(db, doc.department_id)
        org.get_position(db, doc.position_id)
        if db.scalar(select(Employee.id).where(func.lower(Employee.email) == doc.email.lower())):
            raise Conflict("邮箱已被其他员工档案使用，入职未生效", code="EMAIL_EXISTS")
        manager_id = doc.manager_id or dept.manager_employee_id
        if manager_id:
            org.check_manager(db, None, manager_id)
        months = doc.probation_months
        emp = Employee(employee_no=org.next_employee_no(db), name=doc.name, gender=doc.gender, phone=doc.phone,
                       email=doc.email, department_id=dept.id, position_id=doc.position_id, manager_id=manager_id,
                       hire_date=doc.hire_date, status="probation" if months > 0 else "regular",
                       probation_end_date=_add_months(doc.hire_date, months) if months > 0 else None,
                       regularized_date=None if months > 0 else doc.hire_date)
        db.add(emp)
        db.flush()
        org.add_history(db, emp, "onboard", doc.hire_date, operator_id=actor_id, reason="入职审批通过",
                        ref_type="onboarding", ref_id=doc.id)
        user = None
        if doc.create_account:
            user = self._account(db, doc, emp)
            emp.user_id = user.id
            doc.user_id = user.id
        doc.employee_id = emp.id
        leave.ensure_year_balances(db, emp, doc.hire_date.year, actor_id)
        if doc.base_salary_cents:
            db.add(SalaryStructure(employee_id=emp.id, base_cents=doc.base_salary_cents, allowance_cents=0,
                                   effective_from=doc.hire_date, note="入职定薪", created_by=actor_id))
        mgr_user = db.get(Employee, manager_id).user_id if manager_id else None
        from ..workflow.engine import _role_users
        admin_user = next(iter(_role_users(db, "admin")), None)
        owners = {"hr": inst.initiator_id, "manager": mgr_user or inst.initiator_id,
                  "admin": admin_user or inst.initiator_id, "self": user.id if user else inst.initiator_id}
        for i, (title, who) in enumerate(ONBOARDING_TASKS):
            assignee = owners[who]
            db.add(OnboardingTask(onboarding_id=doc.id, employee_id=emp.id, title=title, assignee_id=assignee,
                                  due_date=doc.hire_date + timedelta(days=i)))
            notify(db, assignee, "onboarding_task", f"入职待办：{title}", f"新成员 {emp.name} 入职",
                   "/recruitment?tab=tasks", "onboarding", doc.id)
        if doc.candidate_id:
            cand = db.get(Candidate, doc.candidate_id)
            cand.status = "hired"
            if cand.requisition_id:
                req = db.get(JobRequisition, cand.requisition_id)
                req.hired_count += 1
                if req.hired_count >= req.headcount:
                    req.status = "closed"
        db.flush()

    def after_closed(self, db, doc, inst, actor_id, status):
        if status == "cancelled" and doc.candidate_id:
            cand = db.get(Candidate, doc.candidate_id)
            if cand.status == "onboarding":
                cand.status = "offered"

    def _account(self, db: Session, doc: OnboardingRequest, emp: Employee) -> User:
        uname = (doc.username or re.sub(r"[^a-z0-9_.-]", "", doc.email.split("@")[0].lower()))[:32]
        if not uname:
            raise ValidationFailed("无法生成用户名", code="INVALID_USERNAME")
        user = db.scalar(select(User).where(func.lower(User.username) == uname.lower()))
        if user is None:
            user = db.scalar(select(User).where(func.lower(User.email) == doc.email.lower()))
        if user is not None:
            if db.scalar(select(Employee.id).where(Employee.user_id == user.id, Employee.id != emp.id)):
                raise Conflict(f"账号 {user.username} 已关联其他员工，入职未生效", code="ACCOUNT_ALREADY_LINKED")
            doc.account_linked = True
        else:
            user = User(username=uname, display_name=doc.name, email=doc.email, password_hash=unusable_password(),
                        status="active", must_change_password=True)
            db.add(user)
            db.flush()
        codes = doc.role_codes or ["employee"]
        if "employee" not in codes:
            codes = ["employee", *codes]
        have = {r.code for r in user.roles}
        for code in codes:
            if code in have:
                continue
            role = db.scalar(select(Role).where(Role.code == code))
            if role is None:
                raise ValidationFailed(f"角色 {code} 不存在", code="ROLE_NOT_FOUND")
            if role.code == "admin":
                raise ValidationFailed("入职流程不能直接授予管理员角色", code="ROLE_NOT_ALLOWED")
            user.roles.append(role)
        user.status = "active"
        return user


class RegularizationHandler(DocHandler):
    model = RegularizationRequest
    business_type = "regularization"
    label = "转正申请"

    def on_task_approved(self, db, inst, task, form):
        node = engine.graph_for(db, inst.version_id).node(task.node_id)
        key = (node.get("config") or {}).get("form_key")
        doc = db.get(RegularizationRequest, inst.business_id)
        if key == "manager_evaluation":
            score, evaluation = form.get("score"), form.get("evaluation")
            if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
                raise ValidationFailed("主管评价需要 0-100 的整数评分 score", code="EVALUATION_REQUIRED")
            if not isinstance(evaluation, str) or not evaluation.strip() or len(evaluation) > 2000:
                raise ValidationFailed("主管评价需要填写评价内容 evaluation", code="EVALUATION_REQUIRED")
            doc.manager_score, doc.manager_evaluation = score, evaluation.strip()
        elif key == "hr_review":
            doc.hr_comment = (form.get("comment") or task.comment or "").strip() or None

    def after_approved(self, db, doc, inst, actor_id):
        emp = org.get_employee(db, doc.employee_id)
        if emp.status != "probation":
            raise InvalidState("员工已不是试用期状态，转正未生效", code="NOT_ON_PROBATION")
        if doc.manager_score is None:
            raise InvalidState("缺少主管评价，转正未生效", code="EVALUATION_REQUIRED")
        before = org.snapshot(emp)
        emp.status = "regular"
        emp.regularized_date = doc.planned_date
        org.add_history(db, emp, "regularize", doc.planned_date, operator_id=actor_id,
                        reason=f"转正审批通过（主管评分 {doc.manager_score}）", ref_type="regularization",
                        ref_id=doc.id, before=before)


class TransferHandler(DocHandler):
    model = TransferRequest
    business_type = "transfer"
    label = "调岗申请"

    def after_approved(self, db, doc, inst, actor_id):
        emp = org.get_employee(db, doc.employee_id)
        if emp.status == "resigned":
            raise InvalidState("员工已离职，调岗未生效", code="EMPLOYEE_RESIGNED")
        if emp.department_id != doc.from_department_id:
            raise InvalidState("员工所在部门已变化，请重新发起调岗", code="SOURCE_CHANGED")
        org.get_department(db, doc.to_department_id)
        org.get_position(db, doc.to_position_id)
        to_manager = doc.to_manager_id or db.get(Department, doc.to_department_id).manager_employee_id
        if to_manager == emp.id:
            to_manager = None
        org.check_manager(db, emp.id, to_manager)
        before = org.snapshot(emp)
        for d in db.scalars(select(Department).where(Department.manager_employee_id == emp.id,
                                                     Department.id == emp.department_id)):
            d.manager_employee_id = None
            org.log_department(db, d.id, "manager_change", {"from": emp.id, "to": None, "reason": "负责人调岗"},
                               actor_id)
        emp.department_id = doc.to_department_id
        emp.position_id = doc.to_position_id
        emp.manager_id = to_manager
        db.flush()
        org.add_history(db, emp, "transfer", doc.effective_date, operator_id=actor_id, reason=doc.reason,
                        ref_type="transfer", ref_id=doc.id, before=before)


class CorrectionHandler(DocHandler):
    model = AttendanceCorrection
    business_type = "attendance_correction"
    label = "补卡申请"

    def after_approved(self, db, doc, inst, actor_id):
        emp = org.get_employee(db, doc.employee_id)
        attendance.punch(db, emp, doc.corrected_time, "correction", ref_id=doc.id)


class OvertimeHandler(DocHandler):
    model = OvertimeRequest
    business_type = "overtime"
    label = "加班申请"

    def after_approved(self, db, doc, inst, actor_id):
        if doc.compensation != "leave":
            return
        comp = db.scalar(select(LeaveType).where(LeaveType.code == "comp"))
        if comp is None:
            raise InvalidState("未配置调休假类型", code="NO_COMP_LEAVE_TYPE")
        leave.grant(db, doc.employee_id, comp.id, doc.start_at.year, doc.hours, actor_id,
                    f"加班 {doc.hours} 小时转调休", change_type="overtime_credit", ref_type="overtime_request",
                    ref_id=doc.id)


for _h in (TravelHandler(), ExpenseHandler(), MeetingHandler(), OfferHandler(), OnboardingHandler(),
           RegularizationHandler(), TransferHandler(), CorrectionHandler(), OvertimeHandler()):
    registry.register(_h)
