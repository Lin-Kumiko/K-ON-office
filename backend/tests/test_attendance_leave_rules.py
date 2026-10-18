"""Leave duration/balance rules and attendance calculation (date boundaries, cross-day shifts,
duplicate punches, time zones, holidays, leave conflicts)."""
from datetime import date, datetime

import pytest

from app.models import AttendanceRule
from app.services import attendance as att
from app.services import calendar
from tests.conftest import err, ok

DAY = AttendanceRule(work_start="09:00", work_end="18:00", break_start="12:00", break_end="13:00", cross_day=False,
                     late_grace_minutes=5, early_grace_minutes=0, window_before_minutes=240, window_after_minutes=360)
NIGHT = AttendanceRule(work_start="22:00", work_end="06:00", break_start="02:00", break_end="02:30", cross_day=True,
                       late_grace_minutes=5, early_grace_minutes=0, window_before_minutes=240, window_after_minutes=360)
NOW = datetime(2026, 10, 19, 10, 0)


def dt(s):
    return datetime.fromisoformat(s)


# ------------------------------------------------------------------ calendar / leave hours
HMAP = {date(2026, 10, 1): "holiday", date(2026, 10, 2): "holiday", date(2026, 10, 10): "workday"}


@pytest.mark.parametrize("args,hours", [
    (("2026-10-19", "AM", "2026-10-19", "PM"), 8),          # one full day
    (("2026-10-19", "PM", "2026-10-19", "PM"), 4),          # afternoon only
    (("2026-10-19", "AM", "2026-10-19", "AM"), 4),          # morning only
    (("2026-10-16", "PM", "2026-10-19", "AM"), 8),          # Fri PM + Mon AM, weekend excluded
    (("2026-09-30", "AM", "2026-10-02", "PM"), 8),          # holidays excluded
    (("2026-10-10", "AM", "2026-10-10", "PM"), 8),          # make-up Saturday counts
    (("2026-10-17", "AM", "2026-10-18", "PM"), 0),          # weekend only
])
def test_leave_hours(args, hours):
    s, sh, e, eh = args
    assert calendar.calc_leave_hours(HMAP, date.fromisoformat(s), sh, date.fromisoformat(e), eh)[0] == hours


@pytest.mark.parametrize("args,code", [
    (("2026-10-20", "AM", "2026-10-19", "PM"), "INVALID_DATE_RANGE"),
    (("2026-10-19", "PM", "2026-10-19", "AM"), "INVALID_DATE_RANGE"),
    (("2026-12-31", "AM", "2027-01-04", "PM"), "CROSS_YEAR_LEAVE"),
    (("2026-10-19", "XX", "2026-10-19", "PM"), "INVALID_HALF"),
])
def test_leave_range_validation(args, code):
    from app.core.errors import ValidationFailed
    s, sh, e, eh = args
    with pytest.raises(ValidationFailed) as ei:
        calendar.calc_leave_hours({}, date.fromisoformat(s), sh, date.fromisoformat(e), eh)
    assert ei.value.code == code


# ------------------------------------------------------------------ attendance day calculator
def test_normal_late_early_and_grace():
    d = date(2026, 10, 14)
    r = att.compute_day(DAY, d, [dt("2026-10-14 08:55"), dt("2026-10-14 18:02")], True, None, set(), False, NOW)
    assert (r.status, r.late_minutes, r.early_minutes) == ("normal", 0, 0)
    r = att.compute_day(DAY, d, [dt("2026-10-14 09:05"), dt("2026-10-14 18:00")], True, None, set(), False, NOW)
    assert r.status == "normal"  # within 5 min grace
    r = att.compute_day(DAY, d, [dt("2026-10-14 09:20"), dt("2026-10-14 17:30")], True, None, set(), False, NOW)
    assert (r.status, r.late_minutes, r.early_minutes) == ("late_early", 20, 30)


def test_missing_absent_pending():
    d = date(2026, 10, 14)
    assert att.compute_day(DAY, d, [], True, None, set(), False, NOW).status == "absent"
    assert att.compute_day(DAY, d, [dt("2026-10-14 08:50")], True, None, set(), False, NOW).status == "missing"
    today = date(2026, 10, 19)
    assert att.compute_day(DAY, today, [dt("2026-10-19 08:58")], True, None, set(), False, NOW).status == "pending"
    assert att.compute_day(DAY, today, [], True, None, set(), False, NOW).status == "pending"
    assert att.compute_day(DAY, today, [], True, None, set(), False, dt("2026-10-19 07:00")).status == "upcoming"


