"""Authentication, RBAC, data isolation, input validation, injection/XSS handling, uploads, masking."""
import io

import pytest

from tests.conftest import TEST_PASSWORD, err, login, ok


def test_login_failures_lockout_and_logs(client, as_user, sql):
    for _ in range(4):
        err(client.post("/api/auth/login", json={"username": "mika", "password": "wrong-pass-1"}), 401,
            "INVALID_CREDENTIALS")
    err(client.post("/api/auth/login", json={"username": "nobody", "password": "x"}), 401, "INVALID_CREDENTIALS")
    err(client.post("/api/auth/login", json={"username": "mika", "password": "wrong-pass-1"}), 401)
    # 5th failure locks the account, even the correct password is refused
    err(client.post("/api/auth/login", json={"username": "mika", "password": TEST_PASSWORD}), 423, "ACCOUNT_LOCKED")
    rows = sql("SELECT success, reason FROM login_logs WHERE username='mika' ORDER BY id")
    assert [r[1] for r in rows][-2:] == ["bad_password", "locked"]
    admin = as_user("saito")
    uid = next(u for u in ok(admin.get("/api/users?q=mika"))["items"])["id"]
    assert ok(admin.get(f"/api/users/{uid}"))["locked"] is True
    ok(admin.post(f"/api/users/{uid}/unlock"))
    login(client, "mika")
    logs = ok(admin.get("/api/login-logs?username=mika"))
    assert logs["total"] >= 7
    # password hashes are never exposed
    assert "password" not in str(ok(admin.get(f"/api/users/{uid}"))).lower().replace("must_change_password", "")


def test_logout_and_session_revocation(client):
    api = login(client, "yui")
    second = login(client, "yui")
    sessions = ok(api.get("/api/auth/sessions"))
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    ok(api.delete(f"/api/auth/sessions/{other['id']}"))
    err(second.get("/api/auth/me"), 401, "SESSION_EXPIRED")
    ok(api.post("/api/auth/logout"))
    err(api.get("/api/auth/me"), 401)
    err(client.get("/api/auth/me", headers={"Authorization": "Bearer forged-token"}), 401)


def test_change_password_rules(client):
    api = login(client, "mika")
    err(api.post("/api/auth/change-password", json={"old_password": "wrong", "new_password": "Abcdef123"}), 422,
        "WRONG_PASSWORD")
    err(api.post("/api/auth/change-password", json={"old_password": TEST_PASSWORD, "new_password": "short1"}), 422,
        "WEAK_PASSWORD")
    err(api.post("/api/auth/change-password", json={"old_password": TEST_PASSWORD, "new_password": "onlyletters"}),
        422, "WEAK_PASSWORD")
    other = login(client, "mika")
    ok(api.post("/api/auth/change-password", json={"old_password": TEST_PASSWORD, "new_password": "Costume2026"}))
    err(other.get("/api/auth/me"), 401)  # other sessions revoked
    ok(api.get("/api/auth/me"))
    login(client, "mika", "Costume2026")


def test_disabled_account(as_user, client):
    admin = as_user("saito")
    mika = login(client, "mika")
    uid = ok(mika.get("/api/auth/me"))["id"]
    ok(admin.post(f"/api/users/{uid}/status", json={"status": "disabled"}))
    err(mika.get("/api/auth/me"), 401)
    err(client.post("/api/auth/login", json={"username": "mika", "password": TEST_PASSWORD}), 403, "ACCOUNT_DISABLED")
    err(admin.post(f"/api/users/{ok(admin.get('/api/auth/me'))['id']}/status", json={"status": "disabled"}), 422,
        "SELF_LOCKOUT")


