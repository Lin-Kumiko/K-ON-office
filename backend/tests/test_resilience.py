"""Fault injection at explicit boundaries: the real transaction / business code runs, only the injected
dependency fails. Verifies detection, rollback and recovery."""
import io

import pytest

from tests.conftest import err, ok


def _task(api, instance_id):
    return next(t for t in ok(api.get("/api/workflow/tasks"))["items"] if t["instance_id"] == instance_id)


def _leave(api, day="2026-11-02"):
    lt = next(t for t in ok(api.get("/api/leave/types")) if t["code"] == "annual")["id"]
    return ok(api.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": day, "start_half": "AM", "end_date": day, "end_half": "PM",
        "reason": "x"}), 201)


def test_db_failure_during_final_approval_rolls_back_everything(as_user, sql, monkeypatch):
    """A failing write late in the approval (notification insert) must undo task, instance, balance and
    attendance changes; retrying after the fault is gone succeeds exactly once."""
    yui, mio = as_user("yui"), as_user("mio")
    lv = _leave(yui)
    t = _task(mio, lv["instance_id"])
    import app.workflow.engine as engine_mod

    def boom(*a, **k):
        raise RuntimeError("injected notification failure")
    monkeypatch.setattr(engine_mod, "notify", boom)
    with pytest.raises(RuntimeError):  # TestClient re-raises server errors by default
        mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={})
    assert sql("SELECT status FROM wf_tasks WHERE id=?", id=t["id"])[0][0] == "pending"
    assert sql("SELECT status FROM leave_requests WHERE id=?", id=lv["id"])[0][0] == "pending"
    assert sql("SELECT used_hours, pending_hours FROM leave_balances b JOIN leave_types t ON t.id=b.leave_type_id "
               "WHERE t.code='annual' AND b.employee_id=(SELECT id FROM employees WHERE employee_no='HTT0003')")[0] == (0, 8)
    assert sql("SELECT count(*) FROM leave_ledger WHERE change_type='consume'")[0][0] == 0
    monkeypatch.undo()
    ok(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}))
    assert sql("SELECT count(*) FROM leave_ledger WHERE change_type='consume' AND ref_id=?", id=lv["id"])[0][0] == 1


def test_unhandled_error_returns_generic_500_without_leaking(app, as_user, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.dashboard as dash

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(dash, "_months_back", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        token = c.post("/api/auth/login", json={"username": "yui", "password": __import__("tests.conftest", fromlist=["x"]).TEST_PASSWORD}).json()["token"]
        r = c.get("/api/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text


def test_file_storage_failure_leaves_no_record(as_user, sql, monkeypatch):
    from pathlib import Path

    def broken_write(self, data):
        raise OSError("disk full (injected)")
    monkeypatch.setattr(Path, "write_bytes", broken_write)
    yui = as_user("yui")
    with pytest.raises(OSError):
        yui.post("/api/files", files={"file": ("r.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
                 data={"purpose": "expense_receipt"})
    assert sql("SELECT count(*) FROM files")[0][0] == 0
    monkeypatch.undo()
    ok(yui.post("/api/files", files={"file": ("r.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
                data={"purpose": "expense_receipt"}), 201)


def test_upstream_downstream_inconsistency_is_detected(as_user, app, sql):
    """If the business document was changed behind the engine's back, approval refuses to complete."""
    yui, mio = as_user("yui"), as_user("mio")
    lv = _leave(yui)
    with app.state.db.engine.begin() as c:
        c.exec_driver_sql("UPDATE leave_requests SET status='cancelled' WHERE id=?", (lv["id"],))
    t = _task(mio, lv["instance_id"])
    err(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}), 409, "BUSINESS_STATE_MISMATCH")
    assert sql("SELECT status FROM wf_tasks WHERE id=?", id=t["id"])[0][0] == "pending"
    assert sql("SELECT status FROM wf_instances WHERE id=?", id=lv["instance_id"])[0][0] == "running"
    # recovery: an administrator cancels the orphaned flow
    with app.state.db.engine.begin() as c:
        c.exec_driver_sql("UPDATE leave_requests SET status='pending' WHERE id=?", (lv["id"],))
    ok(as_user("saito").post(f"/api/workflow/instances/{lv['instance_id']}/cancel", json={"comment": "数据修复"}))
    assert sql("SELECT status FROM leave_requests WHERE id=?", id=lv["id"])[0][0] == "cancelled"
    assert sql("SELECT pending_hours FROM leave_balances b JOIN leave_types t ON t.id=b.leave_type_id WHERE "
               "t.code='annual' AND b.employee_id=(SELECT id FROM employees WHERE employee_no='HTT0003')")[0][0] == 0


def test_db_busy_maps_to_retryable_503(app, as_user, monkeypatch):
    from sqlalchemy.exc import OperationalError
    import app.api.leave as leave_api

    def busy(*a, **k):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))
    monkeypatch.setattr(leave_api.svc, "freeze", busy)
    yui = as_user("yui")
    lt = next(t for t in ok(yui.get("/api/leave/types")) if t["code"] == "annual")["id"]
    r = yui.post("/api/leave/requests?submit=true", json={"leave_type_id": lt, "start_date": "2026-11-02",
                                                         "start_half": "AM", "end_date": "2026-11-02", "end_half": "PM",
                                                         "reason": "x"})
    err(r, 503, "DB_BUSY")
    monkeypatch.undo()
    assert ok(yui.get("/api/leave/requests"))["total"] == 0  # nothing half-written


def test_invalid_definition_cannot_break_running_flows(as_user):
    """Publishing is refused for invalid graphs, so running instances keep their valid version."""
    admin, yui = as_user("saito"), as_user("yui")
    lv = _leave(yui)
    d = next(x for x in ok(admin.get("/api/workflow/definitions")) if x["key"] == "leave")
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/draft"))
    ok(admin.put(f"/api/workflow/definitions/{d['id']}/draft", json={"graph": {"nodes": [], "edges": []}}))
    err(admin.post(f"/api/workflow/definitions/{d['id']}/publish"), 422, "INVALID_GRAPH")
    mio = as_user("mio")
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, lv['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/leave/requests/{lv['id']}"))["status"] == "approved"
