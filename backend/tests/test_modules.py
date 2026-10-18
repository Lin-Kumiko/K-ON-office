"""Organisation, employees and the remaining OA/HRM modules through the real API."""
import io

from tests.conftest import err, ok


def _dept(api, code):
    return next(d for d in ok(api.get("/api/departments")) if d["code"] == code)


def _task(api, instance_id):
    return next(t for t in ok(api.get("/api/workflow/tasks"))["items"] if t["instance_id"] == instance_id)


def _emp_body(e):
    return {k: e[k] for k in ("version", "name", "gender", "birth_date", "phone", "email", "department_id",
                              "position_id", "manager_id", "remark")}


# ------------------------------------------------------------------ org
def test_department_tree_and_changes(as_user):
    admin = as_user("ui")
    tree = ok(admin.get("/api/departments/tree"))
    assert len(tree) == 1 and tree[0]["code"] == "HTT"
    music = next(c for c in tree[0]["children"] if c["code"] == "MUSIC")
    assert [c["code"] for c in music["children"]] == ["LIVE"]
    d = ok(admin.post("/api/departments", json={"name": "宣传组", "code": "PR", "parent_id": music["id"]}), 201)
    err(admin.post("/api/departments", json={"name": "dup", "code": "PR"}), 409)
    # moving MUSIC under its own child is a cycle
    err(admin.put(f"/api/departments/{music['id']}", json={"name": "音乐制作部", "parent_id": d["id"]}), 422,
        "DEPARTMENT_CYCLE")
    ok(admin.put(f"/api/departments/{d['id']}", json={"name": "宣传组", "parent_id": tree[0]["id"]}))
    logs = ok(admin.get(f"/api/departments/{d['id']}/logs"))
    assert [log["action"] for log in logs] == ["move", "create"]
    ok(admin.post(f"/api/departments/{d['id']}/disable"))
    err(admin.post(f"/api/departments/{music['id']}/disable"), 409, "DEPARTMENT_NOT_EMPTY")
    members = ok(admin.get(f"/api/departments/{music['id']}/members?include_children=true"))
    assert {m["name"] for m in members} == {"秋山澪", "平泽唯", "中野梓", "若王子苺"}


def test_employee_create_update_optimistic_lock_and_resign(as_user, sql):
    hr, admin = as_user("nodoka"), as_user("ui")
    costume = _dept(hr, "COSTUME")
    sawako_id = next(e for e in ok(hr.get("/api/employees/options")) if e["name"] == "山中佐和子")["id"]
    e = ok(hr.post("/api/employees", json={
        "name": "早乙女纯子", "gender": "女", "email": "junko@htt.example", "phone": "13700000000",
        "department_id": costume["id"], "manager_id": sawako_id, "hire_date": "2026-10-19", "probation_months": 2,
        "create_account": True, "username": "junko", "password": "Sewing2026"}), 201)
    assert e["employee_no"] == "HTT0014" and e["status"] == "probation" and e["probation_end_date"] == "2026-12-19"
    err(hr.post("/api/employees", json={"name": "x", "email": "junko@htt.example", "department_id": costume["id"],
                                        "hire_date": "2026-10-19"}), 409, "EMAIL_EXISTS")
    body = _emp_body(e)
    body["remark"] = "擅长缝纫"
    updated = ok(hr.put(f"/api/employees/{e['id']}", json=body))
    assert updated["version"] == e["version"] + 1
    err(hr.put(f"/api/employees/{e['id']}", json=body), 409, "VERSION_CONFLICT")  # stale version
    # manager cycle: sawako cannot report to her own report
    sawako = ok(hr.get(f"/api/employees/{sawako_id}"))
    sb = _emp_body(sawako)
    sb["manager_id"] = e["id"]
    err(hr.put(f"/api/employees/{sawako_id}", json=sb), 422, "MANAGER_CYCLE")
    # resign: account disabled, sessions revoked, history written
    ok(hr.post(f"/api/employees/{e['id']}/resign", json={"resign_date": "2026-10-31", "reason": "回老家开裁缝店"}))
    row = sql("SELECT u.status FROM users u JOIN employees e ON e.user_id=u.id WHERE e.id=?", id=e["id"])
    assert row[0][0] == "disabled"
    hist = ok(hr.get(f"/api/employees/{e['id']}/history"))
    assert [h["change_type"] for h in hist] == ["onboard", "resign"]
    err(hr.post(f"/api/employees/{e['id']}/resign", json={"resign_date": "2026-10-31", "reason": "x"}), 409)
    assert "早乙女纯子" not in {o["name"] for o in ok(hr.get("/api/employees/options"))}
    assert ok(admin.get("/api/employees?status=resigned"))["total"] == 1


