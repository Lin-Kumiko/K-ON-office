"""Single-endpoint checks for maintenance APIs: success path, validation, permission and DB effect."""
import io

from app.workflow.graph import validate_graph
from tests.conftest import err, ok


def _task(api, instance_id):
    return next(t for t in ok(api.get("/api/workflow/tasks"))["items"] if t["instance_id"] == instance_id)


# ------------------------------------------------------------------ attendance maintenance
def test_attendance_rules_and_team_views(as_user, sql):
    hr, yui = as_user("nodoka"), as_user("yui")
    body = {"name": "早班", "work_start": "07:00", "work_end": "16:00", "break_start": "11:00", "break_end": "12:00",
            "cross_day": False, "late_grace_minutes": 0, "early_grace_minutes": 0, "window_before_minutes": 120,
            "window_after_minutes": 240, "is_default": False}
    r = ok(hr.post("/api/attendance/rules", json=body), 201)
    err(hr.post("/api/attendance/rules", json=body), 409, "RULE_EXISTS")
    err(hr.post("/api/attendance/rules", json={**body, "name": "坏", "work_end": "06:00"}), 422, "INVALID_RULE")
    err(yui.post("/api/attendance/rules", json={**body, "name": "x"}), 403)
    ok(hr.put(f"/api/attendance/rules/{r['id']}", json={**body, "is_default": True}))
    assert sql("SELECT count(*) FROM attendance_rules WHERE is_default=1")[0][0] == 1
    err(hr.put(f"/api/attendance/rules/{r['id']}", json={**body, "is_default": False}), 422, "DEFAULT_RULE_REQUIRED")
    ok(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-14T06:55:00"}))
    assert ok(yui.get("/api/attendance/punches?start=2026-10-14&end=2026-10-14"))[0]["source"] == "simulated"
    team = ok(yui.get("/api/attendance/team?day=2026-10-14"))
    assert [t["employee_name"] for t in team] == ["平泽唯"]
    ok(hr.post("/api/attendance/rebuild", json={"start": "2026-10-12", "end": "2026-10-16"}))
    assert sql("SELECT count(*) FROM attendance_records WHERE work_date BETWEEN '2026-10-12' AND '2026-10-16'")[0][0] == 65
    err(hr.post("/api/attendance/rebuild", json={"start": "2026-01-01", "end": "2026-10-16"}), 422, "INVALID_RANGE")
    err(yui.get("/api/attendance/records?start=2026-10-16&end=2026-10-01"), 422, "INVALID_RANGE")


def test_correction_and_overtime_withdraw_resubmit(as_user):
    yui, mio = as_user("yui"), as_user("mio")
    c = ok(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-15", "kind": "in",
                                                         "corrected_time": "2026-10-15T09:00:00", "reason": "忘带工牌"}), 201)
    ok(yui.post(f"/api/attendance/corrections/{c['id']}/withdraw"))
    err(as_user("azusa").post(f"/api/attendance/corrections/{c['id']}/withdraw"), 403, "NOT_OWNER")
    again = ok(yui.post(f"/api/attendance/corrections/{c['id']}/resubmit", json={
        "work_date": "2026-10-15", "kind": "in", "corrected_time": "2026-10-15T08:58:00", "reason": "补充说明"}))
    assert again["status"] == "pending" and again["corrected_time"] == "2026-10-15T08:58:00"
    assert ok(mio.get("/api/attendance/corrections?scope=all"))["total"] == 1
    err(as_user("mika").get("/api/attendance/corrections?scope=all"), 403)
    o = ok(yui.post("/api/attendance/overtime", json={"start_at": "2026-10-18T10:00:00", "end_at": "2026-10-18T12:00:00",
                                                     "reason": "排练", "compensation": "pay"}), 201)
    err(yui.post("/api/attendance/overtime", json={"start_at": "2026-10-18T10:00:00", "end_at": "2026-10-18T10:20:00",
                                                  "reason": "x"}), 422, "INVALID_OVERTIME_HOURS")
    ok(yui.post(f"/api/attendance/overtime/{o['id']}/withdraw"))
    o2 = ok(yui.post(f"/api/attendance/overtime/{o['id']}/resubmit", json={
        "start_at": "2026-10-18T10:00:00", "end_at": "2026-10-18T13:00:00", "reason": "排练延长", "compensation": "pay"}))
    assert o2["hours"] == 3 and o2["status"] == "pending"
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, o2['instance_id'])['id']}/approve", json={}))
    comp = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "comp")
    assert comp["total_hours"] == 0  # pay compensation does not credit comp leave


