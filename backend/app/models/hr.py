"""HRM tables: attendance, recruitment, onboarding, regularization, transfer, performance, payroll."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedMixin, JSONText, TimestampMixin
from .oa import DOC_STATUSES


class AttendanceRule(TimestampMixin, Base):
    __tablename__ = "attendance_rules"
    __table_args__ = (
        CheckConstraint("late_grace_minutes >= 0 AND early_grace_minutes >= 0", name="grace"),
        CheckConstraint("window_before_minutes BETWEEN 0 AND 720 AND window_after_minutes BETWEEN 0 AND 720",
                        name="window"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    work_start: Mapped[str] = mapped_column(String(5))  # HH:MM
    work_end: Mapped[str] = mapped_column(String(5))
    break_start: Mapped[str | None] = mapped_column(String(5))
    break_end: Mapped[str | None] = mapped_column(String(5))
    cross_day: Mapped[bool] = mapped_column(Boolean, default=False)
    late_grace_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_grace_minutes: Mapped[int] = mapped_column(Integer, default=0)
    window_before_minutes: Mapped[int] = mapped_column(Integer, default=240)
    window_after_minutes: Mapped[int] = mapped_column(Integer, default=360)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class AttendancePunch(CreatedMixin, Base):
    __tablename__ = "attendance_punches"
    __table_args__ = (
        UniqueConstraint("employee_id", "punched_at"),
        Index("ix_attendance_punches_employee_work_date", "employee_id", "work_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    punched_at: Mapped[datetime] = mapped_column(DateTime)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(16), default="web")  # web/simulated/correction
    ref_id: Mapped[int | None] = mapped_column(Integer)


class AttendanceRecord(TimestampMixin, Base):
    """Derived daily result; always recomputable from punches, leaves, travel and calendar."""
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("employee_id", "work_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    expected_start: Mapped[datetime | None] = mapped_column(DateTime)
    expected_end: Mapped[datetime | None] = mapped_column(DateTime)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_minutes: Mapped[int] = mapped_column(Integer, default=0)
    leave_hours: Mapped[int] = mapped_column(Integer, default=0)
    is_travel: Mapped[bool] = mapped_column(Boolean, default=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)


class AttendanceCorrection(TimestampMixin, Base):
    __tablename__ = "attendance_corrections"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("kind IN ('in','out')", name="kind"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(4))
    corrected_time: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class OvertimeRequest(TimestampMixin, Base):
    __tablename__ = "overtime_requests"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("compensation IN ('leave','pay')", name="compensation"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    hours: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    compensation: Mapped[str] = mapped_column(String(8), default="leave")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class JobRequisition(TimestampMixin, Base):
    __tablename__ = "job_requisitions"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="status"),
        CheckConstraint("headcount > 0 AND hired_count >= 0", name="counts"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    hired_count: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Candidate(TimestampMixin, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint("status IN ('new','interviewing','offer_pending','offered','onboarding','hired','rejected')",
                        name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    requisition_id: Mapped[int | None] = mapped_column(ForeignKey("job_requisitions.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(64))
    gender: Mapped[str | None] = mapped_column(String(8))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str | None] = mapped_column(String(32))
    resume_file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")


class Interview(TimestampMixin, Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint("result IN ('pending','pass','fail')", name="result"),
        CheckConstraint("score IS NULL OR (score BETWEEN 0 AND 100)", name="score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    score: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(8), default="pending")


class Offer(TimestampMixin, Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("salary_cents > 0", name="salary_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    salary_cents: Mapped[int] = mapped_column(Integer)
    hire_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class OnboardingRequest(TimestampMixin, Base):
    __tablename__ = "onboarding_requests"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("probation_months BETWEEN 0 AND 6", name="probation"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(64))
    gender: Mapped[str | None] = mapped_column(String(8))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    hire_date: Mapped[date] = mapped_column(Date)
    probation_months: Mapped[int] = mapped_column(Integer, default=3)
    create_account: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str | None] = mapped_column(String(32))
    role_codes: Mapped[list | None] = mapped_column(JSONText)
    base_salary_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    account_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class OnboardingTask(TimestampMixin, Base):
    __tablename__ = "onboarding_tasks"
    __table_args__ = (CheckConstraint("status IN ('todo','done')", name="status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    onboarding_id: Mapped[int] = mapped_column(ForeignKey("onboarding_requests.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(128))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="todo")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)


class RegularizationRequest(TimestampMixin, Base):
    __tablename__ = "regularization_requests"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),
        CheckConstraint("manager_score IS NULL OR (manager_score BETWEEN 0 AND 100)", name="score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    planned_date: Mapped[date] = mapped_column(Date)
    self_review: Mapped[str] = mapped_column(Text)
    manager_evaluation: Mapped[str | None] = mapped_column(Text)
    manager_score: Mapped[int | None] = mapped_column(Integer)
    hr_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class TransferRequest(TimestampMixin, Base):
    __tablename__ = "transfer_requests"
    __table_args__ = (CheckConstraint(f"status IN {DOC_STATUSES}", name="status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    from_department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    to_department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    from_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    to_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    to_manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    effective_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("wf_instances.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class PerformanceCycle(TimestampMixin, Base):
    __tablename__ = "performance_cycles"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','closed')", name="status"),
        CheckConstraint("end_date >= start_date", name="date_order"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    indicators: Mapped[list["PerformanceIndicator"]] = relationship(cascade="all, delete-orphan",
                                                                    order_by="PerformanceIndicator.id",
                                                                    lazy="selectin")


class PerformanceIndicator(CreatedMixin, Base):
    __tablename__ = "performance_indicators"
    __table_args__ = (CheckConstraint("weight > 0 AND weight <= 100", name="weight"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("performance_cycles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    weight: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(255))


class PerformanceReview(TimestampMixin, Base):
    __tablename__ = "performance_reviews"
    __table_args__ = (
        UniqueConstraint("cycle_id", "employee_id"),
        CheckConstraint("status IN ('self_pending','manager_pending','confirm_pending','confirmed')", name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("performance_cycles.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    reviewer_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="self_pending")
    self_scores: Mapped[dict | None] = mapped_column(JSONText)
    self_comment: Mapped[str | None] = mapped_column(Text)
    manager_scores: Mapped[dict | None] = mapped_column(JSONText)
    manager_comment: Mapped[str | None] = mapped_column(Text)
    final_score: Mapped[float | None] = mapped_column()
    grade: Mapped[str | None] = mapped_column(String(2))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SalaryStructure(CreatedMixin, Base):
    __tablename__ = "salary_structures"
    __table_args__ = (
        UniqueConstraint("employee_id", "effective_from"),
        CheckConstraint("base_cents >= 0 AND allowance_cents >= 0", name="non_negative"),
        CheckConstraint("social_rate_bp BETWEEN 0 AND 5000", name="social_rate"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    base_cents: Mapped[int] = mapped_column(Integer)
    allowance_cents: Mapped[int] = mapped_column(Integer, default=0)
    social_rate_bp: Mapped[int] = mapped_column(Integer, default=1050)  # 10.50%
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (CheckConstraint("status IN ('draft','calculated','confirmed')", name="status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    calc_version: Mapped[int] = mapped_column(Integer, default=0)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PayrollAdjustment(CreatedMixin, Base):
    __tablename__ = "payroll_adjustments"
    __table_args__ = (
        CheckConstraint("kind IN ('bonus','deduction')", name="kind"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Payslip(CreatedMixin, Base):
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("run_id", "employee_id", "calc_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    calc_version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    base_cents: Mapped[int] = mapped_column(Integer)
    allowance_cents: Mapped[int] = mapped_column(Integer)
    bonus_cents: Mapped[int] = mapped_column(Integer)
    deduction_cents: Mapped[int] = mapped_column(Integer)
    absence_deduction_cents: Mapped[int] = mapped_column(Integer)
    unpaid_leave_deduction_cents: Mapped[int] = mapped_column(Integer)
    gross_cents: Mapped[int] = mapped_column(Integer)
    social_insurance_cents: Mapped[int] = mapped_column(Integer)
    tax_cents: Mapped[int] = mapped_column(Integer)
    net_cents: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSONText)