def test_rest_holiday_leave_travel():
    assert att.compute_day(DAY, date(2026, 10, 18), [], False, None, set(), False, NOW).status == "rest"
    assert att.compute_day(DAY, date(2026, 10, 1), [], False, "holiday", set(), False, NOW).status == "holiday"
    r = att.compute_day(DAY, date(2026, 10, 14), [], True, None, {"AM", "PM"}, False, NOW)
    assert (r.status, r.leave_hours) == ("leave", 8)
    assert att.compute_day(DAY, date(2026, 10, 14), [], True, None, set(), True, NOW).status == "travel"


def test_half_day_leave_moves_expected_times():
    d = date(2026, 10, 14)
    r = att.compute_day(DAY, d, [dt("2026-10-14 12:58"), dt("2026-10-14 18:01")], True, None, {"AM"}, False, NOW)
    assert (r.status, r.leave_hours, r.late_minutes) == ("normal", 4, 0)
    r = att.compute_day(DAY, d, [dt("2026-10-14 08:59"), dt("2026-10-14 12:00")], True, None, {"PM"}, False, NOW)
    assert (r.status, r.early_minutes) == ("normal", 0)


def test_cross_day_night_shift_attribution():
    # punches at 21:50 on the 14th and 06:05 on the 15th belong to work date 14th
    assert att.attribute_work_date(NIGHT, dt("2026-10-14 21:50")) == date(2026, 10, 14)
    assert att.attribute_work_date(NIGHT, dt("2026-10-15 06:05")) == date(2026, 10, 14)
    assert att.attribute_work_date(NIGHT, dt("2026-10-15 19:00")) == date(2026, 10, 15)
    r = att.compute_day(NIGHT, date(2026, 10, 14), [dt("2026-10-14 22:10"), dt("2026-10-15 06:00")], True, None,
                        set(), False, NOW)
    assert (r.status, r.late_minutes) == ("late", 10)
    # day shift: a 00:30 punch is outside every window and is not counted for the previous day
    assert att.attribute_work_date(DAY, dt("2026-10-15 00:30")) == date(2026, 10, 15)


def test_rule_validation():
    from app.core.errors import ValidationFailed
    att.validate_rule("22:00", "06:00", "02:00", "02:30", True, 240, 360)
    with pytest.raises(ValidationFailed):
        att.validate_rule("09:00", "18:00", None, None, False, 720, 720)  # windows would overlap
    with pytest.raises(ValidationFailed):
        att.validate_rule("18:00", "09:00", None, None, False, 60, 60)
    with pytest.raises(ValidationFailed):
        att.validate_rule("09:00", "18:00", "19:00", "20:00", False, 60, 60)


# ------------------------------------------------------------------ API
def test_punch_api_duplicate_and_timezone(as_user, sql):
    yui = as_user("yui")
    a = ok(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-14T08:58:00+08:00"}))
    assert a["work_date"] == "2026-10-14" and not a["duplicate"] and a["source"] == "simulated"
    b = ok(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-14T08:58:40+08:00"}))
    assert b["duplicate"] and b["punch_id"] == a["punch_id"]
    # 10:30 UTC == 18:30 Asia/Shanghai
    c = ok(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-14T10:30:00Z"}))
    assert c["punched_at"] == "2026-10-14T18:30:00" and c["record"]["status"] == "normal"
    assert sql("SELECT count(*) FROM attendance_punches WHERE work_date='2026-10-14'")[0][0] == 2
    err(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-25T09:00:00"}), 422, "FUTURE_PUNCH")
    recs = ok(yui.get("/api/attendance/records?start=2026-10-12&end=2026-10-16"))
    assert [r["status"] for r in recs if r["work_date"] == "2026-10-14"] == ["normal"]


def test_correction_rules_and_flow(as_user):
    yui, mio = as_user("yui"), as_user("mio")
    ok(yui.post("/api/attendance/punch", json={"punch_time": "2026-10-13T08:50:00"}))
    rec = ok(yui.get("/api/attendance/records?start=2026-10-13&end=2026-10-13"))[0]
    assert rec["status"] == "missing"
    err(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-13", "kind": "out",
                                                      "corrected_time": "2026-10-14T03:00:00", "reason": "忘打卡"}),
        422, "OUT_OF_WINDOW")
    err(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-18", "kind": "in",
                                                      "corrected_time": "2026-10-18T09:00:00", "reason": "x"}),
        422, "NOT_WORKDAY")
    c = ok(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-13", "kind": "out",
                                                         "corrected_time": "2026-10-13T18:05:00",
                                                         "reason": "练琴太投入忘了打卡"}), 201)
    err(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-13", "kind": "out",
                                                      "corrected_time": "2026-10-13T18:06:00", "reason": "dup"}),
        409, "DUPLICATE_CORRECTION")
    t = next(t for t in ok(mio.get("/api/workflow/tasks"))["items"] if t["instance_id"] == c["instance_id"])
    ok(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}))
    rec = ok(yui.get("/api/attendance/records?start=2026-10-13&end=2026-10-13"))[0]
    assert rec["status"] == "normal" and rec["check_out_at"] == "2026-10-13T18:05:00"


