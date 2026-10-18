"""Shared submit/withdraw helpers and a base handler for workflow-backed business documents."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.deps import CurrentUser
from ..core.errors import InvalidState, NotFound
from ..workflow import engine

EDITABLE = ("draft", "rejected", "withdrawn")


def ensure_editable(doc, label: str = "单据") -> None:
    if doc.status not in EDITABLE:
        raise InvalidState(f"{label}当前状态为 {doc.status}，不能修改", code="INVALID_STATE",
                           details={"status": doc.status})


def submit(db: Session, cu: CurrentUser, doc, *, business_type: str, title: str, subject_employee_id: int | None,
           variables: dict, label: str = "单据"):
    if doc.status not in EDITABLE:
        raise InvalidState(f"{label}当前状态为 {doc.status}，不能提交", code="INVALID_STATE",
                           details={"status": doc.status})
    doc.status = "pending"
    doc.submitted_at = timeutil.now()
    doc.decided_at = None
    db.flush()
    inst = engine.start(db, business_type=business_type, business_id=doc.id, title=title, initiator_id=cu.id,
                        subject_employee_id=subject_employee_id, variables=variables)
    doc.instance_id = inst.id
    db.flush()
    return inst


def withdraw(db: Session, cu: CurrentUser, doc, business_type: str, label: str = "单据"):
    if doc.status != "pending":
        raise InvalidState(f"{label}当前状态为 {doc.status}，只有审批中的单据可以撤回", code="INVALID_STATE",
                           details={"status": doc.status})
    inst = engine.withdraw_for_business(db, business_type, doc.id, cu.id)
    if inst is None:
        raise InvalidState("未找到进行中的审批流程", code="INSTANCE_NOT_RUNNING")
    return inst


def cancel(db: Session, cu: CurrentUser, doc, business_type: str, label: str = "单据"):
    """Cancel: pending -> via workflow cancel; draft/rejected/withdrawn -> cancelled directly."""
    if doc.status == "pending":
        inst = engine.withdraw_for_business(db, business_type, doc.id, cu.id, cancel_instead=True,
                                            can_monitor=cu.has("workflow:monitor"))
        if inst is None:
            raise InvalidState("未找到进行中的审批流程", code="INSTANCE_NOT_RUNNING")
        return
    if doc.status not in EDITABLE:
        raise InvalidState(f"{label}当前状态为 {doc.status}，不能取消", code="INVALID_STATE",
                           details={"status": doc.status})
    doc.status = "cancelled"
    doc.decided_at = timeutil.now()


class DocHandler:
    model = None
    business_type = ""
    label = "单据"

    def load(self, db: Session, inst):
        doc = db.get(self.model, inst.business_id)
        if doc is None:
            raise NotFound(f"{self.label}不存在")
        if doc.status != "pending":
            raise InvalidState(f"{self.label}状态为 {doc.status}，与流程不一致", code="BUSINESS_STATE_MISMATCH")
        doc.instance_id = inst.id
        return doc

    def _close(self, db, inst, actor_id, status):
        doc = self.load(db, inst)
        doc.status = status
        doc.decided_at = timeutil.now()
        db.flush()
        self.after_closed(db, doc, inst, actor_id, status)

    def on_approved(self, db, inst, actor_id):
        doc = self.load(db, inst)
        doc.status = "approved"
        doc.decided_at = timeutil.now()
        db.flush()
        self.after_approved(db, doc, inst, actor_id)

    def on_rejected(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "rejected")

    def on_withdrawn(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "withdrawn")

    def on_cancelled(self, db, inst, actor_id):
        self._close(db, inst, actor_id, "cancelled")

    def after_approved(self, db, doc, inst, actor_id):  # pragma: no cover - overridden
        pass

    def after_closed(self, db, doc, inst, actor_id, status):
        pass
