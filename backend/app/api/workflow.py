"""Workflow definitions (designer), instances, tasks and CC."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, idempotent, jsonable, paginate
from ..core.deps import CurrentUser, PageParams, current_user, get_db, require
from ..core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..models import (Role, User, WfCc, WfDefinition, WfDefinitionVersion, WfHistory, WfInstance,
                      WfNodeActivation, WfTask)
from ..workflow import engine, registry
from ..workflow.graph import validate_graph
from .common import ERRORS, CommentIn, Msg, Page

router = APIRouter(prefix="/api/workflow", tags=["工作流"], responses=ERRORS)


@router.get("/business-types", summary="可接入工作流的业务类型及条件变量")
def business_types(cu: CurrentUser = Depends(current_user)):
    return [{"code": k, "name": v["name"], "variables": v["variables"]} for k, v in registry.BUSINESS_TYPES.items()]


# ------------------------------------------------------------------ definitions
class VersionOut(BaseModel):
    id: int
    version: int
    status: str
    graph: dict
    note: str | None
    published_at: datetime | None
    created_at: datetime


class DefinitionOut(BaseModel):
    id: int
    key: str
    name: str
    business_type: str
    business_type_name: str
    description: str | None
    status: str
    current_version_id: int | None
    current_version: int | None
    draft_version_id: int | None
    versions: list[VersionOut] = []
    running_instances: int = 0


def _def_out(db: Session, d: WfDefinition, with_versions: bool = False) -> DefinitionOut:
    vers = db.scalars(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == d.id)
                      .order_by(WfDefinitionVersion.version.desc())).all()
    cur = next((v for v in vers if v.id == d.current_version_id), None)
    draft = next((v for v in vers if v.status == "draft"), None)
    running = db.scalar(select(func.count()).select_from(WfInstance).where(WfInstance.definition_id == d.id,
                                                                           WfInstance.status == "running"))
    return DefinitionOut(
        id=d.id, key=d.key, name=d.name, business_type=d.business_type,
        business_type_name=registry.BUSINESS_TYPES.get(d.business_type, {}).get("name", d.business_type),
        description=d.description, status=d.status, current_version_id=d.current_version_id,
        current_version=cur.version if cur else None, draft_version_id=draft.id if draft else None,
        versions=[VersionOut.model_validate(v, from_attributes=True) for v in vers] if with_versions else [],
        running_instances=running)


class DefinitionIn(BaseModel):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    business_type: str
    description: str | None = Field(None, max_length=255)
    graph: dict | None = None


class DefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=255)


class GraphIn(BaseModel):
    graph: dict
    note: str | None = Field(None, max_length=255)


EMPTY_GRAPH = {"nodes": [{"id": "start", "type": "start", "name": "开始", "x": 80, "y": 200},
                         {"id": "end", "type": "end", "name": "结束", "x": 560, "y": 200}],
               "edges": []}


@router.get("/definitions", response_model=list[DefinitionOut], summary="流程定义列表")
def list_definitions(cu: CurrentUser = Depends(require("workflow:manage")), db: Session = Depends(get_db)):
    return [_def_out(db, d) for d in db.scalars(select(WfDefinition).order_by(WfDefinition.id))]


@router.post("/definitions", response_model=DefinitionOut, status_code=201, summary="新建流程定义（生成 v1 草稿）")
def create_definition(body: DefinitionIn, cu: CurrentUser = Depends(require("workflow:manage")),
                      db: Session = Depends(get_db)):
    if body.business_type not in registry.BUSINESS_TYPES:
        raise ValidationFailed("未知业务类型", code="UNKNOWN_BUSINESS_TYPE")
    if db.scalar(select(WfDefinition.id).where(WfDefinition.key == body.key)):
        raise Conflict("流程标识已存在", code="DEFINITION_EXISTS")
    d = WfDefinition(key=body.key, name=body.name, business_type=body.business_type, description=body.description,
                     status="disabled", created_by=cu.id)
    db.add(d)
    db.flush()
    db.add(WfDefinitionVersion(definition_id=d.id, version=1, graph=body.graph or EMPTY_GRAPH, status="draft",
                               created_by=cu.id))
    audit(db, cu, "create_wf_definition", "wf_definition", d.id)
    db.commit()
    return _def_out(db, d, True)


def _get_def(db: Session, def_id: int) -> WfDefinition:
    d = db.get(WfDefinition, def_id)
    if d is None:
        raise NotFound("流程定义不存在")
    return d


@router.get("/definitions/{def_id}", response_model=DefinitionOut, summary="流程定义详情（含全部版本）")
def get_definition(def_id: int, cu: CurrentUser = Depends(require("workflow:manage")), db: Session = Depends(get_db)):
    return _def_out(db, _get_def(db, def_id), True)


@router.put("/definitions/{def_id}", response_model=DefinitionOut, summary="修改名称描述")
def update_definition(def_id: int, body: DefinitionUpdate, cu: CurrentUser = Depends(require("workflow:manage")),
                      db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    d.name, d.description = body.name, body.description
    db.commit()
    return _def_out(db, d, True)


def _draft(db: Session, d: WfDefinition) -> WfDefinitionVersion | None:
    return db.scalar(select(WfDefinitionVersion).where(WfDefinitionVersion.definition_id == d.id,
                                                       WfDefinitionVersion.status == "draft"))


@router.post("/definitions/{def_id}/draft", response_model=DefinitionOut, summary="基于当前发布版本创建新草稿")
def new_draft(def_id: int, cu: CurrentUser = Depends(require("workflow:manage")), db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    if _draft(db, d):
        raise Conflict("已存在草稿版本", code="DRAFT_EXISTS")
    latest = db.scalar(select(func.max(WfDefinitionVersion.version)).where(WfDefinitionVersion.definition_id == d.id))
    base = db.get(WfDefinitionVersion, d.current_version_id) if d.current_version_id else None
    db.add(WfDefinitionVersion(definition_id=d.id, version=(latest or 0) + 1,
                               graph=base.graph if base else EMPTY_GRAPH, status="draft", created_by=cu.id))
    db.commit()
    return _def_out(db, d, True)


@router.put("/definitions/{def_id}/draft", response_model=DefinitionOut, summary="保存草稿流程图")
def save_draft(def_id: int, body: GraphIn, cu: CurrentUser = Depends(require("workflow:manage")),
               db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    v = _draft(db, d)
    if v is None:
        raise InvalidState("没有可编辑的草稿，请先创建新草稿；已发布版本不可修改", code="NO_DRAFT")
    if not isinstance(body.graph.get("nodes"), list) or not isinstance(body.graph.get("edges"), list):
        raise ValidationFailed("流程图必须包含 nodes 与 edges 数组", code="INVALID_GRAPH")
    if len(str(body.graph)) > 200_000:
        raise ValidationFailed("流程图过大", code="INVALID_GRAPH")
    v.graph = body.graph
    v.note = body.note
    engine._graph_cache.pop(v.id, None)
    db.commit()
    return _def_out(db, d, True)


def _validate(db: Session, d: WfDefinition, graph: dict) -> list[str]:
    roles = set(db.scalars(select(Role.code)))
    users = set(db.scalars(select(User.id).where(User.status == "active")))
    return validate_graph(graph, registry.BUSINESS_TYPES[d.business_type]["variables"], roles, users)


class ValidateOut(BaseModel):
    valid: bool
    errors: list[str]


@router.post("/definitions/{def_id}/validate", response_model=ValidateOut, summary="校验流程图（不保存）")
def validate_definition(def_id: int, body: GraphIn | None = None,
                        cu: CurrentUser = Depends(require("workflow:manage")), db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    graph = body.graph if body else (_draft(db, d).graph if _draft(db, d) else None)
    if graph is None:
        raise InvalidState("没有草稿可校验", code="NO_DRAFT")
    errors = _validate(db, d, graph)
    return ValidateOut(valid=not errors, errors=errors)


@router.post("/definitions/{def_id}/publish", response_model=DefinitionOut, summary="发布草稿（旧版本归档，运行中实例不受影响）")
def publish(def_id: int, cu: CurrentUser = Depends(require("workflow:manage")), db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    v = _draft(db, d)
    if v is None:
        raise InvalidState("没有草稿可发布", code="NO_DRAFT")
    errors = _validate(db, d, v.graph)
    if errors:
        raise ValidationFailed("流程图校验未通过", code="INVALID_GRAPH", details=errors)
    if d.current_version_id:
        old = db.get(WfDefinitionVersion, d.current_version_id)
        old.status = "archived"
    v.status = "published"
    v.published_at = timeutil.now()
    v.published_by = cu.id
    db.flush()
    d.current_version_id = v.id
    d.status = "active"
    # one active definition per business type
    for other in db.scalars(select(WfDefinition).where(WfDefinition.business_type == d.business_type,
                                                       WfDefinition.id != d.id, WfDefinition.status == "active")):
        other.status = "disabled"
    audit(db, cu, "publish_wf_definition", "wf_definition", d.id, {"version": v.version})
    db.commit()
    return _def_out(db, d, True)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


@router.post("/definitions/{def_id}/status", response_model=DefinitionOut, summary="启用/停用（停用不影响运行中实例）")
def set_status(def_id: int, body: StatusIn, cu: CurrentUser = Depends(require("workflow:manage")),
               db: Session = Depends(get_db)):
    d = _get_def(db, def_id)
    if body.status == "active":
        if not d.current_version_id:
            raise InvalidState("尚未发布任何版本，不能启用", code="NOT_PUBLISHED")
        for other in db.scalars(select(WfDefinition).where(WfDefinition.business_type == d.business_type,
                                                           WfDefinition.id != d.id, WfDefinition.status == "active")):
            other.status = "disabled"
    d.status = body.status
    audit(db, cu, "set_wf_definition_status", "wf_definition", d.id, {"status": body.status})
    db.commit()
    return _def_out(db, d, True)


# ------------------------------------------------------------------ instances
class TaskOut(BaseModel):
    id: int
    instance_id: int
    instance_title: str
    business_type: str
    business_id: int
    node_id: str
    node_name: str
    mode: str
    assignee_id: int
    assignee_name: str | None
    status: str
    comment: str | None
    form_data: dict | None
    created_at: datetime
    acted_at: datetime | None
    initiator_name: str | None


class HistoryOut(BaseModel):
    id: int
    action: str
    node_id: str | None
    node_name: str | None
    actor_id: int | None
    actor_name: str | None
    comment: str | None
    detail: dict | None
    created_at: datetime


class InstanceOut(BaseModel):
    id: int
    definition_id: int
    definition_name: str
    version: int
    business_type: str
    business_type_name: str
    business_id: int
    title: str
    initiator_id: int
    initiator_name: str | None
    status: str
    variables: dict
    started_at: datetime
    ended_at: datetime | None
    current_nodes: list[str]
    current_assignees: list[str]


class InstanceDetail(InstanceOut):
    graph: dict
    tasks: list[TaskOut]
    history: list[HistoryOut]
    node_states: dict[str, str]
    cc_users: list[str]


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.display_name)).all())


def _task_out(t: WfTask, inst: WfInstance, names: dict) -> TaskOut:
    return TaskOut(id=t.id, instance_id=t.instance_id, instance_title=inst.title, business_type=inst.business_type,
                   business_id=inst.business_id, node_id=t.node_id, node_name=t.node_name, mode=t.mode,
                   assignee_id=t.assignee_id, assignee_name=names.get(t.assignee_id), status=t.status,
                   comment=t.comment, form_data=t.form_data, created_at=t.created_at, acted_at=t.acted_at,
                   initiator_name=names.get(inst.initiator_id))


def _inst_out(db: Session, i: WfInstance, names: dict) -> InstanceOut:
    pend = db.scalars(select(WfTask).where(WfTask.instance_id == i.id, WfTask.status == "pending")).all()
    d = db.get(WfDefinition, i.definition_id)
    v = db.get(WfDefinitionVersion, i.version_id)
    return InstanceOut(id=i.id, definition_id=i.definition_id, definition_name=d.name, version=v.version,
                       business_type=i.business_type,
                       business_type_name=registry.BUSINESS_TYPES.get(i.business_type, {}).get("name", ""),
                       business_id=i.business_id, title=i.title, initiator_id=i.initiator_id,
                       initiator_name=names.get(i.initiator_id), status=i.status, variables=i.variables or {},
                       started_at=i.started_at, ended_at=i.ended_at,
                       current_nodes=sorted({t.node_name for t in pend}),
                       current_assignees=sorted({names.get(t.assignee_id, "?") for t in pend}))


def _can_view_instance(db: Session, cu: CurrentUser, i: WfInstance) -> bool:
    if cu.has("workflow:monitor") or i.initiator_id == cu.id or i.subject_user_id == cu.id:
        return True
    if db.scalar(select(WfTask.id).where(WfTask.instance_id == i.id, WfTask.assignee_id == cu.id)):
        return True
    return bool(db.scalar(select(WfCc.id).where(WfCc.instance_id == i.id, WfCc.user_id == cu.id)))


@router.get("/instances", response_model=Page[InstanceOut], summary="流程实例（scope=mine 我发起的 / all 需监控权限）")
def list_instances(scope: str = Query("mine", pattern="^(mine|all|related)$"), status: str | None = None,
                   business_type: str | None = None, q: str | None = Query(None, max_length=64),
                   page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(WfInstance)
    if scope == "mine":
        stmt = stmt.where(WfInstance.initiator_id == cu.id)
    elif scope == "related":
        stmt = stmt.where(or_(WfInstance.initiator_id == cu.id, WfInstance.subject_user_id == cu.id,
                              WfInstance.id.in_(select(WfTask.instance_id).where(WfTask.assignee_id == cu.id)),
                              WfInstance.id.in_(select(WfCc.instance_id).where(WfCc.user_id == cu.id))))
    else:
        cu.require("workflow:monitor")
    if status:
        stmt = stmt.where(WfInstance.status == status)
    if business_type:
        stmt = stmt.where(WfInstance.business_type == business_type)
    if q:
        stmt = stmt.where(WfInstance.title.ilike(f"%{q}%"))
    names = _names(db)
    return paginate(db, stmt, page, {"id": WfInstance.id, "started_at": WfInstance.started_at},
                    WfInstance.id.desc(), lambda i: _inst_out(db, i, names))


@router.get("/instances/{inst_id}", response_model=InstanceDetail, summary="实例详情：流程图、任务、完整审批历史")
def get_instance(inst_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    i = db.get(WfInstance, inst_id)
    if i is None:
        raise NotFound("流程实例不存在")
    if not _can_view_instance(db, cu, i):
        raise Forbidden("无权查看该流程", code="DATA_SCOPE_DENIED")
    names = _names(db)
    base = _inst_out(db, i, names)
    tasks = db.scalars(select(WfTask).where(WfTask.instance_id == i.id).order_by(WfTask.id)).all()
    hist = db.scalars(select(WfHistory).where(WfHistory.instance_id == i.id).order_by(WfHistory.id)).all()
    acts = db.scalars(select(WfNodeActivation).where(WfNodeActivation.instance_id == i.id)).all()
    ccs = db.scalars(select(WfCc).where(WfCc.instance_id == i.id)).all()
    return InstanceDetail(**base.model_dump(), graph=db.get(WfDefinitionVersion, i.version_id).graph,
                          tasks=[_task_out(t, i, names) for t in tasks],
                          history=[HistoryOut(id=h.id, action=h.action, node_id=h.node_id, node_name=h.node_name,
                                              actor_id=h.actor_id, actor_name=names.get(h.actor_id), comment=h.comment,
                                              detail=h.detail, created_at=h.created_at) for h in hist],
                          node_states={a.node_id: a.status for a in acts},
                          cc_users=[names.get(c.user_id, "?") for c in ccs])


@router.post("/instances/{inst_id}/withdraw", response_model=InstanceOut, summary="发起人撤回")
def withdraw_instance(inst_id: int, body: CommentIn | None = None, cu: CurrentUser = Depends(current_user),
                      db: Session = Depends(get_db)):
    i = engine.withdraw(db, inst_id, cu.id, body.comment if body else None)
    db.commit()
    return _inst_out(db, i, _names(db))


@router.post("/instances/{inst_id}/cancel", response_model=InstanceOut, summary="取消（发起人或流程管理员）")
def cancel_instance(inst_id: int, body: CommentIn | None = None, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    i = engine.cancel(db, inst_id, cu.id, cu.has("workflow:monitor"), body.comment if body else None)
    audit(db, cu, "cancel_instance", "wf_instance", inst_id)
    db.commit()
    return _inst_out(db, i, _names(db))


# ------------------------------------------------------------------ tasks
@router.get("/tasks", response_model=Page[TaskOut], summary="我的审批任务（status=pending 待办 / done 已办）")
def my_tasks(status: str = Query("pending", pattern="^(pending|done|all)$"), business_type: str | None = None,
             page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(WfTask).join(WfInstance, WfInstance.id == WfTask.instance_id).where(WfTask.assignee_id == cu.id)
    if status == "pending":
        stmt = stmt.where(WfTask.status == "pending")
    elif status == "done":
        stmt = stmt.where(WfTask.status.in_(("approved", "rejected", "transferred")))
    if business_type:
        stmt = stmt.where(WfInstance.business_type == business_type)
    names = _names(db)
    return paginate(db, stmt, page, {"id": WfTask.id, "created_at": WfTask.created_at}, WfTask.id.desc(),
                    lambda t: _task_out(t, db.get(WfInstance, t.instance_id), names))


class ApproveIn(BaseModel):
    comment: str | None = Field(None, max_length=1000)
    form_data: dict | None = None


class RejectIn(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


class TransferIn(BaseModel):
    to_user_id: int
    comment: str | None = Field(None, max_length=1000)


class ActionOut(BaseModel):
    task_id: int
    task_status: str
    instance: InstanceOut


def _action_out(db: Session, task_id: int, inst: WfInstance) -> dict:
    t = db.get(WfTask, task_id)
    return jsonable(ActionOut(task_id=t.id, task_status=t.status, instance=_inst_out(db, inst, _names(db))))


@router.post("/tasks/{task_id}/approve", response_model=ActionOut, summary="通过（会签需全部通过，或签任一通过）")
def approve_task(task_id: int, body: ApproveIn, request: Request, cu: CurrentUser = Depends(current_user),
                 db: Session = Depends(get_db)):
    def action():
        inst = engine.approve(db, task_id, cu.id, body.comment, body.form_data)
        return 200, _action_out(db, task_id, inst)
    return idempotent(db, cu, request, {"task": task_id, **body.model_dump()}, action)


@router.post("/tasks/{task_id}/reject", response_model=ActionOut, summary="驳回（整单驳回，需填写意见）")
def reject_task(task_id: int, body: RejectIn, request: Request, cu: CurrentUser = Depends(current_user),
                db: Session = Depends(get_db)):
    def action():
        inst = engine.reject(db, task_id, cu.id, body.comment)
        return 200, _action_out(db, task_id, inst)
    return idempotent(db, cu, request, {"task": task_id, **body.model_dump()}, action)


@router.post("/tasks/{task_id}/transfer", response_model=TaskOut, summary="转交给其他审批人")
def transfer_task(task_id: int, body: TransferIn, cu: CurrentUser = Depends(current_user),
                  db: Session = Depends(get_db)):
    new = engine.transfer(db, task_id, cu.id, body.to_user_id, body.comment)
    db.commit()
    return _task_out(new, db.get(WfInstance, new.instance_id), _names(db))


@router.post("/tasks/{task_id}/reassign", response_model=TaskOut, summary="管理员改派（审批人不可用时）")
def reassign_task(task_id: int, body: TransferIn, cu: CurrentUser = Depends(require("workflow:monitor")),
                  db: Session = Depends(get_db)):
    new = engine.transfer(db, task_id, cu.id, body.to_user_id, body.comment or "管理员改派", admin_override=True)
    audit(db, cu, "reassign_task", "wf_task", task_id, {"to": body.to_user_id})
    db.commit()
    return _task_out(new, db.get(WfInstance, new.instance_id), _names(db))


class CcOut(BaseModel):
    id: int
    instance_id: int
    title: str
    node_id: str
    status: str
    read_at: datetime | None
    created_at: datetime


@router.get("/cc", response_model=Page[CcOut], summary="抄送我的")
def my_cc(page: PageParams = Depends(), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(WfCc).where(WfCc.user_id == cu.id)

    def tr(c: WfCc):
        i = db.get(WfInstance, c.instance_id)
        return CcOut(id=c.id, instance_id=c.instance_id, title=i.title, node_id=c.node_id, status=i.status,
                     read_at=c.read_at, created_at=c.created_at)
    return paginate(db, stmt, page, None, WfCc.id.desc(), tr)


@router.post("/cc/{cc_id}/read", response_model=Msg, summary="标记抄送已读")
def read_cc(cc_id: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(WfCc, cc_id)
    if c is None or c.user_id != cu.id:
        raise NotFound("抄送记录不存在")
    if c.read_at is None:
        c.read_at = timeutil.now()
    db.commit()
    return Msg()
