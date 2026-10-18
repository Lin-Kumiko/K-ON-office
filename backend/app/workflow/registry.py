"""Business types known to the workflow engine and their handlers.

The engine never imports business modules; each business service registers a handler
object implementing any of: on_approved, on_rejected, on_withdrawn, on_cancelled,
on_task_approved(db, inst, task, form_data). All callbacks run inside the caller's
transaction, so a failing callback rolls back the whole approval step.
"""
from __future__ import annotations

from typing import Protocol

BUSINESS_TYPES: dict[str, dict] = {
    "leave": {"name": "请假", "variables": {"days": "number", "hours": "number", "leave_type": "string",
                                           "department_id": "number"}},
    "expense": {"name": "费用报销", "variables": {"amount": "number", "item_count": "number",
                                               "department_id": "number"}},
    "travel": {"name": "出差", "variables": {"days": "number", "estimated_cost": "number",
                                            "department_id": "number", "is_change": "boolean"}},
    "onboarding": {"name": "员工入职", "variables": {"department_id": "number", "probation_months": "number"}},
    "regularization": {"name": "员工转正", "variables": {"department_id": "number"}},
    "transfer": {"name": "调岗", "variables": {"from_department_id": "number", "to_department_id": "number"}},
    "offer": {"name": "录用审批", "variables": {"salary": "number", "department_id": "number"}},
    "meeting": {"name": "会议室预约", "variables": {"room_id": "number", "duration_hours": "number"}},
    "attendance_correction": {"name": "补卡申请", "variables": {"department_id": "number"}},
    "overtime": {"name": "加班申请", "variables": {"hours": "number", "department_id": "number"}},
}


class Handler(Protocol):  # pragma: no cover - typing only
    business_type: str


_HANDLERS: dict[str, object] = {}


def register(handler) -> None:
    _HANDLERS[handler.business_type] = handler


def get_handler(business_type: str):
    return _HANDLERS.get(business_type)
