"""Anonymous visitors can read public content; every operation asks to log in; self-registration."""
import io

import pytest

from tests.conftest import Api, err, login, ok

PUBLIC_GETS = ["/api/public/overview", "/api/departments", "/api/departments/tree", "/api/positions",
               "/api/announcements", "/api/announcements/categories", "/api/documents", "/api/documents/categories",
               "/api/meeting/rooms", "/api/meeting/calendar?start=2026-10-19&end=2026-10-25"]


@pytest.mark.parametrize("url", PUBLIC_GETS)
def test_visitor_can_browse_public_pages(client, url):
    ok(client.get(url))


@pytest.mark.parametrize("method,url", [
    ("get", "/api/auth/me"), ("get", "/api/dashboard/summary"), ("get", "/api/employees"),
    ("get", "/api/departments/1/members"), ("get", "/api/workflow/tasks"), ("get", "/api/leave/balances"),
    ("get", "/api/announcements?scope=manage"), ("post", "/api/attendance/punch"), ("post", "/api/leave/calculate"),
    ("post", "/api/meeting/bookings"), ("post", "/api/announcements/1/read"), ("get", "/api/documents/1/download"),
    ("get", "/api/meeting/bookings"), ("get", "/api/meeting/rooms/1/usage?month=2026-10"),
])
def test_visitor_operations_require_login(client, method, url):
    body = err(getattr(client, method)(url, **({"json": {}} if method == "post" else {})), 401, "LOGIN_REQUIRED")
    assert body["error"]["message"] == "请先登录后再操作"


def test_visitor_sees_only_public_content(client, as_user):
    hr = as_user("nodoka")
    music = next(d for d in ok(hr.get("/api/departments")) if d["code"] == "MUSIC")
    a_all = ok(hr.post("/api/announcements", json={"title": "全员公告", "content": "大家好"}), 201)
    a_dep = ok(hr.post("/api/announcements", json={"title": "部门公告", "content": "仅音乐部", "scope_type": "departments",
                                                   "scope_department_ids": [music["id"]]}), 201)
    for a in (a_all, a_dep):
        ok(hr.post(f"/api/announcements/{a['id']}/publish"))
    titles = [x["title"] for x in ok(client.get("/api/announcements"))["items"]]
    assert titles == ["全员公告"]
    ok(client.get(f"/api/announcements/{a_all['id']}"))
    err(client.get(f"/api/announcements/{a_dep['id']}"), 404)
    mio = as_user("mio")
    for title, vis in (("公开曲谱", "public"), ("部门曲谱", "department"), ("私人草稿", "private")):
        ok(mio.post("/api/documents", files={"file": ("a.txt", io.BytesIO(b"tea"), "text/plain")},
                    data={"title": title, "visibility": vis}), 201)
    docs = ok(client.get("/api/documents"))["items"]
    assert [d["title"] for d in docs] == ["公开曲谱"] and docs[0]["can_edit"] is False
    overview = ok(client.get("/api/public/overview"))
    assert overview["company_name"] == "放学后茶会株式会社" and overview["registration_open"] is True
    assert overview["stats"]["headcount"] == 13 and overview["stats"]["announcements"] == 1
    assert [x["title"] for x in overview["announcements"]] == ["全员公告"]
    assert "phone" not in str(overview) and "email" not in str(overview)


def test_register_then_login(client, sql):
    r = ok(client.post("/api/auth/register", json={"username": "ui_hirasawa", "password": "Cake2026x"}), 201)
    assert r["message"] == "注册成功，请登录"
    err(client.post("/api/auth/register", json={"username": "UI_HIRASAWA", "password": "Cake2026x"}), 409, "USERNAME_EXISTS")
    err(client.post("/api/auth/register", json={"username": "yui", "password": "Cake2026x"}), 409, "USERNAME_EXISTS")
    api = login(client, "ui_hirasawa", "Cake2026x")
    me = ok(api.get("/api/auth/me"))
    assert me["roles"] == ["employee"] and me["must_change_password"] is False
    assert me["employee"]["department_name"] == "新成员（自助注册）" and me["employee"]["status"] == "regular"
    assert "system" not in {m["key"] for m in me["menus"]}
    err(api.get("/api/users"), 403)  # registered users are ordinary employees, never administrators
    # can operate: punch and apply for leave (no manager yet -> falls back to the super administrator)
    ok(api.post("/api/attendance/punch", json={}))
    lt = next(t for t in ok(api.get("/api/leave/types")) if t["code"] == "annual")["id"]
    lv = ok(api.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "第一次请假"}), 201)
    assert ok(api.get(f"/api/workflow/instances/{lv['instance_id']}"))["current_assignees"] == ["平泽忧"]
    assert sql("SELECT count(*) FROM departments WHERE code='NEWBIE'")[0][0] == 1
    ok(client.post("/api/auth/register", json={"username": "jun_suzuki", "password": "Bass2026x"}), 201)
    assert sql("SELECT count(*) FROM departments WHERE code='NEWBIE'")[0][0] == 1  # created once
    assert sql("SELECT count(*) FROM audit_logs WHERE action='register'")[0][0] == 2


@pytest.mark.parametrize("body,code", [
    ({"username": "ab", "password": "Cake2026x"}, "VALIDATION_ERROR"),
    ({"username": "bad name", "password": "Cake2026x"}, "VALIDATION_ERROR"),
    ({"username": "admin", "password": "Cake2026x"}, "USERNAME_RESERVED"),
    ({"username": "newbie1", "password": "short1"}, "WEAK_PASSWORD"),
    ({"username": "newbie1", "password": "onlyletters"}, "WEAK_PASSWORD"),
    ({"username": "newbie1a", "password": "NEWBIE1A"}, "WEAK_PASSWORD"),
    ({"username": "newbie1"}, "VALIDATION_ERROR"),
])
def test_register_validation(client, body, code):
    err(client.post("/api/auth/register", json=body), 422, code)


def test_register_rate_limit_and_switch(app, client):
    app.state.settings.register_limit_per_hour = 2
    for i in range(2):
        ok(client.post("/api/auth/register", json={"username": f"fan{i}", "password": "Tea2026xx"}), 201)
    err(client.post("/api/auth/register", json={"username": "fan9", "password": "Tea2026xx"}), 429,
        "TOO_MANY_REGISTRATIONS")
    app.state.settings.allow_registration = False
    err(client.post("/api/auth/register", json={"username": "fan8", "password": "Tea2026xx"}), 403,
        "REGISTRATION_CLOSED")
    assert ok(client.get("/api/public/overview"))["registration_open"] is False


def test_expired_token_is_not_treated_as_visitor(client):
    bad = Api(client, "forged-token")
    err(bad.get("/api/announcements"), 401, "SESSION_EXPIRED")
