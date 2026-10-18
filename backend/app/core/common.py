"""Cross-cutting helpers: audit, notification, pagination, money, idempotency."""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import timeutil
from .deps import CurrentUser, PageParams
from .errors import Conflict, ValidationFailed
from ..models import AuditLog, IdempotencyRecord, Notification


def audit(db: Session, cu: CurrentUser | None, action: str, resource_type: str, resource_id: Any = None,
          detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=cu.id if cu else None, action=action, resource_type=resource_type,
                    resource_id=None if resource_id is None else str(resource_id), detail=detail,
                    ip=cu.ip if cu else None))


def notify(db: Session, user_id: int | None, category: str, title: str, content: str | None = None,
           link: str | None = None, ref_type: str | None = None, ref_id: int | None = None) -> None:
    if not user_id:
        return
    db.add(Notification(user_id=user_id, category=category, title=title[:200], content=content, link=link,
                        ref_type=ref_type, ref_id=ref_id))


def paginate(db: Session, stmt, page: PageParams, sort_map: dict[str, Any] | None = None,
             default_order=None, transform: Callable | None = None) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    if page.sort and sort_map:
        desc = page.sort.startswith("-")
        key = page.sort.lstrip("-+")
        col = sort_map.get(key)
        if col is None:
            raise ValidationFailed(f"不支持的排序字段：{key}", code="INVALID_SORT",
                                   details={"allowed": sorted(sort_map)})
        stmt = stmt.order_by(col.desc() if desc else col.asc())
    elif default_order is not None:
        stmt = stmt.order_by(*default_order) if isinstance(default_order, (list, tuple)) else stmt.order_by(
            default_order)
    rows = db.execute(stmt.offset(page.offset).limit(page.page_size)).scalars().all()
    items = [transform(r) for r in rows] if transform else rows
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size}


# ----------------------------------------------------------------- money
CENT = Decimal("0.01")


def to_cents(value: Decimal | str | int | float) -> int:
    d = Decimal(str(value))
    if d != d.quantize(CENT):
        raise ValidationFailed("金额最多保留两位小数", code="INVALID_AMOUNT")
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cents_str(cents: int | None) -> str | None:
    if cents is None:
        return None
    return str((Decimal(cents) / 100).quantize(CENT))


# ----------------------------------------------------------------- idempotency
def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def idempotent(db: Session, cu: CurrentUser, request: Request, payload: Any,
               action: Callable[[], tuple[int, Any]]):
    """Run `action` once per Idempotency-Key. The stored response is written in the same
    transaction as the business change, so either both persist or neither does.

    Without the header the action simply runs (state checks still prevent duplicates)."""
    key = request.headers.get("Idempotency-Key")
    if key is not None:
        key = key.strip()
        if not (1 <= len(key) <= 128):
            raise ValidationFailed("Idempotency-Key 长度需为 1-128", code="INVALID_IDEMPOTENCY_KEY")
        req_hash = _hash_payload({"m": request.method, "p": request.url.path, "b": payload})
        rec = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.user_id == cu.id,
                                                        IdempotencyRecord.key == key))
        if rec is not None:
            if rec.request_hash != req_hash:
                raise Conflict("同一 Idempotency-Key 被用于不同请求", code="IDEMPOTENCY_KEY_REUSED")
            resp = JSONResponse(rec.response_body, status_code=rec.status_code)
            resp.headers["Idempotent-Replay"] = "true"
            return resp
    status, body = action()
    if key is not None:
        db.add(IdempotencyRecord(user_id=cu.id, key=key, method=request.method, path=request.url.path,
                                 request_hash=req_hash, status_code=status, response_body=body))
    db.commit()
    return JSONResponse(body, status_code=status)


def jsonable(obj: Any) -> Any:
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(obj)


def now():
    return timeutil.now()