# ------------------------------------------------------------------ recruitment maintenance
def test_requisition_candidate_maintenance(as_user, sql):
    hr = as_user("nodoka")
    music = next(d for d in ok(hr.get("/api/departments")) if d["code"] == "MUSIC")
    r = ok(hr.post("/api/recruitment/requisitions", json={"title": "贝斯手", "department_id": music["id"], "headcount": 2}), 201)
    ok(hr.put(f"/api/recruitment/requisitions/{r['id']}", json={"title": "贝斯手（爵士）", "department_id": music["id"],
                                                              "headcount": 1}))
    c = ok(hr.post("/api/recruitment/candidates", json={"requisition_id": r["id"], "name": "铃木纯", "email": "jun@x.example"}), 201)
    err(hr.post("/api/recruitment/candidates", json={"name": "铃木纯2", "email": "JUN@x.example"}), 409, "CANDIDATE_EXISTS")
    ok(hr.put(f"/api/recruitment/candidates/{c['id']}", json={"requisition_id": r["id"], "name": "铃木纯", "email": "jun@x.example",
                                                             "source": "爵士研究会"}))
    ok(hr.post(f"/api/recruitment/requisitions/{r['id']}/status", json={"status": "closed"}))
    err(hr.post("/api/recruitment/candidates", json={"requisition_id": r["id"], "name": "x"}), 422, "REQUISITION_CLOSED")
    ok(hr.post(f"/api/recruitment/candidates/{c['id']}/reject"))
    err(hr.post(f"/api/recruitment/candidates/{c['id']}/interviews", json={"interviewer_id": 1,
                                                                            "scheduled_at": "2026-10-20T10:00:00"}), 409)
    assert ok(hr.get("/api/recruitment/requisitions?status=closed"))["total"] == 1
    assert ok(as_user("mugi").get("/api/recruitment/interviews")) == []  # interviewer sees only own interviews
    err(as_user("mugi").get("/api/recruitment/candidates"), 403)
    f = ok(hr.post("/api/files", files={"file": ("cv.pdf", io.BytesIO(b"%PDF-1.4 cv"), "application/pdf")},
                   data={"purpose": "resume"}), 201)
    c2 = ok(hr.post("/api/recruitment/candidates", json={"name": "梓的同学", "resume_file_id": f["id"]}), 201)
    assert c2["resume_file_id"] == f["id"]
    err(as_user("yui").get(f"/api/files/{f['id']}"), 403)


def test_onboarding_update_withdraw_and_cancel_by_other_hr(as_user, sql):
    hr, himeko = as_user("nodoka"), as_user("himeko")
    tea = next(d for d in ok(hr.get("/api/departments")) if d["code"] == "TEA")
    body = {"name": "斋藤菫", "email": "sumire@htt.example", "department_id": tea["id"], "hire_date": "2026-11-02",
            "probation_months": 3, "create_account": False}
    o = ok(hr.post("/api/onboarding", json=body), 201)
    ok(hr.put(f"/api/onboarding/{o['id']}", json={**body, "probation_months": 2}))
    o = ok(hr.post(f"/api/onboarding/{o['id']}/submit"))
    err(hr.put(f"/api/onboarding/{o['id']}", json=body), 409)
    ok(hr.post(f"/api/onboarding/{o['id']}/withdraw"))
    assert ok(hr.get(f"/api/onboarding/{o['id']}"))["status"] == "withdrawn"
    o = ok(hr.post(f"/api/onboarding/{o['id']}/submit"))
    ok(himeko.post(f"/api/onboarding/{o['id']}/withdraw"))  # not the initiator: cancels (terminal)
    assert ok(hr.get(f"/api/onboarding/{o['id']}"))["status"] == "cancelled"
    err(hr.post(f"/api/onboarding/{o['id']}/submit"), 409)
    assert sql("SELECT count(*) FROM employees WHERE email='sumire@htt.example'")[0][0] == 0


