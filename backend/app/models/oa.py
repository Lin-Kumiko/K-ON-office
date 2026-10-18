"""OA tables: leave, travel, expense, meeting rooms, announcements, documents."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedMixin, JSONText, TimestampMixin

DOC_STATUSES = "('draft','pending','approved','rejected','withdrawn','cancelled')"


class LeaveType(TimestampMixin, Base):
    __tablename__ = "leave_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_balance: Mapped[bool] = mapped_column(Boolean, default=True)
    default_hours: Mapped[int] = mapped_column(Integer, default=0)  # yearly grant, hours
    description: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")


class LeaveBalance(TimestampMixin, Base):
    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "year"),
        CheckConstraint("used_hours >= 0 AND pending_hours >= 0 AND total_hours >= 0", name="non_negative"),
        CheckConstraint("used_hours + pending_hours <= total_hours", name="not_overdrawn"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id", ondelete="RESTRICT"))
    year: Mapped[int] = mapped_column(Integer)
    total_hours: Mapped[int] = mapped_column(Integer, default=0)
    used_hours: Mapped[int] = mapped_column(Integer, default=0)
    pending_hours: Mapped[int] = mapped_column(Integer, default=0)
    leave_type = relationship("LeaveType")


class LeaveLedger(CreatedMixin, Base):
    """Every balance movement. (ref_type, ref_id, change_type) is unique so a business event
    can never be applied twice (idempotent deduction)."""
    __tablename__ = "leave_ledger"
    __table_args__ = (
        Index("uq_leave_ledger_ref", "ref_type", "ref_id", "seq", "change_type", unique=True,
              sqlite_where=text("ref_id IS NOT NULL")),
        Index("ix_leave_ledger_employee", "employee_id", "year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    balance_id: Mapped[int] = mapped_column(ForeignKey("leave_balances.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id", ondelete="RESTRICT"))
    year: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(24))  # grant/adjust/freeze/unfreeze/consume/overtime_credit
    hours: Mapped[int] = mapped_column(Integer)
    total_after: Mapped[int] = mapped_column(Integer)
    used_after: Mapped[int] = mapped_column(Integer)
    pending_after: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # submission number of the referenced document
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    remark: Mapped[str | None] = mapped_column(String(255))


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("start_half IN ('AM','PM') AND end_half IN ('AM','PM')", name="halves"),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("hours > 0", name="hours_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id", ondelete="RESTRICT"))
    start_date: Mapped[date] = mapped_column(Date)
    start_half: Mapped[str] = mapped_column(String(2), default="AM")
    end_date: Mapped[date] = mapped_column(Date)
    end_half: Mapped[str] = mapped_column(String(2), default="PM")
    hours: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    submit_seq: Mapped[int] = mapped_column(Integer, default=0)
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    leave_type = relationship("LeaveType")
    employee = relationship("Employee")


class TravelRequest(TimestampMixin, Base):
    __tablename__ = "travel_requests"
    __table_args__ = (
        CheckConstraint("status IN ('draft','pending','approved','rejected','withdrawn','cancelled','changed')",
                        name="status"),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("estimated_cost_cents >= 0", name="cost_non_negative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    destination: Mapped[str] = mapped_column(String(128))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    purpose: Mapped[str] = mapped_column(String(500))
    transport: Mapped[str | None] = mapped_column(String(32))
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    original_id: Mapped[int | None] = mapped_column(ForeignKey("travel_requests.id", ondelete="SET NULL"))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    employee = relationship("Employee")


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    item_limit_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")


class ExpenseClaim(TimestampMixin, Base):
    __tablename__ = "expense_claims"
    __table_args__ = (
        CheckConstraint("status IN ('draft','pending','approved','rejected','withdrawn','cancelled','paid','archived')",
                        name="status"),
        CheckConstraint("total_cents >= 0", name="total_non_negative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_no: Mapped[str] = mapped_column(String(32), unique=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    travel_id: Mapped[int | None] = mapped_column(ForeignKey("travel_requests.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    finance_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finance_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    payment_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    items: Mapped[list["ExpenseItem"]] = relationship(back_populates="claim", cascade="all, delete-orphan",
                                                      order_by="ExpenseItem.id", lazy="selectin")
    employee = relationship("Employee")


class ExpenseItem(CreatedMixin, Base):
    __tablename__ = "expense_items"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="amount_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("expense_claims.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id", ondelete="RESTRICT"))
    occurred_on: Mapped[date] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))
    receipt_file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    claim: Mapped[ExpenseClaim] = relationship(back_populates="items")
    category = relationship("ExpenseCategory", lazy="selectin")


class MeetingRoom(TimestampMixin, Base):
    __tablename__ = "meeting_rooms"
    __table_args__ = (CheckConstraint("capacity > 0", name="capacity_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    location: Mapped[str | None] = mapped_column(String(128))
    capacity: Mapped[int] = mapped_column(Integer, default=6)
    equipment: Mapped[str | None] = mapped_column(String(255))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    open_from: Mapped[str] = mapped_column(String(5), default="08:00")
    open_to: Mapped[str] = mapped_column(String(5), default="21:00")
    status: Mapped[str] = mapped_column(String(16), default="active")


class MeetingBooking(TimestampMixin, Base):
    """Overlap protection is enforced by the API (inside BEGIN IMMEDIATE) and again by the
    `trg_meeting_no_overlap_*` triggers created in the migration."""
    __tablename__ = "meeting_bookings"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','cancelled','withdrawn')", name="status"),
        CheckConstraint("end_at > start_at", name="time_order"),
        Index("ix_meeting_bookings_room_time", "room_id", "start_at", "end_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("meeting_rooms.id", ondelete="RESTRICT"))
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    subject: Mapped[str] = mapped_column(String(128))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    attendee_ids: Mapped[list | None] = mapped_column(JSONText)
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="approved")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    room = relationship("MeetingRoom")


class AnnouncementCategory(CreatedMixin, Base):
    __tablename__ = "announcement_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)


class Announcement(TimestampMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','withdrawn')", name="status"),
        CheckConstraint("scope_type IN ('all','departments')", name="scope_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("announcement_categories.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    scope_type: Mapped[str] = mapped_column(String(16), default="all")
    scope_department_ids: Mapped[list | None] = mapped_column(JSONText)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    category = relationship("AnnouncementCategory")


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime)


class DocCategory(CreatedMixin, Base):
    __tablename__ = "doc_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("doc_categories.id", ondelete="SET NULL"))


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("visibility IN ('public','department','private')", name="visibility"),
        CheckConstraint("status IN ('active','deleted')", name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("doc_categories.id", ondelete="SET NULL"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    keywords: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    category = relationship("DocCategory")


class DocumentVersion(CreatedMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    file = relationship("StoredFile", lazy="selectin")


class DocumentLog(CreatedMixin, Base):
    __tablename__ = "document_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSONText)


# Database-level guard against double booking (also created by the initial migration).
MEETING_OVERLAP_TRIGGERS = [
    """
CREATE TRIGGER IF NOT EXISTS trg_meeting_no_overlap_insert BEFORE INSERT ON meeting_bookings
WHEN NEW.status IN ('pending','approved')
BEGIN
  SELECT RAISE(ABORT, 'meeting booking overlap')
  WHERE EXISTS (SELECT 1 FROM meeting_bookings b WHERE b.room_id = NEW.room_id
                AND b.status IN ('pending','approved') AND b.start_at < NEW.end_at AND b.end_at > NEW.start_at);
END
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_meeting_no_overlap_update BEFORE UPDATE OF status, start_at, end_at, room_id
ON meeting_bookings
WHEN NEW.status IN ('pending','approved')
BEGIN
  SELECT RAISE(ABORT, 'meeting booking overlap')
  WHERE EXISTS (SELECT 1 FROM meeting_bookings b WHERE b.id <> NEW.id AND b.room_id = NEW.room_id
                AND b.status IN ('pending','approved') AND b.start_at < NEW.end_at AND b.end_at > NEW.start_at);
END
""",
]
