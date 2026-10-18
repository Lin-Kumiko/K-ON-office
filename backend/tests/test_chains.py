"""Chains 2-5: onboarding, regularization, expense, meeting room — real API, IDs passed downstream,
final database state verified."""
import io

from tests.conftest import err, ok


def _task_for(api, instance_id):
    tasks = ok(api.get("/api/workflow/tasks"))["items"]
    match = [t for t in tasks if t["instance_id"] == instance_id]
    assert match, f"no pending task for instance {instance_id}"
    return match[0]


def _dept(api, code):
    return next(d for d in ok(api.get("/api/departments")) if d["code"] == code)


def test_onboarding_chain_creates_employee_account_and_todos(as_user, sql):
    hr = as_user("nodoka")
    tea = _dept(hr, "TEA")
    pos = next(p for p in ok(hr.get("/api/positions")) if p["code"] == "TEAS")
    # recruitment front half: requisition -> candidate -> interview -> offer (dept manager + HR and-sign)
    req = ok(hr.post("/api/recruitment/requisitions", json={
        "title": "茶点专员", "department_id": tea["id"], "position_id": pos["id"], "headcount": 1}), 201)
    cand = ok(hr.post("/api/recruitment/candidates", json={
        "requisition_id": req["id"], "name": "奥田直", "gender": "女", "email": "nao@htt.example",
        "phone": "13900000001", "source": "内推（梓的学妹）"}), 201)
    err(hr.post("/api/recruitment/offers", json={"candidate_id": cand["id"], "department_id": tea["id"],
                                                "salary": "9000.00", "hire_date": "2026-11-02"}), 409)
    mugi_uid = ok(as_user("mugi").get("/api/auth/me"))["id"]
    iv = ok(hr.post(f"/api/recruitment/candidates/{cand['id']}/interviews", json={
        "interviewer_id": mugi_uid, "scheduled_at": "2026-10-20T15:00:00", "round": 1}), 201)
    ok(as_user("mugi").post(f"/api/recruitment/interviews/{iv['id']}/result", json={
        "score": 95, "feedback": "做的点心很好吃，做事认真", "result": "pass"}))
    offer = ok(hr.post("/api/recruitment/offers", json={
        "candidate_id": cand["id"], "department_id": tea["id"], "position_id": pos["id"],
        "salary": "9000.00", "hire_date": "2026-11-02"}), 201)
    ok(as_user("mugi").post(f"/api/workflow/tasks/{_task_for(as_user('mugi'), offer['instance_id'])['id']}/approve",
                            json={"comment": "欢迎"}))
    # HR and-sign: both nodoka and himeko must approve
    ok(hr.post(f"/api/workflow/tasks/{_task_for(hr, offer['instance_id'])['id']}/approve", json={}))
    assert ok(hr.get(f"/api/workflow/instances/{offer['instance_id']}"))["status"] == "running"
    himeko = as_user("himeko")
    ok(himeko.post(f"/api/workflow/tasks/{_task_for(himeko, offer['instance_id'])['id']}/approve", json={}))
    assert ok(hr.get(f"/api/recruitment/candidates/{cand['id']}"))["status"] == "offered"

    # chain proper: HR login -> onboarding request -> workflow -> dept manager -> HR
    onb = ok(hr.post("/api/onboarding", json={
        "candidate_id": cand["id"], "name": "奥田直", "gender": "女", "email": "nao@htt.example",
        "phone": "13900000001", "department_id": tea["id"], "position_id": pos["id"], "hire_date": "2026-11-02",
        "probation_months": 3, "create_account": True, "username": "nao", "role_codes": ["employee"],
        "base_salary": "9000.00"}), 201)
    assert onb["status"] == "draft" and onb["employee_id"] is None
    onb = ok(hr.post(f"/api/onboarding/{onb['id']}/submit"))
    assert onb["status"] == "pending"
    # duplicate submission is rejected
    err(hr.post(f"/api/onboarding/{onb['id']}/submit"), 409)
    mugi = as_user("mugi")
    ok(mugi.post(f"/api/workflow/tasks/{_task_for(mugi, onb['instance_id'])['id']}/approve", json={"comment": "确认"}))
    assert sql("SELECT count(*) FROM employees WHERE email='nao@htt.example'")[0][0] == 0  # not before final approval
    t = _task_for(hr, onb["instance_id"])
    ok(hr.post(f"/api/workflow/tasks/{t['id']}/approve", json={"comment": "入职手续齐全"}))

    final = ok(hr.get(f"/api/onboarding/{onb['id']}"))
    assert final["status"] == "approved" and final["employee_id"] and final["user_id"]
    emp = ok(hr.get(f"/api/employees/{final['employee_id']}"))
    assert emp["name"] == "奥田直" and emp["department_id"] == tea["id"] and emp["status"] == "probation"
    assert emp["username"] == "nao" and emp["manager_name"] == "琴吹紬"
    roles = sql("SELECT r.code FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=?",
                id=final["user_id"])
    assert [r[0] for r in roles] == ["employee"]
    assert sql("SELECT must_change_password FROM users WHERE id=?", id=final["user_id"])[0][0] == 1
    tasks = sql("SELECT title, status FROM onboarding_tasks WHERE onboarding_id=?", id=onb["id"])
    assert len(tasks) == 4 and all(s == "todo" for _, s in tasks)
    assert sql("SELECT status, hired_count FROM job_requisitions WHERE id=?", id=req["id"])[0] == ("closed", 1)
    assert sql("SELECT status FROM candidates WHERE id=?", id=cand["id"])[0][0] == "hired"
    assert sql("SELECT count(*) FROM leave_balances WHERE employee_id=?", id=final["employee_id"])[0][0] >= 3
    assert sql("SELECT base_cents FROM salary_structures WHERE employee_id=?", id=final["employee_id"])[0][0] == 900000
    hist = ok(hr.get(f"/api/employees/{final['employee_id']}/history"))
    assert hist[0]["change_type"] == "onboard" and hist[0]["ref_type"] == "onboarding"
    # the new account can be activated by an admin reset and then must change password
    ok(as_user("ui").post(f"/api/users/{final['user_id']}/reset-password", json={"new_password": "UiTea2026x"}))
    from tests.conftest import login
    nao = login(hr.client, "nao", "UiTea2026x")
    err(nao.get("/api/leave/balances"), 403, "PASSWORD_CHANGE_REQUIRED")
    ok(nao.post("/api/auth/change-password", json={"old_password": "UiTea2026x", "new_password": "UiCake2026y"}))
    assert ok(nao.get("/api/auth/me"))["employee"]["name"] == "奥田直"


