"""Real-network tests: a local uvicorn process on an isolated SQLite copy, driven by httpx over TCP.

Covers key chains end-to-end over HTTP, genuine concurrent requests (independent connections, separate DB
sessions inside the server's thread pool) and crash/restart recovery. Limits: single process, single SQLite
file; this is not a production-grade load or multi-node test.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.core.config import BACKEND_DIR
from tests.conftest import FIXED_NOW, ITERATIONS, TEST_PASSWORD

pytestmark = pytest.mark.live


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, db_path, data_dir):
        self.db_path, self.data_dir = db_path, data_dir
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        env = dict(os.environ, DOE_ENV="test", DOE_FIXED_NOW=FIXED_NOW, DOE_DATA_DIR=str(self.data_dir),
                   DOE_DATABASE_URL=f"sqlite:///{self.db_path.as_posix()}", DOE_PASSWORD_ITERATIONS=str(ITERATIONS))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"], cwd=str(BACKEND_DIR), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if httpx.get(self.base + "/api/health", timeout=1).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError("live server did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()  # hard stop on Windows (TerminateProcess): simulates a crash
            self.proc.wait(10)


@pytest.fixture()
def live(template_db, tmp_path):
    db = tmp_path / "live.sqlite3"
    shutil.copy(template_db, db)
    srv = LiveServer(db, tmp_path / "data").start()
    yield srv
    srv.stop()


def login(base, user, password=TEST_PASSWORD):
    r = httpx.post(base + "/api/auth/login", json={"username": user, "password": password}, timeout=10)
    assert r.status_code == 200, r.text
    return httpx.Client(base_url=base, headers={"Authorization": f"Bearer {r.json()['token']}"}, timeout=30)


def j(resp, status=200):
    assert resp.status_code == status, f"{resp.request.method} {resp.request.url} -> {resp.status_code} {resp.text[:300]}"
    return resp.json()


def task_for(c, instance_id):
    return next(t for t in j(c.get("/api/workflow/tasks"))["items"] if t["instance_id"] == instance_id)


def annual(c):
    return next(b for b in j(c.get("/api/leave/balances")) if b["leave_type_code"] == "annual")


def test_leave_chain_over_network(live):
    yui, mio, hr = login(live.base, "yui"), login(live.base, "mio"), login(live.base, "himeko")
    b0 = annual(yui)
    lv = j(yui.post("/api/leave/requests", json={
        "leave_type_id": b0["leave_type_id"], "start_date": "2026-11-02", "start_half": "AM",
        "end_date": "2026-11-05", "end_half": "PM", "reason": "网络链路测试"}), 201)
    lv = j(yui.post(f"/api/leave/requests/{lv['id']}/submit"))
    j(mio.post(f"/api/workflow/tasks/{task_for(mio, lv['instance_id'])['id']}/approve", json={}))
    j(hr.post(f"/api/workflow/tasks/{task_for(hr, lv['instance_id'])['id']}/approve", json={}))
    assert j(yui.get(f"/api/leave/requests/{lv['id']}"))["status"] == "approved"
    b1 = annual(yui)
    assert (b1["used_hours"], b1["pending_hours"]) == (32, 0)


def test_expense_chain_over_network(live):
    yui, mio, ritsu, fin = (login(live.base, u) for u in ("yui", "mio", "ritsu", "megumi"))
    cat = j(yui.get("/api/expense/categories"))[0]["id"]
    c = j(yui.post("/api/expense/claims?submit=true", json={"title": "大额设备", "items": [
        {"category_id": cat, "occurred_on": "2026-10-12", "amount": "5000.01"}]}), 201)
    for api in (mio, ritsu, fin):
        j(api.post(f"/api/workflow/tasks/{task_for(api, c['instance_id'])['id']}/approve", json={}))
    paid = j(fin.post(f"/api/expense/claims/{c['id']}/finance-confirm", json={}))
    assert paid["status"] == "paid" and paid["total"] == "5000.01"


def _parallel(fn, n):
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait()
        return fn(i)
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(run, range(n)))


def test_concurrent_approval_of_same_task(live):
    yui = login(live.base, "yui")
    lv = j(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": annual(yui)["leave_type_id"], "start_date": "2026-11-02", "start_half": "AM",
        "end_date": "2026-11-02", "end_half": "PM", "reason": "并发"}), 201)
    mio_clients = [login(live.base, "mio") for _ in range(8)]
    tid = task_for(mio_clients[0], lv["instance_id"])["id"]
    codes = _parallel(lambda i: mio_clients[i].post(f"/api/workflow/tasks/{tid}/approve", json={}).status_code, 8)
    assert codes.count(200) == 1 and all(c == 409 for c in codes if c != 200), codes
    b = annual(yui)
    assert (b["used_hours"], b["pending_hours"]) == (8, 0)  # consumed exactly once
    hist = j(yui.get(f"/api/workflow/instances/{lv['instance_id']}"))["history"]
    assert [h["action"] for h in hist].count("approve") == 1


def test_concurrent_or_sign_by_different_approvers(live):
    yui, mio = login(live.base, "yui"), login(live.base, "mio")
    lv = j(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": annual(yui)["leave_type_id"], "start_date": "2026-11-02", "start_half": "AM",
        "end_date": "2026-11-05", "end_half": "PM", "reason": "或签并发"}), 201)
    j(mio.post(f"/api/workflow/tasks/{task_for(mio, lv['instance_id'])['id']}/approve", json={}))
    hrs = [login(live.base, "nodoka"), login(live.base, "himeko")]
    tids = [task_for(h, lv["instance_id"])["id"] for h in hrs]
    codes = _parallel(lambda i: hrs[i].post(f"/api/workflow/tasks/{tids[i]}/approve", json={}).status_code, 2)
    assert sorted(codes) == [200, 409], codes
    assert j(yui.get(f"/api/leave/requests/{lv['id']}"))["status"] == "approved"
    assert annual(yui)["used_hours"] == 32


def test_concurrent_submit_of_same_leave(live):
    yui = login(live.base, "yui")
    lv = j(yui.post("/api/leave/requests", json={
        "leave_type_id": annual(yui)["leave_type_id"], "start_date": "2026-11-02", "start_half": "AM",
        "end_date": "2026-11-02", "end_half": "PM", "reason": "重复提交"}), 201)
    clients = [login(live.base, "yui") for _ in range(8)]
    codes = _parallel(lambda i: clients[i].post(f"/api/leave/requests/{lv['id']}/submit").status_code, 8)
    assert codes.count(200) == 1, codes
    assert annual(yui)["pending_hours"] == 8
    inst = j(yui.get("/api/workflow/instances?scope=mine"))
    assert inst["total"] == 1


def test_concurrent_balance_consumption(live):
    """Five different 2-day requests race for 5 days of balance: at most two can be frozen."""
    yui = login(live.base, "yui")
    lt = annual(yui)["leave_type_id"]
    clients = [login(live.base, "yui") for _ in range(5)]
    days = ["2026-11-02", "2026-11-04", "2026-11-09", "2026-11-11", "2026-11-16"]

    def submit(i):
        d = days[i]
        end = {"2026-11-02": "2026-11-03", "2026-11-04": "2026-11-05", "2026-11-09": "2026-11-10",
               "2026-11-11": "2026-11-12", "2026-11-16": "2026-11-17"}[d]
        return clients[i].post("/api/leave/requests?submit=true", json={
            "leave_type_id": lt, "start_date": d, "start_half": "AM", "end_date": end, "end_half": "PM",
            "reason": f"并发余额 {i}"})
    res = _parallel(submit, 5)
    codes = [r.status_code for r in res]
    assert codes.count(201) == 2 and codes.count(409) == 3, codes
    assert all(r.json()["error"]["code"] == "LEAVE_BALANCE_INSUFFICIENT" for r in res if r.status_code == 409)
    b = annual(yui)
    assert b["pending_hours"] == 32 and b["available_hours"] == 8


def test_concurrent_room_booking(live):
    users = ["yui", "mio", "ritsu", "mugi", "azusa", "nodoka", "sawako", "mika"]
    clients = [login(live.base, u) for u in users]
    room = next(r for r in j(clients[0].get("/api/meeting/rooms")) if r["name"] == "茶歇室")["id"]
    res = _parallel(lambda i: clients[i].post("/api/meeting/bookings", json={
        "room_id": room, "subject": f"茶话会 {i}", "start_at": "2026-10-22T15:00:00",
        "end_at": "2026-10-22T16:00:00"}), len(users))
    codes = [r.status_code for r in res]
    assert codes.count(201) == 1 and codes.count(409) == len(users) - 1, codes
    cal = j(clients[0].get(f"/api/meeting/calendar?start=2026-10-22&end=2026-10-22&room_id={room}"))
    assert len(cal) == 1


def test_concurrent_profile_update(live):
    hr = [login(live.base, "nodoka") for _ in range(5)]
    emp = next(e for e in j(hr[0].get("/api/employees?q=中野梓"))["items"])
    body = {k: emp[k] for k in ("version", "name", "gender", "birth_date", "phone", "email", "department_id",
                                "position_id", "manager_id", "remark")}
    res = _parallel(lambda i: hr[i].put(f"/api/employees/{emp['id']}", json={**body, "remark": f"并发 {i}"}), 5)
    codes = [r.status_code for r in res]
    assert codes.count(200) == 1 and codes.count(409) == 4, codes
    final = j(hr[0].get(f"/api/employees/{emp['id']}"))
    assert final["version"] == emp["version"] + 1


def test_concurrent_idempotent_retries(live):
    yui = login(live.base, "yui")
    lt = annual(yui)["leave_type_id"]
    clients = [login(live.base, "yui") for _ in range(6)]
    body = {"leave_type_id": lt, "start_date": "2026-11-02", "start_half": "AM", "end_date": "2026-11-02",
            "end_half": "PM", "reason": "超时重试"}
    res = _parallel(lambda i: clients[i].post("/api/leave/requests?submit=true", json=body,
                                              headers={"Idempotency-Key": "retry-key-1"}), 6)
    ok_bodies = [r.json() for r in res if r.status_code == 201]
    others = [r for r in res if r.status_code != 201]
    assert ok_bodies and all(b == ok_bodies[0] for b in ok_bodies)
    # racing duplicates either replay the stored response or lose the unique race (409), never create twice
    assert all(r.status_code == 409 for r in others)
    assert j(yui.get("/api/leave/requests"))["total"] == 1
    assert annual(yui)["pending_hours"] == 8


def test_crash_and_restart_recovery(live):
    yui, mio = login(live.base, "yui"), login(live.base, "mio")
    lv = j(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": annual(yui)["leave_type_id"], "start_date": "2026-11-02", "start_half": "AM",
        "end_date": "2026-11-02", "end_half": "PM", "reason": "中断恢复"}), 201)
    live.stop()  # hard kill
    live.start()  # same port, same database file
    yui, mio = login(live.base, "yui"), login(live.base, "mio")
    assert j(yui.get(f"/api/leave/requests/{lv['id']}"))["status"] == "pending"
    assert annual(yui)["pending_hours"] == 8
    j(mio.post(f"/api/workflow/tasks/{task_for(mio, lv['instance_id'])['id']}/approve", json={}))
    assert j(yui.get(f"/api/leave/requests/{lv['id']}"))["status"] == "approved"


def test_onboarding_regularization_meeting_chains_over_network(live):
    hr, mugi, yui, azusa = (login(live.base, u) for u in ("nodoka", "mugi", "yui", "azusa"))
    tea = next(d for d in j(hr.get("/api/departments")) if d["code"] == "TEA")
    onb = j(hr.post("/api/onboarding?submit=true", json={
        "name": "奥田直", "email": "nao.net@htt.example", "department_id": tea["id"], "hire_date": "2026-11-02",
        "probation_months": 3, "create_account": True, "username": "nao"}), 201)
    j(mugi.post(f"/api/workflow/tasks/{task_for(mugi, onb['instance_id'])['id']}/approve", json={}))
    j(hr.post(f"/api/workflow/tasks/{task_for(hr, onb['instance_id'])['id']}/approve", json={}))
    final = j(hr.get(f"/api/onboarding/{onb['id']}"))
    assert final["status"] == "approved" and final["employee_id"] and final["user_id"]
    assert len(j(hr.get(f"/api/onboarding-tasks?scope=all&onboarding_id={onb['id']}"))) == 4

    reg = j(azusa.post("/api/regularization?submit=true", json={"planned_date": "2026-11-01", "self_review": "网络链路"}), 201)
    j(yui.post(f"/api/workflow/tasks/{task_for(yui, reg['instance_id'])['id']}/approve",
               json={"form_data": {"score": 88, "evaluation": "稳定可靠"}}))
    j(hr.post(f"/api/workflow/tasks/{task_for(hr, reg['instance_id'])['id']}/approve", json={}))
    emp = j(hr.get(f"/api/employees/{j(azusa.get('/api/auth/me'))['employee']['id']}"))
    assert emp["status"] == "regular"

    hall = next(r for r in j(yui.get("/api/meeting/rooms")) if r["name"] == "讲堂")
    b = j(yui.post("/api/meeting/bookings", json={"room_id": hall["id"], "subject": "网络彩排",
                                                  "start_at": "2026-10-23T14:00:00", "end_at": "2026-10-23T15:00:00"}), 201)
    j(mugi.post(f"/api/workflow/tasks/{task_for(mugi, b['instance_id'])['id']}/approve", json={}))
    cal = j(yui.get(f"/api/meeting/calendar?start=2026-10-23&end=2026-10-23&room_id={hall['id']}"))
    assert [(c["subject"], c["status"]) for c in cal] == [("网络彩排", "approved")]
