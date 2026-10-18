"""Departments, positions, employees and job history."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ..core import timeutil
from ..core.common import audit, paginate
from ..core.deps import (CurrentUser, PageParams, current_user, department_subtree, employee_scope_filter,
                         ensure_can_view_employee, get_db, require)
from ..core.errors import Conflict, ValidationFailed
from ..core.security import hash_password, mask_email, mask_phone, unusable_password, validate_password_strength
from ..models import Department, DepartmentChangeLog, Employee, JobHistory, Position, Role, User
from ..services import leave as leave_svc
from ..services import org
from ..services.handlers import _add_months
from .common import ERRORS, Page

router = APIRouter(prefix="/api", tags=["组织与员工"], responses=ERRORS)


# ------------------------------------------------------------------ departments
class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    parent_id: int | None = None
    manager_employee_id: int | None = None
    sort: int = Field(0, ge=0, le=9999)
    description: str | None = Field(None, max_length=255)


class DepartmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    manager_employee_id: int | None = None
    sort: int = Field(0, ge=0, le=9999)
    description: str | None = Field(None, max_length=255)


class DepartmentOut(BaseModel):
    id: int
    name: str
    code: str
    parent_id: int | None
    manager_employee_id: int | None
    manager_name: str | None
    sort: int
    description: str | None
    status: str
    member_count: int
    children: list["DepartmentOut"] = []


def _dept_outs(db: Session) -> list[DepartmentOut]:
    names = dict(db.execute(select(Employee.id, Employee.name)).all())
    counts = dict(db.execute(select(Employee.department_id, func.count()).where(Employee.status != "resigned")
                             .group_by(Employee.department_id)).all())
    return [DepartmentOut(id=d.id, name=d.name, code=d.code, parent_id=d.parent_id,
                          manager_employee_id=d.manager_employee_id, manager_name=names.get(d.manager_employee_id),
                          sort=d.sort, description=d.description, status=d.status, member_count=counts.get(d.id, 0))
            for d in db.scalars(select(Department).order_by(Department.sort, Department.id))]


@router.get("/departments", response_model=list[DepartmentOut], summary="部门列表（扁平）")
def list_departments(include_disabled: bool = False, cu: CurrentUser = Depends(require("org:read")),
                     db: Session = Depends(get_db)):
    return [d for d in _dept_outs(db) if include_disabled or d.status == "active"]


@router.get("/departments/tree", response_model=list[DepartmentOut], summary="组织树")
def department_tree(include_disabled: bool = False, cu: CurrentUser = Depends(require("org:read")),
                    db: Session = Depends(get_db)):
    nodes = {d.id: d for d in _dept_outs(db) if include_disabled or d.status == "active"}
    roots = []
    for d in nodes.values():
        if d.parent_id and d.parent_id in nodes:
            nodes[d.parent_id].children.append(d)
        else:
            roots.append(d)
    return roots


def _dept_single(db: Session, dept_id: int) -> DepartmentOut:
    return next(d for d in _dept_outs(db) if d.id == dept_id)


@router.post("/departments", response_model=DepartmentOut, status_code=201, summary="创建部门")
def create_department(body: DepartmentIn, cu: CurrentUser = Depends(require("org:manage")),
                      db: Session = Depends(get_db)):
    if db.scalar(select(Department.id).where(Department.code == body.code)):
        raise Conflict("部门编码已存在", code="DEPARTMENT_CODE_EXISTS")
    org.check_parent(db, None, body.parent_id)
    if body.manager_employee_id:
        org.check_manager(db, None, body.manager_employee_id)
    d = Department(name=body.name, code=body.code, parent_id=body.parent_id,
                   manager_employee_id=body.manager_employee_id, sort=body.sort, description=body.description)
    db.add(d)
    db.flush()
    org.log_department(db, d.id, "create", body.model_dump(), cu.id)
    audit(db, cu, "create_department", "department", d.id)
    db.commit()
    return _dept_single(db, d.id)


@router.put("/departments/{dept_id}", response_model=DepartmentOut, summary="修改部门（含调整上级、负责人）")
def update_department(dept_id: int, body: DepartmentUpdate, cu: CurrentUser = Depends(require("org:manage")),
                      db: Session = Depends(get_db)):
    d = org.get_department(db, dept_id, active=False)
    org.check_parent(db, d.id, body.parent_id)
    if body.manager_employee_id:
        org.check_manager(db, None, body.manager_employee_id)
    changes = {}
    for field in ("name", "parent_id", "manager_employee_id", "sort", "description"):
        old, new = getattr(d, field), getattr(body, field)
        if old != new:
            changes[field] = {"from": old, "to": new}
            setattr(d, field, new)
    if changes:
        action = "move" if "parent_id" in changes else (
            "manager_change" if set(changes) == {"manager_employee_id"} else "update")
        org.log_department(db, d.id, action, changes, cu.id)
        audit(db, cu, "update_department", "department", d.id, changes)
    db.commit()
    return _dept_single(db, d.id)


@router.post("/departments/{dept_id}/disable", response_model=DepartmentOut, summary="停用部门")
def disable_department(dept_id: int, cu: CurrentUser = Depends(require("org:manage")), db: Session = Depends(get_db)):
    d = org.get_department(db, dept_id)
    if org.count_active_members(db, d.id):
        raise Conflict("部门仍有在职员工，不能停用", code="DEPARTMENT_NOT_EMPTY")
    if db.scalar(select(Department.id).where(Department.parent_id == d.id, Department.status == "active")):
        raise Conflict("部门仍有启用的下级部门，不能停用", code="DEPARTMENT_NOT_EMPTY")
    d.status = "disabled"
    org.log_department(db, d.id, "disable", {}, cu.id)
    db.commit()
    return _dept_single(db, d.id)


@router.post("/departments/{dept_id}/enable", response_model=DepartmentOut, summary="启用部门")
def enable_department(dept_id: int, cu: CurrentUser = Depends(require("org:manage")), db: Session = Depends(get_db)):
    d = org.get_department(db, dept_id, active=False)
    if d.parent_id:
        org.get_department(db, d.parent_id)
    d.status = "active"
    org.log_department(db, d.id, "enable", {}, cu.id)
    db.commit()
    return _dept_single(db, d.id)


class DeptLogOut(BaseModel):
    id: int
    action: str
    detail: dict | None
    operator_id: int | None
    operator_name: str | None
    created_at: datetime


@router.get("/departments/{dept_id}/logs", response_model=list[DeptLogOut], summary="部门调整记录")
def department_logs(dept_id: int, cu: CurrentUser = Depends(require("org:read")), db: Session = Depends(get_db)):
    org.get_department(db, dept_id, active=False)
    names = dict(db.execute(select(User.id, User.display_name)).all())
    rows = db.scalars(select(DepartmentChangeLog).where(DepartmentChangeLog.department_id == dept_id)
                      .order_by(DepartmentChangeLog.id.desc()))
    return [DeptLogOut(id=r.id, action=r.action, detail=r.detail, operator_id=r.operator_id,
                       operator_name=names.get(r.operator_id), created_at=r.created_at) for r in rows]


# ------------------------------------------------------------------ positions
class PositionIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    level: int = Field(1, ge=1, le=20)
    department_id: int | None = None
    description: str | None = Field(None, max_length=255)


class PositionOut(BaseModel):
    id: int
    name: str
    code: str
    level: int
    department_id: int | None
    description: str | None
    status: str


@router.get("/positions", response_model=list[PositionOut], summary="岗位列表")
def list_positions(cu: CurrentUser = Depends(require("org:read")), db: Session = Depends(get_db)):
    return [PositionOut.model_validate(p, from_attributes=True)
            for p in db.scalars(select(Position).order_by(Position.level.desc(), Position.id))]


@router.post("/positions", response_model=PositionOut, status_code=201, summary="创建岗位")
def create_position(body: PositionIn, cu: CurrentUser = Depends(require("org:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(Position.id).where(Position.code == body.code)):
        raise Conflict("岗位编码已存在", code="POSITION_CODE_EXISTS")
    if body.department_id:
        org.get_department(db, body.department_id)
    p = Position(**body.model_dump())
    db.add(p)
    db.flush()
    audit(db, cu, "create_position", "position", p.id)
    db.commit()
    return PositionOut.model_validate(p, from_attributes=True)


@router.put("/positions/{pos_id}", response_model=PositionOut, summary="修改岗位")
def update_position(pos_id: int, body: PositionIn, cu: CurrentUser = Depends(require("org:manage")),
                    db: Session = Depends(get_db)):
    p = org.get_position(db, pos_id)
    if body.code != p.code and db.scalar(select(Position.id).where(Position.code == body.code)):
        raise Conflict("岗位编码已存在", code="POSITION_CODE_EXISTS")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    audit(db, cu, "update_position", "position", p.id)
    db.commit()
    return PositionOut.model_validate(p, from_attributes=True)


# ------------------------------------------------------------------ employees
class EmployeeOut(BaseModel):
    id: int
    employee_no: str
    name: str
    gender: str | None
    birth_date: date | None
    phone: str | None
    email: str | None
    department_id: int
    department_name: str | None
    position_id: int | None
    position_name: str | None
    manager_id: int | None
    manager_name: str | None
    hire_date: date
    probation_end_date: date | None
    regularized_date: date | None
    resign_date: date | None
    status: str
    user_id: int | None
    username: str | None
    remark: str | None
    version: int


def employee_out(db: Session, cu: CurrentUser, e: Employee, cache: dict | None = None) -> EmployeeOut:
    cache = cache if cache is not None else {}
    if "d" not in cache:
        cache["d"] = dict(db.execute(select(Department.id, Department.name)).all())
        cache["p"] = dict(db.execute(select(Position.id, Position.name)).all())
        cache["e"] = dict(db.execute(select(Employee.id, Employee.name)).all())
        cache["u"] = dict(db.execute(select(User.id, User.username)).all())
    sensitive = cu.has("employee:sensitive") or (cu.employee is not None and cu.employee.id == e.id)
    return EmployeeOut(
        id=e.id, employee_no=e.employee_no, name=e.name, gender=e.gender,
        birth_date=e.birth_date if sensitive else None,
        phone=e.phone if sensitive else mask_phone(e.phone), email=e.email if sensitive else mask_email(e.email),
        department_id=e.department_id, department_name=cache["d"].get(e.department_id), position_id=e.position_id,
        position_name=cache["p"].get(e.position_id), manager_id=e.manager_id, manager_name=cache["e"].get(e.manager_id),
        hire_date=e.hire_date, probation_end_date=e.probation_end_date, regularized_date=e.regularized_date,
        resign_date=e.resign_date, status=e.status, user_id=e.user_id, username=cache["u"].get(e.user_id),
        remark=e.remark, version=e.version)


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    gender: str | None = Field(None, pattern="^(女|男|其他)$")
    birth_date: date | None = None
    phone: str | None = Field(None, pattern=r"^[0-9+\- ]{6,20}$")
    email: str = Field(max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department_id: int
    position_id: int | None = None
    manager_id: int | None = None
    hire_date: date
    probation_months: int = Field(3, ge=0, le=6)
    remark: str | None = Field(None, max_length=255)
    create_account: bool = False
    username: str | None = Field(None, min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str | None = Field(None, max_length=128)
    role_codes: list[str] = Field(default_factory=lambda: ["employee"])


class EmployeeUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=64)
    gender: str | None = Field(None, pattern="^(女|男|其他)$")
    birth_date: date | None = None
    phone: str | None = Field(None, pattern=r"^[0-9+\- ]{6,20}$")
    email: str = Field(max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department_id: int
    position_id: int | None = None
    manager_id: int | None = None
    remark: str | None = Field(None, max_length=255)
    attendance_rule_id: int | None = None


@router.get("/employees", response_model=Page[EmployeeOut], summary="员工列表（按数据权限过滤）")
def list_employees(q: str | None = Query(None, max_length=64), department_id: int | None = None,
                   include_children: bool = True, status: str | None = Query(None, pattern="^(probation|regular|resigned|active)$"),
                   page: PageParams = Depends(), cu: CurrentUser = Depends(current_user),
                   db: Session = Depends(get_db)):
    stmt = select(Employee)
    if not cu.has("employee:read"):
        stmt = stmt.where(Employee.id == (cu.employee.id if cu.employee else -1))
    else:
        f = employee_scope_filter(db, cu, Employee.id)
        if f is not None:
            stmt = stmt.where(f)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Employee.name.ilike(like), Employee.employee_no.ilike(like)))
    if department_id:
        ids = department_subtree(db, department_id) if include_children else {department_id}
        stmt = stmt.where(Employee.department_id.in_(ids))
    if status == "active":
        stmt = stmt.where(Employee.status != "resigned")
    elif status:
        stmt = stmt.where(Employee.status == status)
    cache: dict = {}
    return paginate(db, stmt, page, {"id": Employee.id, "employee_no": Employee.employee_no, "name": Employee.name,
                                     "hire_date": Employee.hire_date}, Employee.employee_no,
                    lambda e: employee_out(db, cu, e, cache))


class EmployeeOption(BaseModel):
    id: int
    name: str
    employee_no: str
    department_id: int
    user_id: int | None
    status: str


@router.get("/employees/options", response_model=list[EmployeeOption], summary="员工选择器（通讯录级字段）")
def employee_options(q: str | None = Query(None, max_length=64), include_resigned: bool = False,
                     cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Employee).order_by(Employee.employee_no)
    if not include_resigned:
        stmt = stmt.where(Employee.status != "resigned")
    if q:
        stmt = stmt.where(or_(Employee.name.ilike(f"%{q}%"), Employee.employee_no.ilike(f"%{q}%")))
    return [EmployeeOption(id=e.id, name=e.name, employee_no=e.employee_no, department_id=e.department_id,
                           user_id=e.user_id, status=e.status) for e in db.scalars(stmt.limit(2000))]


@router.post("/employees", response_model=EmployeeOut, status_code=201, summary="直接创建员工档案（HR）")
def create_employee(body: EmployeeCreate, request: Request, cu: CurrentUser = Depends(require("employee:manage")),
                    db: Session = Depends(get_db)):
    org.get_department(db, body.department_id)
    org.get_position(db, body.position_id)
    if db.scalar(select(Employee.id).where(func.lower(Employee.email) == body.email.lower())):
        raise Conflict("邮箱已被使用", code="EMAIL_EXISTS")
    org.check_manager(db, None, body.manager_id)
    months = body.probation_months
    e = Employee(employee_no=org.next_employee_no(db), name=body.name, gender=body.gender, birth_date=body.birth_date,
                 phone=body.phone, email=body.email, department_id=body.department_id, position_id=body.position_id,
                 manager_id=body.manager_id, hire_date=body.hire_date, remark=body.remark,
                 status="probation" if months else "regular",
                 probation_end_date=_add_months(body.hire_date, months) if months else None,
                 regularized_date=None if months else body.hire_date)
    db.add(e)
    db.flush()
    org.add_history(db, e, "onboard", body.hire_date, operator_id=cu.id, reason="HR 直接建档")
    if body.create_account:
        if not body.username:
            raise ValidationFailed("创建账号需要用户名", code="USERNAME_REQUIRED")
        org.ensure_username_free(db, body.username)
        if body.password:
            validate_password_strength(body.password)
        if "admin" in body.role_codes and not cu.is_admin:
            raise ValidationFailed("只有系统管理员可以授予管理员角色", code="ROLE_NOT_ALLOWED")
        roles = db.scalars(select(Role).where(Role.code.in_(body.role_codes))).all()
        if len(roles) != len(set(body.role_codes)):
            raise ValidationFailed("角色不存在", code="ROLE_NOT_FOUND")
        u = User(username=body.username, display_name=body.name, email=body.email,
                 password_hash=hash_password(body.password, request.app.state.settings.password_iterations)
                 if body.password else unusable_password(), must_change_password=True, roles=list(roles))
        db.add(u)
        db.flush()
        e.user_id = u.id
    leave_svc.ensure_year_balances(db, e, timeutil.today().year, cu.id)
    audit(db, cu, "create_employee", "employee", e.id, {"employee_no": e.employee_no})
    db.commit()
    return employee_out(db, cu, e)


def _load_visible(db: Session, cu: CurrentUser, emp_id: int) -> Employee:
    e = org.get_employee(db, emp_id)
    is_self = cu.employee is not None and cu.employee.id == e.id
    if not is_self:
        cu.require("employee:read")
        ensure_can_view_employee(db, cu, e)
    return e


@router.get("/employees/{emp_id}", response_model=EmployeeOut, summary="员工详情")
def get_employee(emp_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return employee_out(db, cu, _load_visible(db, cu, emp_id))


@router.put("/employees/{emp_id}", response_model=EmployeeOut, summary="修改员工档案（乐观锁 version）")
def update_employee(emp_id: int, body: EmployeeUpdate, cu: CurrentUser = Depends(require("employee:manage")),
                    db: Session = Depends(get_db)):
    e = org.get_employee(db, emp_id)
    if e.version != body.version:
        raise Conflict("档案已被他人修改，请刷新后重试", code="VERSION_CONFLICT",
                       details={"current_version": e.version})
    if e.status == "resigned":
        raise ValidationFailed("离职员工档案不可修改", code="EMPLOYEE_RESIGNED")
    if body.department_id != e.department_id:
        org.get_department(db, body.department_id)
    org.get_position(db, body.position_id)
    org.check_manager(db, e.id, body.manager_id)
    if body.email.lower() != (e.email or "").lower() and db.scalar(
            select(Employee.id).where(func.lower(Employee.email) == body.email.lower(), Employee.id != e.id)):
        raise Conflict("邮箱已被使用", code="EMAIL_EXISTS")
    before = org.snapshot(e)
    data = body.model_dump(exclude={"version"})
    for k, v in data.items():
        setattr(e, k, v)
    try:
        db.flush()
    except StaleDataError as exc:
        raise Conflict("档案已被他人修改，请刷新后重试", code="VERSION_CONFLICT") from exc
    if (before["department_id"], before["position_id"], before["manager_id"]) != (
            e.department_id, e.position_id, e.manager_id):
        org.add_history(db, e, "adjust", timeutil.today(), operator_id=cu.id, reason="档案调整", before=before)
    audit(db, cu, "update_employee", "employee", e.id)
    db.commit()
    return employee_out(db, cu, e)


class HistoryOut(BaseModel):
    id: int
    change_type: str
    effective_date: date
    from_department: str | None
    to_department: str | None
    from_position: str | None
    to_position: str | None
    from_manager: str | None
    to_manager: str | None
    from_status: str | None
    to_status: str | None
    reason: str | None
    ref_type: str | None
    ref_id: int | None
    created_at: datetime


@router.get("/employees/{emp_id}/history", response_model=list[HistoryOut], summary="任职历史")
def employee_history(emp_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    _load_visible(db, cu, emp_id)
    d = dict(db.execute(select(Department.id, Department.name)).all())
    p = dict(db.execute(select(Position.id, Position.name)).all())
    n = dict(db.execute(select(Employee.id, Employee.name)).all())
    rows = db.scalars(select(JobHistory).where(JobHistory.employee_id == emp_id)
                      .order_by(JobHistory.effective_date, JobHistory.id))
    return [HistoryOut(id=h.id, change_type=h.change_type, effective_date=h.effective_date,
                       from_department=d.get(h.from_department_id), to_department=d.get(h.to_department_id),
                       from_position=p.get(h.from_position_id), to_position=p.get(h.to_position_id),
                       from_manager=n.get(h.from_manager_id), to_manager=n.get(h.to_manager_id),
                       from_status=h.from_status, to_status=h.to_status, reason=h.reason, ref_type=h.ref_type,
                       ref_id=h.ref_id, created_at=h.created_at) for h in rows]


class ResignIn(BaseModel):
    resign_date: date
    reason: str = Field(min_length=1, max_length=255)


@router.post("/employees/{emp_id}/resign", response_model=EmployeeOut, summary="办理离职")
def resign(emp_id: int, body: ResignIn, cu: CurrentUser = Depends(require("employee:manage")),
           db: Session = Depends(get_db)):
    e = org.get_employee(db, emp_id)
    if cu.employee is not None and cu.employee.id == e.id:
        raise ValidationFailed("不能为自己办理离职", code="SELF_OPERATION")
    if body.resign_date < e.hire_date:
        raise ValidationFailed("离职日期不能早于入职日期", code="INVALID_DATE")
    org.resign_employee(db, e, body.resign_date, body.reason, cu.id)
    audit(db, cu, "resign_employee", "employee", e.id, {"date": str(body.resign_date)})
    db.commit()
    return employee_out(db, cu, e)


@router.get("/departments/{dept_id}/members", response_model=list[EmployeeOut], summary="部门人员")
def department_members(dept_id: int, include_children: bool = False, cu: CurrentUser = Depends(require("org:read")),
                       db: Session = Depends(get_db)):
    org.get_department(db, dept_id, active=False)
    ids = department_subtree(db, dept_id) if include_children else {dept_id}
    cache: dict = {}
    rows = db.scalars(select(Employee).where(Employee.department_id.in_(ids), Employee.status != "resigned")
                      .order_by(Employee.employee_no))
    out = []
    for e in rows:
        o = employee_out(db, cu, e, cache)
        o.phone = mask_phone(e.phone) if not cu.has("employee:sensitive") else o.phone
        out.append(o)
    return out
