"""Request-scoped dependencies: DB session, current user, permission and data-scope checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterator

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import timeutil
from .errors import Forbidden, Unauthorized
from .security import token_digest
from ..models import Department, Employee, User, UserSession

SCOPE_RANK = {"self": 0, "department": 1, "all": 2}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# What an anonymous visitor may read. Everything else (and every write) answers 401 LOGIN_REQUIRED.
VISITOR_PERMISSIONS = frozenset({"announcement:read", "org:read", "document:read", "meeting:view"})


def login_required() -> Unauthorized:
    return Unauthorized("请先登录后再操作", code="LOGIN_REQUIRED")


def get_db(request: Request) -> Iterator[Session]:
    write = request.method not in READ_METHODS
    db = request.app.state.db.session(write=write)
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def get_write_db(request: Request) -> Iterator[Session]:
    """For GET endpoints that must record something (e.g. download logs)."""
    db = request.app.state.db.session(write=True)
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@dataclass
class CurrentUser:
    user: User | None  # None for an anonymous visitor
    employee: Employee | None
    permissions: set[str]
    role_codes: set[str]
    data_scope: str
    session_id: int
    ip: str | None = None
    _dept_cache: set[int] | None = field(default=None, repr=False)
    _ancestor_cache: set[int] | None = field(default=None, repr=False)

    @property
    def visitor(self) -> bool:
        return self.user is None

    @property
    def id(self) -> int:
        return self.user.id if self.user is not None else -1

    @property
    def is_admin(self) -> bool:
        return "admin" in self.role_codes

    def has(self, perm: str) -> bool:
        return self.is_admin or perm in self.permissions

    def require(self, perm: str) -> None:
        if not self.has(perm):
            if self.visitor:
                raise login_required()
            raise Forbidden(f"缺少权限：{perm}", code="PERMISSION_DENIED")

    def require_employee(self) -> Employee:
        if self.visitor:
            raise login_required()
        if self.employee is None:
            raise Forbidden("当前账号未关联员工档案", code="NO_EMPLOYEE_PROFILE")
        return self.employee


def build_current_user(db: Session, user: User, session_id: int, ip: str | None = None) -> CurrentUser:
    perms: set[str] = set()
    scope = "self"
    for role in user.roles:
        perms.update(p.code for p in role.permissions)
        if SCOPE_RANK[role.data_scope] > SCOPE_RANK[scope]:
            scope = role.data_scope
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    return CurrentUser(user=user, employee=employee, permissions=perms,
                       role_codes={r.code for r in user.roles}, data_scope=scope, session_id=session_id, ip=ip)


def current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise login_required()
    token = header[7:].strip()
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(token)))
    now = timeutil.now()
    if sess is None or sess.revoked_at is not None or sess.expires_at <= now:
        raise Unauthorized("未登录或登录已过期", code="SESSION_EXPIRED")
    user = db.get(User, sess.user_id)
    if user is None or user.status != "active":
        raise Unauthorized("账号已停用", code="ACCOUNT_DISABLED")
    if request.method not in READ_METHODS and (sess.last_seen_at is None or
                                               now - sess.last_seen_at > timedelta(minutes=1)):
        sess.last_seen_at = now  # flushed with the request's own commit
    cu = build_current_user(db, user, sess.id, request.client.host if request.client else None)
    # A user forced to change password may only reach the password / profile endpoints.
    if user.must_change_password and not request.url.path.startswith(("/api/auth/",)):
        raise Forbidden("首次登录或密码已重置，请先修改密码", code="PASSWORD_CHANGE_REQUIRED")
    request.state.current_user = cu
    return cu


def viewer(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """Logged-in user when a token is sent, otherwise a read-only anonymous visitor."""
    if request.headers.get("Authorization"):
        return current_user(request, db)
    return CurrentUser(user=None, employee=None, permissions=set(VISITOR_PERMISSIONS), role_codes=set(),
                       data_scope="self", session_id=0, ip=request.client.host if request.client else None)


def require_view(*perms: str):
    """Like require(), but anonymous visitors pass when they hold one of the permissions."""
    def _dep(cu: CurrentUser = Depends(viewer)) -> CurrentUser:
        if not any(cu.has(p) for p in perms):
            if cu.visitor:
                raise login_required()
            raise Forbidden(f"缺少权限：{' / '.join(perms)}", code="PERMISSION_DENIED")
        return cu
    return _dep


def require(*perms: str):
    def _dep(cu: CurrentUser = Depends(current_user)) -> CurrentUser:
        for p in perms:
            cu.require(p)
        return cu
    return _dep


def require_any(*perms: str):
    def _dep(cu: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not any(cu.has(p) for p in perms):
            raise Forbidden(f"缺少权限：{' / '.join(perms)}", code="PERMISSION_DENIED")
        return cu
    return _dep


# ---------------------------------------------------------------- data scope
def department_subtree(db: Session, root_id: int) -> set[int]:
    rows = db.execute(select(Department.id, Department.parent_id)).all()
    children: dict[int | None, list[int]] = {}
    for did, pid in rows:
        children.setdefault(pid, []).append(did)
    out, stack = set(), [root_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


def own_department_ancestors(db: Session, cu: CurrentUser) -> set[int]:
    """The user's department plus all of its ancestors (cached per request).

    ``x in department_subtree(db, d)`` is equivalent to ``d in department_ancestors(x)``, so visibility checks
    against many scoped departments need one query instead of one per department.
    """
    if cu.employee is None:
        return set()
    if cu._ancestor_cache is None:
        parent = dict(db.execute(select(Department.id, Department.parent_id)).all())
        out: set[int] = set()
        cur = cu.employee.department_id
        while cur is not None and cur not in out:
            out.add(cur)
            cur = parent.get(cur)
        cu._ancestor_cache = out
    return cu._ancestor_cache


def scope_department_ids(db: Session, cu: CurrentUser) -> set[int] | None:
    """None means unrestricted; otherwise the set of department ids the user may see."""
    if cu.data_scope == "all" or cu.is_admin:
        return None
    if cu.data_scope == "department" and cu.employee is not None:
        if cu._dept_cache is None:
            depts = department_subtree(db, cu.employee.department_id)
            # managers also see departments they lead
            for d in db.scalars(select(Department.id).where(Department.manager_employee_id == cu.employee.id)):
                depts |= department_subtree(db, d)
            cu._dept_cache = depts
        return cu._dept_cache
    return set()


def can_view_employee(db: Session, cu: CurrentUser, employee: Employee) -> bool:
    if cu.employee is not None and cu.employee.id == employee.id:
        return True
    depts = scope_department_ids(db, cu)
    if depts is None:
        return True
    if employee.department_id in depts:
        return True
    return cu.employee is not None and employee.manager_id == cu.employee.id


def ensure_can_view_employee(db: Session, cu: CurrentUser, employee: Employee) -> None:
    if not can_view_employee(db, cu, employee):
        raise Forbidden("无权访问该员工数据", code="DATA_SCOPE_DENIED")


def employee_scope_filter(db: Session, cu: CurrentUser, column):
    """SQL filter for queries over an employee_id column honouring the data scope."""
    depts = scope_department_ids(db, cu)
    if depts is None:
        return None
    own = cu.employee.id if cu.employee else -1
    sub = select(Employee.id).where((Employee.department_id.in_(depts)) | (Employee.manager_id == own))
    return (column == own) | column.in_(sub)


class PageParams:
    def __init__(self, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=200),
                 sort: str | None = Query(None, max_length=64)):
        self.page = page
        self.page_size = page_size
        self.sort = sort

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
