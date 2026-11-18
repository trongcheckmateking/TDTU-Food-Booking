"""X-Request-ID: mã truy vết một yêu cầu xuyên các service (logging / tracing).

- accept(raw): giữ header nếu hợp lệ (^[A-Za-z0-9._-]{8,128}$), không thì sinh UUID bỏ dấu gạch (32 ký tự hex).
- bind / unbind / current: lưu rid của yêu cầu đang xử lý trong contextvar (đi theo cả hàm `def` chạy trong threadpool).
- RequestIdFilter: gắn record.request_id cho mọi dòng log ("-" với luồng chạy nền / ngoài yêu cầu).
common/http.py chuyển tiếp rid hiện tại khi gọi service khác.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid

HEADER = "X-Request-ID"
_RID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def accept(raw: str | None) -> str:
    return raw if raw and _RID_RE.match(raw) else uuid.uuid4().hex


def current() -> str | None:
    return _current.get()


def bind(rid: str) -> contextvars.Token:
    return _current.set(rid)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _current.get() or "-"
        return True
