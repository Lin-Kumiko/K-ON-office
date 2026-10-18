"""Workflow runtime.

State machines
--------------
Instance: running -> approved | rejected | withdrawn | cancelled   (all terminal)
Task:     pending -> approved | rejected | transferred | cancelled (all terminal)

Every public function runs inside the caller's write transaction (BEGIN IMMEDIATE),
mutates engine tables and invokes the business handler in the same transaction.
The caller commits once; any exception rolls back engine *and* business changes, so
a failed business callback leaves the task pending and can simply be retried.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..core import timeutil
from ..core.common import notify
from ..core.errors import AppError, Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..models import (Department, Employee, Role, User, WfCc, WfDefinition, WfDefinitionVersion, WfHistory,
                      WfInstance, WfJoinArrival, WfNodeActivation, WfTask, user_roles)
from . import registry
from .graph import Graph, evaluate

_graph_cache: dict[int, Graph] = {}


def graph_for(db: Session, version_id: int) -> Graph:
    g = _graph_cache.get(version_id)
    if g is None:
        ver = db.get(WfDefinitionVersion, version_id)
        g = Graph(ver.graph)
        if ver.status != "draft":  # published/archived graphs are immutable
            _graph_cache[version_id] = g
    return g


class WorkflowError(AppError):
    status_code = 409
    code = "WORKFLOW_ERROR"


# ------------------------------------------------------------------ helpers
def _history(db: Session, inst: WfInstance, action: str, actor_id: int | None = None, node: dict | None = None,
             task: WfTask | None = None, comment: str | None = None, detail: dict | None = None) -> None:
    db.add(WfHistory(instance_id=inst.id, task_id=task.id if task else None,
                     node_id=node["id"] if node else (task.node_id if task else None),
                     node_name=node.get("name") if node else (task.node_name if task else None),
                     action=action, actor_id=actor_id, comment=comment, detail=detail))


def _role_users(db: Session, code: str) -> list[int]:
    return list(db.scalars(
        select(User.id).join(user_roles, user_roles.c.user_id == User.id).join(Role, Role.id == user_roles.c.role_id)
        .where(Role.code == code, User.status == "active").order_by(User.id)))


def _employee_user(db: Session, emp_id: int | None) -> int | None:
    if not emp_id:
        return None
    emp = db.get(Employee, emp_id)
    if emp is None or emp.status == "resigned" or emp.user_id is None:
        return None
    return emp.user_id


def _manager_chain(db: Session, emp_id: int | None, levels: int = 6) -> list[int]:
    """Employee ids of the management chain above emp_id (direct manager first)."""
    out, seen = [], set()
    cur = db.get(Employee, emp_id) if emp_id else None
    while cur is not None and cur.manager_id and len(out) < levels and cur.manager_id not in seen:
        seen.add(cur.manager_id)
        out.append(cur.manager_id)
        cur = db.get(Employee, cur.manager_id)
    return out


def _dept_manager_chain(db: Session, dept_id: int | None, levels: int = 6) -> list[int]:
    out, seen = [], set()
    dept = db.get(Department, dept_id) if dept_id else None
    while dept is not None and len(out) < levels and dept.id not in seen:
        seen.add(dept.id)
        if dept.manager_employee_id:
            out.append(dept.manager_employee_id)
        dept = db.get(Department, dept.parent_id) if dept.parent_id else None
    return out


def resolve_users(db: Session, cfg: dict, inst: WfInstance) -> tuple[list[int], str | None]:
    """Return (active user ids, note). The subject of the request is never their own approver;
    manager-type strategies escalate up the chain when the resolved person is unavailable."""
    subject_user = inst.subject_user_id
    variables = inst.variables or {}
    t = cfg.get("type")
    note = None

    def usable(uid: int | None) -> bool:
        if uid is None or uid == subject_user:
            return False
        u = db.get(User, uid)
        return u is not None and u.status == "active"

    if t == "user":
        ids = [u for u in cfg.get("user_ids", []) if usable(u)]
    elif t in ("role", "hr_admin"):
        ids = [u for u in _role_users(db, cfg.get("role_code", "hr") if t == "role" else "hr") if usable(u)]
    elif t == "direct_manager":
        ids = []
        for i, emp_id in enumerate(_manager_chain(db, inst.subject_employee_id)):
            uid = _employee_user(db, emp_id)
            if usable(uid):
                ids = [uid]
                if i:
                    note = f"直属主管不可用，已上溯 {i} 级"
                break
    elif t == "department_manager":
        var = cfg.get("department_var")
        dept_id = variables.get(var) if var else None
        if dept_id is None and inst.subject_employee_id:
            emp = db.get(Employee, inst.subject_employee_id)
            dept_id = emp.department_id if emp else None
        chain = _dept_manager_chain(db, dept_id)
        level = int(cfg.get("level", 1))
        ids = []
        for i, emp_id in enumerate(chain[level - 1:]):
            uid = _employee_user(db, emp_id)
            if usable(uid):
                ids = [uid]
                if i:
                    note = "部门负责人不可用或为申请人本人，已上溯上级部门"
                break
    elif t == "amount_based":
        field = cfg.get("field", "amount")
        value = variables.get(field)
        chosen = None
        for rule in cfg.get("rules", []):
            mx = rule.get("max")
            if mx is None or (value is not None and evaluate({"field": field, "op": "<=", "value": mx}, variables)):
                chosen = rule["approver"]
                break
        if chosen is None:
            return [], "金额规则未匹配"
        return resolve_users(db, chosen, inst)
    else:
        raise WorkflowError(f"未知审批人策略：{t}")
    return list(dict.fromkeys(ids)), note


# ------------------------------------------------------------------ start
def start(db: Session, *, business_type: str, business_id: int, title: str, initiator_id: int,
          subject_employee_id: int | None, variables: dict) -> WfInstance:
    if business_type not in registry.BUSINESS_TYPES:
        raise ValidationFailed(f"未知业务类型：{business_type}")
    definition = db.scalar(select(WfDefinition).where(
        WfDefinition.business_type == business_type, WfDefinition.status == "active",
        WfDefinition.current_version_id.is_not(None)).order_by(WfDefinition.id))
    if definition is None:
        raise WorkflowError(f"业务类型 {registry.BUSINESS_TYPES[business_type]['name']} 没有已发布的启用流程",
                            code="NO_ACTIVE_WORKFLOW")
    running = db.scalar(select(WfInstance.id).where(WfInstance.business_type == business_type,
                                                    WfInstance.business_id == business_id,
                                                    WfInstance.status == "running"))
    if running:
        raise Conflict("该单据已有进行中的审批流程", code="INSTANCE_ALREADY_RUNNING")
    subject_user = _employee_user(db, subject_employee_id) if subject_employee_id else None
    inst = WfInstance(definition_id=definition.id, version_id=definition.current_version_id,
                      business_type=business_type, business_id=business_id, title=title[:200],
                      initiator_id=initiator_id, subject_employee_id=subject_employee_id,
                      subject_user_id=subject_user, status="running", variables=variables,
                      started_at=timeutil.now())
    db.add(inst)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise Conflict("该单据已有进行中的审批流程", code="INSTANCE_ALREADY_RUNNING") from exc
    g = graph_for(db, inst.version_id)
    ver = db.get(WfDefinitionVersion, inst.version_id)
    _history(db, inst, "start", initiator_id, detail={"definition": definition.key, "version": ver.version})
    _enter(db, inst, g, g.start_id(), None, initiator_id)
    db.flush()
    return inst


def _activate(db: Session, inst: WfInstance, node_id: str) -> None:
    try:
        with db.begin_nested():
            db.add(WfNodeActivation(instance_id=inst.id, node_id=node_id))
            db.flush()
    except IntegrityError as exc:
        raise WorkflowError(f"节点 {node_id} 在同一实例中重复激活，流程定义有误") from exc


def _complete_activation(db: Session, inst: WfInstance, node_id: str, status: str = "completed") -> None:
    db.execute(update(WfNodeActivation).where(WfNodeActivation.instance_id == inst.id,
                                              WfNodeActivation.node_id == node_id)
               .values(status=status, completed_at=timeutil.now()))


def _follow(db: Session, inst: WfInstance, g: Graph, edge: dict, actor_id: int | None) -> None:
    if inst.status != "running":
        return
    _enter(db, inst, g, edge["target"], edge["id"], actor_id)


def _enter(db: Session, inst: WfInstance, g: Graph, node_id: str, via_edge: str | None, actor_id: int | None):
    node = g.node(node_id)
    t = node["type"]
    if t == "join":
        try:
            with db.begin_nested():
                db.add(WfJoinArrival(instance_id=inst.id, join_node_id=node_id, edge_id=via_edge or "?"))
                db.flush()
        except IntegrityError as exc:
            raise WorkflowError("并行汇聚重复到达") from exc
        arrived = db.scalar(select(func.count()).select_from(WfJoinArrival).where(
            WfJoinArrival.instance_id == inst.id, WfJoinArrival.join_node_id == node_id))
        expected = len(g.inc.get(node_id, []))
        _history(db, inst, "join_arrive", None, node, detail={"arrived": arrived, "expected": expected})
        if arrived < expected:
            return
        _activate(db, inst, node_id)
        _complete_activation(db, inst, node_id)
        _follow(db, inst, g, g.out[node_id][0], actor_id)
        return

    _activate(db, inst, node_id)
    if t == "start":
        _complete_activation(db, inst, node_id)
        _follow(db, inst, g, g.out[node_id][0], actor_id)
    elif t == "end":
        _complete_activation(db, inst, node_id)
        _finish(db, inst, "approved", actor_id, node)
    elif t == "condition":
        variables = inst.variables or {}
        chosen = None
        for e in g.out[node_id]:
            if e.get("default"):
                continue
            if evaluate(e.get("condition"), variables):
                chosen = e
                break
        if chosen is None:
            chosen = next(e for e in g.out[node_id] if e.get("default"))
        _history(db, inst, "condition", None, node, detail={"edge": chosen["id"], "target": chosen["target"],
                                                            "label": chosen.get("label")})
        _complete_activation(db, inst, node_id)
        _follow(db, inst, g, chosen, actor_id)
    elif t == "parallel":
        _history(db, inst, "fork", None, node, detail={"branches": len(g.out[node_id])})
        _complete_activation(db, inst, node_id)
        for e in list(g.out[node_id]):
            _follow(db, inst, g, e, actor_id)
    elif t == "cc":
        cfg = node.get("config") or {}
        users, _ = resolve_users(db, cfg.get("targets") or {}, inst)
        for uid in users:
            db.add(WfCc(instance_id=inst.id, node_id=node_id, user_id=uid))
            notify(db, uid, "workflow_cc", f"抄送：{inst.title}", f"流程节点「{node['name']}」抄送给你",
                   f"/approvals?instance={inst.id}", "wf_instance", inst.id)
        _history(db, inst, "cc", None, node, detail={"users": users})
        _complete_activation(db, inst, node_id)
        _follow(db, inst, g, g.out[node_id][0], actor_id)
    elif t == "approval":
        _create_tasks(db, inst, g, node, actor_id)
    else:  # pragma: no cover - validated at publish
        raise WorkflowError(f"未知节点类型 {t}")


def _create_tasks(db: Session, inst: WfInstance, g: Graph, node: dict, actor_id: int | None) -> None:
    cfg = node.get("config") or {}
    users, note = resolve_users(db, cfg.get("approver") or {}, inst)
    if note:
        _history(db, inst, "escalate", None, node, comment=note)
    if not users:
        on_empty = cfg.get("on_empty", "fallback")
        if on_empty == "auto_pass":
            _history(db, inst, "auto_pass", None, node, comment="未找到可用审批人，按配置自动通过")
            _complete_activation(db, inst, node["id"])
            _follow(db, inst, g, g.out[node["id"]][0], actor_id)
            return
        if on_empty == "error":
            raise WorkflowError(f"节点「{node['name']}」没有可用审批人", code="NO_APPROVER")
        users = [u for u in _role_users(db, "admin") if u != inst.subject_user_id][:1]
        if not users:
            raise WorkflowError(f"节点「{node['name']}」没有可用审批人，且无可兜底的管理员", code="NO_APPROVER")
        _history(db, inst, "fallback", None, node, comment="未找到可用审批人，已转交系统管理员",
                 detail={"users": users})
    mode = cfg.get("mode", "or") if len(users) > 1 else "or"
    for uid in users:
        task = WfTask(instance_id=inst.id, node_id=node["id"], node_name=node["name"], mode=mode, assignee_id=uid,
                      status="pending")
        db.add(task)
        db.flush()
        _history(db, inst, "task_created", None, node, task=task, detail={"assignee": uid, "mode": mode})
        notify(db, uid, "workflow_todo", f"待审批：{inst.title}", f"节点「{node['name']}」等待你审批",
               f"/approvals?task={task.id}", "wf_task", task.id)


def _finish(db: Session, inst: WfInstance, status: str, actor_id: int | None, node: dict | None = None,
            comment: str | None = None) -> None:
    if inst.status != "running":
        raise InvalidState("流程已结束", code="INSTANCE_NOT_RUNNING")
    inst.status = status
    inst.ended_at = timeutil.now()
    db.execute(update(WfTask).where(WfTask.instance_id == inst.id, WfTask.status == "pending")
               .values(status="cancelled", acted_at=timeutil.now()))
    db.execute(update(WfNodeActivation).where(WfNodeActivation.instance_id == inst.id,
                                              WfNodeActivation.status == "active")
               .values(status="cancelled", completed_at=timeutil.now()))
    _history(db, inst, {"approved": "end", "rejected": "rejected", "withdrawn": "withdrawn",
                        "cancelled": "cancelled"}[status], actor_id, node, comment=comment)
    db.flush()
    handler = registry.get_handler(inst.business_type)
    callback = getattr(handler, f"on_{status}", None) if handler else None
    if callback:
        callback(db, inst, actor_id)
    label = {"approved": "已通过", "rejected": "已驳回", "withdrawn": "已撤回", "cancelled": "已取消"}[status]
    if actor_id != inst.initiator_id or status == "approved":
        notify(db, inst.initiator_id, "workflow_result", f"{inst.title}{label}", comment,
               f"/approvals?instance={inst.id}", "wf_instance", inst.id)
    if inst.subject_user_id and inst.subject_user_id != inst.initiator_id:
        notify(db, inst.subject_user_id, "workflow_result", f"{inst.title}{label}", comment,
               f"/approvals?instance={inst.id}", "wf_instance", inst.id)


# ------------------------------------------------------------------ task actions
def _load_task(db: Session, task_id: int, user_id: int, admin_override: bool = False) -> tuple[WfTask, WfInstance]:
    task = db.get(WfTask, task_id)
    if task is None:
        raise NotFound("审批任务不存在")
    if task.assignee_id != user_id and not admin_override:
        raise Forbidden("你不是该任务的审批人", code="NOT_TASK_ASSIGNEE")
    if task.status != "pending":
        raise InvalidState("任务已处理，不能重复操作", code="TASK_ALREADY_HANDLED",
                           details={"status": task.status})
    inst = db.get(WfInstance, task.instance_id)
    if inst.status != "running":
        raise InvalidState("流程已结束，不能继续审批", code="INSTANCE_NOT_RUNNING", details={"status": inst.status})
    return task, inst


def _claim(db: Session, task: WfTask, status: str, comment: str | None, form: dict | None = None) -> None:
    now = timeutil.now()
    res = db.execute(update(WfTask).where(WfTask.id == task.id, WfTask.status == "pending")
                     .values(status=status, comment=comment, acted_at=now, form_data=form)
                     .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise InvalidState("任务已处理，不能重复操作", code="TASK_ALREADY_HANDLED")
    db.refresh(task)


def _touch(db: Session, inst: WfInstance) -> None:
    # bump row version: concurrent writers on the same instance conflict instead of interleaving
    flag_modified(inst, "variables")
    db.flush()


def approve(db: Session, task_id: int, user_id: int, comment: str | None = None,
            form_data: dict | None = None) -> WfInstance:
    task, inst = _load_task(db, task_id, user_id)
    _claim(db, task, "approved", comment, form_data)
    g = graph_for(db, inst.version_id)
    node = g.node(task.node_id)
    _history(db, inst, "approve", user_id, node, task, comment)
    handler = registry.get_handler(inst.business_type)
    hook = getattr(handler, "on_task_approved", None) if handler else None
    if hook:
        hook(db, inst, task, form_data or {})
    remaining = db.scalar(select(func.count()).select_from(WfTask).where(
        WfTask.instance_id == inst.id, WfTask.node_id == task.node_id, WfTask.status == "pending"))
    if task.mode == "or" or remaining == 0:
        if remaining:
            db.execute(update(WfTask).where(WfTask.instance_id == inst.id, WfTask.node_id == task.node_id,
                                            WfTask.status == "pending")
                       .values(status="cancelled", acted_at=timeutil.now(), comment="或签：其他审批人已处理"))
        _complete_activation(db, inst, task.node_id)
        _history(db, inst, "node_completed", None, node, detail={"mode": task.mode})
        _follow(db, inst, g, g.out[task.node_id][0], user_id)
    _touch(db, inst)
    return inst


def reject(db: Session, task_id: int, user_id: int, comment: str) -> WfInstance:
    if not comment or not comment.strip():
        raise ValidationFailed("驳回必须填写意见", code="COMMENT_REQUIRED")
    task, inst = _load_task(db, task_id, user_id)
    _claim(db, task, "rejected", comment)
    g = graph_for(db, inst.version_id)
    node = g.node(task.node_id)
    _history(db, inst, "reject", user_id, node, task, comment)
    _complete_activation(db, inst, task.node_id, "rejected")
    _finish(db, inst, "rejected", user_id, node, comment)
    _touch(db, inst)
    return inst


def transfer(db: Session, task_id: int, user_id: int, to_user_id: int, comment: str | None,
             admin_override: bool = False) -> WfTask:
    task, inst = _load_task(db, task_id, user_id, admin_override)
    target = db.get(User, to_user_id)
    if target is None or target.status != "active":
        raise ValidationFailed("转交目标用户不存在或已停用", code="INVALID_TRANSFER_TARGET")
    if to_user_id == task.assignee_id:
        raise ValidationFailed("不能转交给当前审批人", code="INVALID_TRANSFER_TARGET")
    if to_user_id == inst.subject_user_id:
        raise ValidationFailed("不能转交给申请人本人", code="INVALID_TRANSFER_TARGET")
    dup = db.scalar(select(WfTask.id).where(WfTask.instance_id == inst.id, WfTask.node_id == task.node_id,
                                            WfTask.assignee_id == to_user_id, WfTask.status == "pending"))
    if dup:
        raise Conflict("目标用户在该节点已有待办任务", code="INVALID_TRANSFER_TARGET")
    _claim(db, task, "transferred", comment)
    new = WfTask(instance_id=inst.id, node_id=task.node_id, node_name=task.node_name, mode=task.mode,
                 assignee_id=to_user_id, status="pending", transferred_from_task_id=task.id)
    db.add(new)
    db.flush()
    g = graph_for(db, inst.version_id)
    _history(db, inst, "reassign" if admin_override and task.assignee_id != user_id else "transfer", user_id,
             g.node(task.node_id), task, comment, detail={"from": task.assignee_id, "to": to_user_id,
                                                          "new_task": new.id})
    notify(db, to_user_id, "workflow_todo", f"待审批（转交）：{inst.title}", comment,
           f"/approvals?task={new.id}", "wf_task", new.id)
    _touch(db, inst)
    return new


def withdraw(db: Session, instance_id: int, user_id: int, comment: str | None = None) -> WfInstance:
    inst = db.get(WfInstance, instance_id)
    if inst is None:
        raise NotFound("流程实例不存在")
    if inst.initiator_id != user_id:
        raise Forbidden("只有发起人可以撤回", code="NOT_INITIATOR")
    if inst.status != "running":
        raise InvalidState("流程已结束，无法撤回", code="INSTANCE_NOT_RUNNING", details={"status": inst.status})
    _finish(db, inst, "withdrawn", user_id, None, comment)
    _touch(db, inst)
    return inst


def cancel(db: Session, instance_id: int, user_id: int, can_monitor: bool, comment: str | None = None) -> WfInstance:
    inst = db.get(WfInstance, instance_id)
    if inst is None:
        raise NotFound("流程实例不存在")
    if inst.initiator_id != user_id and not can_monitor:
        raise Forbidden("只有发起人或流程管理员可以取消", code="NOT_INITIATOR")
    if inst.status != "running":
        raise InvalidState("流程已结束，无法取消", code="INSTANCE_NOT_RUNNING", details={"status": inst.status})
    _finish(db, inst, "cancelled", user_id, None, comment)
    _touch(db, inst)
    return inst


def withdraw_for_business(db: Session, business_type: str, business_id: int, user_id: int,
                          cancel_instead: bool = False, can_monitor: bool = False) -> WfInstance | None:
    inst = db.scalar(select(WfInstance).where(WfInstance.business_type == business_type,
                                              WfInstance.business_id == business_id,
                                              WfInstance.status == "running"))
    if inst is None:
        return None
    if cancel_instead:
        return cancel(db, inst.id, user_id, can_monitor)
    return withdraw(db, inst.id, user_id)
