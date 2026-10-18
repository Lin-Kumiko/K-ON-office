"""Workflow engine: parallel join, and/or-sign, transfer, versioning, approver fallback, illegal transitions,
business-transaction rollback and history integrity."""
import copy

import pytest

from app.workflow.graph import evaluate, validate_graph
from tests.conftest import err, ok


def _task(api, instance_id):
    return next(t for t in ok(api.get("/api/workflow/tasks"))["items"] if t["instance_id"] == instance_id)


def _dept(api, code):
    return next(d for d in ok(api.get("/api/departments")) if d["code"] == code)


def _emp(api, name):
    return next(e for e in ok(api.get("/api/employees/options")) if e["name"] == name)


def _def(api, key):
    return next(d for d in ok(api.get("/api/workflow/definitions")) if d["key"] == key)


# ------------------------------------------------------------------ pure units
VARS = {"amount": "number", "days": "number", "leave_type": "string"}


def g(nodes, edges):
    return {"nodes": [{"id": i, "type": t, "name": i, **({"config": c} if c else {})} for i, t, c in nodes],
            "edges": [{"id": f"e{n}", "source": s, "target": t, **extra} for n, (s, t, extra) in enumerate(edges)]}


APPROVE = {"approver": {"type": "direct_manager"}}


@pytest.mark.parametrize("graph,needle", [
    (g([("s", "start", None), ("a", "approval", APPROVE)], [("s", "a", {})]), "结束节点"),
    (g([("s", "start", None), ("a", "approval", APPROVE), ("b", "approval", APPROVE), ("e", "end", None)],
       [("s", "a", {}), ("a", "b", {}), ("b", "a", {}), ("b", "e", {})]), "必须有且只有一条出线"),
    (g([("s", "start", None), ("c", "condition", None), ("e", "end", None), ("f", "end", None)],
       [("s", "c", {}), ("c", "e", {"condition": {"field": "amount", "op": ">", "value": 1}}),
        ("c", "f", {"condition": {"field": "amount", "op": "<=", "value": 1}})]), "默认出线"),
    (g([("s", "start", None), ("c", "condition", None), ("e", "end", None), ("f", "end", None)],
       [("s", "c", {}), ("c", "e", {"condition": {"field": "salary", "op": ">", "value": 1}}),
        ("c", "f", {"default": True})]), "不是该业务类型可用变量"),
    (g([("s", "start", None), ("c", "condition", None), ("e", "end", None), ("f", "end", None)],
       [("s", "c", {}), ("c", "e", {"condition": {"field": "leave_type", "op": ">", "value": 1}}),
        ("c", "f", {"default": True})]), "不是数值"),
    (g([("s", "start", None), ("p", "parallel", None), ("a", "approval", APPROVE), ("b", "approval", APPROVE),
        ("e", "end", None), ("f", "end", None)],
       [("s", "p", {}), ("p", "a", {}), ("p", "b", {}), ("a", "e", {}), ("b", "f", {})]), "未经汇聚"),
    (g([("s", "start", None), ("a", "approval", {"approver": {"type": "role", "role_code": "nope"}}),
        ("e", "end", None)], [("s", "a", {}), ("a", "e", {})]), "角色"),
    (g([("s", "start", None), ("a", "approval", {"approver": {"type": "user", "user_ids": [99999]}}),
        ("e", "end", None)], [("s", "a", {}), ("a", "e", {})]), "user_ids"),
    (g([("s", "start", None), ("a", "approval", APPROVE), ("x", "approval", APPROVE), ("e", "end", None)],
       [("s", "a", {}), ("a", "e", {}), ("x", "e", {})]), "没有入线"),
])
def test_invalid_graphs_are_rejected(graph, needle):
    errors = validate_graph(graph, VARS, {"hr", "admin"}, {1, 2})
    assert errors and any(needle in e for e in errors), errors


def test_condition_language_is_data_only():
    v = {"amount": 5000.5, "leave_type": "annual"}
    assert evaluate({"all": [{"field": "amount", "op": ">", "value": "5000"}]}, v)
    assert not evaluate({"field": "amount", "op": "<=", "value": 5000}, v)
    assert evaluate({"any": [{"field": "leave_type", "op": "in", "value": ["sick", "annual"]}]}, v)
    assert not evaluate({"field": "missing", "op": "==", "value": 1}, v)
    # code-looking values are compared as plain strings, never executed
    assert not evaluate({"field": "leave_type", "op": "==", "value": "__import__('os').system('x')"}, v)


