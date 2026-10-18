"""Anonymous, read-only overview for visitors (no login required)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.deps import department_subtree, get_db
from ..models import (Announcement, AnnouncementCategory, Department, Document, Employee, MeetingBooking, MeetingRoom,
                      SystemSetting, WfDefinition)
from .common import ERRORS

router = APIRouter(prefix="/api/public", tags=["公开访问"], responses=ERRORS)


class PublicAnnouncement(BaseModel):
    id: int
    title: str
    category: str | None
    pinned: bool
    published_at: datetime | None


class PublicMeeting(BaseModel):
    subject: str
    room: str
    start_at: datetime
    end_at: datetime


class DeptCount(BaseModel):
    name: str
    headcount: int


class OverviewOut(BaseModel):
    company_name: str
    slogan: str
    stats: dict[str, int]
    announcements: list[PublicAnnouncement]
    meetings: list[PublicMeeting]
    departments: list[DeptCount]
    registration_open: bool


@router.get("/overview", response_model=OverviewOut, summary="公开概览（访客可见，无需登录）")
def overview(request: Request, db: Session = Depends(get_db)):
    settings = {s.key: s.value for s in db.scalars(select(SystemSetting))}
    now = timeutil.now()
    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery()))  # noqa: E731
    stats = {
        "departments": count(select(Department.id).where(Department.status == "active")),
        "headcount": count(select(Employee.id).where(Employee.status != "resigned")),
        "rooms": count(select(MeetingRoom.id).where(MeetingRoom.status == "active")),
        "announcements": count(select(Announcement.id).where(Announcement.status == "published",
                                                             Announcement.scope_type == "all")),
        "documents": count(select(Document.id).where(Document.status == "active", Document.visibility == "public")),
        "workflows": count(select(WfDefinition.id).where(WfDefinition.status == "active")),
    }
    cats = dict(db.execute(select(AnnouncementCategory.id, AnnouncementCategory.name)).all())
    anns = db.scalars(select(Announcement).where(Announcement.status == "published", Announcement.scope_type == "all")
                      .order_by(Announcement.pinned.desc(), Announcement.published_at.desc()).limit(5))
    rooms = dict(db.execute(select(MeetingRoom.id, MeetingRoom.name)).all())
    meetings = db.scalars(select(MeetingBooking).where(
        MeetingBooking.status == "approved", MeetingBooking.end_at >= now,
        MeetingBooking.start_at <= now + timedelta(days=7)).order_by(MeetingBooking.start_at).limit(8))
    root = db.scalar(select(Department).where(Department.parent_id.is_(None)).order_by(Department.id))
    active = dict(db.execute(select(Employee.department_id, func.count()).where(Employee.status != "resigned")
                             .group_by(Employee.department_id)).all())
    depts = []
    if root is not None:
        for d in db.scalars(select(Department).where(Department.parent_id == root.id, Department.status == "active")
                            .order_by(Department.sort, Department.id)):
            depts.append(DeptCount(name=d.name, headcount=sum(active.get(x, 0) for x in department_subtree(db, d.id))))
    return OverviewOut(
        company_name=str(settings.get("company.name") or "放学后茶会株式会社"),
        slogan=str(settings.get("company.slogan") or ""),
        stats=stats,
        announcements=[PublicAnnouncement(id=a.id, title=a.title, category=cats.get(a.category_id), pinned=a.pinned,
                                          published_at=a.published_at) for a in anns],
        meetings=[PublicMeeting(subject=b.subject, room=rooms.get(b.room_id, ""), start_at=b.start_at, end_at=b.end_at)
                  for b in meetings],
        departments=depts,
        registration_open=request.app.state.settings.allow_registration,
    )
