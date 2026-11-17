"""Tạo ứng dụng FastAPI dùng chung: CORS, xử lý lỗi, health/readiness, log."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, request_id
from .db import Database
from .errors import install_error_handlers

access_log = logging.getLogger("tdtu.access")


def setup_logging() -> None:
    logging.basicConfig(level=config.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s [%(name)s] %(message)s rid=%(request_id)s")
    for h in logging.getLogger().handlers:                # mọi dòng log có rid (luồng nền: rid=-)
        if not any(isinstance(f, request_id.RequestIdFilter) for f in h.filters):
            h.addFilter(request_id.RequestIdFilter())


def create_app(service: str, title: str, description: str, db: Database,
               on_startup: Callable[[], None] | None = None,
               on_shutdown: Callable[[], None] | None = None, tags: list[dict] | None = None) -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        config.require("INTERNAL_KEY", 24)   # dừng sớm nếu thiếu cấu hình bí mật
        db.init()
        if on_startup:
            on_startup()
        yield
        if on_shutdown:
            on_shutdown()

    app = FastAPI(title=title, description=description, version="1.0.0", lifespan=lifespan,
                  openapi_tags=tags, swagger_ui_parameters={"persistAuthorization": True})
    @app.middleware("http")
    async def catch_unexpected(request: Request, call_next):
        # Nằm BÊN TRONG CORS: lỗi 500 vẫn có header CORS để trình duyệt hiện đúng thông báo lỗi
        try:
            return await call_next(request)
        except Exception:
            logging.getLogger("tdtu").exception("Lỗi không mong đợi tại %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Có lỗi nội bộ, vui lòng thử lại sau", "code": "INTERNAL_ERROR"},
                                status_code=500)

    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
                       expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_id_and_access_log(request: Request, call_next):
        # Thêm SAU catch_unexpected và CORS nên bọc ngoài cùng: mọi response (lỗi, preflight CORS) đều có X-Request-ID
        rid = request_id.accept(request.headers.get(request_id.HEADER))
        token = request_id.bind(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[request_id.HEADER] = rid
            if request.url.path != "/health":
                access_log.info("%s %s %s %dms", request.method, request.url.path, response.status_code,
                                (time.perf_counter() - t0) * 1000)
            return response
        finally:
            request_id.unbind(token)

    install_error_handlers(app)

    @app.get("/", tags=["health"], summary="Thông tin service")
    def root():
        return {"service": service, "status": "ok", "docs": "/docs"}

    @app.get("/health", tags=["health"], summary="Readiness: service và DB sẵn sàng")
    def health():
        ok = db.check()
        return JSONResponse({"service": service, "status": "ok" if ok else "degraded",
                             "db": "ok" if ok else "error"}, status_code=200 if ok else 503)

    return app
