"""Unified error model: every failure returns {"error": {"code", "message", "details"}}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("doe")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class InvalidState(AppError):
    status_code = 409
    code = "INVALID_STATE"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def _clean_validation(errors: list[dict]) -> list[dict]:
    out = []
    for e in errors:
        out.append({
            "loc": [str(x) for x in e.get("loc", [])],
            "msg": e.get("msg", ""),
            "type": e.get("type", ""),
        })
    return out


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError):
        return JSONResponse(error_body("VALIDATION_ERROR", "请求参数校验失败", _clean_validation(exc.errors())),
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR")
        msg = exc.detail if isinstance(exc.detail, str) else "请求失败"
        if exc.status_code == 404 and msg == "Not Found":
            msg = "资源不存在"
        return JSONResponse(error_body(code, msg), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def _integrity(_req: Request, exc: IntegrityError):
        log.warning("integrity error: %s", exc.orig)
        return JSONResponse(error_body("CONSTRAINT_VIOLATION", "数据约束冲突，操作未生效", str(exc.orig)[:200]),
                            status_code=409)

    @app.exception_handler(OperationalError)
    async def _operational(_req: Request, exc: OperationalError):
        text = str(exc.orig).lower()
        if "locked" in text or "busy" in text:
            return JSONResponse(error_body("DB_BUSY", "数据库繁忙，请稍后重试"), status_code=503)
        if "overlap" in text:
            return JSONResponse(error_body("BOOKING_CONFLICT", "会议室该时段已被占用"), status_code=409)
        log.exception("database error")
        return JSONResponse(error_body("DB_ERROR", "数据库操作失败"), status_code=500)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):  # pragma: no cover - defensive
        log.exception("unhandled error")
        return JSONResponse(error_body("INTERNAL_ERROR", "服务器内部错误"), status_code=500)
