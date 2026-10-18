"""Permission catalogue and default role grants (single source of truth)."""
from __future__ import annotations

PERMISSIONS: list[tuple[str, str, str]] = [
    # code, name, group
    ("dashboard:view", "查看工作台", "工作台"),
    ("org:read", "查看组织架构", "组织"),
    ("org:manage", "管理组织架构", "组织"),
    ("employee:read", "查看员工档案", "人事"),
    ("employee:manage", "管理员工档案", "人事"),
    ("employee:sensitive", "查看敏感信息", "人事"),
    ("user:manage", "用户管理", "系统"),
    ("role:manage", "角色权限管理", "系统"),
    ("audit:read", "查看审计与登录日志", "系统"),
    ("settings:manage", "系统设置", "系统"),
    ("attendance:punch", "打卡", "考勤"),
    ("attendance:read", "查看考勤", "考勤"),
    ("attendance:manage", "考勤管理", "考勤"),
    ("leave:apply", "请假申请", "假期"),
    ("leave:manage", "假期管理", "假期"),
    ("travel:apply", "出差申请", "出差"),
    ("expense:apply", "费用报销", "报销"),
    ("expense:finance", "财务确认", "报销"),
    ("meeting:book", "会议室预约", "会议"),
    ("meeting:manage", "会议室管理", "会议"),
    ("announcement:read", "查看公告", "公告"),
    ("announcement:manage", "公告管理", "公告"),
    ("document:read", "查看文档", "文档"),
    ("document:upload", "上传文档", "文档"),
    ("document:manage", "文档管理", "文档"),
    ("workflow:manage", "流程定义管理", "工作流"),
    ("workflow:monitor", "流程监控", "工作流"),
    ("recruit:manage", "招聘管理", "招聘"),
    ("onboarding:manage", "入职管理", "招聘"),
    ("regularization:apply", "转正申请", "人事"),
    ("regularization:manage", "转正管理", "人事"),
    ("transfer:manage", "调岗管理", "人事"),
    ("performance:self", "参与绩效", "绩效"),
    ("performance:manage", "绩效管理", "绩效"),
    ("payroll:self", "查看本人工资单", "薪资"),
    ("payroll:manage", "薪资管理", "薪资"),
    ("report:view", "统计报表", "报表"),
]

ALL_CODES = [p[0] for p in PERMISSIONS]

_EMPLOYEE = [
    "dashboard:view", "org:read", "attendance:punch", "attendance:read", "leave:apply", "travel:apply",
    "expense:apply", "meeting:book", "announcement:read", "document:read", "document:upload",
    "regularization:apply", "performance:self", "payroll:self",
]

DEFAULT_ROLES: dict[str, dict] = {
    "admin": {"name": "系统管理员", "data_scope": "all", "permissions": ALL_CODES,
              "description": "拥有全部权限（琴吹家执事专用）"},
    "employee": {"name": "普通员工", "data_scope": "self", "permissions": _EMPLOYEE,
                 "description": "放课后茶会全体成员的基础权限"},
    "manager": {"name": "部门主管", "data_scope": "department",
                "permissions": _EMPLOYEE + ["employee:read", "report:view"],
                "description": "可查看本部门及下级部门数据"},
    "hr": {"name": "人事管理员", "data_scope": "all",
           "permissions": _EMPLOYEE + ["employee:read", "employee:manage", "employee:sensitive", "attendance:manage",
                                       "leave:manage", "recruit:manage", "onboarding:manage",
                                       "regularization:manage", "transfer:manage", "performance:manage",
                                       "payroll:manage", "announcement:manage", "report:view", "user:manage"],
           "description": "人事、考勤、招聘与薪资"},
    "finance": {"name": "财务", "data_scope": "self",
                "permissions": _EMPLOYEE + ["expense:finance", "report:view"],
                "description": "报销财务确认与归档"},
    "ceo": {"name": "总经理", "data_scope": "all",
            "permissions": _EMPLOYEE + ["employee:read", "report:view", "workflow:monitor", "announcement:manage"],
            "description": "公司全局视图与大额审批"},
    "admin_staff": {"name": "行政", "data_scope": "self",
                    "permissions": _EMPLOYEE + ["meeting:manage", "announcement:manage", "document:manage"],
                    "description": "会议室、公告与文档"},
}

# Menu entries (frontend route name -> required permission, or a list meaning "any of"). The API returns the
# filtered list so the UI can render navigation; the backend still checks every call.
MENUS: list[dict] = [
    {"key": "dashboard", "title": "工作台", "perm": "dashboard:view"},
    {"key": "approvals", "title": "审批中心", "perm": "dashboard:view"},
    {"key": "org", "title": "组织架构", "perm": "org:read"},
    {"key": "employees", "title": "员工档案", "perm": "employee:read"},
    {"key": "recruitment", "title": "招聘入职", "perm": "recruit:manage"},
    {"key": "hr-changes", "title": "转正调岗", "perm": "regularization:apply"},
    {"key": "attendance", "title": "考勤管理", "perm": "attendance:read"},
    {"key": "leave", "title": "请假与假期", "perm": "leave:apply"},
    {"key": "travel", "title": "出差管理", "perm": "travel:apply"},
    {"key": "expense", "title": "费用报销", "perm": "expense:apply"},
    {"key": "meeting", "title": "会议室", "perm": "meeting:book"},
    {"key": "announcements", "title": "公告通知", "perm": "announcement:read"},
    {"key": "documents", "title": "文档中心", "perm": "document:read"},
    {"key": "performance", "title": "绩效管理", "perm": "performance:self"},
    {"key": "payroll", "title": "模拟薪资", "perm": "payroll:self"},
    {"key": "workflow", "title": "流程设计", "perm": "workflow:manage"},
    {"key": "reports", "title": "统计报表", "perm": "report:view"},
    {"key": "system", "title": "系统与权限", "perm": ["user:manage", "role:manage", "audit:read", "settings:manage"]},
]


def menu_allowed(has, menu: dict) -> bool:
    """`has` is a permission predicate (e.g. CurrentUser.has); list perms mean "any of"."""
    perm = menu["perm"]
    return any(has(p) for p in (perm if isinstance(perm, list) else [perm]))