def test_onboarding_links_existing_account_without_duplicate(as_user, sql):
    admin, hr = as_user("ui"), as_user("nodoka")
    u = ok(admin.post("/api/users", json={"username": "jun", "display_name": "铃木纯", "email": "jun@htt.example",
                                          "role_codes": ["employee"]}), 201)
    music = _dept(hr, "MUSIC")
    onb = ok(hr.post("/api/onboarding?submit=true", json={
        "name": "铃木纯", "email": "jun@htt.example", "department_id": music["id"], "hire_date": "2026-11-02",
        "probation_months": 0, "create_account": True, "username": "jun"}), 201)
    mio = as_user("mio")
    ok(mio.post(f"/api/workflow/tasks/{_task_for(mio, onb['instance_id'])['id']}/approve", json={}))
    ok(hr.post(f"/api/workflow/tasks/{_task_for(hr, onb['instance_id'])['id']}/approve", json={}))
    final = ok(hr.get(f"/api/onboarding/{onb['id']}"))
    assert final["user_id"] == u["id"] and final["account_linked"] is True
    assert sql("SELECT count(*) FROM users WHERE username='jun'")[0][0] == 1
    assert ok(hr.get(f"/api/employees/{final['employee_id']}"))["status"] == "regular"


def test_regularization_chain(as_user, sql):
    hr = as_user("nodoka")
    probation = ok(hr.get("/api/regularization/probation-employees"))
    azusa = next(p for p in probation if p["name"] == "中野梓")
    reg = ok(as_user("azusa").post("/api/regularization?submit=true", json={
        "planned_date": "2026-11-01", "self_review": "三个月里认真练习，也学会了在社团里喝茶"}), 201)
    assert reg["status"] == "pending"
    yui = as_user("yui")  # azusa's direct manager evaluates
    t = _task_for(yui, reg["instance_id"])
    err(yui.post(f"/api/workflow/tasks/{t['id']}/approve", json={"comment": "ok"}), 422, "EVALUATION_REQUIRED")
    assert ok(yui.get(f"/api/workflow/instances/{reg['instance_id']}"))["status"] == "running"  # rolled back
    ok(yui.post(f"/api/workflow/tasks/{t['id']}/approve", json={
        "comment": "小梓很可靠", "form_data": {"score": 92, "evaluation": "技术扎实，带动大家认真练习"}}))
    t2 = _task_for(hr, reg["instance_id"])
    ok(hr.post(f"/api/workflow/tasks/{t2['id']}/approve", json={"comment": "同意转正",
                                                                "form_data": {"comment": "材料齐全"}}))
    final = ok(hr.get(f"/api/regularization/{reg['id']}"))
    assert final["status"] == "approved" and final["manager_score"] == 92 and final["hr_comment"] == "材料齐全"
    emp = ok(hr.get(f"/api/employees/{azusa['id']}"))
    assert emp["status"] == "regular" and emp["regularized_date"] == "2026-11-01"
    hist = ok(hr.get(f"/api/employees/{azusa['id']}/history"))
    assert hist[-1]["change_type"] == "regularize" and hist[-1]["from_status"] == "probation"
    assert hist[-1]["to_status"] == "regular"
    # a regular employee cannot apply again
    err(as_user("azusa").post("/api/regularization", json={"planned_date": "2026-12-01", "self_review": "x"}),
        409, "NOT_ON_PROBATION")