# ------------------------------------------------------------------ API-level engine behaviour
def test_parallel_transfer_with_join_and_history(as_user, sql):
    hr = as_user("nodoka")
    ichigo = _emp(hr, "若王子苺")
    costume = _dept(hr, "COSTUME")
    tr = ok(hr.post("/api/transfers", json={"employee_id": ichigo["id"], "to_department_id": costume["id"],
                                            "effective_date": "2026-11-01", "reason": "去做学园祭话剧服装"}), 201)
    inst = ok(hr.get(f"/api/workflow/instances/{tr['instance_id']}"))
    assert set(inst["current_nodes"]) == {"调出部门负责人", "调入部门负责人"}
    yui, sawako = as_user("yui"), as_user("sawako")  # LIVE manager and COSTUME manager
    ok(sawako.post(f"/api/workflow/tasks/{_task(sawako, tr['instance_id'])['id']}/approve", json={}))
    inst = ok(hr.get(f"/api/workflow/instances/{tr['instance_id']}"))
    assert inst["current_nodes"] == ["调出部门负责人"]  # join waits for the other branch
    ok(yui.post(f"/api/workflow/tasks/{_task(yui, tr['instance_id'])['id']}/approve", json={}))
    inst = ok(hr.get(f"/api/workflow/instances/{tr['instance_id']}"))
    assert inst["current_nodes"] == ["人事审批"]
    # nodoka initiated but is not the subject: she may approve
    ok(hr.post(f"/api/workflow/tasks/{_task(hr, tr['instance_id'])['id']}/approve", json={}))
    detail = ok(hr.get(f"/api/workflow/instances/{tr['instance_id']}"))
    assert detail["status"] == "approved"
    actions = [h["action"] for h in detail["history"]]
    assert actions[0] == "start" and actions[-1] == "end"
    assert actions.count("join_arrive") == 2 and "fork" in actions
    assert detail["node_states"]["join"] == "completed"
    emp = ok(hr.get(f"/api/employees/{ichigo['id']}"))
    assert emp["department_id"] == costume["id"] and emp["manager_name"] == "山中佐和子"
    assert ok(hr.get(f"/api/employees/{ichigo['id']}/history"))[-1]["change_type"] == "transfer"


def test_parallel_branch_rejection_stops_everything(as_user):
    hr = as_user("nodoka")
    ichigo = _emp(hr, "若王子苺")
    tr = ok(hr.post("/api/transfers", json={"employee_id": ichigo["id"], "to_department_id": _dept(hr, "TEA")["id"],
                                            "effective_date": "2026-11-01", "reason": "试试茶点"}), 201)
    yui = as_user("yui")
    ok(yui.post(f"/api/workflow/tasks/{_task(yui, tr['instance_id'])['id']}/reject", json={"comment": "演出组缺人"}))
    detail = ok(hr.get(f"/api/workflow/instances/{tr['instance_id']}"))
    assert detail["status"] == "rejected"
    assert {t["status"] for t in detail["tasks"]} == {"rejected", "cancelled"}
    assert ok(hr.get(f"/api/transfers/{tr['id']}"))["status"] == "rejected"
    assert ok(hr.get(f"/api/employees/{ichigo['id']}"))["department_name"] == "现场演出组"
    mugi = as_user("mugi")
    other = next(t for t in detail["tasks"] if t["status"] == "cancelled")
    err(mugi.post(f"/api/workflow/tasks/{other['id']}/approve", json={}), 409, "TASK_ALREADY_HANDLED")


def test_transfer_task_and_admin_reassign(as_user):
    yui, mio = as_user("yui"), as_user("mio")
    lt = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["leave_type_id"]
    leave = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-05", "start_half": "AM", "end_date": "2026-11-05",
        "end_half": "PM", "reason": "体检"}), 201)
    t = _task(mio, leave["instance_id"])
    ritsu_id = ok(as_user("ritsu").get("/api/auth/me"))["id"]
    yui_id = ok(yui.get("/api/auth/me"))["id"]
    err(mio.post(f"/api/workflow/tasks/{t['id']}/transfer", json={"to_user_id": yui_id}), 422,
        "INVALID_TRANSFER_TARGET")  # never to the applicant
    new = ok(mio.post(f"/api/workflow/tasks/{t['id']}/transfer", json={"to_user_id": ritsu_id, "comment": "我在录音"}))
    assert new["assignee_id"] == ritsu_id and new["status"] == "pending"
    err(mio.post(f"/api/workflow/tasks/{t['id']}/approve", json={}), 409, "TASK_ALREADY_HANDLED")
    # admin re-assigns the pending task to mugi (e.g. ritsu is on vacation)
    mugi_id = ok(as_user("mugi").get("/api/auth/me"))["id"]
    err(mio.post(f"/api/workflow/tasks/{new['id']}/reassign", json={"to_user_id": mugi_id}), 403)
    again = ok(as_user("ui").post(f"/api/workflow/tasks/{new['id']}/reassign", json={"to_user_id": mugi_id}))
    ok(as_user("mugi").post(f"/api/workflow/tasks/{again['id']}/approve", json={}))
    hist = [h["action"] for h in ok(yui.get(f"/api/workflow/instances/{leave['instance_id']}"))["history"]]
    assert "transfer" in hist and "reassign" in hist and hist[-1] == "end"


