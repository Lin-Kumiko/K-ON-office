"""Create demo business data through the REAL HTTP API (no direct DB writes).

Run after init_db.py with the backend started:
    backend\\.venv\\Scripts\\python.exe scripts\\demo_data.py --base http://127.0.0.1:8000
Seed account password: DOE_SEED_PASSWORD env var or hidden prompt. Safe to re-run: it stops if the
demo marker announcement already exists.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import os
import sys
from datetime import date, datetime, timedelta

import httpx

MARKER = "欢迎来到放学后茶会株式会社"


class Client:
    def __init__(self, base: str, user: str, password: str):
        self.user = user
        r = httpx.post(f"{base}/api/auth/login", json={"username": user, "password": password}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"[error] {user} 登录失败：{r.json().get('error', {}).get('message')}")
        self.c = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {r.json()['token']}"}, timeout=60)

    def call(self, method: str, url: str, expect=(200, 201), **kw):
        r = self.c.request(method, url, **kw)
        if r.status_code not in expect:
            raise RuntimeError(f"{self.user} {method} {url} -> {r.status_code} {r.text[:300]}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None

    def get(self, url, **kw):
        return self.call("GET", url, **kw)

    def post(self, url, json=None, **kw):
        return self.call("POST", url, json=json, **kw)

    def task(self, instance_id: int):
        items = self.get("/api/workflow/tasks", params={"page_size": 200})["items"]
        return next(t for t in items if t["instance_id"] == instance_id)

    def approve(self, instance_id: int, **body):
        return self.post(f"/api/workflow/tasks/{self.task(instance_id)['id']}/approve", json=body)


def workdays_back(n: int, today: date) -> list[date]:
    out, d = [], today - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def next_workday(start: date, k: int = 1) -> date:
    d = start
    while k:
        d += timedelta(days=1)
        if d.weekday() < 5:
            k -= 1
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    pw = os.environ.get("DOE_SEED_PASSWORD") or getpass.getpass("种子账号密码：")
    users = ["ui", "ritsu", "mio", "yui", "azusa", "ichigo", "mugi", "megumi", "fuuko", "nodoka", "himeko", "sawako",
             "mika"]
    c = {u: Client(args.base, u, pw) for u in users}
    if any(a["title"] == MARKER for a in c["nodoka"].get("/api/announcements", params={"scope": "manage", "page_size": 200})["items"]):
        print("[skip] 演示数据已存在")
        return 0
    today = date.today()
    print("[1/9] 模拟打卡（最近 10 个工作日）")
    hol = {h["day"]: h["kind"] for h in c["nodoka"].get("/api/holidays", params={"year": today.year})}
    for u in users:
        for d in workdays_back(10, today):
            if hol.get(str(d)) == "holiday":
                continue
            h = int(hashlib.md5(f"{u}{d}".encode()).hexdigest(), 16) % 20
            if h == 0:
                continue  # absent
            ins = datetime.combine(d, datetime.min.time()) + timedelta(hours=8, minutes=40 + (h * 3 if h > 15 else h))
            outs = datetime.combine(d, datetime.min.time()) + timedelta(hours=18, minutes=h)
            c[u].post("/api/attendance/punch", json={"punch_time": ins.isoformat()})
            if h != 1:
                c[u].post("/api/attendance/punch", json={"punch_time": (outs - timedelta(minutes=40 if h == 2 else 0)).isoformat()})

    print("[2/9] 请假")
    types = {t["code"]: t["id"] for t in c["yui"].get("/api/leave/types")}
    d1 = next_workday(today, 3)
    lv = c["yui"].post("/api/leave/requests", params={"submit": "true"}, json={
        "leave_type_id": types["annual"], "start_date": str(d1), "start_half": "AM", "end_date": str(next_workday(d1)),
        "end_half": "PM", "reason": "去乐器店给吉太做保养"})
    c["mio"].approve(lv["instance_id"], comment="记得回来练新曲")
    c["azusa"].post("/api/leave/requests", params={"submit": "true"}, json={
        "leave_type_id": types["sick"], "start_date": str(next_workday(today, 2)), "start_half": "PM",
        "end_date": str(next_workday(today, 2)), "end_half": "PM", "reason": "感冒去医院"})
    lv3 = c["mika"].post("/api/leave/requests", params={"submit": "true"}, json={
        "leave_type_id": types["personal"], "start_date": str(next_workday(today, 4)), "start_half": "AM",
        "end_date": str(next_workday(today, 4)), "end_half": "PM", "reason": "陪家人"})
    c["sawako"].post(f"/api/workflow/tasks/{c['sawako'].task(lv3['instance_id'])['id']}/reject",
                     json={"comment": "那天要赶学园祭服装，换一天吧"})

    print("[3/9] 加班与补卡")
    sat = today - timedelta(days=(today.weekday() + 2) % 7 or 7)
    ot = c["yui"].post("/api/attendance/overtime", json={"start_at": f"{sat}T13:00:00", "end_at": f"{sat}T17:00:00",
                                                       "reason": "周末录音", "compensation": "leave"})
    c["mio"].approve(ot["instance_id"])

    print("[4/9] 出差与报销")
    tr = c["ritsu"].post("/api/travel", params={"submit": "true"}, json={
        "destination": "琴吹家海边别墅", "start_date": str(next_workday(today, 6)), "end_date": str(next_workday(today, 8)),
        "purpose": "夏季合宿：新曲集训", "transport": "琴吹家专车", "estimated_cost": "3000.00"})
    c["ui"].approve(tr["instance_id"], comment="已安排别墅")
    cats = {x["code"]: x["id"] for x in c["yui"].get("/api/expense/categories")}
    f = c["yui"].call("POST", "/api/files", files={"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 synthetic receipt"),
                                                            "application/pdf")}, data={"purpose": "expense_receipt"})
    ex = c["yui"].post("/api/expense/claims", params={"submit": "true"}, json={"title": "吉他弦与茶点", "items": [
        {"category_id": cats["instrument"], "occurred_on": str(today - timedelta(days=3)), "amount": "180.00",
         "description": "吉他弦两套", "receipt_file_id": f["id"]},
        {"category_id": cats["tea"], "occurred_on": str(today - timedelta(days=2)), "amount": "66.60", "description": "蛋糕"}]})
    c["mio"].approve(ex["instance_id"])
    c["megumi"].approve(ex["instance_id"])
    c["fuuko"].post(f"/api/expense/claims/{ex['id']}/finance-confirm", json={"note": "模拟付款"})
    big = c["mio"].post("/api/expense/claims", params={"submit": "true"}, json={"title": "录音室设备", "items": [
        {"category_id": cats["instrument"], "occurred_on": str(today - timedelta(days=5)), "amount": "8800.00",
         "description": "监听音箱"}]})
    c["ritsu"].approve(big["instance_id"], comment="好，买！")

    print("[5/9] 会议室")
    rooms = {r["name"]: r["id"] for r in c["yui"].get("/api/meeting/rooms")}
    for i, u in enumerate(["yui", "mio", "mugi"]):
        d = next_workday(today, i + 1)
        c[u].post("/api/meeting/bookings", json={"room_id": rooms["音乐准备室"], "subject": ["新曲排练", "作词讨论", "下午茶"][i],
                                                 "start_at": f"{d}T15:30:00", "end_at": f"{d}T17:00:00"})
    c["ritsu"].post("/api/meeting/bookings", json={"room_id": rooms["讲堂"], "subject": "学园祭彩排",
                                                   "start_at": f"{next_workday(today, 5)}T14:00:00",
                                                   "end_at": f"{next_workday(today, 5)}T16:00:00"})

    print("[6/9] 公告与文档")
    cat = c["nodoka"].get("/api/announcements/categories")[0]["id"]
    a = c["nodoka"].post("/api/announcements", json={"title": MARKER, "content": "这里是轻音部。\n认真工作，然后喝茶。", "category_id": cat, "pinned": True})
    c["nodoka"].post(f"/api/announcements/{a['id']}/publish")
    music = next(d["id"] for d in c["nodoka"].get("/api/departments") if d["code"] == "MUSIC")
    a2 = c["nodoka"].post("/api/announcements", json={"title": "学园祭排练安排", "content": "每天放学后在音乐准备室排练两小时。",
                                                      "scope_type": "departments", "scope_department_ids": [music]})
    c["nodoka"].post(f"/api/announcements/{a2['id']}/publish")
    dcat = c["mio"].get("/api/documents/categories")[0]["id"]
    c["mio"].call("POST", "/api/documents", files={"file": ("arrangement_v1.txt", io.BytesIO("新曲编曲草稿 v1".encode()),
                                                             "text/plain")},
                  data={"title": "新曲编曲稿", "visibility": "department", "category_id": str(dcat), "keywords": "编曲,新曲"})
    c["nodoka"].call("POST", "/api/documents", files={"file": ("handbook.md", io.BytesIO("# 员工手册\n准时喝茶。".encode()),
                                                                "text/markdown")},
                     data={"title": "员工手册", "visibility": "public", "keywords": "制度"})

    print("[7/9] 招聘与转正")
    tea = next(d["id"] for d in c["nodoka"].get("/api/departments") if d["code"] == "TEA")
    req = c["nodoka"].post("/api/recruitment/requisitions", json={"title": "茶点专员", "department_id": tea, "headcount": 1})
    cand = c["nodoka"].post("/api/recruitment/candidates", json={"requisition_id": req["id"], "name": "奥田直", "gender": "女",
                                                                 "email": "nao@htt.example", "source": "内推"})
    mugi_id = c["mugi"].get("/api/auth/me")["id"]
    iv = c["nodoka"].post(f"/api/recruitment/candidates/{cand['id']}/interviews",
                          json={"interviewer_id": mugi_id, "scheduled_at": f"{today}T15:00:00"})
    c["mugi"].post(f"/api/recruitment/interviews/{iv['id']}/result", json={"score": 96, "feedback": "厨艺满分", "result": "pass"})
    c["nodoka"].post("/api/recruitment/offers", json={"candidate_id": cand["id"], "department_id": tea, "salary": "9000.00",
                                                      "hire_date": str(next_workday(today, 10))})
    c["azusa"].post("/api/regularization", params={"submit": "true"},
                    json={"planned_date": "2026-11-01", "self_review": "三个月来认真练习，也学会了在社团里喝茶。"})

    print("[8/9] 绩效周期")
    cyc = c["nodoka"].post("/api/performance/cycles", json={
        "name": f"{today.year} 下半年", "start_date": f"{today.year}-07-01", "end_date": f"{today.year}-12-31",
        "indicators": [{"name": "演奏技术", "weight": 50}, {"name": "团队协作", "weight": 30}, {"name": "茶话会参与", "weight": 20}]})
    c["nodoka"].post(f"/api/performance/cycles/{cyc['id']}/activate")

    print("[9/9] 模拟薪资（上月）")
    last = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    run = c["nodoka"].post("/api/payroll/runs", json={"month": last})
    c["nodoka"].post(f"/api/payroll/runs/{run['id']}/calculate")
    print("[ok] 演示数据创建完成（全部通过真实 API）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