def test_correction_rejected_on_full_leave_day(as_user):
    yui, mio = as_user("yui"), as_user("mio")
    lt = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "sick")["leave_type_id"]
    lv = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-10-15", "start_half": "AM", "end_date": "2026-10-15",
        "end_half": "PM", "reason": "感冒"}), 201)
    t = next(t for t in ok(mio.get("/api/workflow/tasks"))["items"] if t["instance_id"] == lv["instance_id"])
    ok(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}))
    err(yui.post("/api/attendance/corrections", json={"work_date": "2026-10-15", "kind": "in",
                                                      "corrected_time": "2026-10-15T09:00:00", "reason": "x"}),
        422, "DAY_ON_LEAVE")


def test_overtime_credits_comp_leave_once(as_user, sql):
    yui, mio = as_user("yui"), as_user("mio")
    ot = ok(yui.post("/api/attendance/overtime", json={"start_at": "2026-10-17T13:00:00",
                                                      "end_at": "2026-10-17T17:30:00", "reason": "周末录音",
                                                      "compensation": "leave"}), 201)
    assert ot["hours"] == 4
    err(yui.post("/api/attendance/overtime", json={"start_at": "2026-10-17T16:00:00", "end_at": "2026-10-17T18:00:00",
                                                  "reason": "重叠"}), 409, "OVERTIME_OVERLAP")
    t = next(t for t in ok(mio.get("/api/workflow/tasks"))["items"] if t["instance_id"] == ot["instance_id"])
    ok(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}))
    comp = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "comp")
    assert comp["total_hours"] == 4 and comp["available_hours"] == 4
    assert sql("SELECT count(*) FROM leave_ledger WHERE ref_type='overtime_request' AND ref_id=?",
               id=ot["id"])[0][0] == 1
    # HR was copied
    assert sql("SELECT count(*) FROM wf_cc WHERE instance_id=?", id=ot["instance_id"])[0][0] == 2


def test_monthly_statistics(as_user):
    yui = as_user("yui")
    for p in ("2026-10-12T09:30:00", "2026-10-12T18:10:00", "2026-10-13T08:40:00", "2026-10-13T17:00:00",
              "2026-10-14T08:50:00", "2026-10-14T18:00:00"):
        ok(yui.post("/api/attendance/punch", json={"punch_time": p}))
    rows = ok(yui.get("/api/attendance/monthly?month=2026-10"))
    assert {r["name"] for r in rows} == {"平泽唯", "中野梓", "若王子苺"}  # group lead: own department
    assert [r["name"] for r in ok(as_user("azusa").get("/api/attendance/monthly?month=2026-10"))] == ["中野梓"]
    s = next(r for r in rows if r["name"] == "平泽唯")
    # Oct 1-19: 8,9,10(make-up Sat),12-16,19 = 9 workdays; 1,2,5,6,7 are holidays
    assert s["workdays"] == 9
    assert (s["late"], s["early"], s["normal"]) == (1, 1, 1)
    assert s["absent"] == 9 - 3 - 1  # today (19th) is still pending
    hr_rows = ok(as_user("nodoka").get("/api/attendance/monthly?month=2026-10"))
    assert len(hr_rows) == 13
    err(yui.get("/api/attendance/monthly?month=2026-13"), 422)


