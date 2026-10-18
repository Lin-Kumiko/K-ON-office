"""FastAPI application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .core import timeutil
from .core.config import Settings, load_settings
from .core.db import Database
from .core.errors import install_error_handlers

API_VERSION = "1.0.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    timeutil.configure(settings.timezone)
    if settings.env == "test" and settings.fixed_now:
        from datetime import datetime
        timeutil.set_fixed_now(datetime.fromisoformat(settings.fixed_now))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="DragonOffice Enterprise API",
        version=API_VERSION,
        description="放课后茶会株式会社 · OA / HRM / 工作流一体化平台（全部数据为合成数据）",
    )
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    install_error_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    # business handlers register themselves with the workflow engine on import
    from .services import handlers as _handlers  # noqa: F401
    from .services import leave as _leave  # noqa: F401
    from .api import ROUTERS
    for r in ROUTERS:
        app.include_router(r)

    @app.get("/api/health", tags=["系统与权限"], summary="健康检查")
    def health():
        with app.state.db.engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok", "version": API_VERSION}

    dist: Path = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                from .core.errors import NotFound
                raise NotFound("接口不存在")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    @app.on_event("shutdown")
    def _shutdown():
        app.state.db.dispose()

    return app