def test_resigning_manager_moves_reports_and_tasks(as_user, sql):
    hr = as_user("nodoka")
    yui = as_user("yui")
    lt = next(t for t in ok(yui.get("/api/leave/types")) if t["code"] == "annual")["id"]
    azusa = as_user("azusa")
    lv = ok(azusa.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "x"}), 201)
    assert ok(azusa.get(f"/api/workflow/instances/{lv['instance_id']}"))["current_assignees"] == ["平泽唯"]
    yui_emp = ok(yui.get("/api/auth/me"))["employee"]["id"]
    ok(hr.post(f"/api/employees/{yui_emp}/resign", json={"resign_date": "2026-10-19", "reason": "去读大学"}))
    # pending task moved to yui's manager (mio); azusa now reports to mio; LIVE has no manager
    detail = ok(azusa.get(f"/api/workflow/instances/{lv['instance_id']}"))
    assert detail["current_assignees"] == ["秋山澪"]
    azusa_emp = ok(azusa.get("/api/auth/me"))["employee"]
    assert ok(hr.get(f"/api/employees/{azusa_emp['id']}"))["manager_name"] == "秋山澪"
    assert _dept(hr, "LIVE")["manager_employee_id"] is None


def test_positions(as_user):
    admin = as_user("ui")
    p = ok(admin.post("/api/positions", json={"name": "鼓手", "code": "DRUM", "level": 4}), 201)
    err(admin.post("/api/positions", json={"name": "鼓手2", "code": "DRUM"}), 409)
    ok(admin.put(f"/api/positions/{p['id']}", json={"name": "鼓手（兼社长）", "code": "DRUM", "level": 5}))
    assert any(x["name"] == "鼓手（兼社长）" for x in ok(admin.get("/api/positions")))