def test_withdraw_cancel_and_illegal_transitions(as_user, sql):
    yui, mio = as_user("yui"), as_user("mio")
    lt = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["leave_type_id"]
    body = {"leave_type_id": lt, "start_date": "2026-11-09", "start_half": "AM", "end_date": "2026-11-09",
            "end_half": "AM", "reason": "x"}
    draft = ok(yui.post("/api/leave/requests", json=body), 201)
    # not submitted -> no workflow -> nothing to approve / withdraw
    err(yui.post(f"/api/leave/requests/{draft['id']}/withdraw"), 409, "INVALID_STATE")
    sub = ok(yui.post(f"/api/leave/requests/{draft['id']}/submit"))
    err(mio.post(f"/api/workflow/instances/{sub['instance_id']}/withdraw"), 403, "NOT_INITIATOR")
    ok(yui.post(f"/api/leave/requests/{draft['id']}/withdraw"))
    assert ok(yui.get(f"/api/leave/requests/{draft['id']}"))["status"] == "withdrawn"
    err(yui.post(f"/api/workflow/instances/{sub['instance_id']}/withdraw"), 409, "INSTANCE_NOT_RUNNING")
    task = ok(mio.get("/api/workflow/tasks?status=all"))["items"][0]
    err(mio.post(f"/api/workflow/tasks/{task['id']}/approve", json={}), 409)
    # resubmit then cancel -> terminal; cannot be resubmitted
    sub2 = ok(yui.post(f"/api/leave/requests/{draft['id']}/submit"))
    ok(yui.post(f"/api/leave/requests/{draft['id']}/cancel"))
    assert ok(yui.get(f"/api/workflow/instances/{sub2['instance_id']}"))["status"] == "cancelled"
    err(yui.post(f"/api/leave/requests/{draft['id']}/submit"), 409, "INVALID_STATE")
    err(yui.put(f"/api/leave/requests/{draft['id']}", json=body), 409, "INVALID_STATE")
    bal = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")
    assert bal["pending_hours"] == 0 and bal["used_hours"] == 0


def test_new_version_does_not_change_running_instances(as_user):
    admin, yui, mio = as_user("ui"), as_user("yui"), as_user("mio")
    d = _def(admin, "travel")
    old = ok(yui.post("/api/travel?submit=true", json={"destination": "琴吹家别墅", "start_date": "2026-11-10",
                                                      "end_date": "2026-11-12", "purpose": "合宿"}), 201)
    # publish v2: manager -> HR
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/draft"))
    graph = copy.deepcopy(ok(admin.get(f"/api/workflow/definitions/{d['id']}"))["versions"][0]["graph"])
    graph["nodes"].insert(2, {"id": "hr", "type": "approval", "name": "人事备案",
                              "config": {"approver": {"type": "hr_admin"}}, "x": 400, "y": 200})
    graph["edges"] = [{"id": "e1", "source": "start", "target": "mgr"}, {"id": "e2", "source": "mgr", "target": "hr"},
                      {"id": "e3", "source": "hr", "target": "end"}]
    ok(admin.put(f"/api/workflow/definitions/{d['id']}/draft", json={"graph": graph}))
    published = ok(admin.post(f"/api/workflow/definitions/{d['id']}/publish"))
    assert published["current_version"] == 2
    assert [v["status"] for v in published["versions"]] == ["published", "archived"]
    new = ok(yui.post("/api/travel?submit=true", json={"destination": "Live House", "start_date": "2026-11-20",
                                                      "end_date": "2026-11-20", "purpose": "演出"}), 201)
    assert ok(yui.get(f"/api/workflow/instances/{old['instance_id']}"))["version"] == 1
    assert ok(yui.get(f"/api/workflow/instances/{new['instance_id']}"))["version"] == 2
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, old['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/travel/{old['id']}"))["status"] == "approved"  # old graph: finished after manager
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, new['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/workflow/instances/{new['instance_id']}"))["current_nodes"] == ["人事备案"]
    # published versions are immutable; an invalid draft cannot be published
    err(admin.put(f"/api/workflow/definitions/{d['id']}/draft", json={"graph": graph}), 409, "NO_DRAFT")
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/draft"))
    bad = copy.deepcopy(graph)
    bad["edges"].append({"id": "loop", "source": "hr", "target": "mgr"})
    ok(admin.put(f"/api/workflow/definitions/{d['id']}/draft", json={"graph": bad}))
    e = err(admin.post(f"/api/workflow/definitions/{d['id']}/publish"), 422, "INVALID_GRAPH")
    assert e["error"]["details"]


def test_disabled_definition_blocks_new_submissions_only(as_user):
    admin, yui = as_user("ui"), as_user("yui")
    d = _def(admin, "travel")
    running = ok(yui.post("/api/travel?submit=true", json={"destination": "A", "start_date": "2026-11-10",
                                                          "end_date": "2026-11-10", "purpose": "p"}), 201)
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/status", json={"status": "disabled"}))
    err(yui.post("/api/travel?submit=true", json={"destination": "B", "start_date": "2026-11-12",
                                                 "end_date": "2026-11-12", "purpose": "p"}), 409, "NO_ACTIVE_WORKFLOW")
    mio = as_user("mio")
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, running['instance_id'])['id']}/approve", json={}))
    assert ok(yui.get(f"/api/travel/{running['id']}"))["status"] == "approved"