def test_expense_chain_amount_branches_and_finance(as_user, sql, client):
    yui = as_user("yui")
    cats = {c["code"]: c["id"] for c in ok(yui.get("/api/expense/categories"))}
    receipt = ok(yui.post("/api/files", files={"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 synthetic"),
                                                        "application/pdf")}, data={"purpose": "expense_receipt"}), 201)
    small = ok(yui.post("/api/expense/claims", json={"title": "吉太保养", "items": [
        {"category_id": cats["instrument"], "occurred_on": "2026-10-15", "amount": "1200.10",
         "description": "换弦与调音", "receipt_file_id": receipt["id"]},
        {"category_id": cats["tea"], "occurred_on": "2026-10-16", "amount": "88.80", "description": "蛋糕"}]}), 201)
    assert small["total"] == "1288.90" and small["status"] == "draft"
    small = ok(yui.post(f"/api/expense/claims/{small['id']}/submit"))
    mio = as_user("mio")
    ok(mio.post(f"/api/workflow/tasks/{_task_for(mio, small['instance_id'])['id']}/approve", json={}))
    inst = ok(mio.get(f"/api/workflow/instances/{small['instance_id']}"))
    assert inst["current_nodes"] == ["财务审核"]  # <= 5000 skips CEO
    fin = as_user("megumi")
    ok(fin.post(f"/api/workflow/tasks/{_task_for(fin, small['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/expense/claims/{small['id']}"))["status"] == "approved"
    # archive before finance confirm is illegal
    err(fin.post(f"/api/expense/claims/{small['id']}/archive"), 409, "INVALID_STATE")
    paid = ok(fin.post(f"/api/expense/claims/{small['id']}/finance-confirm", json={"note": "模拟付款"}))
    assert paid["status"] == "paid" and paid["payment_ref"].startswith("SIM-")
    err(fin.post(f"/api/expense/claims/{small['id']}/finance-confirm", json={}), 409, "INVALID_STATE")
    arch = ok(fin.post(f"/api/expense/claims/{small['id']}/archive"))
    assert arch["status"] == "archived"
    assert sql("SELECT total_cents, status FROM expense_claims WHERE id=?", id=small["id"])[0] == (128890, "archived")
    assert sql("SELECT sum(amount_cents) FROM expense_items WHERE claim_id=?", id=small["id"])[0][0] == 128890

    # big claim (> 5000) goes through CEO; a rejection returns it for modification
    big = ok(yui.post("/api/expense/claims?submit=true", json={"title": "学园祭音箱", "items": [
        {"category_id": cats["instrument"], "occurred_on": "2026-10-10", "amount": "6800.00"}]}), 201)
    ok(mio.post(f"/api/workflow/tasks/{_task_for(mio, big['instance_id'])['id']}/approve", json={}))
    ritsu = as_user("ritsu")
    assert ok(ritsu.get(f"/api/workflow/instances/{big['instance_id']}"))["current_nodes"] == ["社长审批（大额）"]
    ok(ritsu.post(f"/api/workflow/tasks/{_task_for(ritsu, big['instance_id'])['id']}/reject",
                  json={"comment": "先用旧音箱，下个月再买"}))
    assert ok(yui.get(f"/api/expense/claims/{big['id']}"))["status"] == "rejected"
    # cannot finance-confirm a rejected claim
    err(fin.post(f"/api/expense/claims/{big['id']}/finance-confirm", json={}), 409)
    ok(yui.put(f"/api/expense/claims/{big['id']}", json={"title": "学园祭音箱（租赁）", "items": [
        {"category_id": cats["instrument"], "occurred_on": "2026-10-10", "amount": "800.00"}]}))
    again = ok(yui.post(f"/api/expense/claims/{big['id']}/submit"))
    ok(mio.post(f"/api/workflow/tasks/{_task_for(mio, again['instance_id'])['id']}/approve", json={}))
    assert ok(mio.get(f"/api/workflow/instances/{again['instance_id']}"))["current_nodes"] == ["财务审核"]


