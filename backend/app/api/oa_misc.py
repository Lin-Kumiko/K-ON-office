"""Meeting rooms, announcements, notifications and personal schedules."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core import timeutil
from ..core.common import audit, idempotent, jsonable, notify, paginate
from ..core.deps import CurrentUser, PageParams, current_user, department_subtree, get_db, require
from ..core.errors import Conflict, Forbidden, InvalidState, NotFound, ValidationFailed
from ..models import (Announcement, AnnouncementCategory, AnnouncementRead, Department, Employee, MeetingBooking,
                      MeetingRoom, Notification, Schedule, User)
from ..workflow import engine
from .common import ERRORS, Msg, Page

router = APIRouter(prefix="/api", tags=["会议室·公告·通知·日程"], responses=ERRORS)

# ================================================================== meeting rooms


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    location: str | None = Field(None, max_length=128)
    capacity: int = Field(ge=1, le=1000)
    equipment: str | None = Field(None, max_length=255)
    requires_approval: bool = False
    open_from: str = Field("08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    open_to: str = Field("21:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    status: str = Field("active", pattern="^(active|disabled)$")


class RoomOut(RoomIn):
    id: int


@router.get("/meeting/rooms", response_model=list[RoomOut], summary="会议室列表")
def list_rooms(cu: CurrentUser = Depends(require("meeting:book")), db: Session = Depends(get_db)):
    return [RoomOut.model_validate(r, from_attributes=True) for r in db.scalars(select(MeetingRoom).order_by(MeetingRoom.id))]


@router.post("/meeting/rooms", response_model=RoomOut, status_code=201, summary="创建会议室")
def create_room(body: RoomIn, cu: CurrentUser = Depends(require("meeting:manage")), db: Session = Depends(get_db)):
    if db.scalar(select(MeetingRoom.id).where(MeetingRoom.name == body.name)):
        raise Conflict("会议室名称已存在", code="ROOM_EXISTS")
    if body.open_to <= body.open_from:
        raise ValidationFailed("开放结束时间需晚于开始时间", code="INVALID_OPEN_HOURS")
    r = MeetingRoom(**body.model_dump())
    db.add(r)
    db.flush()
    audit(db, cu, "create_room", "meeting_room", r.id)
    db.commit()
    return RoomOut.model_validate(r, from_attributes=True)


@router.put("/meeting/rooms/{room_id}", response_model=RoomOut, summary="修改会议室")
def update_room(room_id: int, body: RoomIn, cu: CurrentUser = Depends(require("meeting:manage")),
                db: Session = Depends(get_db)):
    r = db.get(MeetingRoom, room_id)
    if r is None:
        raise NotFound("会议室不存在")
    if body.open_to <= body.open_from:
        raise ValidationFailed("开放结束时间需晚于开始时间", code="INVALID_OPEN_HOURS")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit(db, cu, "update_room", "meeting_room", r.id)
    db.commit()
    return RoomOut.model_validate(r, from_attributes=True)


class BookingIn(BaseModel):
    room_id: int
    subject: str = Field(min_length=1, max_length=128)
    start_at: datetime
    end_at: datetime
    attendee_ids: list[int] = Field(default_factory=list, max_length=200)
    note: str | None = Field(None, max_length=500)


class BookingOut(BaseModel):
    id: int
    room_id: int
    room_name: str
    organizer_id: int
    organizer_name: str | None
    subject: str
    start_at: datetime
    end_at: datetime
    attendee_ids: list[int]
    note: str | None
    status: str
    instance_id: int | None
    created_at: datetime


def booking_out(db: Session, b: MeetingBooking) -> BookingOut:
    org = db.get(User, b.organizer_id)
    return BookingOut(id=b.id, room_id=b.room_id, room_name=b.room.name, organizer_id=b.organizer_id,
                      organizer_name=org.display_name if org else None, subject=b.subject, start_at=b.start_at,
                      end_at=b.end_at, attendee_ids=b.attendee_ids or [], note=b.note, status=b.status,
                      instance_id=b.instance_id, created_at=b.created_at)


def _overlap(db: Session, room_id: int, start: datetime, end: datetime, exclude: int | None = None):
    return db.scalar(select(MeetingBooking).where(
        MeetingBooking.room_id == room_id, MeetingBooking.status.in_(("pending", "approved")),
        MeetingBooking.start_at < end, MeetingBooking.end_at > start, MeetingBooking.id != (exclude or -1)))


class SlotOut(BaseModel):
    booking_id: int
    start_at: datetime
    end_at: datetime
    status: str
    subject: str


class AvailabilityOut(BaseModel):
    room_id: int
    day: date
    open_from: str
    open_to: str
    busy: list[SlotOut]


@router.get("/meeting/rooms/{room_id}/availability", response_model=AvailabilityOut, summary="查询某日占用情况")
def availability(room_id: int, day: date, cu: CurrentUser = Depends(require("meeting:book")),
                 db: Session = Depends(get_db)):
    r = db.get(MeetingRoom, room_id)
    if r is None:
        raise NotFound("会议室不存在")
    start = datetime.combine(day, time())
    rows = db.scalars(select(MeetingBooking).where(
        MeetingBooking.room_id == room_id, MeetingBooking.status.in_(("pending", "approved")),
        MeetingBooking.start_at < start + timedelta(days=1), MeetingBooking.end_at > start)
        .order_by(MeetingBooking.start_at))
    return AvailabilityOut(room_id=r.id, day=day, open_from=r.open_from, open_to=r.open_to,
                           busy=[SlotOut(booking_id=b.id, start_at=b.start_at, end_at=b.end_at, status=b.status,
                                         subject=b.subject) for b in rows])


@router.post("/meeting/bookings", response_model=BookingOut, status_code=201,
             summary="预约会议室（冲突检测；需审批的会议室发起流程）")
def create_booking(body: BookingIn, request: Request, cu: CurrentUser = Depends(require("meeting:book")),
                   db: Session = Depends(get_db)):
    def action():
        r = db.get(MeetingRoom, body.room_id)
        if r is None or r.status != "active":
            raise ValidationFailed("会议室不存在或已停用", code="ROOM_UNAVAILABLE")
        s, e = timeutil.to_local(body.start_at), timeutil.to_local(body.end_at)
        if e <= s:
            raise ValidationFailed("结束时间必须晚于开始时间", code="INVALID_TIME_RANGE")
        if s < timeutil.now():
            raise ValidationFailed("不能预约过去的时间", code="PAST_BOOKING")
        if s.date() != e.date():
            raise ValidationFailed("预约不能跨天", code="CROSS_DAY_BOOKING")
        if e - s > timedelta(hours=8) or e - s < timedelta(minutes=15):
            raise ValidationFailed("单次预约时长需在 15 分钟到 8 小时之间", code="INVALID_DURATION")
        if s.strftime("%H:%M") < r.open_from or e.strftime("%H:%M") > r.open_to:
            raise ValidationFailed(f"会议室开放时间为 {r.open_from}-{r.open_to}", code="OUT_OF_OPEN_HOURS")
        attendees = list(dict.fromkeys(a for a in body.attendee_ids if a != cu.id))
        if attendees:
            found = set(db.scalars(select(User.id).where(User.id.in_(attendees), User.status == "active")))
            if found != set(attendees):
                raise ValidationFailed("参会人包含不存在或已停用的用户", code="INVALID_ATTENDEES")
        if len(attendees) + 1 > r.capacity:
            raise ValidationFailed(f"参会人数超过会议室容量 {r.capacity}", code="OVER_CAPACITY")
        clash = _overlap(db, r.id, s, e)
        if clash:
            raise Conflict(f"该时段已被预约（{clash.start_at:%H:%M}-{clash.end_at:%H:%M}）", code="BOOKING_CONFLICT",
                           details={"booking_id": clash.id})
        b = MeetingBooking(room_id=r.id, organizer_id=cu.id, subject=body.subject, start_at=s, end_at=e,
                           attendee_ids=attendees, note=body.note,
                           status="pending" if r.requires_approval else "approved")
        db.add(b)
        db.flush()  # DB trigger is the final guard against concurrent double booking
        if r.requires_approval:
            inst = engine.start(db, business_type="meeting", business_id=b.id,
                                title=f"{cu.user.display_name}预约「{r.name}」：{b.subject}（{s:%m-%d %H:%M}）",
                                initiator_id=cu.id, subject_employee_id=cu.employee.id if cu.employee else None,
                                variables={"room_id": r.id, "duration_hours": (e - s).total_seconds() / 3600})
            b.instance_id = inst.id
        else:
            for uid in attendees:
                notify(db, uid, "meeting", f"会议邀请：{b.subject}", f"{r.name} {s:%m-%d %H:%M}-{e:%H:%M}",
                       f"/meeting?booking={b.id}", "meeting_booking", b.id)
        db.flush()
        db.refresh(b)
        return 201, jsonable(booking_out(db, b))
    return idempotent(db, cu, request, body.model_dump(mode="json"), action)


@router.get("/meeting/bookings", response_model=Page[BookingOut], summary="预约记录（mine / all）")
def list_bookings(scope: str = Query("mine", pattern="^(mine|all)$"), room_id: int | None = None,
                  status: str | None = None, start: date | None = None, end: date | None = None,
                  page: PageParams = Depends(), cu: CurrentUser = Depends(require("meeting:book")),
                  db: Session = Depends(get_db)):
    stmt = select(MeetingBooking)
    if scope == "mine":
        stmt = stmt.where(MeetingBooking.organizer_id == cu.id)
    else:
        cu.require("meeting:manage")
    if room_id:
        stmt = stmt.where(MeetingBooking.room_id == room_id)
    if status:
        stmt = stmt.where(MeetingBooking.status == status)
    if start:
        stmt = stmt.where(MeetingBooking.end_at >= datetime.combine(start, time()))
    if end:
        stmt = stmt.where(MeetingBooking.start_at < datetime.combine(end + timedelta(days=1), time()))
    return paginate(db, stmt, page, {"start_at": MeetingBooking.start_at, "id": MeetingBooking.id},
                    MeetingBooking.start_at.desc(), lambda b: booking_out(db, b))


@router.get("/meeting/calendar", response_model=list[BookingOut], summary="会议日历（有效预约）")
def calendar_view(start: date, end: date, room_id: int | None = None,
                  cu: CurrentUser = Depends(require("meeting:book")), db: Session = Depends(get_db)):
    if end < start or (end - start).days > 62:
        raise ValidationFailed("日历区间需在 62 天内", code="INVALID_RANGE")
    stmt = select(MeetingBooking).where(
        MeetingBooking.status.in_(("pending", "approved")),
        MeetingBooking.start_at < datetime.combine(end + timedelta(days=1), time()),
        MeetingBooking.end_at > datetime.combine(start, time()))
    if room_id:
        stmt = stmt.where(MeetingBooking.room_id == room_id)
    return [booking_out(db, b) for b in db.scalars(stmt.order_by(MeetingBooking.start_at))]


@router.post("/meeting/bookings/{bid}/cancel", response_model=BookingOut, summary="取消预约")
def cancel_booking(bid: int, cu: CurrentUser = Depends(require("meeting:book")), db: Session = Depends(get_db)):
    b = db.get(MeetingBooking, bid)
    if b is None:
        raise NotFound("预约不存在")
    if b.organizer_id != cu.id and not cu.has("meeting:manage"):
        raise Forbidden("只能取消本人的预约", code="NOT_OWNER")
    if b.status == "pending":
        engine.withdraw_for_business(db, "meeting", b.id, cu.id, cancel_instead=True,
                                     can_monitor=cu.has("meeting:manage") or cu.has("workflow:monitor"))
    elif b.status == "approved":
        if b.end_at <= timeutil.now():
            raise InvalidState("会议已结束，不能取消", code="MEETING_FINISHED")
        b.status = "cancelled"
    else:
        raise InvalidState(f"预约状态为 {b.status}，不能取消", code="INVALID_STATE")
    b.cancelled_at = timeutil.now()
    for uid in b.attendee_ids or []:
        notify(db, uid, "meeting", f"会议已取消：{b.subject}", None, None, "meeting_booking", b.id)
    db.commit()
    return booking_out(db, b)


class UsageOut(BaseModel):
    room_id: int
    month: str
    bookings: int
    hours: float
    records: list[BookingOut]


@router.get("/meeting/rooms/{room_id}/usage", response_model=UsageOut, summary="会议室使用记录")
def room_usage(room_id: int, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
               cu: CurrentUser = Depends(require("meeting:book")), db: Session = Depends(get_db)):
    if db.get(MeetingRoom, room_id) is None:
        raise NotFound("会议室不存在")
    s, e = timeutil.month_bounds(month)
    rows = db.scalars(select(MeetingBooking).where(
        MeetingBooking.room_id == room_id, MeetingBooking.status == "approved",
        MeetingBooking.start_at >= datetime.combine(s, time()),
        MeetingBooking.start_at < datetime.combine(e + timedelta(days=1), time())).order_by(MeetingBooking.start_at)).all()
    return UsageOut(room_id=room_id, month=month, bookings=len(rows),
                    hours=round(sum((b.end_at - b.start_at).total_seconds() for b in rows) / 3600, 2),
                    records=[booking_out(db, b) for b in rows])


# ================================================================== announcements
class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20000)
    category_id: int | None = None
    scope_type: str = Field("all", pattern="^(all|departments)$")
    scope_department_ids: list[int] = Field(default_factory=list, max_length=100)
    pinned: bool = False


class AnnouncementOut(BaseModel):
    id: int
    title: str
    content: str
    category_id: int | None
    category_name: str | None
    status: str
    scope_type: str
    scope_department_ids: list[int]
    pinned: bool
    author_id: int
    author_name: str | None
    published_at: datetime | None
    withdrawn_at: datetime | None
    created_at: datetime
    read: bool = False


def ann_out(db: Session, a: Announcement, read: bool = False) -> AnnouncementOut:
    author = db.get(User, a.author_id)
    return AnnouncementOut(id=a.id, title=a.title, content=a.content, category_id=a.category_id,
                           category_name=a.category.name if a.category else None, status=a.status,
                           scope_type=a.scope_type, scope_department_ids=a.scope_department_ids or [],
                           pinned=a.pinned, author_id=a.author_id, author_name=author.display_name if author else None,
                           published_at=a.published_at, withdrawn_at=a.withdrawn_at, created_at=a.created_at,
                           read=read)


def _audience(db: Session, a: Announcement) -> list[int]:
    stmt = select(Employee.user_id).where(Employee.status != "resigned", Employee.user_id.is_not(None))
    if a.scope_type == "departments":
        depts: set[int] = set()
        for d in a.scope_department_ids or []:
            depts |= department_subtree(db, d)
        stmt = stmt.where(Employee.department_id.in_(depts))
    return list(db.scalars(stmt))


def _visible(db: Session, cu: CurrentUser, a: Announcement) -> bool:
    if cu.has("announcement:manage"):
        return True
    return _visible_to_member(db, cu, a)


def _visible_to_member(db: Session, cu: CurrentUser, a: Announcement) -> bool:
    if a.status != "published":
        return False
    if a.scope_type == "all":
        return True
    if cu.employee is None:
        return False
    for d in a.scope_department_ids or []:
        if cu.employee.department_id in department_subtree(db, d):
            return True
    return False


@router.get("/announcements/categories", summary="公告分类")
def ann_categories(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(AnnouncementCategory).order_by(AnnouncementCategory.id))]


@router.get("/announcements", response_model=Page[AnnouncementOut], summary="公告列表（visible 可见 / manage 管理）")
def list_announcements(scope: str = Query("visible", pattern="^(visible|manage)$"), status: str | None = None,
                       category_id: int | None = None, q: str | None = Query(None, max_length=64),
                       unread_only: bool = False, page: PageParams = Depends(),
                       cu: CurrentUser = Depends(require("announcement:read")), db: Session = Depends(get_db)):
    stmt = select(Announcement)
    if scope == "manage":
        cu.require("announcement:manage")
        if status:
            stmt = stmt.where(Announcement.status == status)
    else:
        stmt = stmt.where(Announcement.status == "published")
        ids = [a.id for a in db.scalars(select(Announcement).where(Announcement.status == "published"))
               if _visible_to_member(db, cu, a)]
        stmt = stmt.where(Announcement.id.in_(ids))
    if category_id:
        stmt = stmt.where(Announcement.category_id == category_id)
    if q:
        stmt = stmt.where(Announcement.title.ilike(f"%{q}%"))
    reads = set(db.scalars(select(AnnouncementRead.announcement_id).where(AnnouncementRead.user_id == cu.id)))
    if unread_only:
        stmt = stmt.where(Announcement.id.not_in(reads) if reads else Announcement.id.is_not(None))
    result = paginate(db, stmt, page, {"published_at": Announcement.published_at, "id": Announcement.id},
                      (Announcement.pinned.desc(), Announcement.published_at.desc(), Announcement.id.desc()),
                      lambda a: ann_out(db, a, a.id in reads))
    return result


def _get_ann(db: Session, cu: CurrentUser, aid: int) -> Announcement:
    a = db.get(Announcement, aid)
    if a is None or not _visible(db, cu, a):
        raise NotFound("公告不存在")
    return a


def _ann_validate(db: Session, body: AnnouncementIn) -> None:
    if body.category_id and db.get(AnnouncementCategory, body.category_id) is None:
        raise ValidationFailed("公告分类不存在", code="INVALID_CATEGORY")
    if body.scope_type == "departments":
        if not body.scope_department_ids:
            raise ValidationFailed("按部门发布需选择部门", code="SCOPE_REQUIRED")
        n = db.scalar(select(func.count()).select_from(Department).where(Department.id.in_(body.scope_department_ids)))
        if n != len(set(body.scope_department_ids)):
            raise ValidationFailed("阅读范围包含不存在的部门", code="INVALID_SCOPE")


@router.post("/announcements", response_model=AnnouncementOut, status_code=201, summary="新建公告草稿")
def create_announcement(body: AnnouncementIn, cu: CurrentUser = Depends(require("announcement:manage")),
                        db: Session = Depends(get_db)):
    _ann_validate(db, body)
    a = Announcement(**body.model_dump(), author_id=cu.id, status="draft")
    if body.scope_type == "all":
        a.scope_department_ids = []
    db.add(a)
    db.flush()
    audit(db, cu, "create_announcement", "announcement", a.id)
    db.commit()
    return ann_out(db, a)


@router.get("/announcements/{aid}", response_model=AnnouncementOut, summary="公告详情")
def get_announcement(aid: int, cu: CurrentUser = Depends(require("announcement:read")), db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    read = db.get(AnnouncementRead, (a.id, cu.id)) is not None
    return ann_out(db, a, read)


@router.put("/announcements/{aid}", response_model=AnnouncementOut, summary="编辑公告（草稿或已撤回）")
def update_announcement(aid: int, body: AnnouncementIn, cu: CurrentUser = Depends(require("announcement:manage")),
                        db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    if a.status == "published":
        raise InvalidState("已发布公告需先撤回再编辑", code="INVALID_STATE")
    _ann_validate(db, body)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return ann_out(db, a)


@router.post("/announcements/{aid}/publish", response_model=AnnouncementOut, summary="发布（向阅读范围发送站内通知）")
def publish_announcement(aid: int, cu: CurrentUser = Depends(require("announcement:manage")),
                         db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    if a.status == "published":
        raise InvalidState("公告已发布", code="INVALID_STATE")
    a.status = "published"
    a.published_at = timeutil.now()
    a.withdrawn_at = None
    for uid in _audience(db, a):
        notify(db, uid, "announcement", f"新公告：{a.title}", None, f"/announcements?id={a.id}", "announcement", a.id)
    audit(db, cu, "publish_announcement", "announcement", a.id)
    db.commit()
    return ann_out(db, a)


@router.post("/announcements/{aid}/withdraw", response_model=AnnouncementOut, summary="撤回公告")
def withdraw_announcement(aid: int, cu: CurrentUser = Depends(require("announcement:manage")),
                          db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    if a.status != "published":
        raise InvalidState("只有已发布公告可以撤回", code="INVALID_STATE")
    a.status = "withdrawn"
    a.withdrawn_at = timeutil.now()
    audit(db, cu, "withdraw_announcement", "announcement", a.id)
    db.commit()
    return ann_out(db, a)


@router.delete("/announcements/{aid}", response_model=Msg, summary="删除草稿公告")
def delete_announcement(aid: int, cu: CurrentUser = Depends(require("announcement:manage")),
                        db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    if a.status != "draft":
        raise InvalidState("只有草稿可以删除", code="INVALID_STATE")
    db.delete(a)
    db.commit()
    return Msg(message="已删除")


@router.post("/announcements/{aid}/read", response_model=Msg, summary="标记已读（幂等）")
def read_announcement(aid: int, cu: CurrentUser = Depends(require("announcement:read")), db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    if a.status != "published":
        raise InvalidState("公告未发布", code="INVALID_STATE")
    if db.get(AnnouncementRead, (a.id, cu.id)) is None:
        db.add(AnnouncementRead(announcement_id=a.id, user_id=cu.id, read_at=timeutil.now()))
    db.execute(update(Notification).where(Notification.user_id == cu.id, Notification.ref_type == "announcement",
                                          Notification.ref_id == a.id, Notification.read_at.is_(None))
               .values(read_at=timeutil.now()))
    db.commit()
    return Msg()


class ReadStatOut(BaseModel):
    target: int
    read: int
    unread_names: list[str]


@router.get("/announcements/{aid}/reads", response_model=ReadStatOut, summary="阅读统计")
def announcement_reads(aid: int, cu: CurrentUser = Depends(require("announcement:manage")),
                       db: Session = Depends(get_db)):
    a = _get_ann(db, cu, aid)
    audience = set(_audience(db, a))
    read = set(db.scalars(select(AnnouncementRead.user_id).where(AnnouncementRead.announcement_id == a.id)))
    names = dict(db.execute(select(User.id, User.display_name)).all())
    return ReadStatOut(target=len(audience), read=len(audience & read),
                       unread_names=sorted(names.get(u, "?") for u in audience - read))


# ================================================================== notifications
class NotificationOut(BaseModel):
    id: int
    category: str
    title: str
    content: str | None
    link: str | None
    ref_type: str | None
    ref_id: int | None
    read_at: datetime | None
    created_at: datetime


@router.get("/notifications", response_model=Page[NotificationOut], summary="站内通知（历史）")
def list_notifications(unread_only: bool = False, category: str | None = None, page: PageParams = Depends(),
                       cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == cu.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if category:
        stmt = stmt.where(Notification.category == category)
    return paginate(db, stmt, page, None, Notification.id.desc(),
                    lambda n: NotificationOut.model_validate(n, from_attributes=True))


@router.get("/notifications/unread-count", summary="未读数")
def unread_count(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return {"count": db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == cu.id, Notification.read_at.is_(None)))}


@router.post("/notifications/{nid}/read", response_model=Msg, summary="标记已读")
def read_notification(nid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None or n.user_id != cu.id:
        raise NotFound("通知不存在")
    if n.read_at is None:
        n.read_at = timeutil.now()
    db.commit()
    return Msg()


@router.post("/notifications/read-all", response_model=Msg, summary="全部标记已读")
def read_all(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    res = db.execute(update(Notification).where(Notification.user_id == cu.id, Notification.read_at.is_(None))
                     .values(read_at=timeutil.now()))
    db.commit()
    return Msg(message=f"已读 {res.rowcount} 条")


# ================================================================== schedules
class ScheduleIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    start_at: datetime
    end_at: datetime
    remind_at: datetime | None = None
    note: str | None = Field(None, max_length=1000)


class ScheduleOut(ScheduleIn):
    id: int


def _sched_check(body: ScheduleIn) -> None:
    if body.end_at <= body.start_at:
        raise ValidationFailed("结束时间必须晚于开始时间", code="INVALID_TIME_RANGE")
    if body.remind_at and body.remind_at > body.start_at:
        raise ValidationFailed("提醒时间不能晚于开始时间", code="INVALID_REMIND_TIME")


@router.get("/schedules", response_model=list[ScheduleOut], summary="我的日程")
def list_schedules(start: date, end: date, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Schedule).where(Schedule.user_id == cu.id,
                                             Schedule.start_at < datetime.combine(end + timedelta(days=1), time()),
                                             Schedule.end_at > datetime.combine(start, time()))
                      .order_by(Schedule.start_at))
    return [ScheduleOut.model_validate(s, from_attributes=True) for s in rows]


@router.post("/schedules", response_model=ScheduleOut, status_code=201, summary="新建日程")
def create_schedule(body: ScheduleIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    body = ScheduleIn(**{k: timeutil.to_local(v) if isinstance(v, datetime) else v for k, v in body.model_dump().items()})
    _sched_check(body)
    s = Schedule(user_id=cu.id, **body.model_dump())
    db.add(s)
    db.commit()
    return ScheduleOut.model_validate(s, from_attributes=True)


@router.put("/schedules/{sid}", response_model=ScheduleOut, summary="修改日程")
def update_schedule(sid: int, body: ScheduleIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Schedule, sid)
    if s is None or s.user_id != cu.id:
        raise NotFound("日程不存在")
    body = ScheduleIn(**{k: timeutil.to_local(v) if isinstance(v, datetime) else v for k, v in body.model_dump().items()})
    _sched_check(body)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return ScheduleOut.model_validate(s, from_attributes=True)


@router.delete("/schedules/{sid}", response_model=Msg, summary="删除日程")
def delete_schedule(sid: int, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Schedule, sid)
    if s is None or s.user_id != cu.id:
        raise NotFound("日程不存在")
    db.delete(s)
    db.commit()
    return Msg(message="已删除")
