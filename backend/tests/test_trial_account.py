"""The shared trial account: broad business + management access, but no account/permission administration,
and it never becomes an approver of existing flows by itself."""
import sys

import pytest

from app.core.config import PROJECT_DIR
from app.core.errors import ValidationFailed
from app.seed import GUEST_EXCLUDED, seed_test_account
from tests.conftest import ITERATIONS, TEST_PASSWORD, err, login, ok

sys.path.insert(0, str(PROJECT_DIR / "scripts"))
from create_test_account import create  # noqa: E402

TRIAL_PW = "TrialTea2026"


def _trial(app, client):
    assert create(app.state.db, TRIAL_PW, ITERATIONS, "test") > 0
    return login(client, "test", TRIAL_PW)


def test_trial_account_creation_rules(app, client, sql):
    _trial(app, client)
    assert create(app.state.db, TRIAL_PW, ITERATIONS, "test") == 0  # idempotent
    with pytest.raises(ValidationFailed):  # must not reuse a seed account password
        create(app.state.db, TEST_PASSWORD, ITERATIONS, "test2")
    # an older, narrower guest role is brought up to date on re-run
    with app.state.db.engine.begin() as c:
        c.exec_driver_sql("DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE code='guest') AND "
                          "permission_id IN (SELECT id FROM permissions WHERE code IN ('payroll:manage','workflow:manage'))")
    with app.state.db.session(write=True) as s:
        assert seed_test_account(s, TRIAL_PW, ITERATIONS) is None
        s.commit()
    perms = {r[0] for r in sql("SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id=rp.permission_id "
                               "JOIN roles r ON r.id=rp.role_id WHERE r.code='guest'")}
    assert {"payroll:manage", "workflow:manage"} <= perms and not (perms & GUEST_EXCLUDED)


def test_trial_account_has_broad_access(app, client):
    t = _trial(app, client)
    me = ok(t.get("/api/auth/me"))
    assert me["roles"] == ["guest"] and me["data_scope"] == "all" and me["must_change_password"] is False
    assert {"workflow", "payroll", "reports", "system", "recruitment"} <= {m["key"] for m in me["menus"]}
    ok(t.get("/api/dashboard/summary"))  # menu with any-of permissions must not break quick entries
    emps = ok(t.get("/api/employees?page_size=50"))
    assert emps["total"] == 14 and "****" not in next(e for e in emps["items"] if e["name"] == "中野梓")["phone"]
    for url in ("/api/audit-logs", "/api/workflow/definitions", "/api/payroll/runs", "/api/reports/overview",
                "/api/recruitment/candidates", "/api/expense/claims?scope=finance", "/api/workflow/instances?scope=all"):
        ok(t.get(url))
    music = next(d for d in ok(t.get("/api/departments")) if d["code"] == "MUSIC")
    ok(t.post("/api/employees", json={"name": "体验新人", "email": "trial.new@htt.example",
                                      "department_id": music["id"], "hire_date": "2026-10-19"}), 201)
    ok(t.post("/api/payroll/runs", json={"month": "2026-09"}), 201)


def test_trial_account_cannot_administer_accounts_or_permissions(app, client):
    t = _trial(app, client)
    admin = login(client, "saito")
    yui_id = ok(login(client, "yui").get("/api/auth/me"))["id"]
    role_id = next(r for r in ok(admin.get("/api/roles")) if r["code"] == "guest")["id"]
    err(t.get("/api/users"), 403)
    err(t.post("/api/users", json={"username": "evil", "display_name": "x"}), 403)
    err(t.post(f"/api/users/{yui_id}/reset-password", json={"new_password": "Hijack2026x"}), 403)
    err(t.post(f"/api/users/{yui_id}/status", json={"status": "disabled"}), 403)
    err(t.put(f"/api/users/{yui_id}/roles", json={"role_codes": ["admin"]}), 403)
    err(t.put(f"/api/roles/{role_id}", json={"name": "x", "data_scope": "all", "permissions": ["user:manage"]}), 403)
    err(t.put("/api/settings", json={"values": {"company.slogan": "x"}}), 403)


def test_trial_account_does_not_change_approvers_but_can_take_over(app, client):
    t = _trial(app, client)
    yui = login(client, "yui")
    lt = next(x for x in ok(yui.get("/api/leave/types")) if x["code"] == "annual")["id"]
    lv = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-05",
        "end_half": "PM", "reason": "x"}), 201)
    inst = ok(t.get(f"/api/workflow/instances/{lv['instance_id']}"))
    assert inst["current_assignees"] == ["秋山澪"]
    task = next(x for x in inst["tasks"] if x["status"] == "pending")
    err(t.post(f"/api/workflow/tasks/{task['id']}/approve", json={}), 403, "NOT_TASK_ASSIGNEE")
    me = ok(t.get("/api/auth/me"))["id"]
    mine = ok(t.post(f"/api/workflow/tasks/{task['id']}/reassign", json={"to_user_id": me, "comment": "体验改派"}))
    ok(t.post(f"/api/workflow/tasks/{mine['id']}/approve", json={}))
    nxt = ok(t.get(f"/api/workflow/instances/{lv['instance_id']}"))
    assert nxt["current_assignees"] == ["真锅和", "立花姬子"]  # HR review: trial account is not added to role hr
