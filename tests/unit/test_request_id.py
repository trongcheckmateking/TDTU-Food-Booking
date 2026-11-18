"""Unit test X-Request-ID dùng chung của Auth (common/request_id.py, common/app.py, common/http.py)."""
import logging
import os
import re

os.environ.setdefault("TDTU_ENV_FILE", os.path.join(os.path.dirname(__file__), "no-such.env"))

import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from common import http, request_id  # noqa: E402

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_accept_keeps_valid_and_generates_otherwise():
    assert request_id.accept("demo-rid-0001") == "demo-rid-0001"
    assert request_id.accept("A.b_c-1234") == "A.b_c-1234"
    for bad in (None, "", "ngan", "co dau cach!!", "x" * 129, "rid/khong-hop-le"):
        assert HEX32.match(request_id.accept(bad)), bad


def test_bind_current_unbind_and_log_filter():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    request_id.RequestIdFilter().filter(rec)
    assert rec.request_id == "-"                                  # ngoài request (luồng nền)
    token = request_id.bind("demo-rid-0001")
    try:
        assert request_id.current() == "demo-rid-0001"
        request_id.RequestIdFilter().filter(rec)
        assert rec.request_id == "demo-rid-0001"
    finally:
        request_id.unbind(token)
    assert request_id.current() is None


def test_http_call_forwards_current_rid(monkeypatch):
    seen = {}

    def fake_request(method, url, headers=None, **kw):
        seen.update(headers)
        r = requests.Response()
        r.status_code, r._content = 200, b"{}"
        return r
    monkeypatch.setattr(requests, "request", fake_request)
    token = request_id.bind("demo-rid-0001")
    try:
        http.call("GET", "http://x/api", "X")
    finally:
        request_id.unbind(token)
    assert seen["X-Request-ID"] == "demo-rid-0001"
    seen.clear()
    http.call("GET", "http://x/api", "X")                         # không có request đang xử lý: không gửi header
    assert "X-Request-ID" not in seen


def test_auth_app_echoes_rid_on_every_response(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "j" * 40)
    monkeypatch.setenv("INTERNAL_KEY", "k" * 30)
    from services.auth.app import app
    c = TestClient(app)
    assert c.get("/khong-co", headers={"X-Request-ID": "demo-rid-0001"}).headers["X-Request-ID"] == "demo-rid-0001"
    r = c.get("/api/users/me")                                    # response lỗi 401 cũng có rid
    assert r.status_code == 401 and HEX32.match(r.headers["X-Request-ID"])
    pre = c.options("/api/users/me", headers={"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "GET",
                                              "Access-Control-Request-Headers": "x-request-id"})
    assert HEX32.match(pre.headers["X-Request-ID"])               # preflight CORS cũng có
    cors = c.get("/", headers={"Origin": "http://127.0.0.1:8000"})
    assert "x-request-id" in cors.headers.get("access-control-expose-headers", "").lower()