# ------------------------------------------------------------------ travel
def test_travel_change_and_cancel(as_user, sql):
    yui, mio = as_user("yui"), as_user("mio")
    t = ok(yui.post("/api/travel?submit=true", json={"destination": "伦敦", "start_date": "2026-11-16",
                                                    "end_date": "2026-11-19", "purpose": "毕业旅行演出",
                                                    "estimated_cost": "12000.50", "transport": "飞机"}), 201)
    assert t["days"] == 4 and t["estimated_cost"] == "12000.50"
    err(yui.post("/api/travel?submit=true", json={"destination": "x", "start_date": "2026-11-18",
                                                 "end_date": "2026-11-20", "purpose": "p"}), 409, "TRAVEL_OVERLAP")
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, t['instance_id'])['id']}/approve", json={}))
    change = ok(yui.post(f"/api/travel/{t['id']}/change", json={"destination": "伦敦", "start_date": "2026-11-16",
                                                               "end_date": "2026-11-20", "purpose": "加演一场"}), 201)
    assert change["original_id"] == t["id"] and change["status"] == "pending"
    err(yui.post(f"/api/travel/{t['id']}/change", json={"destination": "x", "start_date": "2026-11-16",
                                                       "end_date": "2026-11-17", "purpose": "p"}), 409)
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, change['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/travel/{t['id']}"))["status"] == "changed"
    assert ok(yui.get(f"/api/travel/{change['id']}"))["status"] == "approved"
    # attendance shows travel days
    recs = sql("SELECT status FROM attendance_records WHERE work_date BETWEEN '2026-11-16' AND '2026-11-20' "
               "AND employee_id=(SELECT id FROM employees WHERE employee_no='HTT0003')")
    assert [r[0] for r in recs] == ["travel"] * 5
    ok(yui.post(f"/api/travel/{change['id']}/cancel", json={"reason": "签证没下来"}))
    assert ok(yui.get(f"/api/travel/{change['id']}"))["status"] == "cancelled"
    assert sql("SELECT count(*) FROM attendance_records WHERE work_date BETWEEN '2026-11-16' AND '2026-11-20' "
               "AND employee_id=(SELECT id FROM employees WHERE employee_no='HTT0003')")[0][0] == 0
    hist = ok(yui.get("/api/travel?page_size=50"))
    assert hist["total"] == 2


# ------------------------------------------------------------------ announcements / notifications / schedules
def test_announcement_scope_read_and_notifications(as_user):
    hr, yui, mika = as_user("nodoka"), as_user("yui"), as_user("mika")
    cat = ok(hr.get("/api/announcements/categories"))[0]
    music = _dept(hr, "MUSIC")
    a = ok(hr.post("/api/announcements", json={"title": "学园祭排练安排", "content": "每天放学后在音乐准备室排练",
                                               "category_id": cat["id"], "scope_type": "departments",
                                               "scope_department_ids": [music["id"]], "pinned": True}), 201)
    assert a["status"] == "draft"
    err(yui.get(f"/api/announcements/{a['id']}"), 404)  # drafts invisible
    ok(hr.post(f"/api/announcements/{a['id']}/publish"))
    err(hr.post(f"/api/announcements/{a['id']}/publish"), 409)
    # yui is in LIVE (child of MUSIC) -> visible; mika (COSTUME) -> not
    assert [x["title"] for x in ok(yui.get("/api/announcements"))["items"]] == ["学园祭排练安排"]
    assert ok(mika.get("/api/announcements"))["total"] == 0
    err(mika.get(f"/api/announcements/{a['id']}"), 404)
    notes = ok(yui.get("/api/notifications?unread_only=true"))["items"]
    assert any(n["ref_type"] == "announcement" and n["ref_id"] == a["id"] for n in notes)
    ok(yui.post(f"/api/announcements/{a['id']}/read"))
    ok(yui.post(f"/api/announcements/{a['id']}/read"))  # idempotent
    assert ok(yui.get(f"/api/announcements/{a['id']}"))["read"] is True
    stats = ok(hr.get(f"/api/announcements/{a['id']}/reads"))
    assert stats["target"] == 4 and stats["read"] == 1 and "秋山澪" in stats["unread_names"]
    err(hr.put(f"/api/announcements/{a['id']}", json={"title": "x", "content": "y"}), 409)
    ok(hr.post(f"/api/announcements/{a['id']}/withdraw"))
    assert ok(yui.get("/api/announcements"))["total"] == 0
    count = ok(yui.get("/api/notifications/unread-count"))["count"]
    ok(yui.post("/api/notifications/read-all"))
    assert ok(yui.get("/api/notifications/unread-count"))["count"] == 0 and count >= 0


def test_schedules(as_user):
    yui = as_user("yui")
    s = ok(yui.post("/api/schedules", json={"title": "买新吉他弦", "start_at": "2026-10-20T16:00:00",
                                            "end_at": "2026-10-20T17:00:00", "remind_at": "2026-10-20T15:30:00"}), 201)
    err(yui.post("/api/schedules", json={"title": "x", "start_at": "2026-10-20T16:00:00",
                                         "end_at": "2026-10-20T15:00:00"}), 422)
    assert len(ok(yui.get("/api/schedules?start=2026-10-20&end=2026-10-20"))) == 1
    err(as_user("mio").delete(f"/api/schedules/{s['id']}"), 404)
    ok(yui.delete(f"/api/schedules/{s['id']}"))


# ------------------------------------------------------------------ documents
def test_document_versions_permissions_and_history(as_user, client):
    mio, yui, mika = as_user("mio"), as_user("yui"), as_user("mika")
    cat = ok(mio.get("/api/documents/categories"))[0]
    files = {"file": ("ふわふわ編曲.txt", io.BytesIO("v1 编曲草稿".encode()), "text/plain")}
    d = ok(mio.post("/api/documents", files=files, data={"title": "新曲编曲稿", "visibility": "department",
                                                       "category_id": str(cat["id"]), "keywords": "编曲,新曲"}), 201)
    assert d["current_version"] == 1 and d["department_name"] == "音乐制作部"
    assert ok(yui.get("/api/documents?q=编曲"))["total"] == 1  # LIVE is under MUSIC
    assert ok(mika.get("/api/documents?q=编曲"))["total"] == 0
    err(mika.get(f"/api/documents/{d['id']}"), 404)
    err(yui.post(f"/api/documents/{d['id']}/versions", files={"file": ("x.txt", io.BytesIO(b"v"), "text/plain")}), 403)
    v2 = ok(mio.post(f"/api/documents/{d['id']}/versions",
                     files={"file": ("arr_v2.txt", io.BytesIO("v2 定稿".encode()), "text/plain")},
                     data={"note": "加了贝斯 solo"}), 201)
    assert v2["current_version"] == 2 and [v["version_no"] for v in v2["versions"]] == [2, 1]
    assert yui.get(f"/api/documents/{d['id']}/download").content == "v2 定稿".encode()
    assert yui.get(f"/api/documents/{d['id']}/download?version=1").content == "v1 编曲草稿".encode()
    ok(mio.put(f"/api/documents/{d['id']}", json={"title": "新曲编曲稿", "visibility": "public",
                                                 "category_id": cat["id"]}))
    assert ok(mika.get("/api/documents?q=编曲"))["total"] == 1
    logs = [log["action"] for log in ok(mio.get(f"/api/documents/{d['id']}/logs"))]
    assert logs[:4] == ["permission", "download", "download", "upload"] and logs[-1] == "create"
    err(yui.get(f"/api/documents/{d['id']}/logs"), 403)
    ok(mio.delete(f"/api/documents/{d['id']}"))
    assert ok(mika.get("/api/documents?q=编曲"))["total"] == 0


# ------------------------------------------------------------------ performance
def test_performance_cycle_flow_and_stats(as_user):
    hr, yui, azusa = as_user("nodoka"), as_user("yui"), as_user("azusa")
    err(hr.post("/api/performance/cycles", json={"name": "bad", "start_date": "2026-10-01", "end_date": "2026-12-31",
                                                 "indicators": [{"name": "a", "weight": 50}]}), 422, "INVALID_WEIGHTS")
    c = ok(hr.post("/api/performance/cycles", json={
        "name": "2026 下半年", "start_date": "2026-07-01", "end_date": "2026-12-31",
        "indicators": [{"name": "演奏技术", "weight": 50}, {"name": "团队协作", "weight": 30},
                       {"name": "茶话会参与", "weight": 20}]}), 201)
    ok(hr.post(f"/api/performance/cycles/{c['id']}/activate"))
    assert ok(hr.get("/api/performance/cycles"))[0]["review_total"] == 13
    mine = ok(azusa.get("/api/performance/reviews"))["items"][0]
    ind = [str(i["id"]) for i in mine["indicators"]]
    err(yui.post(f"/api/performance/reviews/{mine['id']}/manager",
                 json={"scores": dict.fromkeys(ind, 90), "comment": "x"}), 409, "INVALID_STATE")
    err(azusa.post(f"/api/performance/reviews/{mine['id']}/self", json={"scores": {ind[0]: 90}, "comment": "x"}),
        422, "INCOMPLETE_SCORES")
    ok(azusa.post(f"/api/performance/reviews/{mine['id']}/self",
                  json={"scores": {ind[0]: 90, ind[1]: 80, ind[2]: 70}, "comment": "认真练习"}))
    err(as_user("mika").post(f"/api/performance/reviews/{mine['id']}/manager",
                             json={"scores": dict.fromkeys(ind, 90), "comment": "x"}), 403, "NOT_REVIEWER")
    team = ok(yui.get("/api/performance/reviews?scope=team"))["items"]
    assert {r["employee_name"] for r in team} == {"中野梓", "若王子苺"}
    r = ok(yui.post(f"/api/performance/reviews/{mine['id']}/manager",
                    json={"scores": {ind[0]: 95, ind[1]: 90, ind[2]: 100}, "comment": "小梓最棒"}))
    # self = 90*.5+80*.3+70*.2 = 83 ; mgr = 95*.5+90*.3+100*.2 = 94.5 ; final = 83*.3 + 94.5*.7 = 91.05
    assert r["final_score"] == 91.05 and r["grade"] == "A" and r["status"] == "confirm_pending"
    ok(hr.post(f"/api/performance/reviews/{mine['id']}/confirm", json={"action": "confirm"}))
    err(hr.post(f"/api/performance/cycles/{c['id']}/close"), 409, "REVIEWS_PENDING")
    stats = ok(hr.get(f"/api/performance/stats?cycle_id={c['id']}"))
    assert stats["by_grade"] == {"A": 1} and stats["by_status"]["confirmed"] == 1


# ------------------------------------------------------------------ payroll
def test_payroll_calculation_history_and_confirm(as_user, sql):
    hr, azusa = as_user("nodoka"), as_user("azusa")
    # azusa: one absent workday in Sep 2026 is not possible (hired Aug), use October with punches/absence
    run = ok(hr.post("/api/payroll/runs", json={"month": "2026-09"}), 201)
    err(hr.post("/api/payroll/runs", json={"month": "2026-09"}), 409)
    err(hr.post(f"/api/payroll/runs/{run['id']}/confirm"), 409)  # must calculate first
    azusa_emp = ok(azusa.get("/api/auth/me"))["employee"]["id"]
    ok(hr.post(f"/api/payroll/runs/{run['id']}/adjustments", json={"employee_id": azusa_emp, "kind": "bonus",
                                                                    "amount": "500.00", "reason": "学园祭演出奖金"}), 201)
    calc = ok(hr.post(f"/api/payroll/runs/{run['id']}/calculate"))
    assert calc["status"] == "calculated" and calc["calc_version"] == 1 and calc["payslip_count"] == 13
    slips = {s["employee_name"]: s for s in ok(hr.get(f"/api/payroll/runs/{run['id']}/payslips"))}
    a = slips["中野梓"]
    # no punches recorded for September in seed data -> every workday is absent: deductions capped by gross
    assert a["bonus"] == "500.00" and a["detail"]["absent_days"] > 0
    from decimal import Decimal
    for s in slips.values():
        assert Decimal(s["net"]) == Decimal(s["gross"]) - Decimal(s["social_insurance"]) - Decimal(s["tax"])
        assert Decimal(s["net"]) >= 0
    # recalculation keeps history
    ok(hr.post(f"/api/payroll/runs/{run['id']}/calculate"))
    hist = ok(hr.get(f"/api/payroll/runs/{run['id']}/history?employee_id={azusa_emp}"))
    assert [h["calc_version"] for h in hist] == [2, 1] and [h["is_current"] for h in hist] == [True, False]
    assert ok(azusa.get("/api/payroll/my-payslips")) == []  # not visible before confirmation
    ok(hr.post(f"/api/payroll/runs/{run['id']}/confirm"))
    err(hr.post(f"/api/payroll/runs/{run['id']}/calculate"), 409, "RUN_CONFIRMED")
    mine = ok(azusa.get("/api/payroll/my-payslips"))
    assert len(mine) == 1 and mine[0]["month"] == "2026-09"
    err(azusa.get(f"/api/payroll/runs/{run['id']}/payslips"), 403)


def test_simulated_tax_table():
    from app.api.hr_perf_pay import simulated_tax
    assert simulated_tax(0) == 0
    assert simulated_tax(300000) == 9000          # 3000 * 3%
    assert simulated_tax(1000000) == 79000        # 10000 * 10% - 210
    assert simulated_tax(-5) == 0


# ------------------------------------------------------------------ dashboard / reports
def test_dashboard_and_reports(as_user):
    yui, mio, ritsu = as_user("yui"), as_user("mio"), as_user("ritsu")
    lt = next(t for t in ok(yui.get("/api/leave/types")) if t["code"] == "annual")["id"]
    ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
        "end_half": "PM", "reason": "x"}), 201)
    dash = ok(mio.get("/api/dashboard/summary"))
    assert dash["stats"]["pending_tasks"] == 1 and dash["todo"][0]["business_type"] == "leave"
    assert dash["company_view"] is True and dash["stats"]["headcount"] == 4
    mine = ok(yui.get("/api/dashboard/summary"))
    assert mine["my_applications"][0]["status"] == "running" and mine["annual_leave"]["pending_hours"] == 8
    assert {q["key"] for q in mine["quick_entries"]} >= {"leave", "expense", "attendance"}
    rep = ok(ritsu.get("/api/reports/overview?month=2026-10"))
    assert rep["scope"] == "all" and sum(rep["headcount_by_department"].values()) == 13
    assert rep["workflow_status"] == {"running": 1}
    mrep = ok(mio.get("/api/reports/overview"))
    assert mrep["scope"] == "department" and sum(mrep["headcount_by_department"].values()) == 4
    err(as_user("azusa").get("/api/reports/overview"), 403)


def test_settings_and_holidays(as_user):
    admin, hr = as_user("ui"), as_user("nodoka")
    ok(admin.put("/api/settings", json={"values": {"company.slogan": "先喝茶，再加油"}}))
    assert any(s["value"] == "先喝茶，再加油" for s in ok(hr.get("/api/settings")))
    err(admin.put("/api/settings", json={"values": {"evil": 1}}), 422)
    err(hr.put("/api/settings", json={"values": {"company.slogan": "x"}}), 403)
    h = ok(hr.post("/api/holidays", json={"day": "2026-12-25", "name": "圣诞茶会", "kind": "holiday"}), 201)
    err(hr.post("/api/holidays", json={"day": "2026-12-25", "name": "dup"}), 409)
    calc = ok(hr.post("/api/leave/calculate", json={"start_date": "2026-12-24", "start_half": "AM",
                                                    "end_date": "2026-12-25", "end_half": "PM"}))
    assert calc["hours"] == 8
    ok(hr.delete(f"/api/holidays/{h['id']}"))
