from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..core import timeutil

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class JSONText(TypeDecorator):
    """JSON stored as TEXT (portable, readable in SQLite)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


def _now() -> datetime:
    return timeutil.now()


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class TimestampMixin(CreatedMixin):
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)