# ------------------------------------------------------------------ meeting rooms / schedules
def test_room_maintenance_and_booking_rules(as_user):
    mugi, yui, mio = as_user("mugi"), as_user("yui"), as_user("mio")
    room = ok(mugi.post("/api/meeting/rooms", json={"name": "屋顶", "capacity": 2, "open_from": "09:00",
                                                   "open_to": "18:00"}), 201)
    err(mugi.post("/api/meeting/rooms", json={"name": "屋顶", "capacity": 2}), 409, "ROOM_EXISTS")
    err(yui.post("/api/meeting/rooms", json={"name": "x", "capacity": 2}), 403)
    base = {"room_id": room["id"], "subject": "合奏", "start_at": "2026-10-21T10:00:00", "end_at": "2026-10-21T11:00:00"}
    err(yui.post("/api/meeting/bookings", json={**base, "start_at": "2026-10-21T08:00:00"}), 422, "OUT_OF_OPEN_HOURS")
    err(yui.post("/api/meeting/bookings", json={**base, "start_at": "2026-10-18T10:00:00", "end_at": "2026-10-18T11:00:00"}),
        422, "PAST_BOOKING")
    err(yui.post("/api/meeting/bookings", json={**base, "end_at": "2026-10-22T11:00:00"}), 422, "CROSS_DAY_BOOKING")
    mio_id = ok(mio.get("/api/auth/me"))["id"]
    mugi_id = ok(mugi.get("/api/auth/me"))["id"]
    err(yui.post("/api/meeting/bookings", json={**base, "attendee_ids": [mio_id, mugi_id]}), 422, "OVER_CAPACITY")
    b = ok(yui.post("/api/meeting/bookings", json={**base, "attendee_ids": [mio_id]}), 201)
    assert any(n["ref_id"] == b["id"] for n in ok(mio.get("/api/notifications"))["items"])
    err(mio.post(f"/api/meeting/bookings/{b['id']}/cancel"), 403, "NOT_OWNER")
    err(yui.get("/api/meeting/bookings?scope=all"), 403)
    ok(mugi.get("/api/meeting/bookings?scope=all"))
    ok(mugi.put(f"/api/meeting/rooms/{room['id']}", json={"name": "屋顶", "capacity": 2, "open_from": "09:00",
                                                          "open_to": "18:00", "status": "disabled"}))
    err(yui.post("/api/meeting/bookings", json={**base, "start_at": "2026-10-22T10:00:00", "end_at": "2026-10-22T11:00:00"}),
        422, "ROOM_UNAVAILABLE")
    ok(yui.post(f"/api/meeting/bookings/{b['id']}/cancel"))
    err(yui.post(f"/api/meeting/bookings/{b['id']}/cancel"), 409)
    usage = ok(yui.get(f"/api/meeting/rooms/{room['id']}/usage?month=2026-10"))
    assert usage["bookings"] == 0
    # pending booking cancelled through the workflow
    hall = next(r for r in ok(yui.get("/api/meeting/rooms")) if r["name"] == "讲堂")
    p = ok(yui.post("/api/meeting/bookings", json={**base, "room_id": hall["id"]}), 201)
    ok(yui.post(f"/api/meeting/bookings/{p['id']}/cancel"))
    assert ok(yui.get(f"/api/workflow/instances/{p['instance_id']}"))["status"] == "cancelled"


def test_schedule_update_and_doc_category(as_user):
    yui = as_user("yui")
    s = ok(yui.post("/api/schedules", json={"title": "练琴", "start_at": "2026-10-20T19:00:00",
                                            "end_at": "2026-10-20T20:00:00"}), 201)
    upd = ok(yui.put(f"/api/schedules/{s['id']}", json={"title": "练琴（延长）", "start_at": "2026-10-20T19:00:00",
                                                       "end_at": "2026-10-20T21:00:00"}))
    assert upd["title"] == "练琴（延长）"
    err(yui.put(f"/api/schedules/{s['id']}", json={"title": "x", "start_at": "2026-10-20T19:00:00",
                                                  "end_at": "2026-10-20T20:00:00", "remind_at": "2026-10-20T19:30:00"}),
        422, "INVALID_REMIND_TIME")
    mugi = as_user("mugi")
    c = ok(mugi.post("/api/documents/categories", json={"name": "茶点食谱"}), 201)
    err(mugi.post("/api/documents/categories", json={"name": "茶点食谱"}), 409)
    err(yui.post("/api/documents/categories", json={"name": "x"}), 403)
    assert any(x["id"] == c["id"] for x in ok(yui.get("/api/documents/categories")))