def test_leave_balance_and_overlap_rules(as_user, sql):
    yui = as_user("yui")
    types = {t["code"]: t["id"] for t in ok(yui.get("/api/leave/types"))}
    annual = types["annual"]
    calc = ok(yui.post("/api/leave/calculate", json={"start_date": "2026-11-02", "start_half": "AM",
                                                     "end_date": "2026-11-09", "end_half": "PM"}))
    assert calc["hours"] == 48 and calc["days"] == 6
    # 6 days > 5 days available
    err(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": annual, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-09",
        "end_half": "PM", "reason": "x"}), 409, "LEAVE_BALANCE_INSUFFICIENT")
    assert sql("SELECT count(*) FROM leave_requests")[0][0] == 0  # nothing persisted on failure
    first = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": annual, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-03",
        "end_half": "AM", "reason": "x"}), 201)
    err(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": types["personal"], "start_date": "2026-11-03", "start_half": "AM",
        "end_date": "2026-11-03", "end_half": "AM", "reason": "x"}), 409, "LEAVE_OVERLAP")
    ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": types["personal"], "start_date": "2026-11-03", "start_half": "PM",
        "end_date": "2026-11-03", "end_half": "PM", "reason": "下午事假"}), 201)  # adjacent half is fine
    err(yui.post("/api/leave/requests", json={
        "leave_type_id": annual, "start_date": "2026-11-07", "start_half": "AM", "end_date": "2026-11-08",
        "end_half": "PM", "reason": "weekend"}), 422, "NO_WORKDAY_IN_RANGE")
    assert first["hours"] == 12


def test_idempotency_key_prevents_duplicate_submission(as_user, sql):
    yui = as_user("yui")
    lt = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["leave_type_id"]
    body = {"leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
            "end_half": "PM", "reason": "x"}
    h = {"Idempotency-Key": "leave-req-001"}
    r1 = yui.post("/api/leave/requests?submit=true", json=body, headers=h)
    r2 = yui.post("/api/leave/requests?submit=true", json=body, headers=h)
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert sql("SELECT count(*) FROM leave_requests")[0][0] == 1
    assert next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["pending_hours"] == 8
    err(yui.post("/api/leave/requests?submit=true", json={**body, "reason": "other"}, headers=h), 409,
        "IDEMPOTENCY_KEY_REUSED")
    # repeated plain submit of the same document is rejected by state
    rid = r1.json()["id"]
    err(yui.post(f"/api/leave/requests/{rid}/submit"), 409, "INVALID_STATE")


def test_hr_adjust_balance_and_ledger(as_user):
    hr, yui = as_user("nodoka"), as_user("yui")
    me = ok(yui.get("/api/auth/me"))["employee"]
    sick = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "sick")
    ok(hr.post("/api/leave/balances/adjust", json={"employee_id": me["id"], "leave_type_id": sick["leave_type_id"],
                                                   "year": 2026, "hours": 16, "remark": "学园祭加班奖励"}))
    err(hr.post("/api/leave/balances/adjust", json={"employee_id": me["id"], "leave_type_id": sick["leave_type_id"],
                                                    "year": 2026, "hours": -1000, "remark": "x"}),
        409, "LEAVE_BALANCE_INSUFFICIENT")
    err(yui.post("/api/leave/balances/adjust", json={"employee_id": me["id"], "leave_type_id": sick["leave_type_id"],
                                                     "year": 2026, "hours": 16, "remark": "self"}), 403)
    led = ok(yui.get("/api/leave/ledger?page_size=5"))
    assert led["items"][0]["change_type"] == "adjust" and led["items"][0]["hours"] == 16
    assert ok(hr.get(f"/api/leave/ledger?employee_id={me['id']}"))["total"] == led["total"]


def test_records_include_absent_days_without_punches(as_user):
    """Regression: days without any punch were missing from the personal record list."""
    recs = ok(as_user("azusa").get("/api/attendance/records?start=2026-10-12&end=2026-10-18"))
    assert [(r["work_date"], r["status"]) for r in recs] == [
        ("2026-10-12", "absent"), ("2026-10-13", "absent"), ("2026-10-14", "absent"), ("2026-10-15", "absent"),
        ("2026-10-16", "absent"), ("2026-10-17", "rest"), ("2026-10-18", "rest")]
    dash = ok(as_user("azusa").get("/api/dashboard/summary"))
    assert dash["recent_attendance"][0]["status"] == "pending"  # today (Mon 19th, 10:00) still in progress
    assert dash["recent_attendance"][1]["status"] == "absent"