@pytest.mark.parametrize("method,url,body", [
    ("get", "/api/users", None),
    ("post", "/api/departments", {"name": "x", "code": "X1"}),
    ("get", "/api/audit-logs", None),
    ("post", "/api/workflow/definitions", {"key": "kk", "name": "n", "business_type": "leave"}),
    ("get", "/api/payroll/runs", None),
    ("post", "/api/leave/balances/adjust", {"employee_id": 1, "leave_type_id": 1, "year": 2026, "hours": 8,
                                            "remark": "x"}),
    ("get", "/api/expense/claims?scope=finance", None),
    ("get", "/api/recruitment/candidates", None),
    ("post", "/api/announcements", {"title": "t", "content": "c"}),
    ("get", "/api/reports/overview", None),
    ("put", "/api/roles/1", {"name": "x"}),
    ("post", "/api/payroll/runs", {"month": "2026-10"}),
])
def test_backend_enforces_permissions(as_user, method, url, body):
    api = as_user("mika")  # plain employee
    resp = getattr(api, method)(url, json=body) if body is not None else getattr(api, method)(url)
    err(resp, 403)


def test_data_isolation_between_users(as_user):
    mika, yui, hr = as_user("mika"), as_user("yui"), as_user("nodoka")
    azusa_id = next(e for e in ok(hr.get("/api/employees/options")) if e["name"] == "中野梓")["id"]
    nodoka_emp = ok(hr.get("/api/auth/me"))["employee"]["id"]
    # plain employee: only self in the employee list, other profiles forbidden
    assert [e["name"] for e in ok(mika.get("/api/employees"))["items"]] == ["佐伯三花"]
    err(mika.get(f"/api/employees/{azusa_id}"), 403)
    err(mika.get(f"/api/leave/balances?employee_id={azusa_id}"), 403)
    err(mika.get(f"/api/attendance/records?start=2026-10-01&end=2026-10-10&employee_id={azusa_id}"), 403)
    # group lead sees own subtree, but not other departments
    ok(yui.get(f"/api/employees/{azusa_id}"))
    err(yui.get(f"/api/employees/{nodoka_emp}"), 403, "DATA_SCOPE_DENIED")
    names = {e["name"] for e in ok(yui.get("/api/employees"))["items"]}
    assert names == {"平泽唯", "中野梓", "若王子苺"}
    # leave requests of others are not visible via scope=mine and ids are protected
    lt = next(t for t in ok(as_user("azusa").get("/api/leave/types")) if t["code"] == "annual")["id"]
    lv = ok(as_user("azusa").post("/api/leave/requests", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "x"}), 201)
    err(mika.get(f"/api/leave/requests/{lv['id']}"), 403)
    err(yui.put(f"/api/leave/requests/{lv['id']}", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "hijack"}), 403, "NOT_OWNER")
    err(mika.post(f"/api/leave/requests/{lv['id']}/submit"), 403)
    # notifications are private
    n = ok(hr.get("/api/notifications"))["items"]
    if n:
        err(mika.post(f"/api/notifications/{n[0]['id']}/read"), 404)


def test_sensitive_fields_are_masked(as_user):
    yui, hr = as_user("yui"), as_user("nodoka")
    azusa = next(e for e in ok(yui.get("/api/employees"))["items"] if e["name"] == "中野梓")
    assert "****" in azusa["phone"] and azusa["email"].startswith("a***@")
    full = ok(hr.get(f"/api/employees/{azusa['id']}"))
    assert "****" not in full["phone"]
    me = ok(yui.get(f"/api/employees/{ok(yui.get('/api/auth/me'))['employee']['id']}"))
    assert "****" not in me["phone"]


@pytest.mark.parametrize("q", ["' OR 1=1 --", "\"; DROP TABLE employees; --", "%' UNION SELECT * FROM users --"])
def test_sql_injection_in_search_is_inert(as_user, sql, q):
    hr = as_user("nodoka")
    res = ok(hr.get("/api/employees", params={"q": q}))
    assert res["total"] == 0
    ok(hr.get("/api/documents", params={"q": q}))
    ok(hr.get("/api/announcements", params={"q": q}))
    assert sql("SELECT count(*) FROM employees")[0][0] == 13


