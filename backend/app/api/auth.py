"""Authentication, current-user profile, password and sessions."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit
from ..core.deps import CurrentUser, build_current_user, current_user, get_db
from ..core.errors import AppError, Forbidden, NotFound, Unauthorized, ValidationFailed
from ..core.permissions import MENUS, menu_allowed
from ..core.security import (hash_password, new_token, token_digest, validate_password_strength, verify_password)
from ..models import Department, LoginLog, Position, User, UserSession
from .common import ERRORS, Msg

router = APIRouter(prefix="/api/auth", tags=["认证"], responses=ERRORS)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class EmployeeBrief(BaseModel):
    id: int
    employee_no: str
    name: str
    department_id: int
    department_name: str | None
    position_name: str | None
    manager_id: int | None
    status: str


class MeOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    must_change_password: bool
    roles: list[str]
    role_names: list[str]
    permissions: list[str]
    data_scope: str
    menus: list[dict]
    employee: EmployeeBrief | None


class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: MeOut


def me_payload(db: Session, cu: CurrentUser) -> MeOut:
    emp = cu.employee
    brief = None
    if emp is not None:
        dept = db.get(Department, emp.department_id)
        pos = db.get(Position, emp.position_id) if emp.position_id else None
        brief = EmployeeBrief(id=emp.id, employee_no=emp.employee_no, name=emp.name, department_id=emp.department_id,
                              department_name=dept.name if dept else None, position_name=pos.name if pos else None,
                              manager_id=emp.manager_id, status=emp.status)
    perms = sorted(cu.permissions) if not cu.is_admin else sorted(
        {p.code for r in cu.user.roles for p in r.permissions} | cu.permissions)
    menus = [m for m in MENUS if menu_allowed(cu.has, m)]
    return MeOut(id=cu.user.id, username=cu.user.username, display_name=cu.user.display_name, email=cu.user.email,
                 must_change_password=cu.user.must_change_password, roles=sorted(cu.role_codes),
                 role_names=[r.name for r in cu.user.roles], permissions=perms, data_scope=cu.data_scope,
                 menus=menus, employee=brief)


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None, (request.headers.get("user-agent") or "")[:255])


@router.post("/login", response_model=LoginOut, summary="登录")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    ip, ua = _client(request)
    now = timeutil.now()
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))

    def fail(reason: str, exc: AppError):
        db.add(LoginLog(username=body.username[:64], user_id=user.id if user else None, success=False, reason=reason,
                        ip=ip, user_agent=ua))
        db.commit()
        raise exc

    if user is None:
        fail("no_user", Unauthorized("用户名或密码错误", code="INVALID_CREDENTIALS"))
    if user.locked_until and user.locked_until > now:
        fail("locked", AppError("连续登录失败次数过多，账号已临时锁定", code="ACCOUNT_LOCKED", status_code=423,
                                details={"locked_until": user.locked_until.isoformat()}))
    if not verify_password(body.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.max_login_failures:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
        fail("bad_password", Unauthorized("用户名或密码错误", code="INVALID_CREDENTIALS"))
    if user.status != "active":
        fail("disabled", Forbidden("账号已停用", code="ACCOUNT_DISABLED"))
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    token = new_token()
    sess = UserSession(user_id=user.id, token_hash=token_digest(token),
                       expires_at=now + timedelta(hours=settings.session_hours), last_seen_at=now, ip=ip, user_agent=ua)
    db.add(sess)
    db.add(LoginLog(username=user.username, user_id=user.id, success=True, reason="ok", ip=ip, user_agent=ua))
    db.flush()
    cu = build_current_user(db, user, sess.id, ip)
    payload = LoginOut(token=token, expires_at=sess.expires_at, user=me_payload(db, cu))
    db.commit()
    return payload


@router.post("/logout", response_model=Msg, summary="退出登录")
def logout(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    sess = db.get(UserSession, cu.session_id)
    sess.revoked_at = timeutil.now()
    db.commit()
    return Msg(message="已退出")


@router.get("/me", response_model=MeOut, summary="当前用户、权限与菜单")
def me(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, cu)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


@router.post("/change-password", response_model=Msg, summary="修改密码（会注销其他会话）")
def change_password(body: ChangePasswordIn, request: Request, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    user = cu.user
    if not verify_password(body.old_password, user.password_hash):
        raise ValidationFailed("原密码不正确", code="WRONG_PASSWORD")
    validate_password_strength(body.new_password)
    if body.new_password == body.old_password:
        raise ValidationFailed("新密码不能与原密码相同", code="PASSWORD_REUSED")
    user.password_hash = hash_password(body.new_password, request.app.state.settings.password_iterations)
    user.must_change_password = False
    user.password_changed_at = timeutil.now()
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.id != cu.session_id,
                                         UserSession.revoked_at.is_(None)).values(revoked_at=timeutil.now()))
    audit(db, cu, "change_password", "user", user.id)
    db.commit()
    return Msg(message="密码已修改")


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    ip: str | None
    user_agent: str | None
    current: bool


@router.get("/sessions", response_model=list[SessionOut], summary="我的有效会话")
def my_sessions(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    now = timeutil.now()
    rows = db.scalars(select(UserSession).where(UserSession.user_id == cu.id, UserSession.revoked_at.is_(None),
                                                UserSession.expires_at > now).order_by(UserSession.id.desc()))
    return [SessionOut(id=s.id, created_at=s.created_at, expires_at=s.expires_at, last_seen_at=s.last_seen_at,
                       ip=s.ip, user_agent=s.user_agent, current=s.id == cu.session_id) for s in rows]


@router.delete("/sessions/{session_id}", response_model=Msg, summary="注销指定会话")
def revoke_session(session_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != cu.id:
        raise NotFound("会话不存在")
    s.revoked_at = timeutil.now()
    db.commit()
    return Msg(message="会话已注销")


class LoginLogOut(BaseModel):
    id: int
    username: str
    success: bool
    reason: str | None
    ip: str | None
    created_at: datetime


@router.get("/login-logs", response_model=list[LoginLogOut], summary="我的最近登录记录")
def my_login_logs(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(LoginLog).where(LoginLog.user_id == cu.id).order_by(LoginLog.id.desc()).limit(20))
    return [LoginLogOut.model_validate(r, from_attributes=True) for r in rows]
