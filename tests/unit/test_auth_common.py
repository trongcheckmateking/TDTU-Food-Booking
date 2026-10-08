"""Unit test phần Python (Auth Service + thư viện common): ánh xạ lỗi REST, dừng khi thiếu secret, OpenAPI của Auth.

Các service ngôn ngữ khác có test riêng (node --test, go test, php tests/run.php, JUnit) và được kiểm tra
hộp đen trong tests/integration.
"""
import os

import pytest
import requests

os.environ.setdefault("TDTU_ENV_FILE", os.path.join(os.path.dirname(__file__), "no-such.env"))
os.environ.setdefault("JWT_SECRET", "unit-jwt-secret-" + "x" * 32)
os.environ.setdefault("INTERNAL_KEY", "unit-internal-key-" + "y" * 16)

import common.http as http  # noqa: E402
from common.errors import ApiError  # noqa: E402


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.mark.parametrize("behaviour,status,code", [
    (requests.Timeout(), 503, "UPSTREAM_UNAVAILABLE"),
    (requests.ConnectionError(), 503, "UPSTREAM_UNAVAILABLE"),
    (FakeResp(500, {"detail": "x"}), 502, "UPSTREAM_ERROR"),
    (FakeResp(404, {"detail": "x"}), 502, "UPSTREAM_REJECTED"),
    (FakeResp(200, ValueError("bad json")), 502, "UPSTREAM_BAD_RESPONSE"),
    (FakeResp(200, "chuỗi"), 502, "UPSTREAM_BAD_RESPONSE"),
])
def test_http_call_error_mapping(monkeypatch, behaviour, status, code):
    def fake(*a, **kw):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour
    monkeypatch.setattr(http.requests, "request", fake)
    with pytest.raises(ApiError) as e:
        http.call("GET", "http://127.0.0.1:8002/x", "Restaurant Service")
    assert (e.value.status, e.value.code) == (status, code)


def test_http_call_allow_and_success(monkeypatch):
    monkeypatch.setattr(http.requests, "request", lambda *a, **kw: FakeResp(404, {"code": "X"}))
    assert http.call("GET", "http://127.0.0.1:8002/x", "R", allow=(404,)) == (404, {"code": "X"})
    monkeypatch.setattr(http.requests, "request", lambda *a, **kw: FakeResp(200, {"ok": 1}))
    assert http.call("GET", "http://127.0.0.1:8002/x", "R") == (200, {"ok": 1})


def test_auth_missing_or_short_jwt_secret_stops_startup(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from services.auth.app import app
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(app):
            pass
    monkeypatch.setenv("JWT_SECRET", "ngan")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(app):
            pass


def test_auth_openapi_has_bearer():
    from services.auth.app import app
    spec = app.openapi()
    assert spec["info"]["title"] == "Auth Service"
    assert any(v.get("scheme") == "bearer" for v in spec["components"]["securitySchemes"].values())
