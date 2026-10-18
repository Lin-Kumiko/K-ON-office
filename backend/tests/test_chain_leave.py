"""Chain 1 — employee leave: login -> balance -> create -> submit -> workflow -> manager -> HR -> done."""
from tests.conftest import err, ok


def _annual(api):
    bal = ok(api.get("/api/leave/balances"))
    return next(b for b in bal if b["leave_type_code"] == "annual")


def test_leave_chain_long_leave_goes_through_hr(as_user, sql):
    yui = as_user("yui")
    before = _annual(yui)
    assert before["available_hours"] == 40
    # 2026-10-26 (Mon) .. 2026-10-29 (Thu) = 4 workdays = 32h -> needs HR review (> 3 days)
    leave = ok(yui.post("/api/leave/requests", json={
        "leave_type_id": before["leave_type_id"], "start_date": "2026-10-26", "start_half": "AM",
        "end_date": "2026-10-29", "end_half": "PM", "reason": "去琴吹家别墅合宿练习"}), 201)
    assert leave["status"] == "draft" and leave["hours"] == 32
    submitted = ok(yui.post(f"/api/leave/requests/{leave['id']}/submit"))
    assert submitted["status"] == "pending" and submitted["instance_id"]
    assert _annual(yui)["pending_hours"] == 32 and _annual(yui)["available_hours"] == 8

    # employee cannot approve own; manager mio has the task
    mio = as_user("mio")
    tasks = ok(mio.get("/api/workflow/tasks"))["items"]
    task = next(t for t in tasks if t["business_id"] == leave["id"] and t["business_type"] == "leave")
    err(yui.post(f"/api/workflow/tasks/{task['id']}/approve", json={}), 403, "NOT_TASK_ASSIGNEE")
    res = ok(mio.post(f"/api/workflow/tasks/{task['id']}/approve", json={"comment": "合宿加油"}))
    assert res["task_status"] == "approved" and res["instance"]["status"] == "running"
    assert res["instance"]["current_nodes"] == ["人事审核"]
    # repeated approval of a finished task is rejected
    err(mio.post(f"/api/workflow/tasks/{task['id']}/approve", json={}), 409, "TASK_ALREADY_HANDLED")

    # HR review is an or-sign between nodoka and himeko
    hr_task = next(t for t in ok(as_user("himeko").get("/api/workflow/tasks"))["items"]
                   if t["instance_id"] == submitted["instance_id"])
    res = ok(as_user("himeko").post(f"/api/workflow/tasks/{hr_task['id']}/approve", json={"comment": "同意"}))
    assert res["instance"]["status"] == "approved"
    assert not [t for t in ok(as_user("nodoka").get("/api/workflow/tasks"))["items"]
                if t["instance_id"] == submitted["instance_id"]]

    after = _annual(yui)
    assert (after["used_hours"], after["pending_hours"], after["available_hours"]) == (32, 0, 8)
    assert ok(yui.get(f"/api/leave/requests/{leave['id']}"))["status"] == "approved"
    # ledger: freeze + consume, exactly once
    rows = sql("SELECT change_type, hours FROM leave_ledger WHERE ref_type='leave_request' AND ref_id=? ORDER BY id",
               id=leave["id"])
    assert rows == [("freeze", -32), ("consume", -32)]
    # attendance synced for the leave days
    recs = sql("SELECT work_date, status, leave_hours FROM attendance_records WHERE employee_id="
               "(SELECT id FROM employees WHERE employee_no='HTT0003') AND work_date BETWEEN '2026-10-26' AND "
               "'2026-10-29' ORDER BY work_date")
    assert [r[1] for r in recs] == ["leave"] * 4
    # notifications: initiator informed, CC to HR recorded
    assert sql("SELECT count(*) FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.username='yui' AND "
               "n.category='workflow_result'")[0][0] == 1
    assert sql("SELECT count(*) FROM wf_cc WHERE instance_id=?", id=submitted["instance_id"])[0][0] == 2


def test_short_leave_skips_hr_and_reject_resubmit(as_user, sql):
    yui, mio = as_user("yui"), as_user("mio")
    lt = _annual(yui)["leave_type_id"]
    leave = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-10-21", "start_half": "PM", "end_date": "2026-10-21",
        "end_half": "PM", "reason": "下午去修吉他（吉太）"}), 201)
    assert leave["status"] == "pending" and leave["hours"] == 4
    task = next(t for t in ok(mio.get("/api/workflow/tasks"))["items"] if t["business_id"] == leave["id"])
    err(mio.post(f"/api/workflow/tasks/{task['id']}/reject", json={"comment": ""}), 422)
    ok(mio.post(f"/api/workflow/tasks/{task['id']}/reject", json={"comment": "那天下午有排练，请改期"}))
    assert ok(yui.get(f"/api/leave/requests/{leave['id']}"))["status"] == "rejected"
    assert _annual(yui)["pending_hours"] == 0
    # cannot approve after rejection
    err(mio.post(f"/api/workflow/tasks/{task['id']}/approve", json={}), 409, "TASK_ALREADY_HANDLED")
    # modify and resubmit
    ok(yui.put(f"/api/leave/requests/{leave['id']}", json={
        "leave_type_id": lt, "start_date": "2026-10-22", "start_half": "PM", "end_date": "2026-10-22",
        "end_half": "PM", "reason": "改到周四下午"}))
    again = ok(yui.post(f"/api/leave/requests/{leave['id']}/submit"))
    assert again["instance_id"] != leave["instance_id"]
    task2 = next(t for t in ok(mio.get("/api/workflow/tasks"))["items"] if t["instance_id"] == again["instance_id"])
    inst = ok(mio.post(f"/api/workflow/tasks/{task2['id']}/approve", json={}))["instance"]
    assert inst["status"] == "approved"  # 0.5 day <= 3 -> no HR node
    assert _annual(yui)["used_hours"] == 4
    rows = sql("SELECT change_type, seq FROM leave_ledger WHERE ref_id=? AND ref_type='leave_request' ORDER BY id",
               id=leave["id"])
    assert rows == [("freeze", 1), ("unfreeze", 1), ("freeze", 2), ("consume", 2)]
