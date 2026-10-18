"""Users, roles, permissions, audit/login logs, settings, holidays."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, paginate
from ..core.deps import CurrentUser, PageParams, current_user, get_db, require, require_any
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..core.permissions import PERMISSIONS
from ..core.security import hash_password, unusable_password, validate_password_strength
from ..models import (AuditLog, Employee, Holiday, LoginLog, Permission, Role, SystemSetting, User, UserSession,
                      user_roles)
from ..services import org
from .common import ERRORS, Msg, Page

router = APIRouter(prefix="/api", tags=["系统与权限"], responses=ERRORS)


# ------------------------------------------------------------------ users
class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    status: str
    must_change_password: bool
    locked: bool
    last_login_at: datetime | None
    roles: list[str]
    employee_id: int | None
    employee_name: str | None
    created_at: datetime


def user_out(db: Session, u: User) -> UserOut:
    emp = db.scalar(select(Employee).where(Employee.user_id == u.id))
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, email=u.email, status=u.status,
                   must_change_password=u.must_change_password,
                   locked=bool(u.locked_until and u.locked_until > timeutil.now()), last_login_at=u.last_login_at,
                   roles=sorted(r.code for r in u.roles), employee_id=emp.id if emp else None,
                   employee_name=emp.name if emp else None, created_at=u.created_at)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=64)
    email: str | None = Field(None, max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str | None = Field(None, max_length=128)
    role_codes: list[str] = Field(default_factory=lambda: ["employee"])
    employee_id: int | None = None


class UserUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)
    email: str | None = Field(None, max_length=128, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class RolesIn(BaseModel):
    role_codes: list[str] = Field(min_length=1, max_length=20)


def _assign_roles(db: Session, cu: CurrentUser, user: User, codes: list[str]) -> None:
    codes = list(dict.fromkeys(codes))
    roles = db.scalars(select(Role).where(Role.code.in_(codes))).all()
    missing = set(codes) - {r.code for r in roles}
    if missing:
        raise ValidationFailed(f"角色不存在：{', '.join(sorted(missing))}", code="ROLE_NOT_FOUND")
    current = {r.code for r in user.roles}
    if ("admin" in codes) != ("admin" in current) and not cu.is_admin:
        raise Forbidden("只有系统管理员可以授予或移除管理员角色", code="PERMISSION_DENIED")
    if user.id == cu.id and "admin" in current and "admin" not in codes:
        raise ValidationFailed("不能移除自己的管理员角色", code="SELF_LOCKOUT")
    user.roles = list(roles)


@router.get("/users", response_model=Page[UserOut], summary="用户列表")
def list_users(q: str | None = Query(None, max_length=64), status: str | None = Query(None),
               role: str | None = Query(None), page: PageParams = Depends(),
               cu: CurrentUser = Depends(require("user:manage")), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.display_name.ilike(like)))
    if status:
        stmt = stmt.where(User.status == status)
    if role:
        stmt = stmt.where(User.id.in_(select(user_roles.c.user_id).join(Role, Role.id == user_roles.c.role_id)
                                      .where(Role.code == role)))
    return paginate(db, stmt, page, {"id": User.id, "username": User.username, "last_login_at": User.last_login_at},
                    User.id, lambda u: user_out(db, u))


@router.post("/users", response_model=UserOut, status_code=201, summary="创建用户")
def create_user(body: UserCreate, request: Request, cu: CurrentUser = Depends(require("user:manage")),
                db: Session = Depends(get_db)):
    org.ensure_username_free(db, body.username)
    if body.password:
        validate_password_strength(body.password)
    user = User(username=body.username, display_name=body.display_name, email=body.email,
                password_hash=hash_password(body.password, request.app.state.settings.password_iterations)
                if body.password else unusable_password(), must_change_password=True, status="active")
    db.add(user)
    db.flush()
    _assign_roles(db, cu, user, body.role_codes)
    if body.employee_id is not None:
        emp = org.get_employee(db, body.employee_id)
        if emp.user_id is not None:
            raise Conflict("该员工已关联账号", code="EMPLOYEE_HAS_ACCOUNT")
        emp.user_id = user.id
    audit(db, cu, "create_user", "user", user.id, {"username": user.username, "roles": body.role_codes})
    db.commit()
    return user_out(db, user)


def _get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("用户不存在")
    return u


@router.get("/users/{user_id}", response_model=UserOut, summary="用户详情")
def get_user(user_id: int, cu: CurrentUser = Depends(require("user:manage")), db: Session = Depends(get_db)):
    return user_out(db, _get_user(db, user_id))


@router.put("/users/{user_id}", response_model=UserOut, summary="修改用户资料")
def update_user(user_id: int, body: UserUpdate, cu: CurrentUser = Depends(require("user:manage")),
                db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    u.display_name, u.email = body.display_name, body.email
    audit(db, cu, "update_user", "user", u.id)
    db.commit()
    return user_out(db, u)


@router.post("/users/{user_id}/status", response_model=UserOut, summary="启用/停用用户")
def set_user_status(user_id: int, body: StatusIn, cu: CurrentUser = Depends(require("user:manage")),
                    db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    if u.id == cu.id and body.status != "active":
        raise ValidationFailed("不能停用自己的账号", code="SELF_LOCKOUT")
    if "admin" in {r.code for r in u.roles} and not cu.is_admin:
        raise Forbidden("只有系统管理员可以修改管理员账号状态")
    u.status = body.status
    if body.status == "disabled":
        db.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))
                   .values(revoked_at=timeutil.now()))
        emp = db.scalar(select(Employee).where(Employee.user_id == u.id))
        mgr_user = db.get(Employee, emp.manager_id).user_id if emp and emp.manager_id else None
        org.reassign_pending_tasks(db, u.id, mgr_user, cu.id, f"审批人账号 {u.username} 已停用，任务自动转交")
    audit(db, cu, "set_user_status", "user", u.id, {"status": body.status})
    db.commit()
    return user_out(db, u)


@router.post("/users/{user_id}/reset-password", response_model=Msg, summary="重置密码（下次登录需修改）")
def reset_password(user_id: int, body: ResetPasswordIn, request: Request,
                   cu: CurrentUser = Depends(require("user:manage")), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    if "admin" in {r.code for r in u.roles} and not cu.is_admin:
        raise Forbidden("只有系统管理员可以重置管理员密码")
    validate_password_strength(body.new_password)
    u.password_hash = hash_password(body.new_password, request.app.state.settings.password_iterations)
    u.must_change_password = True
    u.failed_attempts = 0
    u.locked_until = None
    db.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=timeutil.now()))
    audit(db, cu, "reset_password", "user", u.id)
    db.commit()
    return Msg(message="密码已重置，用户下次登录需修改密码")


@router.post("/users/{user_id}/unlock", response_model=UserOut, summary="解除登录锁定")
def unlock_user(user_id: int, cu: CurrentUser = Depends(require("user:manage")), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    u.locked_until = None
    u.failed_attempts = 0
    audit(db, cu, "unlock_user", "user", u.id)
    db.commit()
    return user_out(db, u)


@router.put("/users/{user_id}/roles", response_model=UserOut, summary="分配角色")
def set_user_roles(user_id: int, body: RolesIn, cu: CurrentUser = Depends(require("user:manage")),
                   db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    before = sorted(r.code for r in u.roles)
    _assign_roles(db, cu, u, body.role_codes)
    audit(db, cu, "set_user_roles", "user", u.id, {"before": before, "after": sorted(body.role_codes)})
    db.commit()
    return user_out(db, u)


# ------------------------------------------------------------------ roles
class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    data_scope: str
    is_system: bool
    permissions: list[str]
    user_count: int


class RoleIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    data_scope: str = Field("self", pattern="^(self|department|all)$")
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    data_scope: str = Field("self", pattern="^(self|department|all)$")
    permissions: list[str] = Field(default_factory=list)


def role_out(db: Session, r: Role) -> RoleOut:
    cnt = db.scalar(select(func.count()).select_from(user_roles).where(user_roles.c.role_id == r.id))
    return RoleOut(id=r.id, code=r.code, name=r.name, description=r.description, data_scope=r.data_scope,
                   is_system=r.is_system, permissions=sorted(p.code for p in r.permissions), user_count=cnt)


def _perms(db: Session, codes: list[str]) -> list[Permission]:
    rows = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    missing = set(codes) - {p.code for p in rows}
    if missing:
        raise ValidationFailed(f"权限不存在：{', '.join(sorted(missing))}", code="PERMISSION_NOT_FOUND")
    return list(rows)


@router.get("/permissions", summary="权限清单")
def list_permissions(cu: CurrentUser = Depends(require_any("role:manage", "user:manage"))):
    return [{"code": c, "name": n, "group": g} for c, n, g in PERMISSIONS]


@router.get("/roles", response_model=list[RoleOut], summary="角色列表")
def list_roles(cu: CurrentUser = Depends(require_any("role:manage", "user:manage", "workflow:manage")),
               db: Session = Depends(get_db)):
    return [role_out(db, r) for r in db.scalars(select(Role).order_by(Role.id))]


@router.post("/roles", response_model=RoleOut, status_code=201, summary="创建角色")
def create_role(body: RoleIn, cu: CurrentUser = Depends(require("role:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(Role.id).where(Role.code == body.code)):
        raise Conflict("角色编码已存在", code="ROLE_EXISTS")
    r = Role(code=body.code, name=body.name, description=body.description, data_scope=body.data_scope,
             is_system=False, permissions=_perms(db, body.permissions))
    db.add(r)
    db.flush()
    audit(db, cu, "create_role", "role", r.id, {"permissions": body.permissions})
    db.commit()
    return role_out(db, r)


@router.put("/roles/{role_id}", response_model=RoleOut, summary="修改角色与权限")
def update_role(role_id: int, body: RoleUpdate, cu: CurrentUser = Depends(require("role:manage")),
                db: Session = Depends(get_db)):
    r = db.get(Role, role_id)
    if r is None:
        raise NotFound("角色不存在")
    if r.code == "admin":
        raise ValidationFailed("管理员角色固定拥有全部权限，不可修改", code="ROLE_IMMUTABLE")
    before = sorted(p.code for p in r.permissions)
    r.name, r.description, r.data_scope = body.name, body.description, body.data_scope
    r.permissions = _perms(db, body.permissions)
    audit(db, cu, "update_role", "role", r.id, {"before": before, "after": sorted(body.permissions)})
    db.commit()
    return role_out(db, r)


@router.delete("/roles/{role_id}", response_model=Msg, summary="删除角色")
def delete_role(role_id: int, cu: CurrentUser = Depends(require("role:manage")), db: Session = Depends(get_db)):
    r = db.get(Role, role_id)
    if r is None:
        raise NotFound("角色不存在")
    if r.is_system:
        raise ValidationFailed("系统内置角色不能删除", code="ROLE_IMMUTABLE")
    if db.scalar(select(func.count()).select_from(user_roles).where(user_roles.c.role_id == r.id)):
        raise Conflict("角色仍有关联用户，不能删除", code="ROLE_IN_USE")
    db.delete(r)
    audit(db, cu, "delete_role", "role", role_id)
    db.commit()
    return Msg(message="已删除")


# ------------------------------------------------------------------ logs
class AuditOut(BaseModel):
    id: int
    user_id: int | None
    username: str | None
    action: str
    resource_type: str
    resource_id: str | None
    detail: dict | None
    ip: str | None
    created_at: datetime


@router.get("/audit-logs", response_model=Page[AuditOut], summary="审计日志")
def audit_logs(action: str | None = None, user_id: int | None = None, resource_type: str | None = None,
               page: PageParams = Depends(), cu: CurrentUser = Depends(require("audit:read")),
               db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    names = dict(db.execute(select(User.id, User.username)).all())
    return paginate(db, stmt, page, {"id": AuditLog.id}, AuditLog.id.desc(),
                    lambda a: AuditOut(id=a.id, user_id=a.user_id, username=names.get(a.user_id), action=a.action,
                                       resource_type=a.resource_type, resource_id=a.resource_id, detail=a.detail,
                                       ip=a.ip, created_at=a.created_at))


class LoginLogOut(BaseModel):
    id: int
    username: str
    user_id: int | None
    success: bool
    reason: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime


@router.get("/login-logs", response_model=Page[LoginLogOut], summary="登录日志")
def login_logs(username: str | None = None, success: bool | None = None, page: PageParams = Depends(),
               cu: CurrentUser = Depends(require("audit:read")), db: Session = Depends(get_db)):
    stmt = select(LoginLog)
    if username:
        stmt = stmt.where(LoginLog.username == username)
    if success is not None:
        stmt = stmt.where(LoginLog.success.is_(success))
    return paginate(db, stmt, page, {"id": LoginLog.id}, LoginLog.id.desc(),
                    lambda r: LoginLogOut.model_validate(r, from_attributes=True))


# ------------------------------------------------------------------ settings
SETTING_SCHEMA = {
    "leave.hr_review_days": ("请假超过多少天需 HR 审核（仅说明，流程条件以流程定义为准）", int),
    "expense.ceo_threshold": ("报销金额超过该值需总经理审批（仅说明）", int),
    "company.name": ("公司名称", str),
    "company.slogan": ("公司标语", str),
    "attendance.simulation_note": ("模拟打卡说明", str),
}


class SettingOut(BaseModel):
    key: str
    value: object
    description: str | None
    updated_at: datetime | None


class SettingIn(BaseModel):
    values: dict[str, object]


@router.get("/settings", response_model=list[SettingOut], summary="系统设置")
def get_settings(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = {s.key: s for s in db.scalars(select(SystemSetting))}
    return [SettingOut(key=k, value=rows[k].value if k in rows else None, description=d,
                       updated_at=rows[k].updated_at if k in rows else None) for k, (d, _t) in SETTING_SCHEMA.items()]


@router.put("/settings", response_model=list[SettingOut], summary="修改系统设置")
def put_settings(body: SettingIn, cu: CurrentUser = Depends(require("settings:manage")), db: Session = Depends(get_db)):
    for k, v in body.values.items():
        if k not in SETTING_SCHEMA:
            raise ValidationFailed(f"未知设置项：{k}", code="UNKNOWN_SETTING")
        typ = SETTING_SCHEMA[k][1]
        if not isinstance(v, typ) or isinstance(v, bool):
            raise ValidationFailed(f"设置项 {k} 类型错误", code="INVALID_SETTING")
        if isinstance(v, str) and len(v) > 200:
            raise ValidationFailed(f"设置项 {k} 过长", code="INVALID_SETTING")
        s = db.get(SystemSetting, k)
        if s is None:
            db.add(SystemSetting(key=k, value=v, description=SETTING_SCHEMA[k][0]))
        else:
            s.value = v
    audit(db, cu, "update_settings", "settings", None, {"keys": sorted(body.values)})
    db.commit()
    return get_settings(cu, db)


# ------------------------------------------------------------------ holidays
class HolidayOut(BaseModel):
    id: int
    day: date
    name: str
    kind: str


class HolidayIn(BaseModel):
    day: date
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field("holiday", pattern="^(holiday|workday)$")


@router.get("/holidays", response_model=list[HolidayOut], summary="节假日与调休工作日")
def list_holidays(year: int = Query(..., ge=2000, le=2100), cu: CurrentUser = Depends(current_user),
                  db: Session = Depends(get_db)):
    rows = db.scalars(select(Holiday).where(Holiday.day >= date(year, 1, 1), Holiday.day <= date(year, 12, 31))
                      .order_by(Holiday.day))
    return [HolidayOut.model_validate(h, from_attributes=True) for h in rows]


@router.post("/holidays", response_model=HolidayOut, status_code=201, summary="新增节假日")
def add_holiday(body: HolidayIn, cu: CurrentUser = Depends(require("leave:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(Holiday.id).where(Holiday.day == body.day)):
        raise Conflict("该日期已配置", code="HOLIDAY_EXISTS")
    h = Holiday(day=body.day, name=body.name, kind=body.kind)
    db.add(h)
    db.flush()
    audit(db, cu, "add_holiday", "holiday", h.id, {"day": str(body.day), "kind": body.kind})
    db.commit()
    return HolidayOut.model_validate(h, from_attributes=True)


@router.delete("/holidays/{holiday_id}", response_model=Msg, summary="删除节假日")
def delete_holiday(holiday_id: int, cu: CurrentUser = Depends(require("leave:manage")), db: Session = Depends(get_db)):
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise NotFound("节假日不存在")
    db.delete(h)
    audit(db, cu, "delete_holiday", "holiday", holiday_id)
    db.commit()
    return Msg(message="已删除")
