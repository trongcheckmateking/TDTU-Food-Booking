"""Hợp đồng chung của 5 service (5 ngôn ngữ) kiểm tra hộp đen trên tiến trình thật:
Swagger/ReDoc/OpenAPI (Bearer), /health, CORS chỉ cho origin cấu hình, lỗi JSON thống nhất, 404/422,
ánh xạ lỗi khi gọi service khác (Auth sập/chậm/500/JSON hỏng) giống nhau ở mọi ngôn ngữ, dừng khi thiếu khóa.
"""
import os
import subprocess

import pytest

import manage
from tests.conftest import INTERNAL, SERVICES

LANG = {"auth": "Python", "restaurant": "Node.js", "order": "Java", "notification": "Go", "review": "PHP"}


@pytest.mark.parametrize("name", SERVICES)
def test_docs_openapi_health_cors_404(system, name):
    c = system.clients[name]
    docs = c.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert c.get("/redoc").status_code == 200
    spec = c.get("/openapi.json").json()
    assert spec["info"]["title"].endswith("Service")
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert any(v.get("scheme") == "bearer" for v in schemes.values()), schemes
    h = c.get("/health")
    assert h.status_code == 200 and h.json() == {"service": name, "status": "ok", "db": "ok"}
    pre = c.options("/health", headers={"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "GET",
                                        "Access-Control-Request-Headers": "authorization"})
    assert pre.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"
    bad = c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    nf = c.get("/khong-ton-tai")
    assert nf.status_code == 404 and nf.json()["code"] == "NOT_FOUND" and isinstance(nf.json()["detail"], str)


# mỗi service: 1 API cần đăng nhập để kiểm tra ánh xạ lỗi khi gọi Auth
PROTECTED = {"restaurant": "/api/restaurants/mine", "order": "/api/orders/me",
             "notification": "/api/notifications/me", "review": "/api/reviews/me"}


@pytest.mark.parametrize("name", list(PROTECTED))
def test_auth_errors_and_upstream_mapping_same_in_every_language(world, name):
    s = world.s
    c, path = s.clients[name], PROTECTED[name]
    who = world.owner if name == "restaurant" else world.sv
    assert c.get(path, headers=who).status_code == 200
    r = c.get(path)
    assert (r.status_code, r.json()["code"]) == (401, "UNAUTHORIZED"), LANG[name]
    r = c.get(path, headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_INVALID", (LANG[name], r.text)
    for kind, status, code in (("down", 503, "UPSTREAM_UNAVAILABLE"), ("timeout", 503, "UPSTREAM_UNAVAILABLE"),
                               ("500", 502, "UPSTREAM_ERROR"), ("badjson", 502, "UPSTREAM_BAD_RESPONSE")):
        s.fault("auth", kind)
        r = c.get(path, headers=who)
        assert (r.status_code, r.json()["code"]) == (status, code), (LANG[name], kind, r.text)
    s.fault("auth", None)
    assert c.get(path, headers=who).status_code == 200


@pytest.mark.parametrize("name", ["restaurant", "order", "notification", "review"])
def test_validation_error_format(world, name):
    s = world.s
    calls = {
        "restaurant": ("POST", "/api/restaurants", world.owner, {"name": "   ", "address": "Q7 abc", "owner_id": "x"}),
        "order": ("POST", "/api/cart/items", world.sv, {"restaurant_id": "x", "item_id": world.item1, "quantity": 1.5}),
        "notification": ("POST", "/internal/notifications/events", INTERNAL, {"event": "order_shipped"}),
        "review": ("POST", "/api/reviews", world.sv, {"order_id": "x", "rating": "5"}),
    }
    method, path, headers, body = calls[name]
    r = s.clients[name].request(method, path, headers=headers, json=body)
    assert r.status_code == 422, (name, r.text)
    j = r.json()
    assert j["code"] == "VALIDATION_ERROR" and isinstance(j["detail"], str)
    assert j["errors"] and all(set(e) == {"field", "message"} for e in j["errors"]), j
    broken = s.clients[name].request(method, path, headers={**headers, "Content-Type": "application/json"},
                                     content=b'{"x":')
    assert broken.status_code == 422 and broken.json()["detail"] == "JSON gửi lên không hợp lệ", (name, broken.text)


@pytest.mark.parametrize("name", ["restaurant", "order", "notification"])
def test_missing_internal_key_stops_startup(cluster, name, tmp_path):
    cmd, cwd, extra = manage.service_command(name, "127.0.0.1", 1)
    env = {k: v for k, v in cluster.env_for(name).items() if k != "INTERNAL_KEY"}
    env["TDTU_ENV_FILE"] = str(tmp_path / "none.env")
    r = subprocess.run(cmd, cwd=cwd, env={**env, **extra}, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "INTERNAL_KEY" in (r.stdout + r.stderr), (name, r.stdout[-500:], r.stderr[-500:])


def test_review_refuses_requests_without_internal_key(cluster, tmp_path):
    """php -S không có bước khởi động riêng: thiếu khóa thì mọi request trả 500 CONFIG_ERROR (không chạy nghiệp vụ)."""
    import socket
    import time

    import requests
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    cmd, cwd, extra = manage.service_command("review", "127.0.0.1", port)
    env = {k: v for k, v in cluster.env_for("review").items() if k != "INTERNAL_KEY"}
    env["TDTU_ENV_FILE"] = str(tmp_path / "none.env")
    p = subprocess.Popen(cmd, cwd=cwd, env={**env, **extra}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if manage.tcp_open("127.0.0.1", port, 0.2):
                break
            time.sleep(0.1)
        s = requests.Session()
        s.trust_env = False
        r = s.get(f"http://127.0.0.1:{port}/api/reviews/me", timeout=10)
        assert r.status_code == 500 and r.json()["code"] == "CONFIG_ERROR" and "INTERNAL_KEY" in r.json()["detail"]
    finally:
        p.terminate()
        p.wait(10)


def test_internal_apis_require_key_in_every_language(world):
    s = world.s
    o = s.place_order(world.sv, world.rid, [(world.item1, 1)])
    checks = [
        (s.restaurant, "POST", "/internal/quote", {"restaurant_id": world.rid, "items": [{"item_id": world.item1, "quantity": 1}]}),
        (s.restaurant, "GET", f"/internal/owners/{s.me(world.owner)}/restaurant-count", None),
        (s.order, "GET", f"/internal/orders/{o['id']}", None),
        (s.notification, "POST", "/internal/notifications/events", {}),
    ]
    for client, method, path, body in checks:
        for headers in ({}, {"X-Internal-Key": "sai-khoa-" + "z" * 20}, world.admin):
            r = client.request(method, path, headers=headers, json=body)
            assert r.status_code == 403 and r.json()["code"] == "INTERNAL_ONLY", (path, headers.keys(), r.text)
        assert client.request(method, path, headers=INTERNAL, json=body).status_code in (200, 201, 422), path
