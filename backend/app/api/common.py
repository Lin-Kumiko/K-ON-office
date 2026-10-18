"""Shared API schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core import timeutil

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Msg(BaseModel):
    ok: bool = True
    message: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


ERRORS = {
    400: {"model": ErrorResponse, "description": "请求错误"},
    401: {"model": ErrorResponse, "description": "未认证"},
    403: {"model": ErrorResponse, "description": "无权限"},
    404: {"model": ErrorResponse, "description": "资源不存在"},
    409: {"model": ErrorResponse, "description": "状态冲突 / 重复 / 并发冲突"},
    422: {"model": ErrorResponse, "description": "参数校验失败"},
}


class CommentIn(BaseModel):
    comment: str | None = Field(None, max_length=1000)


class LocalDateTime(BaseModel):
    """Mixin validator: aware datetimes are converted to company-local naive."""

    @field_validator("*", mode="after")
    @classmethod
    def _localize(cls, v):
        if isinstance(v, datetime):
            return timeutil.to_local(v)
        return v


def clean_text(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


Str32 = Field(min_length=1, max_length=32)
DateField = date
