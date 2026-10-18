"""Uploads (simulated receipts, resumes, document versions): type whitelist, size limit, safe storage."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.common import audit
from ..core.deps import CurrentUser, current_user, get_db
from ..core.errors import Forbidden, NotFound, ValidationFailed
from ..models import ExpenseClaim, ExpenseItem, StoredFile, WfTask
from .common import ERRORS

router = APIRouter(prefix="/api/files", tags=["附件"], responses=ERRORS)

ALLOWED = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAGIC = {".pdf": [b"%PDF"], ".png": [b"\x89PNG"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
         ".docx": [b"PK\x03\x04"], ".xlsx": [b"PK\x03\x04"], ".pptx": [b"PK\x03\x04"]}
PURPOSES = {"expense_receipt", "resume", "document"}


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", base).strip(" .")
    return (base or "file")[:120]


def store_upload(request: Request, db: Session, cu: CurrentUser, upload: UploadFile, purpose: str) -> StoredFile:
    if purpose not in PURPOSES:
        raise ValidationFailed("不支持的上传用途", code="INVALID_PURPOSE")
    name = safe_name(upload.filename or "")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise ValidationFailed(f"不支持的文件类型 {ext or '(无扩展名)'}，允许：{', '.join(sorted(ALLOWED))}",
                               code="FILE_TYPE_NOT_ALLOWED")
    limit = request.app.state.settings.max_upload_bytes
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed(f"文件超过 {limit // 1024 // 1024}MB 限制", code="FILE_TOO_LARGE")
    if not data:
        raise ValidationFailed("文件为空", code="FILE_EMPTY")
    if ext in MAGIC and not any(data.startswith(m) for m in MAGIC[ext]):
        raise ValidationFailed("文件内容与扩展名不符", code="FILE_CONTENT_MISMATCH")
    if ext in (".txt", ".md", ".csv"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationFailed("文本文件需为 UTF-8 编码", code="FILE_CONTENT_MISMATCH") from None
    storage = secrets.token_hex(16) + ext
    upload_dir: Path = request.app.state.settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = (upload_dir / storage).resolve()
    if upload_dir.resolve() not in target.parents:  # defensive: never escape the upload directory
        raise ValidationFailed("非法路径", code="INVALID_PATH")
    target.write_bytes(data)
    f = StoredFile(storage_name=storage, original_name=name, content_type=ALLOWED[ext], size=len(data),
                   sha256=hashlib.sha256(data).hexdigest(), purpose=purpose, uploaded_by=cu.id)
    db.add(f)
    db.flush()
    return f


class FileOut(BaseModel):
    id: int
    original_name: str
    content_type: str
    size: int
    sha256: str
    purpose: str
    created_at: datetime


@router.post("", response_model=FileOut, status_code=201, summary="上传附件（模拟票据 / 简历）")
def upload(request: Request, file: UploadFile = File(...), purpose: str = Form(...),
           cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    if purpose == "resume" and not cu.has("recruit:manage"):
        raise Forbidden("无权上传简历", code="PERMISSION_DENIED")
    f = store_upload(request, db, cu, file, purpose)
    audit(db, cu, "upload_file", "file", f.id, {"purpose": purpose, "size": f.size})
    db.commit()
    return FileOut.model_validate(f, from_attributes=True)


def can_read_file(db: Session, cu: CurrentUser, f: StoredFile) -> bool:
    if f.uploaded_by == cu.id or cu.is_admin:
        return True
    if f.purpose == "resume":
        return cu.has("recruit:manage")
    if f.purpose == "expense_receipt":
        if cu.has("expense:finance"):
            return True
        claim_ids = db.scalars(select(ExpenseItem.claim_id).where(ExpenseItem.receipt_file_id == f.id)).all()
        for cid in claim_ids:
            claim = db.get(ExpenseClaim, cid)
            if claim and claim.instance_id and db.scalar(select(WfTask.id).where(
                    WfTask.instance_id == claim.instance_id, WfTask.assignee_id == cu.id)):
                return True
    return False


@router.get("/{file_id}", summary="下载附件（按用途校验权限）")
def download(file_id: int, request: Request, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    f = db.get(StoredFile, file_id)
    if f is None or f.purpose == "document":
        raise NotFound("文件不存在")
    if not can_read_file(db, cu, f):
        raise Forbidden("无权下载该文件", code="PERMISSION_DENIED")
    path = request.app.state.settings.upload_dir / f.storage_name
    if not path.is_file():
        raise NotFound("文件内容缺失", code="FILE_MISSING")
    return FileResponse(path, media_type=f.content_type, filename=f.original_name)