# ------------------------------------------------------------------ travel / expense edits
def test_travel_and_expense_edit_paths(as_user):
    yui = as_user("yui")
    t = ok(yui.post("/api/travel", json={"destination": "京都", "start_date": "2026-11-10", "end_date": "2026-11-11",
                                         "purpose": "修学旅行"}), 201)
    ok(yui.put(f"/api/travel/{t['id']}", json={"destination": "京都", "start_date": "2026-11-10", "end_date": "2026-11-12",
                                               "purpose": "修学旅行"}))
    t = ok(yui.post(f"/api/travel/{t['id']}/submit"))
    ok(yui.post(f"/api/travel/{t['id']}/withdraw"))
    err(yui.post(f"/api/travel/{t['id']}/change", json={"destination": "x", "start_date": "2026-11-10",
                                                       "end_date": "2026-11-10", "purpose": "p"}), 409)
    err(yui.post("/api/travel", json={"destination": "x", "start_date": "2026-11-10", "end_date": "2026-11-09",
                                      "purpose": "p"}), 422, "INVALID_DATE_RANGE")
    cats = {c["code"]: c["id"] for c in ok(yui.get("/api/expense/categories"))}
    err(yui.post("/api/expense/claims", json={"title": "x", "items": [
        {"category_id": cats["tea"], "occurred_on": "2026-10-10", "amount": "2000.01"}]}), 422, "ITEM_OVER_LIMIT")
    err(yui.post("/api/expense/claims", json={"title": "x", "items": [
        {"category_id": cats["tea"], "occurred_on": "2026-10-10", "amount": "1.005"}]}), 422)
    err(yui.post("/api/expense/claims", json={"title": "x", "items": [
        {"category_id": cats["tea"], "occurred_on": "2026-12-10", "amount": "10"}]}), 422, "INVALID_DATE")
    mf = ok(as_user("mio").post("/api/files", files={"file": ("m.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
                                data={"purpose": "expense_receipt"}), 201)
    err(yui.post("/api/expense/claims", json={"title": "x", "items": [
        {"category_id": cats["tea"], "occurred_on": "2026-10-10", "amount": "10", "receipt_file_id": mf["id"]}]}),
        422, "INVALID_RECEIPT")
    c = ok(yui.post("/api/expense/claims?submit=true", json={"title": "茶叶", "items": [
        {"category_id": cats["tea"], "occurred_on": "2026-10-10", "amount": "10"}]}), 201)
    ok(yui.post(f"/api/expense/claims/{c['id']}/withdraw"))
    ok(yui.post(f"/api/expense/claims/{c['id']}/cancel"))
    assert ok(yui.get(f"/api/expense/claims/{c['id']}"))["status"] == "cancelled"
    err(as_user("mika").get(f"/api/expense/claims/{c['id']}"), 403)


# ------------------------------------------------------------------ admin catalogs
def test_leave_types_users_and_roles(as_user, sql):
    hr, admin = as_user("nodoka"), as_user("ui")
    t = ok(hr.post("/api/leave/types", json={"code": "study", "name": "学习假", "default_hours": 16}), 201)
    err(hr.post("/api/leave/types", json={"code": "study", "name": "dup"}), 409)
    err(hr.put(f"/api/leave/types/{t['id']}", json={"code": "other", "name": "x"}), 422, "IMMUTABLE_FIELD")
    ok(hr.put(f"/api/leave/types/{t['id']}", json={"code": "study", "name": "学习假（考证）", "default_hours": 24}))
    ok(hr.post("/api/leave/balances/grant-annual", json={"year": 2026}))
    assert sql("SELECT count(*) FROM leave_balances WHERE leave_type_id=?", id=t["id"])[0][0] == 13
    yui = as_user("yui")
    d = ok(yui.post("/api/leave/requests", json={"leave_type_id": t["id"], "start_date": "2026-11-02", "start_half": "AM",
                                                 "end_date": "2026-11-02", "end_half": "PM", "reason": "考证"}), 201)
    ok(yui.delete(f"/api/leave/requests/{d['id']}"))
    u = ok(admin.post("/api/users", json={"username": "tomo", "display_name": "外援", "password": "Guitar2026x",
                                          "role_codes": ["employee"]}), 201)
    err(admin.post("/api/users", json={"username": "TOMO", "display_name": "x"}), 409, "USERNAME_EXISTS")
    ok(admin.put(f"/api/users/{u['id']}", json={"display_name": "外援吉他手", "email": "tomo@x.example"}))
    assert ok(admin.get(f"/api/users/{u['id']}"))["display_name"] == "外援吉他手"
    role = next(r for r in ok(admin.get("/api/roles")) if r["code"] == "employee")
    err(admin.delete(f"/api/roles/{role['id']}"), 422, "ROLE_IMMUTABLE")
    custom = ok(admin.post("/api/roles", json={"code": "guest", "name": "访客", "permissions": ["dashboard:view"]}), 201)
    ok(admin.put(f"/api/users/{u['id']}/roles", json={"role_codes": ["guest"]}))
    err(admin.delete(f"/api/roles/{custom['id']}"), 409, "ROLE_IN_USE")
    err(admin.post("/api/roles", json={"code": "bad", "name": "x", "permissions": ["no:such"]}), 422, "PERMISSION_NOT_FOUND")
    assert len(ok(admin.get("/api/permissions"))) >= 30


def test_graph_validation_branches():
    vars_ = {"amount": "number", "department_id": "number"}
    base_nodes = [{"id": "s", "type": "start", "name": "开始"}, {"id": "e", "type": "end", "name": "结束"}]
    ok_amount = {"nodes": base_nodes + [{"id": "a", "type": "approval", "name": "按金额", "config": {"approver": {
        "type": "amount_based", "field": "amount", "rules": [
            {"max": 1000, "approver": {"type": "direct_manager"}},
            {"max": None, "approver": {"type": "role", "role_code": "hr"}}]}}}],
        "edges": [{"id": "e1", "source": "s", "target": "a"}, {"id": "e2", "source": "a", "target": "e"}]}
    assert validate_graph(ok_amount, vars_, {"hr"}, set()) == []
    bad = {**ok_amount, "nodes": base_nodes + [{"id": "a", "type": "approval", "name": "按金额", "config": {"approver": {
        "type": "amount_based", "rules": [{"max": 5000, "approver": {"type": "direct_manager"}},
                                          {"max": 1000, "approver": {"type": "direct_manager"}}]}}}]}
    errs = validate_graph(bad, vars_, {"hr"}, set())
    assert any("兜底" in e for e in errs) and any("递增" in e for e in errs)
    nested = {"nodes": base_nodes + [
        {"id": "p", "type": "parallel", "name": "外并行"}, {"id": "q", "type": "parallel", "name": "内并行"},
        {"id": "a1", "type": "approval", "name": "a1", "config": {"approver": {"type": "hr_admin"}}},
        {"id": "a2", "type": "approval", "name": "a2", "config": {"approver": {"type": "hr_admin"}}},
        {"id": "a3", "type": "approval", "name": "a3", "config": {"approver": {"type": "hr_admin"}}},
        {"id": "jq", "type": "join", "name": "内汇聚"}, {"id": "jp", "type": "join", "name": "外汇聚"}],
        "edges": [{"id": f"x{i}", "source": s, "target": t} for i, (s, t) in enumerate([
            ("s", "p"), ("p", "q"), ("p", "a3"), ("q", "a1"), ("q", "a2"), ("a1", "jq"), ("a2", "jq"), ("jq", "jp"),
            ("a3", "jp"), ("jp", "e")])]}
    assert validate_graph(nested, vars_, {"hr"}, set()) == []
    orphan_join = {"nodes": base_nodes + [{"id": "c", "type": "condition", "name": "判断"}, {"id": "j", "type": "join", "name": "汇聚"}],
                   "edges": [{"id": "e1", "source": "s", "target": "c"},
                             {"id": "e2", "source": "c", "target": "j", "condition": {"field": "amount", "op": ">", "value": 1}},
                             {"id": "e3", "source": "c", "target": "j", "default": True}, {"id": "e4", "source": "j", "target": "e"}]}
    assert any("没有对应的并行分支" in e or "重复连线" in e for e in validate_graph(orphan_join, vars_, set(), set()))
    deep = {"field": "amount", "op": ">", "value": 1}
    for _ in range(6):
        deep = {"all": [deep]}
    g = {"nodes": base_nodes + [{"id": "c", "type": "condition", "name": "深"}],
         "edges": [{"id": "e1", "source": "s", "target": "c"}, {"id": "e2", "source": "c", "target": "e", "condition": deep},
                   {"id": "e3", "source": "c", "target": "e", "default": True}]}
    assert validate_graph(g, vars_, set(), set())  # too deep and duplicate pair are both rejected
    assert validate_graph({"nodes": "x"}, vars_, set(), set()) == ["流程图必须包含 nodes 与 edges 数组"]