def test_meeting_chain_conflict_and_approval(as_user, sql):
    yui, mio = as_user("yui"), as_user("mio")
    rooms = {r["name"]: r for r in ok(yui.get("/api/meeting/rooms"))}
    club = rooms["音乐准备室"]
    avail = ok(yui.get(f"/api/meeting/rooms/{club['id']}/availability?day=2026-10-21"))
    assert avail["busy"] == []
    b1 = ok(yui.post("/api/meeting/bookings", json={
        "room_id": club["id"], "subject": "新曲排练", "start_at": "2026-10-21T15:00:00",
        "end_at": "2026-10-21T17:00:00", "attendee_ids": []}), 201)
    assert b1["status"] == "approved"  # no approval needed
    err(mio.post("/api/meeting/bookings", json={"room_id": club["id"], "subject": "作词会",
                                                "start_at": "2026-10-21T16:30:00", "end_at": "2026-10-21T18:00:00"}),
        409, "BOOKING_CONFLICT")
    ok(mio.post("/api/meeting/bookings", json={"room_id": club["id"], "subject": "作词会",
                                               "start_at": "2026-10-21T17:00:00", "end_at": "2026-10-21T18:00:00"}),
       201)  # touching boundary is allowed
    # auditorium needs approval by admin_staff (mugi)
    hall = rooms["讲堂"]
    b2 = ok(yui.post("/api/meeting/bookings", json={"room_id": hall["id"], "subject": "学园祭彩排",
                                                    "start_at": "2026-10-23T14:00:00",
                                                    "end_at": "2026-10-23T16:00:00"}), 201)
    assert b2["status"] == "pending"
    # a pending booking already blocks the slot
    err(mio.post("/api/meeting/bookings", json={"room_id": hall["id"], "subject": "x",
                                                "start_at": "2026-10-23T15:00:00", "end_at": "2026-10-23T15:30:00"}),
        409, "BOOKING_CONFLICT")
    mugi = as_user("mugi")
    ok(mugi.post(f"/api/workflow/tasks/{_task_for(mugi, b2['instance_id'])['id']}/approve", json={}))
    cal = ok(yui.get("/api/meeting/calendar?start=2026-10-21&end=2026-10-23"))
    assert {(c["subject"], c["status"]) for c in cal} == {("新曲排练", "approved"), ("作词会", "approved"),
                                                         ("学园祭彩排", "approved")}
    assert sql("SELECT status FROM meeting_bookings WHERE id=?", id=b2["id"])[0][0] == "approved"
    # cancel frees the slot
    ok(yui.post(f"/api/meeting/bookings/{b1['id']}/cancel"))
    ok(mio.post("/api/meeting/bookings", json={"room_id": club["id"], "subject": "补位", "start_at": "2026-10-21T15:00:00",
                                               "end_at": "2026-10-21T16:00:00"}), 201)
    # the DB trigger rejects an overlapping insert even if the API check is bypassed
    import sqlite3
    import pytest
    path = sql.__closure__[0].cell_contents.state.db.url.replace("sqlite:///", "")
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="overlap"):
        con.execute("INSERT INTO meeting_bookings (room_id, organizer_id, subject, start_at, end_at, status, created_at,"
                    " updated_at) VALUES (?, 1, 'bypass', '2026-10-21 15:30:00.000000', '2026-10-21 15:45:00.000000',"
                    " 'approved', '2026-10-19 10:00:00', '2026-10-19 10:00:00')", (club["id"],))
    con.close()
