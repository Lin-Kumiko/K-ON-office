"""Generic workflow engine tables (business-agnostic)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedMixin, JSONText, TimestampMixin


class WfDefinition(TimestampMixin, Base):
    __tablename__ = "wf_definitions"
    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    business_type: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_definition_versions.id", use_alter=True, name="fk_wf_definitions_current_version",
                   ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WfDefinitionVersion(CreatedMixin, Base):
    __tablename__ = "wf_definition_versions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version"),
        CheckConstraint("status IN ('draft','published','archived')", name="status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("wf_definitions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict] = mapped_column(JSONText)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(255))


class WfInstance(Base):
    __tablename__ = "wf_instances"
    __table_args__ = (
        CheckConstraint("status IN ('running','approved','rejected','withdrawn','cancelled')", name="status"),
        # A business document can have at most one running instance at any time.
        Index("uq_wf_instances_running_business", "business_type", "business_id", unique=True,
              sqlite_where=text("status = 'running'")),
        Index("ix_wf_instances_initiator", "initiator_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("wf_definitions.id", ondelete="RESTRICT"))
    version_id: Mapped[int] = mapped_column(ForeignKey("wf_definition_versions.id", ondelete="RESTRICT"))
    business_type: Mapped[str] = mapped_column(String(32))
    business_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    initiator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    subject_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="running")
    variables: Mapped[dict] = mapped_column(JSONText, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    version_row: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    version = relationship("WfDefinitionVersion")
    definition = relationship("WfDefinition")
    __mapper_args__ = {"version_id_col": version_row}


class WfTask(CreatedMixin, Base):
    __tablename__ = "wf_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','transferred','cancelled')", name="status"),
        Index("ix_wf_tasks_assignee_status", "assignee_id", "status"),
        Index("ix_wf_tasks_instance_node", "instance_id", "node_id"),
        # one pending task per assignee per node activation
        Index("uq_wf_tasks_pending_assignee", "instance_id", "node_id", "assignee_id", unique=True,
              sqlite_where=text("status = 'pending'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("wf_instances.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(64))
    node_name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(8), default="or")  # or / and
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    comment: Mapped[str | None] = mapped_column(Text)
    form_data: Mapped[dict | None] = mapped_column(JSONText)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime)
    transferred_from_task_id: Mapped[int | None] = mapped_column(ForeignKey("wf_tasks.id", ondelete="SET NULL"))

    instance = relationship("WfInstance")


class WfJoinArrival(CreatedMixin, Base):
    __tablename__ = "wf_join_arrivals"
    __table_args__ = (UniqueConstraint("instance_id", "join_node_id", "edge_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("wf_instances.id", ondelete="CASCADE"))
    join_node_id: Mapped[str] = mapped_column(String(64))
    edge_id: Mapped[str] = mapped_column(String(64))


class WfNodeActivation(CreatedMixin, Base):
    """Each node may be activated once per instance (graphs are DAGs)."""
    __tablename__ = "wf_node_activations"
    __table_args__ = (UniqueConstraint("instance_id", "node_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("wf_instances.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/completed/rejected/cancelled
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class WfHistory(CreatedMixin, Base):
    __tablename__ = "wf_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("wf_instances.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("wf_tasks.id", ondelete="SET NULL"))
    node_id: Mapped[str | None] = mapped_column(String(64))
    node_name: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONText)


class WfCc(CreatedMixin, Base):
    __tablename__ = "wf_cc"
    __table_args__ = (UniqueConstraint("instance_id", "node_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("wf_instances.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
