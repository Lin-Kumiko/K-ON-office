"""The shared trial account: can browse and apply, cannot administer or approve for others."""
import sys

import pytest

from app.core.config import PROJECT_DIR
from app.core.errors import ValidationFailed
from tests.conftest import ITERATIONS, TEST_PASSWORD, err, login, ok

sys.path.insert(0, str(PROJECT_DIR / "scripts"))
from create_test_account import create  # noqa: E402

TRIAL_PW = "TrialTea2026"


def test_trial_account_permissions(app, client, sql):
    assert create(app.state.db, TRIAL_PW, ITERATIONS, "test") > 0
    assert create(app.state.db, TRIAL_PW, ITERATIONS, "test") == 0  # idempotent
    with pytest.raises(ValidationFailed):  # must not reuse a seed account password
        create(app.state.db, TEST_PASSWORD, ITERATIONS, "test2")
    t = login(client, "test", TRIAL_PW)
    me = ok(t.get("/api/auth/me"))
    assert me["roles"] == ["guest"] and me["must_change_password"] is False
    assert me["employee"]["department_name"] == "音乐制作部"
    # browse: whole company, sensitive fields masked
    emps = ok(t.get("/api/employees?page_size=50"))
    assert emps["total"] == 14
    azusa = next(e for e in emps["items"] if e["name"] == "中野梓")
    assert "****" in azusa["phone"]
    ok(t.get("/api/reports/overview"))
    # apply: own leave goes to the direct manager (mio)
    lt = next(x for x in ok(t.get("/api/leave/types")) if x["code"] == "annual")["id"]
    lv = ok(t.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "体验请假"}), 201)
    assert ok(t.get(f"/api/workflow/instances/{lv['instance_id']}"))["current_assignees"] == ["秋山澪"]
    # no administration
    for url in ("/api/users", "/api/audit-logs", "/api/workflow/definitions", "/api/payroll/runs"):
        err(t.get(url), 403)
    err(t.post("/api/employees", json={"name": "x", "email": "x@x.example", "department_id": 1,
                                       "hire_date": "2026-10-19"}), 403)
    # cannot act on other people's tasks
    yui = login(client, "yui")
    other = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-03", "start_half": "AM", "end_date": "2026-11-03",
        "end_half": "PM", "reason": "x"}), 201)
    task_id = sql("SELECT id FROM wf_tasks WHERE instance_id=?", id=other["instance_id"])[0][0]
    err(t.post(f"/api/workflow/tasks/{task_id}/approve", json={}), 403, "NOT_TASK_ASSIGNEE")
