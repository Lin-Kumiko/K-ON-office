"""Document center: categories, upload, versions, search, access control and history."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.common import audit, paginate
from ..core.deps import CurrentUser, PageParams, department_subtree, get_db, get_write_db, require
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import Department, DocCategory, Document, DocumentLog, DocumentVersion, User
from .common import ERRORS, Msg, Page
from .files import store_upload

router = APIRouter(prefix="/api/documents", tags=["文档中心"], responses=ERRORS)


class DocCategoryOut(BaseModel):
    id: int
    name: str
    parent_id: int | None


class DocCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None


@router.get("/categories", response_model=list[DocCategoryOut], summary="文档分类")
def categories(cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_db)):
    return [DocCategoryOut.model_validate(c, from_attributes=True) for c in db.scalars(select(DocCategory).order_by(DocCategory.id))]


@router.post("/categories", response_model=DocCategoryOut, status_code=201, summary="新建文档分类")
def create_category(body: DocCategoryIn, cu: CurrentUser = Depends(require("document:manage")),
                    db: Session = Depends(get_db)):
    if db.scalar(select(DocCategory.id).where(DocCategory.name == body.name)):
        raise Conflict("分类已存在", code="CATEGORY_EXISTS")
    if body.parent_id and db.get(DocCategory, body.parent_id) is None:
        raise ValidationFailed("上级分类不存在", code="INVALID_CATEGORY")
    c = DocCategory(name=body.name, parent_id=body.parent_id)
    db.add(c)
    db.commit()
    return DocCategoryOut.model_validate(c, from_attributes=True)


class VersionOut(BaseModel):
    id: int
    version_no: int
    file_name: str
    size: int
    sha256: str
    note: str | None
    uploaded_by: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    id: int
    title: str
    category_id: int | None
    category_name: str | None
    owner_id: int
    owner_name: str | None
    visibility: str
    department_id: int | None
    department_name: str | None
    keywords: str | None
    description: str | None
    current_version: int
    status: str
    created_at: datetime
    updated_at: datetime
    can_edit: bool
    versions: list[VersionOut] = []


def can_read(db: Session, cu: CurrentUser, d: Document) -> bool:
    if d.status != "active":
        return cu.has("document:manage")
    if cu.has("document:manage") or d.owner_id == cu.id or d.visibility == "public":
        return True
    if d.visibility == "department" and d.department_id and cu.employee is not None:
        return cu.employee.department_id in department_subtree(db, d.department_id)
    return False


def can_edit(cu: CurrentUser, d: Document) -> bool:
    return d.owner_id == cu.id or cu.has("document:manage")


def doc_out(db: Session, cu: CurrentUser, d: Document, with_versions: bool = False) -> DocumentOut:
    users = dict(db.execute(select(User.id, User.display_name)).all())
    dept = db.get(Department, d.department_id) if d.department_id else None
    versions = []
    if with_versions:
        for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d.id)
                            .order_by(DocumentVersion.version_no.desc())):
            versions.append(VersionOut(id=v.id, version_no=v.version_no, file_name=v.file.original_name,
                                       size=v.file.size, sha256=v.file.sha256, note=v.note,
                                       uploaded_by=users.get(v.uploaded_by), created_at=v.created_at))
    return DocumentOut(id=d.id, title=d.title, category_id=d.category_id,
                       category_name=d.category.name if d.category else None, owner_id=d.owner_id,
                       owner_name=users.get(d.owner_id), visibility=d.visibility, department_id=d.department_id,
                       department_name=dept.name if dept else None, keywords=d.keywords, description=d.description,
                       current_version=d.current_version, status=d.status, created_at=d.created_at,
                       updated_at=d.updated_at, can_edit=can_edit(cu, d), versions=versions)


def _log(db: Session, d: Document, cu: CurrentUser, action: str, detail: dict | None = None) -> None:
    db.add(DocumentLog(document_id=d.id, user_id=cu.id, action=action, detail=detail))


def _check_meta(db: Session, cu: CurrentUser, category_id: int | None, visibility: str, department_id: int | None):
    if visibility not in ("public", "department", "private"):
        raise ValidationFailed("可见范围无效", code="INVALID_VISIBILITY")
    if category_id is not None and db.get(DocCategory, category_id) is None:
        raise ValidationFailed("分类不存在", code="INVALID_CATEGORY")
    if visibility == "department":
        if department_id is None:
            department_id = cu.employee.department_id if cu.employee else None
        if department_id is None or db.get(Department, department_id) is None:
            raise ValidationFailed("部门可见需指定有效部门", code="INVALID_DEPARTMENT")
    else:
        department_id = None
    return department_id


@router.get("", response_model=Page[DocumentOut], summary="文档搜索（标题/关键字/描述，按权限过滤）")
def list_documents(q: str | None = Query(None, max_length=64), category_id: int | None = None,
                   mine: bool = False, include_deleted: bool = False, page: PageParams = Depends(),
                   cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_db)):
    stmt = select(Document)
    if not (include_deleted and cu.has("document:manage")):
        stmt = stmt.where(Document.status == "active")
    if mine:
        stmt = stmt.where(Document.owner_id == cu.id)
    if not cu.has("document:manage"):
        conds = [Document.visibility == "public", Document.owner_id == cu.id]
        if cu.employee is not None:
            depts = [d for d in db.scalars(select(Department.id))
                     if cu.employee.department_id in department_subtree(db, d)]
            conds.append((Document.visibility == "department") & Document.department_id.in_(depts))
        stmt = stmt.where(or_(*conds))
    if category_id:
        stmt = stmt.where(Document.category_id == category_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.keywords.ilike(like),
                              Document.description.ilike(like)))
    return paginate(db, stmt, page, {"updated_at": Document.updated_at, "title": Document.title},
                    Document.updated_at.desc(), lambda d: doc_out(db, cu, d))


@router.post("", response_model=DocumentOut, status_code=201, summary="上传新文档（生成 v1）")
def create_document(request: Request, title: str = Form(..., min_length=1, max_length=128),
                    visibility: str = Form("public"), category_id: int | None = Form(None),
                    department_id: int | None = Form(None), keywords: str | None = Form(None, max_length=255),
                    description: str | None = Form(None, max_length=500), note: str | None = Form(None, max_length=255),
                    file: UploadFile = File(...), cu: CurrentUser = Depends(require("document:upload")),
                    db: Session = Depends(get_db)):
    department_id = _check_meta(db, cu, category_id, visibility, department_id)
    f = store_upload(request, db, cu, file, "document")
    d = Document(title=title.strip(), category_id=category_id, owner_id=cu.id, visibility=visibility,
                 department_id=department_id, keywords=keywords, description=description, current_version=1)
    db.add(d)
    db.flush()
    db.add(DocumentVersion(document_id=d.id, version_no=1, file_id=f.id, note=note or "初始版本", uploaded_by=cu.id))
    _log(db, d, cu, "create", {"version": 1, "file": f.original_name})
    audit(db, cu, "create_document", "document", d.id)
    db.commit()
    return doc_out(db, cu, d, True)


def _get(db: Session, cu: CurrentUser, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if d is None or not can_read(db, cu, d):
        raise NotFound("文档不存在或无权访问")
    return d


@router.get("/{doc_id}", response_model=DocumentOut, summary="文档详情（含版本）")
def get_document(doc_id: int, cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_db)):
    return doc_out(db, cu, _get(db, cu, doc_id), True)


class DocUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    category_id: int | None = None
    visibility: str = Field(pattern="^(public|department|private)$")
    department_id: int | None = None
    keywords: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=500)


@router.put("/{doc_id}", response_model=DocumentOut, summary="修改文档信息与访问权限")
def update_document(doc_id: int, body: DocUpdate, cu: CurrentUser = Depends(require("document:read")),
                    db: Session = Depends(get_db)):
    d = _get(db, cu, doc_id)
    if not can_edit(cu, d):
        raise Forbidden("只有上传者或文档管理员可以修改", code="NOT_OWNER")
    dept = _check_meta(db, cu, body.category_id, body.visibility, body.department_id)
    perm_change = (d.visibility, d.department_id) != (body.visibility, dept)
    before = {"visibility": d.visibility, "department_id": d.department_id}
    d.title, d.category_id, d.visibility, d.department_id = body.title, body.category_id, body.visibility, dept
    d.keywords, d.description = body.keywords, body.description
    _log(db, d, cu, "permission" if perm_change else "update",
         {"before": before, "after": {"visibility": d.visibility, "department_id": dept}} if perm_change else None)
    db.commit()
    return doc_out(db, cu, d, True)


@router.post("/{doc_id}/versions", response_model=DocumentOut, status_code=201, summary="上传新版本")
def upload_version(doc_id: int, request: Request, file: UploadFile = File(...),
                   note: str | None = Form(None, max_length=255), cu: CurrentUser = Depends(require("document:upload")),
                   db: Session = Depends(get_db)):
    d = _get(db, cu, doc_id)
    if not can_edit(cu, d):
        raise Forbidden("只有上传者或文档管理员可以上传新版本", code="NOT_OWNER")
    if d.status != "active":
        raise Conflict("文档已删除", code="DOCUMENT_DELETED")
    f = store_upload(request, db, cu, file, "document")
    d.current_version += 1
    db.add(DocumentVersion(document_id=d.id, version_no=d.current_version, file_id=f.id, note=note, uploaded_by=cu.id))
    _log(db, d, cu, "upload", {"version": d.current_version, "file": f.original_name})
    db.commit()
    return doc_out(db, cu, d, True)


@router.get("/{doc_id}/download", summary="下载（默认当前版本；记录下载日志）")
def download(doc_id: int, request: Request, version: int | None = Query(None, ge=1),
             cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_write_db)):
    d = _get(db, cu, doc_id)
    v = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == d.id,
                                                DocumentVersion.version_no == (version or d.current_version)))
    if v is None:
        raise NotFound("版本不存在")
    path = request.app.state.settings.upload_dir / v.file.storage_name
    if not path.is_file():
        raise NotFound("文件内容缺失", code="FILE_MISSING")
    _log(db, d, cu, "download", {"version": v.version_no})
    db.commit()
    return FileResponse(path, media_type=v.file.content_type, filename=v.file.original_name)


class LogOut(BaseModel):
    id: int
    action: str
    user_name: str | None
    detail: dict | None
    created_at: datetime


@router.get("/{doc_id}/logs", response_model=list[LogOut], summary="文档历史记录")
def doc_logs(doc_id: int, cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_db)):
    d = _get(db, cu, doc_id)
    if not can_edit(cu, d):
        raise Forbidden("只有上传者或文档管理员可以查看历史", code="NOT_OWNER")
    users = dict(db.execute(select(User.id, User.display_name)).all())
    return [LogOut(id=g.id, action=g.action, user_name=users.get(g.user_id), detail=g.detail, created_at=g.created_at)
            for g in db.scalars(select(DocumentLog).where(DocumentLog.document_id == d.id).order_by(DocumentLog.id.desc()))]


@router.delete("/{doc_id}", response_model=Msg, summary="删除文档（软删除，可由管理员查看）")
def delete_document(doc_id: int, cu: CurrentUser = Depends(require("document:read")), db: Session = Depends(get_db)):
    d = _get(db, cu, doc_id)
    if not can_edit(cu, d):
        raise Forbidden("只有上传者或文档管理员可以删除", code="NOT_OWNER")
    d.status = "deleted"
    _log(db, d, cu, "delete")
    audit(db, cu, "delete_document", "document", d.id)
    db.commit()
    return Msg(message="已删除")