def test_unavailable_approver_escalates_and_falls_back(as_user, sql):
    admin, hr = as_user("ui"), as_user("nodoka")
    # mio (yui's manager) is disabled -> yui's request escalates to ritsu
    mio_uid = ok(as_user("mio").get("/api/auth/me"))["id"]
    ok(admin.post(f"/api/users/{mio_uid}/status", json={"status": "disabled"}))
    yui = as_user("yui")
    t = ok(yui.post("/api/travel?submit=true", json={"destination": "A", "start_date": "2026-11-10",
                                                    "end_date": "2026-11-10", "purpose": "p"}), 201)
    detail = ok(yui.get(f"/api/workflow/instances/{t['instance_id']}"))
    assert detail["current_assignees"] == ["田井中律"]
    assert any(h["action"] == "escalate" for h in detail["history"])
    # nodoka's own leave: HR role users minus herself = himeko; ritsu approves as manager
    lt = next(b for b in ok(hr.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["leave_type_id"]
    lv = ok(hr.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-16", "start_half": "AM", "end_date": "2026-11-20",
        "end_half": "PM", "reason": "学生会同学聚会旅行"}), 201)
    ritsu = as_user("ritsu")
    ok(ritsu.post(f"/api/workflow/tasks/{_task(ritsu, lv['instance_id'])['id']}/approve", json={}))
    detail = ok(hr.get(f"/api/workflow/instances/{lv['instance_id']}"))
    assert detail["current_assignees"] == ["立花姬子"]
    # disabling an assignee moves their pending task automatically
    himeko_uid = ok(as_user("himeko").get("/api/auth/me"))["id"]
    ok(admin.post(f"/api/users/{himeko_uid}/status", json={"status": "disabled"}))
    detail = ok(hr.get(f"/api/workflow/instances/{lv['instance_id']}"))
    assert detail["current_assignees"] and "立花姬子" not in detail["current_assignees"]
    assert any(h["action"] == "reassign" for h in detail["history"])


def test_business_failure_rolls_back_approval(as_user, sql):
    """If the business callback fails, the approval step is rolled back and the task stays pending."""
    hr = as_user("nodoka")
    ichigo = _emp(hr, "若王子苺")
    tr = ok(hr.post("/api/transfers", json={"employee_id": ichigo["id"], "to_department_id": _dept(hr, "TEA")["id"],
                                            "effective_date": "2026-11-01", "reason": "r"}), 201)
    for u in ("yui", "mugi"):
        api = as_user(u)
        ok(api.post(f"/api/workflow/tasks/{_task(api, tr['instance_id'])['id']}/approve", json={}))
    # meanwhile the target department is disabled -> approval cannot take effect
    tea = _dept(hr, "TEA")
    admin = as_user("ui")
    # move TEA members out first so it can be disabled
    mugi_emp = _emp(hr, "琴吹紬")
    emp = ok(hr.get(f"/api/employees/{mugi_emp['id']}"))
    emp.update({"department_id": _dept(hr, "HTT")["id"]})
    ok(hr.put(f"/api/employees/{mugi_emp['id']}", json={k: emp[k] for k in (
        "version", "name", "gender", "birth_date", "phone", "email", "department_id", "position_id", "manager_id",
        "remark")}))
    ok(admin.post(f"/api/departments/{tea['id']}/disable"))
    t = _task(hr, tr["instance_id"])
    err(hr.post(f"/api/workflow/tasks/{t['id']}/approve", json={}), 422, "DEPARTMENT_DISABLED")
    assert sql("SELECT status FROM wf_tasks WHERE id=?", id=t["id"])[0][0] == "pending"
    assert sql("SELECT status FROM wf_instances WHERE id=?", id=tr["instance_id"])[0][0] == "running"
    assert sql("SELECT status FROM transfer_requests WHERE id=?", id=tr["id"])[0][0] == "pending"
    # recovery: re-enable the department and retry the same task
    ok(admin.post(f"/api/departments/{tea['id']}/enable"))
    ok(hr.post(f"/api/workflow/tasks/{t['id']}/approve", json={}))
    assert ok(hr.get(f"/api/transfers/{tr['id']}"))["status"] == "approved"


