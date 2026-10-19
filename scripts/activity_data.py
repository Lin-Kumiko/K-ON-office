"""Add a realistic round of day-to-day activity for the existing staff, through the REAL HTTP API.

    backend\\.venv\\Scripts\\python.exe scripts\\activity_data.py --base https://kon.example.com --passwords pw.json

`pw.json` maps username -> password ({"ui": "...", "yui": "...", ...}); keep it outside the repository.
Nothing is written to the database directly, so every record goes through validation, workflows and audit logs.
Safe to re-run: it stops if the marker announcement already exists.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date, timedelta

import httpx

MARKER = "学园祭筹备进度通报"
USERS = ["ui", "ritsu", "mio", "yui", "azusa", "ichigo", "mugi", "megumi", "fuuko", "nodoka", "himeko", "sawako", "mika"]


class Client:
    def __init__(self, base: str, user: str, password: str):
        self.user = user
        r = httpx.post(f"{base}/api/auth/login", json={"username": user, "password": password}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"[error] {user} 登录失败：{r.json().get('error', {}).get('message')}")
        body = r.json()
        self.name = body["user"]["display_name"]
        self.c = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {body['token']}"}, timeout=60)

    def call(self, method: str, url: str, expect=(200, 201), **kw):
        r = self.c.request(method, url, **kw)
        if r.status_code not in expect:
            raise RuntimeError(f"{self.user} {method} {url} -> {r.status_code} {r.text[:300]}")
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None

    def get(self, url, **kw):
        return self.call("GET", url, **kw)

    def post(self, url, json=None, **kw):
        return self.call("POST", url, json=json, **kw)

    def task_id(self, instance_id: int) -> int:
        items = self.get("/api/workflow/tasks", params={"page_size": 200})["items"]
        return next(t["id"] for t in items if t["instance_id"] == instance_id)


class World:
    def __init__(self, base: str, passwords: dict[str, str]):
        self.c = {u: Client(base, u, passwords[u]) for u in USERS}
        self.by_name = {cl.name: cl for cl in self.c.values()}
        self.ok = 0
        self.failed: list[str] = []

    def drive(self, owner: str, instance_id: int, steps: list):
        """Walk a workflow: each step is 'approve', ('approve', comment) or ('reject', comment); stops early when done."""
        for step in steps:
            inst = self.c[owner].get(f"/api/workflow/instances/{instance_id}")
            if inst["status"] != "running" or not inst["current_assignees"]:
                return inst["status"]
            actor = self.by_name[inst["current_assignees"][0]]
            kind, comment = (step, None) if isinstance(step, str) else step
            body = {"comment": comment} if comment else {}
            actor.post(f"/api/workflow/tasks/{actor.task_id(instance_id)}/{kind}", json=body)
        return self.c[owner].get(f"/api/workflow/instances/{instance_id}")["status"]

    def step(self, label: str, fn):
        try:
            fn()
            self.ok += 1
            print(f"  [ok] {label}")
        except Exception as e:  # keep going: one rejected record should not stop the rest
            self.failed.append(label)
            print(f"  [skip] {label}: {e}")


def workday(start: date, k: int) -> date:
    """k-th workday after (k > 0) or before (k < 0) start."""
    d, step = start, (1 if k > 0 else -1)
    while k:
        d += timedelta(days=step)
        if d.weekday() < 5:
            k -= step
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--passwords", required=True, help="JSON file mapping username to password")
    args = ap.parse_args()
    with open(args.passwords, encoding="utf-8") as f:
        w = World(args.base.rstrip("/"), json.load(f))
    c = w.c
    if any(a["title"] == MARKER for a in c["nodoka"].get("/api/announcements", params={"scope": "manage", "page_size": 200})["items"]):
        print("[skip] 本轮活动数据已存在")
        return 0
    today = date.today()
    types = {t["code"]: t["id"] for t in c["yui"].get("/api/leave/types")}
    cats = {x["code"]: x["id"] for x in c["yui"].get("/api/expense/categories")}
    rooms = {r["name"]: r["id"] for r in c["yui"].get("/api/meeting/rooms")}
    depts = {d["code"]: d["id"] for d in c["nodoka"].get("/api/departments")}

    def leave(user, code, start, end, reason, steps, start_half="AM", end_half="PM"):
        r = c[user].post("/api/leave/requests", params={"submit": "true"}, json={
            "leave_type_id": types[code], "start_date": str(start), "start_half": start_half, "end_date": str(end),
            "end_half": end_half, "reason": reason})
        w.drive(user, r["instance_id"], steps)

    print("[1/9] 请假")
    w.step("琴吹紬 年假（采茶季回家）", lambda: leave(
        "mugi", "annual", workday(today, 5), workday(today, 6), "家里茶园采茶季，回去帮忙", ["approve", "approve"]))
    w.step("曾我部惠 年假（已批准）", lambda: leave(
        "megumi", "annual", workday(today, 8), workday(today, 8), "季度结账后休息一天", ["approve"]))
    w.step("若王子苺 事假（待主管审批）", lambda: leave(
        "ichigo", "personal", workday(today, 3), workday(today, 3), "去区役所办手续", [], end_half="AM"))
    w.step("立花姬子 病假（已批准）", lambda: leave(
        "himeko", "sick", workday(today, -3), workday(today, -3), "发烧在家休息", ["approve", "approve"]))
    w.step("田井中律 年假（被驳回）", lambda: leave(
        "ritsu", "annual", workday(today, 4), workday(today, 4), "想去看演唱会",
        [("reject", "那天要和投资方开会，换个时间吧")]))

    print("[2/9] 加班与补卡")

    def overtime(user, day, start, end, reason, steps):
        r = c[user].post("/api/attendance/overtime", json={"start_at": f"{day}T{start}", "end_at": f"{day}T{end}",
                                                           "reason": reason, "compensation": "leave"})
        w.drive(user, r["instance_id"], steps)

    last_sat = today - timedelta(days=(today.weekday() + 2) % 7 or 7)
    w.step("秋山澪 周末加班（已批准）", lambda: overtime("mio", last_sat, "10:00:00", "15:00:00", "新曲混音", ["approve"]))
    w.step("山中佐和子 周末加班（审批中）", lambda: overtime(
        "sawako", last_sat, "13:00:00", "18:00:00", "赶制学园祭演出服", []))

    def correction(user, day, kind, time, reason, steps):
        r = c[user].post("/api/attendance/corrections", json={"work_date": str(day), "kind": kind,
                                                              "corrected_time": f"{day}T{time}", "reason": reason})
        if r.get("instance_id"):
            w.drive(user, r["instance_id"], steps)

    w.step("中野梓 补卡（已批准）", lambda: correction(
        "azusa", workday(today, -2), "out", "18:10:00", "练琴太投入忘了打卡", ["approve"]))
    w.step("高桥风子 补卡（审批中）", lambda: correction(
        "fuuko", workday(today, -1), "in", "08:55:00", "工牌落在家里", []))

    print("[3/9] 出差")

    def travel(user, dest, start, end, purpose, transport, cost, steps):
        r = c[user].post("/api/travel", params={"submit": "true"}, json={
            "destination": dest, "start_date": str(start), "end_date": str(end), "purpose": purpose,
            "transport": transport, "estimated_cost": cost})
        w.drive(user, r["instance_id"], steps)

    w.step("秋山澪 东京录音（已批准）", lambda: travel(
        "mio", "东京·录音棚", workday(today, 7), workday(today, 9), "新专辑人声录制", "新干线", "4200.00",
        ["approve", "approve"]))
    w.step("山中佐和子 采购面料（审批中）", lambda: travel(
        "sawako", "大阪·布料市场", workday(today, 10), workday(today, 10), "采购学园祭演出服面料", "电车", "800.00", []))

    print("[4/9] 费用报销")

    def receipt(user, name):
        return c[user].call("POST", "/api/files", files={"file": (name, io.BytesIO(b"%PDF-1.4 synthetic receipt"),
                                                                  "application/pdf")}, data={"purpose": "expense_receipt"})["id"]

    def claim(user, title, items, steps, finance=False):
        r = c[user].post("/api/expense/claims", params={"submit": "true"}, json={"title": title, "items": items})
        status = w.drive(user, r["instance_id"], steps)
        if finance and status == "approved":
            c["fuuko"].post(f"/api/expense/claims/{r['id']}/finance-confirm", json={"note": "已模拟付款"})

    def item(code, days_ago, amount, desc, file_id=None):
        out = {"category_id": cats[code], "occurred_on": str(today - timedelta(days=days_ago)), "amount": amount,
               "description": desc}
        if file_id:
            out["receipt_file_id"] = file_id
        return out

    w.step("琴吹紬 茶叶与点心（已付款）", lambda: claim("mugi", "十月茶会茶叶与点心", [
        item("tea", 6, "386.00", "大吉岭红茶两罐", receipt("mugi", "tea.pdf")),
        item("tea", 4, "248.50", "草莓蛋糕与马卡龙")], ["approve", "approve", "approve"], finance=True))
    w.step("田井中律 鼓棒与鼓皮（审批中）", lambda: claim("ritsu", "鼓棒与军鼓鼓皮", [
        item("instrument", 3, "520.00", "鼓棒三副"), item("instrument", 3, "760.00", "军鼓鼓皮")], []))
    w.step("山中佐和子 演出服面料（待财务确认）", lambda: claim("sawako", "学园祭演出服面料", [
        item("costume", 5, "1680.00", "缎面布料 12 米", receipt("sawako", "fabric.pdf"))], ["approve", "approve", "approve"]))
    w.step("中野梓 吉他弦（被驳回）", lambda: claim("azusa", "吉他弦", [
        item("instrument", 2, "95.00", "吉他弦一套")], [("reject", "上周已经报过同一笔，请核对后重新提交")]))

    print("[5/9] 会议室")
    bookings = [
        ("ritsu", "讲堂", 1, "10:00:00", "11:30:00", "学园祭筹备周会"),
        ("nodoka", "茶歇室", 2, "14:00:00", "15:00:00", "新成员入职面谈"),
        ("megumi", "茶歇室", 3, "10:00:00", "11:00:00", "十月预算复盘"),
        ("yui", "音乐准备室", 4, "15:30:00", "17:30:00", "Live 曲目合练"),
        ("mio", "音乐准备室", 6, "15:30:00", "17:00:00", "新曲编曲讨论"),
    ]
    for user, room, k, start, end, subject in bookings:
        if room not in rooms:
            continue
        d = workday(today, k)
        w.step(f"{subject}（{room}）", lambda u=user, r=room, d=d, s=start, e=end, t=subject: c[u].post(
            "/api/meeting/bookings", json={"room_id": rooms[r], "subject": t, "start_at": f"{d}T{s}", "end_at": f"{d}T{e}"}))

    print("[6/9] 公告与文档")
    acat = c["nodoka"].get("/api/announcements/categories")[0]["id"]

    def announce(title, content, dept=None, pinned=False):
        body = {"title": title, "content": content, "category_id": acat, "pinned": pinned}
        if dept:
            body.update(scope_type="departments", scope_department_ids=[depts[dept]])
        a = c["nodoka"].post("/api/announcements", json=body)
        c["nodoka"].post(f"/api/announcements/{a['id']}/publish")

    w.step("公告：报销提交说明", lambda: announce(
        "十月报销提交说明", "本月报销请在 28 日前提交，茶点类单笔不超过 2000 元，乐器维修请附上发票。"))
    w.step("公告：音乐准备室维护", lambda: announce(
        "音乐准备室设备维护", "周五下午调音台和音箱例行检修，期间暂停预约。", dept="MUSIC"))

    def doc(user, fname, text, title, visibility, keywords, mime="text/markdown"):
        c[user].call("POST", "/api/documents", files={"file": (fname, io.BytesIO(text.encode()), mime)},
                     data={"title": title, "visibility": visibility, "keywords": keywords})

    w.step("文档：学园祭节目单", lambda: doc("ritsu", "festival.md",
                                     "# 学园祭节目单\n1. 轻飘飘时间\n2. 米饭是配菜\n3. 给你的歌\n", "学园祭节目单", "public", "学园祭,演出"))
    w.step("文档：演出设备清单", lambda: doc("yui", "gear.md",
                                     "# 演出设备清单\n- 吉他 ×2\n- 贝斯 ×1\n- 键盘 ×1\n- 鼓组 ×1\n", "演出设备清单", "department", "设备"))
    w.step("文档：茶点采购记录", lambda: doc("mugi", "tea-log.md",
                                     "# 十月茶点采购记录\n- 大吉岭红茶\n- 草莓蛋糕\n", "十月茶点采购记录", "department", "茶点,采购"))

    print("[7/9] 日程")
    for user, k, start, end, title in [
            ("yui", 1, "19:00:00", "20:00:00", "在家练习新曲"), ("mio", 2, "20:00:00", "21:00:00", "写歌词"),
            ("nodoka", 1, "09:30:00", "10:00:00", "整理入职材料"), ("ui", 2, "16:00:00", "16:30:00", "检查系统备份")]:
        d = workday(today, k)
        w.step(f"日程：{title}", lambda u=user, d=d, s=start, e=end, t=title: c[u].post(
            "/api/schedules", json={"title": t, "start_at": f"{d}T{s}", "end_at": f"{d}T{e}"}))

    print("[8/9] 绩效自评与主管评价")
    self_scores = {"yui": (88, 92, 98), "azusa": (93, 85, 80), "ichigo": (82, 80, 75), "mio": (95, 88, 85),
                   "fuuko": (80, 86, 90)}

    def self_review(user, scores, comment):
        mine = [r for r in c[user].get("/api/performance/reviews")["items"] if r["status"] in ("self_pending", "pending")]
        if not mine:
            raise RuntimeError("没有待自评的绩效")
        r = mine[0]
        ind = [str(i["id"]) for i in r["indicators"]]
        c[user].post(f"/api/performance/reviews/{r['id']}/self", json={"scores": dict(zip(ind, scores)), "comment": comment})
        return r

    for user, scores in self_scores.items():
        w.step(f"自评：{c[user].name}", lambda u=user, s=scores: self_review(u, s, "这半年认真练习，也按时参加茶会"))

    def manager_review(manager, employee_name, scores, comment):
        team = c[manager].get("/api/performance/reviews", params={"scope": "team"})["items"]
        r = next(x for x in team if x["employee_name"] == employee_name)
        ind = [str(i["id"]) for i in r["indicators"]]
        c[manager].post(f"/api/performance/reviews/{r['id']}/manager", json={"scores": dict(zip(ind, scores)), "comment": comment})

    w.step("主管评价：中野梓", lambda: manager_review("yui", "中野梓", (95, 90, 85), "技术扎实，带动大家认真练习"))

    print("[9/9] 招聘")

    def recruit():
        req = c["nodoka"].post("/api/recruitment/requisitions", json={"title": "宣传设计", "department_id": depts["HTT"],
                                                                      "headcount": 1})
        mugi_id = c["mugi"].get("/api/auth/me")["id"]
        for name, email, source, result in [("铃木纯", "jun.design@htt.example", "校园招聘", "pass"),
                                            ("佐藤明", "akira@htt.example", "招聘网站", None)]:
            cand = c["nodoka"].post("/api/recruitment/candidates", json={"requisition_id": req["id"], "name": name,
                                                                         "gender": "女", "email": email, "source": source})
            iv = c["nodoka"].post(f"/api/recruitment/candidates/{cand['id']}/interviews",
                                  json={"interviewer_id": mugi_id, "scheduled_at": f"{workday(today, 2)}T15:00:00"})
            if result:
                c["mugi"].post(f"/api/recruitment/interviews/{iv['id']}/result",
                               json={"score": 88, "feedback": "作品集很有想法", "result": result})

    w.step("招聘：宣传设计岗（两位候选人）", recruit)

    w.step("公告：学园祭筹备进度", lambda: announce(
        MARKER, "节目单已定稿，演出服本周完成打样；周三上午在讲堂开筹备周会，请各部门准时参加。", pinned=False))
    print(f"[done] 成功 {w.ok} 项，跳过 {len(w.failed)} 项")
    return 0 if not w.failed else 1


if __name__ == "__main__":
    sys.exit(main())
