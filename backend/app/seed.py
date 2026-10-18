"""Base synthetic data for 放学后茶会株式会社 (Houkago Tea Time Inc.).

Everything here is fictional/synthetic. Only *base* data (org, accounts, rules, catalogs,
workflow definitions) is inserted directly; business documents are created through the real
API by scripts/demo_data.py so no business step is ever skipped.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import timeutil
from .core.permissions import DEFAULT_ROLES, PERMISSIONS
from .core.security import hash_password
from .models import (AnnouncementCategory, AttendanceRule, Department, DocCategory, Employee, ExpenseCategory,
                     Holiday, JobHistory, LeaveType, MeetingRoom, Permission, Position, Role, SalaryStructure,
                     SystemSetting, User, WfDefinition, WfDefinitionVersion)
from .services import leave as leave_svc

COMPANY = "放学后茶会株式会社"

DEPARTMENTS = [
    # code, name, parent_code, description
    ("HTT", COMPANY, None, "樱丘出身的乐队公司：认真工作，然后喝茶"),
    ("MUSIC", "音乐制作部", "HTT", "作曲、作词、编曲与录音"),
    ("LIVE", "现场演出组", "MUSIC", "学园祭与 Live House 演出执行"),
    ("TEA", "茶点后勤部", "HTT", "茶点、器材搬运与合宿后勤"),
    ("FIN", "财务部", "HTT", "报销审核与模拟薪资"),
    ("HR", "人事部", "HTT", "招聘、入职、考勤与绩效"),
    ("COSTUME", "服装设计部", "HTT", "演出服装设计与制作"),
    ("IT", "信息系统部", "HTT", "系统运维（由平泽忧负责）"),
]

POSITIONS = [
    ("CEO", "社长", 10), ("MGR", "部门经理", 8), ("LEAD", "组长", 6), ("GUITAR", "吉他手", 4),
    ("BASS", "贝斯手", 4), ("KEYS", "键盘手", 4), ("STAGE", "舞台监督", 4), ("HRS", "人事专员", 3),
    ("FINS", "财务专员", 3), ("DESIGN", "服装设计师", 3), ("SYSADM", "系统管理员", 5), ("TEAS", "茶点专员", 3),
]

# username, name, gender, dept, position, manager_username, roles, hire, status, phone
PEOPLE = [
    ("ritsu", "田井中律", "女", "HTT", "CEO", None, ["employee", "manager", "ceo"], date(2024, 4, 1), "regular"),
    ("mio", "秋山澪", "女", "MUSIC", "MGR", "ritsu", ["employee", "manager"], date(2024, 4, 1), "regular"),
    ("yui", "平泽唯", "女", "LIVE", "LEAD", "mio", ["employee", "manager"], date(2024, 4, 1), "regular"),
    ("azusa", "中野梓", "女", "LIVE", "GUITAR", "yui", ["employee"], date(2026, 8, 1), "probation"),
    ("ichigo", "若王子苺", "女", "LIVE", "STAGE", "yui", ["employee"], date(2025, 4, 1), "regular"),
    ("mugi", "琴吹紬", "女", "TEA", "MGR", "ritsu", ["employee", "manager", "admin_staff"], date(2024, 4, 1), "regular"),
    ("megumi", "曾我部惠", "女", "FIN", "MGR", "ritsu", ["employee", "manager", "finance"], date(2024, 9, 1), "regular"),
    ("fuuko", "高桥风子", "女", "FIN", "FINS", "megumi", ["employee", "finance"], date(2025, 4, 1), "regular"),
    ("nodoka", "真锅和", "女", "HR", "MGR", "ritsu", ["employee", "manager", "hr"], date(2024, 4, 1), "regular"),
    ("himeko", "立花姬子", "女", "HR", "HRS", "nodoka", ["employee", "hr"], date(2025, 4, 1), "regular"),
    ("sawako", "山中佐和子", "女", "COSTUME", "MGR", "ritsu", ["employee", "manager"], date(2024, 4, 1), "regular"),
    ("mika", "佐伯三花", "女", "COSTUME", "DESIGN", "sawako", ["employee"], date(2025, 7, 1), "regular"),
    ("ui", "平泽忧", "女", "IT", "SYSADM", "mugi", ["employee", "admin"], date(2024, 4, 1), "regular"),
]

DEPT_MANAGERS = {"HTT": "ritsu", "MUSIC": "mio", "LIVE": "yui", "TEA": "mugi", "FIN": "megumi", "HR": "nodoka",
                 "COSTUME": "sawako", "IT": "ui"}

BASE_SALARY = {"ritsu": 3200000, "mio": 2200000, "yui": 1800000, "azusa": 1200000, "ichigo": 1300000,
               "mugi": 2200000, "megumi": 2000000, "fuuko": 1300000, "nodoka": 2100000, "himeko": 1250000,
               "sawako": 2000000, "mika": 1200000, "ui": 2500000}  # cents

LEAVE_TYPES = [
    ("annual", "年假", True, True, 40, "每年 5 天，按小时计（半天 = 4 小时）"),
    ("sick", "病假", True, True, 80, "每年 10 天带薪病假"),
    ("personal", "事假", False, False, 0, "无薪，不占用余额"),
    ("comp", "调休", True, True, 0, "由加班审批通过后自动入账"),
    ("marriage", "婚假", True, False, 0, "带薪，按制度 3 天"),
]

HOLIDAYS_2026 = [
    ("2026-01-01", "元旦", "holiday"), ("2026-02-16", "春节", "holiday"), ("2026-02-17", "春节", "holiday"),
    ("2026-02-18", "春节", "holiday"), ("2026-02-19", "春节", "holiday"), ("2026-02-20", "春节", "holiday"),
    ("2026-02-14", "春节调休上班", "workday"), ("2026-04-06", "清明节", "holiday"),
    ("2026-05-01", "劳动节", "holiday"), ("2026-06-19", "端午节", "holiday"),
    ("2026-10-01", "国庆节", "holiday"), ("2026-10-02", "国庆节", "holiday"), ("2026-10-05", "国庆节", "holiday"),
    ("2026-10-06", "国庆节", "holiday"), ("2026-10-07", "国庆节", "holiday"),
    ("2026-10-10", "国庆调休上班", "workday"), ("2026-11-27", "放学后茶会成立纪念日", "holiday"),
]


def _approval(nid, name, approver, x, y, mode="or", form_key=None, on_empty="fallback"):
    cfg = {"approver": approver, "mode": mode, "on_empty": on_empty}
    if form_key:
        cfg["form_key"] = form_key
    return {"id": nid, "type": "approval", "name": name, "config": cfg, "x": x, "y": y}


def _n(nid, typ, name, x, y, config=None):
    d = {"id": nid, "type": typ, "name": name, "x": x, "y": y}
    if config:
        d["config"] = config
    return d


def _e(eid, s, t, condition=None, default=False, label=None):
    d = {"id": eid, "source": s, "target": t}
    if condition is not None:
        d["condition"] = condition
    if default:
        d["default"] = True
    if label:
        d["label"] = label
    return d


def workflow_graphs() -> list[dict]:
    hr = {"type": "hr_admin"}
    mgr = {"type": "direct_manager"}
    return [
        {"key": "leave", "name": "请假审批", "business_type": "leave", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _approval("mgr", "直属主管审批", mgr, 220, 200),
                      _n("cond", "condition", "请假天数判断", 400, 200),
                      _approval("hr", "人事审核", hr, 580, 100),
                      _n("cc", "cc", "抄送人事部", 760, 200, {"targets": {"type": "role", "role_code": "hr"}}),
                      _n("end", "end", "结束", 920, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "cond"),
                      _e("e3", "cond", "hr", {"all": [{"field": "days", "op": ">", "value": 3}]}, label="超过 3 天"),
                      _e("e4", "cond", "cc", default=True, label="3 天及以内"), _e("e5", "hr", "cc"),
                      _e("e6", "cc", "end")]}},
        {"key": "expense", "name": "费用报销审批", "business_type": "expense", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _approval("mgr", "直属主管审批", mgr, 220, 200),
                      _n("cond", "condition", "金额判断", 400, 200),
                      _approval("ceo", "社长审批（大额）", {"type": "role", "role_code": "ceo"}, 580, 100),
                      _approval("fin", "财务审核", {"type": "role", "role_code": "finance"}, 760, 200),
                      _n("end", "end", "结束", 920, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "cond"),
                      _e("e3", "cond", "ceo", {"all": [{"field": "amount", "op": ">", "value": 5000}]},
                         label="金额 > 5000"),
                      _e("e4", "cond", "fin", default=True, label="金额 ≤ 5000"), _e("e5", "ceo", "fin"),
                      _e("e6", "fin", "end")]}},
        {"key": "travel", "name": "出差审批", "business_type": "travel", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _approval("mgr", "直属主管审批", mgr, 260, 200),
                      _n("end", "end", "结束", 460, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "end")]}},
        {"key": "onboarding", "name": "员工入职审批", "business_type": "onboarding", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200),
                      _approval("dept", "用人部门负责人确认",
                                {"type": "department_manager", "department_var": "department_id"}, 260, 200),
                      _approval("hr", "人事审批", hr, 460, 200), _n("end", "end", "结束", 660, 200)],
            "edges": [_e("e1", "start", "dept"), _e("e2", "dept", "hr"), _e("e3", "hr", "end")]}},
        {"key": "regularization", "name": "员工转正审批", "business_type": "regularization", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200),
                      _approval("mgr", "直属主管评价", mgr, 260, 200, form_key="manager_evaluation"),
                      _approval("hr", "人事审核", hr, 460, 200, form_key="hr_review"),
                      _n("end", "end", "结束", 660, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "hr"), _e("e3", "hr", "end")]}},
        {"key": "transfer", "name": "调岗审批（并行会审）", "business_type": "transfer", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _n("fork", "parallel", "并行会审", 220, 200),
                      _approval("from", "调出部门负责人",
                                {"type": "department_manager", "department_var": "from_department_id"}, 400, 100),
                      _approval("to", "调入部门负责人",
                                {"type": "department_manager", "department_var": "to_department_id"}, 400, 300),
                      _n("join", "join", "汇聚", 580, 200), _approval("hr", "人事审批", hr, 740, 200),
                      _n("end", "end", "结束", 900, 200)],
            "edges": [_e("e1", "start", "fork"), _e("e2", "fork", "from"), _e("e3", "fork", "to"),
                      _e("e4", "from", "join"), _e("e5", "to", "join"), _e("e6", "join", "hr"),
                      _e("e7", "hr", "end")]}},
        {"key": "offer", "name": "录用审批（人事会签）", "business_type": "offer", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200),
                      _approval("dept", "用人部门负责人",
                                {"type": "department_manager", "department_var": "department_id"}, 260, 200),
                      _approval("hr", "人事会签", {"type": "role", "role_code": "hr"}, 460, 200, mode="and"),
                      _n("end", "end", "结束", 660, 200)],
            "edges": [_e("e1", "start", "dept"), _e("e2", "dept", "hr"), _e("e3", "hr", "end")]}},
        {"key": "meeting", "name": "会议室预约审批", "business_type": "meeting", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200),
                      _approval("admin", "行政审批（或签）", {"type": "role", "role_code": "admin_staff"}, 260, 200),
                      _n("end", "end", "结束", 460, 200)],
            "edges": [_e("e1", "start", "admin"), _e("e2", "admin", "end")]}},
        {"key": "attendance_correction", "name": "补卡审批", "business_type": "attendance_correction", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _approval("mgr", "直属主管审批", mgr, 260, 200),
                      _n("end", "end", "结束", 460, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "end")]}},
        {"key": "overtime", "name": "加班审批", "business_type": "overtime", "graph": {
            "nodes": [_n("start", "start", "开始", 60, 200), _approval("mgr", "直属主管审批", mgr, 240, 200),
                      _n("cc", "cc", "抄送人事部", 420, 200, {"targets": {"type": "role", "role_code": "hr"}}),
                      _n("end", "end", "结束", 600, 200)],
            "edges": [_e("e1", "start", "mgr"), _e("e2", "mgr", "cc"), _e("e3", "cc", "end")]}},
    ]


def seed_base(db: Session, password: str, iterations: int, year: int | None = None) -> dict:
    """Insert base data into an empty database. Returns {username: user_id}."""
    if db.scalar(select(Role.id).limit(1)) is not None:
        raise RuntimeError("数据库已有基础数据，拒绝重复初始化")
    year = year or timeutil.today().year

    perms = {}
    for code, name, group in PERMISSIONS:
        p = Permission(code=code, name=name, group=group)
        db.add(p)
        perms[code] = p
    roles = {}
    for code, cfg in DEFAULT_ROLES.items():
        r = Role(code=code, name=cfg["name"], description=cfg["description"], data_scope=cfg["data_scope"],
                 is_system=True, permissions=[perms[c] for c in dict.fromkeys(cfg["permissions"])])
        db.add(r)
        roles[code] = r
    db.flush()

    rule = AttendanceRule(name="标准班（09:00-18:00）", work_start="09:00", work_end="18:00", break_start="12:00",
                          break_end="13:00", cross_day=False, late_grace_minutes=5, early_grace_minutes=0,
                          window_before_minutes=240, window_after_minutes=360, is_default=True)
    night = AttendanceRule(name="夜间排练班（22:00-次日06:00）", work_start="22:00", work_end="06:00",
                           break_start="02:00", break_end="02:30", cross_day=True, late_grace_minutes=5,
                           early_grace_minutes=0, window_before_minutes=240, window_after_minutes=360)
    db.add_all([rule, night])

    depts = {}
    for code, name, parent, desc in DEPARTMENTS:
        d = Department(code=code, name=name, parent_id=depts[parent].id if parent else None, description=desc,
                       sort=len(depts))
        db.add(d)
        db.flush()
        depts[code] = d
    positions = {}
    for code, name, level in POSITIONS:
        p = Position(code=code, name=name, level=level)
        db.add(p)
        positions[code] = p
    db.flush()

    pw_hash = hash_password(password, iterations)
    users, emps = {}, {}
    for i, (uname, name, gender, dept, pos, mgr, role_codes, hire, status) in enumerate(PEOPLE, start=1):
        u = User(username=uname, display_name=name, email=f"{uname}@htt.example", password_hash=pw_hash,
                 status="active", must_change_password=False, roles=[roles[c] for c in role_codes])
        db.add(u)
        db.flush()
        e = Employee(employee_no=f"HTT{i:04d}", name=name, gender=gender, phone=f"1380000{i:04d}",
                     email=f"{uname}@htt.example", department_id=depts[dept].id, position_id=positions[pos].id,
                     manager_id=emps[mgr].id if mgr else None, hire_date=hire, status=status,
                     probation_end_date=date(2026, 11, 1) if status == "probation" else None,
                     regularized_date=hire if status == "regular" else None, user_id=u.id)
        db.add(e)
        db.flush()
        db.add(JobHistory(employee_id=e.id, change_type="onboard", effective_date=hire, to_department_id=e.department_id,
                          to_position_id=e.position_id, to_manager_id=e.manager_id, to_status=status,
                          reason="初始化合成数据"))
        db.add(SalaryStructure(employee_id=e.id, base_cents=BASE_SALARY[uname], allowance_cents=50000,
                               social_rate_bp=1050, effective_from=hire, note="初始定薪"))
        users[uname], emps[uname] = u, e
    for code, uname in DEPT_MANAGERS.items():
        depts[code].manager_employee_id = emps[uname].id
    db.flush()

    for code, name, paid, needs, hours, desc in LEAVE_TYPES:
        db.add(LeaveType(code=code, name=name, paid=paid, requires_balance=needs, default_hours=hours, description=desc))
    db.flush()
    for e in emps.values():
        leave_svc.ensure_year_balances(db, e, year, None)

    for d, name, kind in HOLIDAYS_2026:
        db.add(Holiday(day=date.fromisoformat(d), name=name, kind=kind))

    for code, name, limit in [("instrument", "乐器与设备维护", 2000000), ("costume", "演出服装", 1000000),
                              ("tea", "茶点采购", 200000), ("travel", "合宿差旅", 1500000),
                              ("office", "办公用品", 300000), ("entertain", "招待费", 500000)]:
        db.add(ExpenseCategory(code=code, name=name, item_limit_cents=limit))
    for name, loc, cap, eq, approval in [
        ("音乐准备室", "樱丘大楼 3F", 8, "鼓组、音箱、茶具", False),
        ("讲堂", "樱丘大楼 1F", 200, "舞台、灯光、音响", True),
        ("茶歇室", "樱丘大楼 2F", 6, "茶具、白板", False),
        ("琴吹别墅会议厅", "琴吹家海边别墅", 20, "投影、合宿设备", True),
    ]:
        db.add(MeetingRoom(name=name, location=loc, capacity=cap, equipment=eq, requires_approval=approval))
    for name in ["公司通知", "演出活动", "制度规范", "茶话会"]:
        db.add(AnnouncementCategory(name=name))
    for name in ["乐谱与编曲", "规章制度", "演出资料", "财务模板"]:
        db.add(DocCategory(name=name))
    for key, value, desc in [("company.name", COMPANY, "公司名称"),
                             ("company.slogan", "认真工作，然后喝茶", "公司标语"),
                             ("leave.hr_review_days", 3, "请假超过多少天需 HR 审核（说明用）"),
                             ("expense.ceo_threshold", 5000, "报销金额超过该值需社长审批（说明用）"),
                             ("attendance.simulation_note", "模拟打卡：可指定打卡时间用于测试与演示", "模拟打卡说明")]:
        db.add(SystemSetting(key=key, value=value, description=desc))

    admin = users["ui"]
    now = timeutil.now()
    for wf in workflow_graphs():
        d = WfDefinition(key=wf["key"], name=wf["name"], business_type=wf["business_type"], status="active",
                         created_by=admin.id, description="系统初始化流程")
        db.add(d)
        db.flush()
        v = WfDefinitionVersion(definition_id=d.id, version=1, graph=wf["graph"], status="published",
                                published_at=now, published_by=admin.id, created_by=admin.id)
        db.add(v)
        db.flush()
        d.current_version_id = v.id
    db.flush()
    return {k: u.id for k, u in users.items()}
