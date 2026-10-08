"""Định dạng lỗi thống nhất cho cả 5 service.

Mọi lỗi trả JSON: {"detail": "<thông báo tiếng Việt>", "code": "<MÃ_LỖI>"}
Lỗi dữ liệu vào (422) có thêm "errors": [{"field": "...", "message": "..."}].
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("tdtu")

DEFAULT_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR", 429: "TOO_MANY_REQUESTS", 500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR", 503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


def _body(code: str, message: str, **extra) -> dict:
    return {"detail": message, "code": code, **extra}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, **exc.extra), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Yêu cầu không hợp lệ"
        if exc.status_code == 404 and message == "Not Found":
            message = "Không tìm thấy API"
        if exc.status_code == 405:
            message = "Phương thức HTTP không được hỗ trợ"
        return JSONResponse(_body(DEFAULT_CODES.get(exc.status_code, "ERROR"), message),
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path", "header")]
            errors.append({"field": ".".join(loc) or "body", "message": str(e.get("msg", ""))})
        message = "Dữ liệu không hợp lệ"
        if any(e.get("type") == "json_invalid" for e in exc.errors()):
            message = "JSON gửi lên không hợp lệ"
        return JSONResponse(_body("VALIDATION_ERROR", message, errors=errors), status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("Lỗi không mong đợi tại %s %s", request.method, request.url.path)
        return JSONResponse(_body("INTERNAL_ERROR", "Có lỗi nội bộ, vui lòng thử lại sau"), status_code=500)
