"""Organisation and employee rules shared by OA, HRM and workflow."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import notify
from ..core.deps import department_subtree
from ..core.errors import Conflict, InvalidState, NotFound, ValidationFailed
from ..models import (Department, DepartmentChangeLog, Employee, JobHistory, Position, Role, User, UserSession,
                      WfHistory, WfInstance, WfTask)

EMPLOYEE_PREFIX = "HTT"


def get_department(db: Session, dept_id: int, active: bool = True) -> Department:
    d = db.get(Department, dept_id)
    if d is None:
        raise NotFound("部门不存在", code="DEPARTMENT_NOT_FOUND")
    if active and d.status != "active":
        raise ValidationFailed("部门已停用", code="DEPARTMENT_DISABLED")
    return d


def get_employee(db: Session, emp_id: int) -> Employee:
    e = db.get(Employee, emp_id)
    if e is None:
        raise NotFound("员工不存在", code="EMPLOYEE_NOT_FOUND")
    return e


def get_position(db: Session, pos_id: int | None) -> Position | None:
    if pos_id is None:
        return None
    p = db.get(Position, pos_id)
    if p is None:
        raise NotFound("岗位不存在", code="POSITION_NOT_FOUND")
    return p


def log_department(db: Session, dept_id: int, action: str, detail: dict, operator_id: int | None) -> None:
    db.add(DepartmentChangeLog(department_id=dept_id, action=action, detail=detail, operator_id=operator_id))


def check_parent(db: Session, dept_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    get_department(db, parent_id)
    if dept_id is not None and parent_id in department_subtree(db, dept_id):
        raise ValidationFailed("上级部门不能是自身或下级部门", code="DEPARTMENT_CYCLE")


def check_manager(db: Session, employee_id: int | None, manager_id: int | None) -> None:
    """Manager must exist, be active and must not create a reporting cycle."""
    if manager_id is None:
        return
    mgr = db.get(Employee, manager_id)
    if mgr is None:
        raise NotFound("直属上级不存在", code="MANAGER_NOT_FOUND")
    if mgr.status == "resigned":
        raise ValidationFailed("直属上级已离职", code="MANAGER_RESIGNED")
    if employee_id is None:
        return
    cur, seen = mgr, set()
    while cur is not None:
        if cur.id == employee_id:
            raise ValidationFailed("直属上级设置会形成汇报环", code="MANAGER_CYCLE")
        if cur.id in seen or cur.manager_id is None:
            break
        seen.add(cur.id)
        cur = db.get(Employee, cur.manager_id)


def next_employee_no(db: Session) -> str:
    rows = db.scalars(select(Employee.employee_no).where(Employee.employee_no.like(f"{EMPLOYEE_PREFIX}%")))
    best = 0
    for no in rows:
        m = re.match(rf"{EMPLOYEE_PREFIX}(\d+)$", no)
        if m:
            best = max(best, int(m.group(1)))
    return f"{EMPLOYEE_PREFIX}{best + 1:04d}"


def add_history(db: Session, emp: Employee, change_type: str, effective: date, *, operator_id: int | None,
                reason: str | None = None, ref_type: str | None = None, ref_id: int | None = None,
                before: dict | None = None) -> JobHistory:
    before = before or {}
    h = JobHistory(employee_id=emp.id, change_type=change_type, effective_date=effective, reason=reason,
                   ref_type=ref_type, ref_id=ref_id, operator_id=operator_id,
                   from_department_id=before.get("department_id"), to_department_id=emp.department_id,
                   from_position_id=before.get("position_id"), to_position_id=emp.position_id,
                   from_manager_id=before.get("manager_id"), to_manager_id=emp.manager_id,
                   from_status=before.get("status"), to_status=emp.status)
    db.add(h)
    return h


def snapshot(emp: Employee) -> dict:
    return {"department_id": emp.department_id, "position_id": emp.position_id, "manager_id": emp.manager_id,
            "status": emp.status}


def default_role(db: Session, code: str = "employee") -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise ValidationFailed(f"角色 {code} 不存在", code="ROLE_NOT_FOUND")
    return role


def reassign_pending_tasks(db: Session, user_id: int, fallback_user_id: int | None, operator_id: int | None,
                           reason: str) -> int:
    """Move pending workflow tasks of an unavailable user to a fallback approver."""
    from ..workflow.engine import _role_users  # noqa: WPS433
    tasks = db.scalars(select(WfTask).where(WfTask.assignee_id == user_id, WfTask.status == "pending")).all()
    moved = 0
    for t in tasks:
        inst = db.get(WfInstance, t.instance_id)
        target = fallback_user_id
        if target in (None, inst.subject_user_id, user_id):
            target = next((u for u in _role_users(db, "admin") if u not in (inst.subject_user_id, user_id)), None)
        if target is None:
            continue
        already = db.scalar(select(WfTask.id).where(WfTask.instance_id == t.instance_id, WfTask.node_id == t.node_id,
                                                    WfTask.assignee_id == target, WfTask.status == "pending"))
        t.status = "transferred"
        t.comment = reason
        t.acted_at = timeutil.now()
        db.flush()
        if not already:
            new = WfTask(instance_id=t.instance_id, node_id=t.node_id, node_name=t.node_name, mode=t.mode,
                         assignee_id=target, status="pending", transferred_from_task_id=t.id)
            db.add(new)
            db.flush()
            notify(db, target, "workflow_todo", f"待审批（自动转交）：{inst.title}", reason,
                   f"/approvals?task={new.id}", "wf_task", new.id)
        db.add(WfHistory(instance_id=t.instance_id, task_id=t.id, node_id=t.node_id, node_name=t.node_name,
                         action="reassign", actor_id=operator_id, comment=reason,
                         detail={"from": user_id, "to": target}))
        moved += 1
    return moved


def resign_employee(db: Session, emp: Employee, resign_date: date, reason: str, operator_id: int | None) -> None:
    if emp.status == "resigned":
        raise InvalidState("员工已离职", code="ALREADY_RESIGNED")
    before = snapshot(emp)
    emp.status = "resigned"
    emp.resign_date = resign_date
    add_history(db, emp, "resign", resign_date, operator_id=operator_id, reason=reason, before=before)
    for d in db.scalars(select(Department).where(Department.manager_employee_id == emp.id)):
        d.manager_employee_id = None
        log_department(db, d.id, "manager_change", {"from": emp.id, "to": None, "reason": "负责人离职"}, operator_id)
    # direct reports move up to the resigned employee's manager
    db.execute(update(Employee).where(Employee.manager_id == emp.id, Employee.id != emp.id)
               .values(manager_id=emp.manager_id, version=Employee.version + 1))
    if emp.user_id:
        user = db.get(User, emp.user_id)
        user.status = "disabled"
        db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                   .values(revoked_at=timeutil.now()))
        mgr_user = db.get(Employee, emp.manager_id).user_id if emp.manager_id else None
        reassign_pending_tasks(db, user.id, mgr_user, operator_id, f"{emp.name} 已离职，任务自动转交")


def count_active_members(db: Session, dept_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Employee).where(Employee.department_id == dept_id,
                                                                      Employee.status != "resigned"))


def ensure_username_free(db: Session, username: str) -> None:
    if db.scalar(select(User.id).where(func.lower(User.username) == username.lower())):
        raise Conflict("用户名已存在", code="USERNAME_EXISTS")