def test_xss_payload_stored_as_plain_text(as_user):
    admin = as_user("saito")
    payload = "<script>alert('mio')</script><img src=x onerror=alert(1)>"
    a = ok(admin.post("/api/announcements", json={"title": payload[:100], "content": payload}), 201)
    assert ok(admin.get(f"/api/announcements/{a['id']}"))["content"] == payload  # returned verbatim as JSON data
    r = admin.get(f"/api/announcements/{a['id']}")
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_upload_restrictions(as_user, app):
    yui = as_user("yui")
    up = lambda name, data, purpose="expense_receipt": yui.post(  # noqa: E731
        "/api/files", files={"file": (name, io.BytesIO(data), "application/octet-stream")}, data={"purpose": purpose})
    err(up("evil.exe", b"MZ\x90\x00"), 422, "FILE_TYPE_NOT_ALLOWED")
    err(up("fake.pdf", b"<html>not a pdf</html>"), 422, "FILE_CONTENT_MISMATCH")
    err(up("empty.txt", b""), 422, "FILE_EMPTY")
    err(up("big.txt", b"a" * (app.state.settings.max_upload_bytes + 1)), 422, "FILE_TOO_LARGE")
    err(up("r.pdf", b"%PDF-1.4", purpose="resume"), 403)
    err(up("r.pdf", b"%PDF-1.4", purpose="../../etc"), 422, "INVALID_PURPOSE")
    f = ok(up("../../../../Windows/win.ini.txt", b"tea time"), 201)
    assert f["original_name"] == "win.ini.txt"
    stored = list(app.state.settings.upload_dir.iterdir())
    assert len(stored) == 1 and stored[0].parent == app.state.settings.upload_dir
    assert "win" not in stored[0].name
    # other users cannot download someone else's receipt
    err(as_user("mika").get(f"/api/files/{f['id']}"), 403)
    assert yui.get(f"/api/files/{f['id']}").content == b"tea time"
    assert as_user("megumi").get(f"/api/files/{f['id']}").status_code == 200  # finance may


def test_input_validation_errors_are_structured(as_user):
    yui = as_user("yui")
    e = err(yui.post("/api/leave/requests", json={"leave_type_id": "abc", "start_date": "not-a-date"}), 422,
            "VALIDATION_ERROR")
    locs = {tuple(d["loc"]) for d in e["error"]["details"]}
    assert ("body", "leave_type_id") in locs and ("body", "start_date") in locs and ("body", "reason") in locs
    err(yui.get("/api/employees?page=0"), 422)
    err(yui.get("/api/employees?page_size=1000"), 422)
    err(yui.get("/api/employees?sort=password_hash"), 422)
    err(yui.get("/api/leave/requests/999999"), 404, "NOT_FOUND")
    err(yui.get("/api/no-such-endpoint"), 404)


def test_role_and_user_admin_guards(as_user):
    admin, hr = as_user("saito"), as_user("nodoka")
    yui_id = ok(as_user("yui").get("/api/auth/me"))["id"]
    err(hr.put(f"/api/users/{yui_id}/roles", json={"role_codes": ["employee", "admin"]}), 403)  # hr cannot grant admin
    ok(hr.put(f"/api/users/{yui_id}/roles", json={"role_codes": ["employee", "manager"]}))
    admin_role = next(r for r in ok(admin.get("/api/roles")) if r["code"] == "admin")
    err(admin.put(f"/api/roles/{admin_role['id']}", json={"name": "x", "data_scope": "all", "permissions": []}),
        422, "ROLE_IMMUTABLE")
    role = ok(admin.post("/api/roles", json={"code": "intern", "name": "实习生", "permissions": ["dashboard:view"]}),
              201)
    err(admin.post("/api/roles", json={"code": "intern", "name": "dup"}), 409)
    ok(admin.delete(f"/api/roles/{role['id']}"))
    audit = ok(admin.get("/api/audit-logs?action=set_user_roles"))
    assert audit["total"] == 1 and audit["items"][0]["detail"]["after"] == ["employee", "manager"]
