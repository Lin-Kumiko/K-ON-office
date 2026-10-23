"""Performance measurements on synthetic volume (run explicitly: pytest -m slow tests/test_performance.py).

Volume: ~1000 employees, ~30000 punches, 120 workflow instances. The bulk volume is inserted directly
(it is base/synthetic data, not a business step under test); every measured operation goes through
the HTTP API. Results are written to tests/performance.json at the project root.
"""
from __future__ import annotations

import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from app.core.config import PROJECT_DIR
from app.core.security import hash_password
from app.models import AttendancePunch, Department, Employee, Role, User, user_roles
from tests.conftest import ITERATIONS, TEST_PASSWORD, Api, login

pytestmark = pytest.mark.slow
RESULTS: dict = {}


def _bulk(app, n_emp=990, days=15):
    db = app.state.db
    rnd = random.Random(42)
    with db.session(write=True) as s:
        depts = list(s.scalars(select(Department.id)))
        emp_role = s.scalar(select(Role).where(Role.code == "employee"))
        pw = hash_password(TEST_PASSWORD, ITERATIONS)
        manager = s.scalar(select(Employee.id).where(Employee.employee_no == "HTT0002"))
        users = [{"username": f"perf{i:04d}", "display_name": f"压测成员{i}", "password_hash": pw, "status": "active",
                  "must_change_password": False, "failed_attempts": 0, "created_at": datetime(2026, 1, 1),
                  "updated_at": datetime(2026, 1, 1)} for i in range(120)]
        s.execute(insert(User), users)
        uid = {u.username: u.id for u in s.scalars(select(User).where(User.username.like("perf%")))}
        s.execute(insert(user_roles), [{"user_id": v, "role_id": emp_role.id} for v in uid.values()])
        emps = []
        for i in range(n_emp):
            emps.append({"employee_no": f"PF{i:05d}", "name": f"合成员工{i}", "department_id": rnd.choice(depts),
                         "manager_id": manager, "hire_date": date(2025, 1, 1), "status": "regular", "version": 1,
                         "email": f"pf{i}@perf.example", "user_id": uid.get(f"perf{i:04d}"),
                         "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)})
        s.execute(insert(Employee), emps)
        ids = list(s.scalars(select(Employee.id).where(Employee.employee_no.like("PF%"))))
        punches, d = [], date(2026, 10, 19)
        workdays = []
        while len(workdays) < days:
            d -= timedelta(days=1)
            if d.weekday() < 5 and d not in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)):
                workdays.append(d)
        for eid in ids:
            for wd in workdays:
                base = datetime.combine(wd, datetime.min.time())
                punches.append({"employee_id": eid, "work_date": wd, "source": "simulated",
                                "punched_at": base + timedelta(hours=8, minutes=rnd.randint(30, 75)),
                                "created_at": base})
                punches.append({"employee_id": eid, "work_date": wd, "source": "simulated",
                                "punched_at": base + timedelta(hours=17, minutes=rnd.randint(45, 120)),
                                "created_at": base})
        s.execute(insert(AttendancePunch), punches)
        s.commit()
    return len(ids), len(punches)


def _time(fn, n=10):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    xs.sort()
    return {"n": n, "p50_ms": round(statistics.median(xs), 1), "p95_ms": round(xs[int(0.95 * (n - 1))], 1),
            "max_ms": round(xs[-1], 1)}


def test_performance_profile(app):
    t0 = time.perf_counter()
    n_emp, n_punch = _bulk(app)
    RESULTS["volume"] = {"employees": n_emp + 13, "punches": n_punch,
                         "insert_seconds": round(time.perf_counter() - t0, 2)}
    with TestClient(app) as c:
        hr = login(c, "nodoka")
        ceo = login(c, "ritsu")

        def ok(r):
            assert r.status_code in (200, 201), r.text[:300]
            return r.json()
        RESULTS["employee_list_page50"] = _time(lambda: ok(hr.get("/api/employees?page_size=50&q=合成")))
        RESULTS["employee_list_page200_filter_dept"] = _time(lambda: ok(hr.get("/api/employees?page_size=200&department_id=1")))
        RESULTS["employee_options_all"] = _time(lambda: ok(hr.get("/api/employees/options")), 5)
        RESULTS["attendance_monthly_all"] = _time(lambda: ok(hr.get("/api/attendance/monthly?month=2026-10")), 3)
        RESULTS["attendance_rebuild_month_all"] = _time(lambda: ok(hr.post("/api/attendance/rebuild", json={
            "start": "2026-10-01", "end": "2026-10-19"})), 1)
        RESULTS["reports_overview"] = _time(lambda: ok(ceo.get("/api/reports/overview?month=2026-10")), 3)
        RESULTS["dashboard_summary_ceo"] = _time(lambda: ok(ceo.get("/api/dashboard/summary")), 5)

        # batch approvals: 100 single-day travel requests approved one after another
        perf = [login(c, f"perf{i:04d}") for i in range(100)]
        mgr = login(c, "mio")
        insts = []
        for i, api in enumerate(perf):
            day = date(2026, 11, 2) + timedelta(days=(i % 5))
            insts.append(ok(api.post("/api/travel?submit=true", json={"destination": f"站点{i}", "start_date": str(day),
                                                                      "end_date": str(day), "purpose": "压测"}))["instance_id"])
        tasks = {t["instance_id"]: t["id"] for t in ok(mgr.get("/api/workflow/tasks?page_size=200"))["items"]}
        t = time.perf_counter()
        for iid in insts:
            ok(mgr.post(f"/api/workflow/tasks/{tasks[iid]}/approve", json={}))
        total = time.perf_counter() - t
        RESULTS["batch_approve_100"] = {"total_s": round(total, 2), "per_task_ms": round(total * 10, 1)}
        RESULTS["task_list_after_batch"] = _time(lambda: ok(mgr.get("/api/workflow/tasks?status=done&page_size=50")))
        RESULTS["instance_list_related_page50"] = _time(
            lambda: ok(mgr.get("/api/workflow/instances?scope=related&page_size=50")))

    # multi-user requests: 4 worker threads, 20 workflow submissions + dashboard reads each
    with TestClient(app) as c:
        users = [Api(c, login(c, f"perf{100 + i:04d}").token) for i in range(4)]

        def worker(k):
            api = users[k]
            lat = []
            for j in range(5):
                s = time.perf_counter()
                r = api.post("/api/travel?submit=true", json={"destination": f"并发{k}-{j}", "start_date": f"2026-12-{j + 1:02d}",
                                                             "end_date": f"2026-12-{j + 1:02d}", "purpose": "并发"})
                assert r.status_code == 201, r.text
                assert api.get("/api/dashboard/summary").status_code == 200
                lat.append((time.perf_counter() - s) * 1000)
            return lat
        t = time.perf_counter()
        with ThreadPoolExecutor(4) as ex:
            lats = sorted(x for part in ex.map(worker, range(4)) for x in part)
        RESULTS["concurrent_4_users_submit_and_read"] = {"requests": 40, "wall_s": round(time.perf_counter() - t, 2),
                                                        "p50_ms": round(statistics.median(lats), 1),
                                                        "max_ms": round(lats[-1], 1), "errors": 0}
    RESULTS["note"] = "In-process HTTP (TestClient) on an isolated SQLite file; single process, Windows dev machine."
    out = PROJECT_DIR / "tests" / "performance.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
