"""Hạ tầng test liên service: chạy 5 service THẬT (Python, Node.js, Java, Go, PHP) thành tiến trình riêng.

- Mỗi lần chạy pytest dùng thư mục dữ liệu tạm, cổng trống và một schema PostgreSQL riêng (xóa khi xong),
  nên không đụng dữ liệu demo/dev.
- Lời gọi giữa các service đi qua "fault proxy" (HTTP proxy nhỏ trong tiến trình test): bình thường chuyển tiếp
  nguyên vẹn; `system.fault(service, kind)` giả lập service sập / chậm quá timeout / trả 500 / trả JSON hỏng
  để kiểm tra ánh xạ lỗi của từng ngôn ngữ. Client trong test gọi thẳng cổng thật của service.
- Mỗi test tự tạo người dùng/quán với hậu tố ngẫu nhiên nên các test không phụ thuộc nhau.
Cần: Node.js 22+, Java 17+ (đã có services/order/target/order-service.jar), Go binary đã build, PHP 8.1+,
PostgreSQL (NOTIFICATION_TEST_DB_URL hoặc NOTIFICATION_DB_URL trong .env). Chạy `python manage.py build` trước.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import manage  # noqa: E402

SERVICES = ["auth", "restaurant", "order", "notification", "review"]
JWT_SECRET = "test-jwt-secret-" + "x" * 32
INTERNAL_KEY = "test-internal-key-" + "y" * 16
INTERNAL = {"X-Internal-Key": INTERNAL_KEY}
HTTP_TIMEOUT = 2


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_env_file(path: Path) -> dict:
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def _pg_url() -> str | None:
    return os.environ.get("NOTIFICATION_TEST_DB_URL") or read_env_file(ROOT / ".env").get("NOTIFICATION_DB_URL")


# ---------------------------------------------------------------------------- fault proxy
class FaultProxy:
    """Proxy HTTP giữa các service; mode None = chuyển tiếp, hoặc down / timeout / 500 / badjson."""

    def __init__(self, target_port: int):
        self.target_port = target_port
        self.mode: str | None = None
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else None
                mode = proxy.mode
                if mode == "down":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if mode == "timeout":
                    time.sleep(HTTP_TIMEOUT + 1.5)
                    self.close_connection = True
                    return
                if mode in ("500", "badjson"):
                    data = b'{"detail":"boom"}' if mode == "500" else b"<html>not json</html>"
                    self.send_response(500 if mode == "500" else 200)
                    self.send_header("Content-Type", "application/json" if mode == "500" else "text/html")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                conn = http.client.HTTPConnection("127.0.0.1", proxy.target_port, timeout=30)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
                conn.request(self.command, self.path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                conn.close()

            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


# ---------------------------------------------------------------------------- client
class Client:
    """Gọi thẳng 1 service; trả requests.Response (status_code, json(), headers, text)."""

    def __init__(self, base: str):
        self.base = base
        self.s = requests.Session()
        self.s.trust_env = False

    def request(self, method, path, headers=None, json=None, params=None, content=None):
        return self.s.request(method, self.base + path, headers=headers, json=json, params=params, data=content,
                              timeout=60)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def options(self, path, **kw):
        return self.request("OPTIONS", path, **kw)


class Cluster:
    def __init__(self, tmp: Path):
        pg = _pg_url()
        if not pg:
            pytest.exit("Cần PostgreSQL cho Notification: đặt NOTIFICATION_TEST_DB_URL hoặc chạy `python manage.py init-env` "
                        "+ `pg-setup`.", returncode=2)
        self.tmp = tmp
        self.schema = "pytest_" + uuid.uuid4().hex[:10]
        self.ports = {s: free_port() for s in SERVICES}
        self.proxies = {s: FaultProxy(self.ports[s]) for s in SERVICES}
        self.data = tmp / "data"
        self.data.mkdir()
        self.env_file = tmp / "test.env"
        self.env_file.write_text("", encoding="utf-8")
        self.base_env = {k: v for k, v in os.environ.items() if not k.endswith("_URL") and k not in (
            "JWT_SECRET", "INTERNAL_KEY", "DATA_DIR", "OUTBOX_INTERVAL", "CORS_ORIGINS", "HTTP_TIMEOUT")}
        self.base_env.update({
            "TDTU_ENV_FILE": str(self.env_file), "TDTU_ROOT": str(ROOT), "JWT_SECRET": JWT_SECRET,
            "INTERNAL_KEY": INTERNAL_KEY, "DATA_DIR": str(self.data), "OUTBOX_INTERVAL": "0",
            "HTTP_TIMEOUT": str(HTTP_TIMEOUT), "CORS_ORIGINS": "http://127.0.0.1:8000", "LOG_LEVEL": "INFO",
            "NOTIFICATION_DB_URL": pg, "NOTIFICATION_DB_SCHEMA": self.schema, "PYTHONUTF8": "1",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        self.procs: dict[str, subprocess.Popen] = {}
        self.url = {s: f"http://127.0.0.1:{p}" for s, p in self.ports.items()}

    def env_for(self, name: str) -> dict:
        """Service tự lắng nghe ở cổng thật của nó; gọi service khác qua fault proxy."""
        env = dict(self.base_env)
        for s in SERVICES:
            port = self.ports[s] if s == name else self.proxies[s].port
            env[f"{s.upper()}_URL"] = f"http://127.0.0.1:{port}"
        return env

    def start(self, name: str):
        cmd, cwd, extra = manage.service_command(name, "127.0.0.1", self.ports[name])
        log = open(self.tmp / f"{name}.log", "a", encoding="utf-8")
        kw = {"cwd": cwd, "stdout": log, "stderr": subprocess.STDOUT, "env": {**self.env_for(name), **extra}}
        if os.name != "nt":
            kw["start_new_session"] = True
        self.procs[name] = subprocess.Popen(cmd, **kw)

    def wait_ready(self, names, timeout=180):
        deadline = time.time() + timeout
        pending = set(names)
        while pending and time.time() < deadline:
            for n in list(pending):
                if manage.http_ok(self.url[n] + "/health"):
                    pending.discard(n)
                elif self.procs[n].poll() is not None:
                    raise RuntimeError(f"{n} dừng khi khởi động:\n" + (self.tmp / f"{n}.log").read_text()[-3000:])
            time.sleep(0.3)
        if pending:
            raise RuntimeError(f"Không khởi động được: {pending}")

    def stop_all(self):
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        for p in self.procs.values():
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        for px in self.proxies.values():
            px.close()
        # xóa schema PostgreSQL dùng cho lần test này
        subprocess.run([str(manage.NOTI_BIN)], cwd=manage.SVC / "notification",
                       env={**self.env_for("notification"), "NOTIFICATION_DROP_SCHEMA": "1"}, capture_output=True)

    def auth_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.data / "auth.db", timeout=10, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn


@pytest.fixture(scope="session")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("cluster"))
    try:
        for s in SERVICES:
            c.start(s)
        c.wait_ready(SERVICES)
        yield c
    finally:
        c.stop_all()


# ---------------------------------------------------------------------------- tiện ích cho test
class System:
    def __init__(self, cluster: Cluster):
        self.c = cluster
        self.tag = uuid.uuid4().hex[:8]
        self.clients = {s: Client(cluster.url[s]) for s in SERVICES}

    def __getattr__(self, name):
        if name in SERVICES:
            return self.clients[name]
        raise AttributeError(name)

    def fault(self, service: str, kind: str | None):
        self.c.proxies[service].mode = kind

    def email(self, local: str) -> str:
        """Email duy nhất cho mỗi test: an@x.vn -> an.<tag>@x.vn."""
        name, domain = local.split("@")
        return f"{name}.{self.tag}@{domain}"

    def register(self, email, role="sinh_vien", name="Người Dùng", password="matkhau123", phone=None):
        body = {"name": name, "email": email, "password": password, "role": role}
        if phone:
            body["phone"] = phone
        r = self.auth.post("/api/users/register", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def login(self, email, password="matkhau123") -> dict:
        r = self.auth.post("/api/users/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def user(self, email, role="sinh_vien", **kw) -> dict:
        self.register(email, role, **kw)
        return self.login(email)

    def admin(self, email=None) -> dict:
        """Admin chỉ tạo được bằng công cụ quản trị của Auth (ghi DB của chính Auth), giống lệnh create-admin."""
        import bcrypt
        email = email or self.email("admin@test.tdtu.vn")
        conn = self.c.auth_db()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute("INSERT INTO users (id,name,email,password_hash,role,status,token_version,created_at,updated_at) "
                     "VALUES (?,?,?,?, 'admin', 'active', 0, ?, ?)",
                     (str(uuid.uuid4()), "Admin Test", email, bcrypt.hashpw(b"matkhau123", bcrypt.gensalt(4)).decode(), ts, ts))
        conn.close()
        return self.login(email)

    def me(self, h) -> str:
        return self.auth.get("/api/users/me", headers=h).json()["id"]

    def make_restaurant(self, owner: dict, admin: dict, name="Quán Test", items=(("Cơm sườn", 35000), ("Trà đá", 3000))):
        r = self.restaurant.post("/api/restaurants", headers=owner, json={"name": name, "address": "19 Nguyễn Hữu Thọ, Q7"})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        assert self.restaurant.patch(f"/api/admin/restaurants/{rid}/status", headers=admin,
                                     json={"status": "active"}).status_code == 200
        ids = []
        for n, p in items:
            m = self.restaurant.post(f"/api/restaurants/{rid}/menu", headers=owner, json={"name": n, "price": p})
            assert m.status_code == 201, m.text
            ids.append(m.json()["id"])
        return rid, ids

    def place_order(self, student: dict, rid: str, lines: list[tuple[str, int]], key: str | None = None):
        self.order.delete("/api/cart", headers=student)
        for iid, q in lines:
            r = self.order.post("/api/cart/items", headers=student,
                                json={"restaurant_id": rid, "item_id": iid, "quantity": q})
            assert r.status_code == 200, r.text
        h = dict(student)
        if key:
            h["Idempotency-Key"] = key
        r = self.order.post("/api/orders/checkout", headers=h, json={"delivery_address": "KTX TDTU B305"})
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def system(cluster):
    s = System(cluster)
    yield s
    for svc in SERVICES:
        s.fault(svc, None)


@pytest.fixture
def world(system):
    """Bộ dữ liệu riêng cho mỗi test: admin, 2 chủ quán, 2 sinh viên, 1 quán đã duyệt với 2 món."""
    w = type("World", (), {})()
    s = w.s = system
    w.emails = {k: s.email(v) for k, v in {"owner": "owner1@test.tdtu.vn", "owner2": "owner2@test.tdtu.vn",
                                            "sv": "sv1@student.tdtu.edu.vn", "sv2": "sv2@student.tdtu.edu.vn"}.items()}
    w.admin = s.admin()
    w.owner = s.user(w.emails["owner"], "chu_quan", name="Chủ Quán Một")
    w.owner2 = s.user(w.emails["owner2"], "chu_quan", name="Chủ Quán Hai")
    w.sv = s.user(w.emails["sv"], name="Sinh Viên Một", phone="0901234567")
    w.sv2 = s.user(w.emails["sv2"], name="Sinh Viên Hai")
    w.rid, (w.item1, w.item2) = s.make_restaurant(w.owner, w.admin)
    return w
