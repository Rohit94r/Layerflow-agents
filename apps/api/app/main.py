"""FastAPI application: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.routers import articles, auth, dashboard, feed, jobs, publications, seo, settings, social

log = logging.getLogger("app.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_engine()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title="LayerFlow Agents API",
        version="1.0.0",
        docs_url="/api/v1/docs" if not s.is_production else None,
        openapi_url="/api/v1/openapi.json" if not s.is_production else None,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def _context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "same-origin")
        if not request.url.path.startswith("/site/"):
            response.headers.setdefault("x-frame-options", "DENY")
        if request.url.path.startswith("/api/") and request.url.path != "/api/v1/health":
            log.info(
                "%s %s %s", request.method, request.url.path, response.status_code,
                extra={"path": request.url.path, "status": response.status_code, "latency_ms": int((time.perf_counter() - started) * 1000)},
            )
        return response

    prefix = "/api/v1"
    for r in (auth.router, dashboard.router, feed.router, articles.router, seo.router, publications.router, social.router, settings.router, jobs.router):
        app.include_router(r, prefix=prefix)

    # Local staging site for the ten_static adapter (no SFTP host configured): /site/<tenant>/<route>/<slug>/
    site_root = Path(s.site_root)
    site_root.mkdir(parents=True, exist_ok=True)
    app.mount("/site", StaticFiles(directory=str(site_root), html=True), name="site")
    return app


app = create_app()