def test_duplicate_running_instance_is_refused(as_user, app):
    """Directly starting a second running instance for the same document is rejected by the engine."""
    from app.core.errors import Conflict
    from app.workflow import engine
    yui = as_user("yui")
    t = ok(yui.post("/api/travel?submit=true", json={"destination": "A", "start_date": "2026-11-10",
                                                    "end_date": "2026-11-10", "purpose": "p"}), 201)
    with app.state.db.session(write=True) as s:
        with pytest.raises(Conflict):
            engine.start(s, business_type="travel", business_id=t["id"], title="dup", initiator_id=1,
                         subject_employee_id=None, variables={})
        s.rollback()


def test_task_visibility_and_cc(as_user):
    yui = as_user("yui")
    lt = next(b for b in ok(yui.get("/api/leave/balances")) if b["leave_type_code"] == "annual")["leave_type_id"]
    lv = ok(yui.post("/api/leave/requests?submit=true", json={
        "leave_type_id": lt, "start_date": "2026-11-11", "start_half": "AM", "end_date": "2026-11-11",
        "end_half": "PM", "reason": "x"}), 201)
    err(as_user("mika").get(f"/api/workflow/instances/{lv['instance_id']}"), 403)
    mio = as_user("mio")
    ok(mio.post(f"/api/workflow/tasks/{_task(mio, lv['instance_id'])['id']}/approve", json={}))
    cc = ok(as_user("himeko").get("/api/workflow/cc"))["items"]
    assert cc and cc[0]["instance_id"] == lv["instance_id"]
    ok(as_user("himeko").get(f"/api/workflow/instances/{lv['instance_id']}"))  # cc user may view
    ok(as_user("himeko").post(f"/api/workflow/cc/{cc[0]['id']}/read"))
    assert ok(as_user("mio").get("/api/workflow/tasks?status=done"))["total"] == 1


def test_amount_based_approver_strategy_at_runtime(as_user):
    """expense v2: a single approval node whose approver depends on the amount."""
    admin, yui = as_user("ui"), as_user("yui")
    d = _def(admin, "expense")
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/draft"))
    graph = {"nodes": [
        {"id": "start", "type": "start", "name": "开始", "x": 60, "y": 100},
        {"id": "amt", "type": "approval", "name": "按金额审批", "x": 220, "y": 100, "config": {"approver": {
            "type": "amount_based", "field": "amount", "rules": [
                {"max": 1000, "approver": {"type": "direct_manager"}},
                {"max": None, "approver": {"type": "role", "role_code": "ceo"}}]}}},
        {"id": "end", "type": "end", "name": "结束", "x": 380, "y": 100}],
        "edges": [{"id": "e1", "source": "start", "target": "amt"}, {"id": "e2", "source": "amt", "target": "end"}]}
    ok(admin.put(f"/api/workflow/definitions/{d['id']}/draft", json={"graph": graph}))
    ok(admin.post(f"/api/workflow/definitions/{d['id']}/publish"))
    cat = ok(yui.get("/api/expense/categories"))[0]["id"]
    small = ok(yui.post("/api/expense/claims?submit=true", json={"title": "小额", "items": [
        {"category_id": cat, "occurred_on": "2026-10-10", "amount": "999.99"}]}), 201)
    big = ok(yui.post("/api/expense/claims?submit=true", json={"title": "大额", "items": [
        {"category_id": cat, "occurred_on": "2026-10-10", "amount": "1000.01"}]}), 201)
    assert ok(yui.get(f"/api/workflow/instances/{small['instance_id']}"))["current_assignees"] == ["秋山澪"]
    assert ok(yui.get(f"/api/workflow/instances/{big['instance_id']}"))["current_assignees"] == ["田井中律"]
