"""E2E với 5 service THẬT khởi động bằng đúng lệnh `manage.py start` mà người dùng chạy
(Python/uvicorn, Node.js, java -jar, Go binary, php -S; SQLite + H2 + PostgreSQL trên đĩa).

Dùng cổng trống, thư mục tạm và schema PostgreSQL riêng nên không đụng dữ liệu demo/dev. Kiểm tra: luồng nghiệp
vụ đầy đủ, dữ liệu còn sau restart, Notification sập không làm mất đơn và worker tự gửi lại không trùng, CORS.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cluster:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.ports = {n: free_port() for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW", "WEB")}
        env = {k: v for k, v in os.environ.items()
               if k not in ("JWT_SECRET", "INTERNAL_KEY", "DATA_DIR", "OUTBOX_INTERVAL", "CORS_ORIGINS", "HTTP_TIMEOUT")}
        from tests.conftest import _pg_url
        self.schema = "pytest_e2e_" + uuid.uuid4().hex[:8]
        env.update({"NOTIFICATION_DB_URL": _pg_url() or "", "NOTIFICATION_DB_SCHEMA": self.schema,
                    "TDTU_ENV_FILE": str(tmp / ".env"), "TDTU_RUN_DIR": str(tmp / "run"), "TDTU_LOG_DIR": str(tmp / "logs"),
                    "DATA_DIR": str(tmp / "data"), "OUTBOX_INTERVAL": "2", "WEB_PORT": str(self.ports["WEB"]),
                    "CORS_ORIGINS": f"http://127.0.0.1:{self.ports['WEB']}", "LOG_LEVEL": "WARNING"})
        for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW"):
            env[f"{n}_URL"] = f"http://127.0.0.1:{self.ports[n]}"
        self.env = env
        self.url = {n.lower(): f"http://127.0.0.1:{p}" for n, p in self.ports.items()}

    def manage(self, *args, check=True, extra_env=None):
        r = subprocess.run([sys.executable, str(ROOT / "manage.py"), *args], env={**self.env, **(extra_env or {})},
                           capture_output=True, text=True, timeout=300)
        if check and r.returncode != 0:
            logs = "\n".join(f"--- {p.name}\n{p.read_text()[-1500:]}" for p in (self.tmp / "logs").glob("*.log"))
            raise AssertionError(f"manage.py {args} lỗi:\n{r.stdout}\n{r.stderr}\n{logs}")
        return r

    def pids(self) -> dict:
        return json.loads((self.tmp / "run" / "pids.json").read_text())


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("e2e"))
    c.manage("init-env")
    c.manage("init-db")
    c.manage("create-admin", "--email", "admin@e2e.tdtu.vn", "--name", "Admin E2E",
             extra_env={"ADMIN_PASSWORD": "Admin@E2E123"})
    c.manage("start")
    yield c
    c.manage("stop", check=False)
    import manage                         # xóa schema PostgreSQL của lần test này
    subprocess.run([str(manage.NOTI_BIN)], cwd=manage.SVC / "notification", capture_output=True,
                   env={**c.env, "NOTIFICATION_DROP_SCHEMA": "1"})


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(c, email, pw="matkhau123"):
    r = requests.post(c.url["auth"] + "/api/users/login", json={"email": email, "password": pw}, timeout=10)
    assert r.status_code == 200, r.text
    return H(r.json()["access_token"])


def register(c, email, role):
    r = requests.post(c.url["auth"] + "/api/users/register", timeout=10,
                      json={"name": "Người Dùng E2E", "email": email, "password": "matkhau123", "role": role})
    assert r.status_code == 201, r.text
    return login(c, email)


def test_status_and_docs(cluster):
    r = cluster.manage("status")
    assert r.stdout.count("OK") == 6, r.stdout
    for lang in ("Python/FastAPI", "Node.js/Express", "Java/Spring Boot", "Go/Gin", "PHP"):
        assert lang in r.stdout
    for name in ("auth", "restaurant", "order", "notification", "review"):
        base = cluster.url[name]
        assert requests.get(base + "/docs", timeout=5).status_code == 200
        assert requests.get(base + "/redoc", timeout=5).status_code == 200
        assert "bearer" in json.dumps(requests.get(base + "/openapi.json", timeout=5).json()["components"]["securitySchemes"]).lower()
        pre = requests.options(base + "/health", timeout=5, headers={"Origin": cluster.url["web"],
                               "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        assert pre.headers.get("access-control-allow-origin") == cluster.url["web"]
    cfg = requests.get(cluster.url["web"] + "/config.js", timeout=5).text
    assert cluster.url["order"] in cfg
    assert requests.get(cluster.url["web"] + "/student.html", timeout=5).status_code == 200


def test_full_business_flow_restart_and_notification_outage(cluster):
    c, u = cluster, cluster.url
    admin = login(c, "admin@e2e.tdtu.vn", "Admin@E2E123")
    tag = uuid.uuid4().hex[:6]
    owner = register(c, f"owner{tag}@e2e.tdtu.vn", "chu_quan")
    sv = register(c, f"sv{tag}@e2e.tdtu.vn", "sinh_vien")
    sv2 = register(c, f"svb{tag}@e2e.tdtu.vn", "sinh_vien")

    # quán -> chờ duyệt -> admin duyệt -> menu
    rid = requests.post(u["restaurant"] + "/api/restaurants", headers=owner, timeout=10,
                        json={"name": "Quán E2E", "address": "19 Nguyễn Hữu Thọ, Q7"}).json()["id"]
    assert requests.post(u["order"] + "/api/cart/items", headers=sv, timeout=10,
                         json={"restaurant_id": rid, "item_id": str(uuid.uuid4())}).status_code in (409,)
    assert requests.patch(u["restaurant"] + f"/api/admin/restaurants/{rid}/status", headers=admin, timeout=10,
                          json={"status": "active"}).status_code == 200
    items = [requests.post(u["restaurant"] + f"/api/restaurants/{rid}/menu", headers=owner, timeout=10,
                           json={"name": n, "price": p}).json()["id"] for n, p in (("Cơm gà", 40000), ("Nước cam", 15000))]

    # giỏ -> checkout
    for iid, q in zip(items, (2, 1)):
        assert requests.post(u["order"] + "/api/cart/items", headers=sv, timeout=10,
                             json={"restaurant_id": rid, "item_id": iid, "quantity": q}).status_code == 200
    key = str(uuid.uuid4())
    o = requests.post(u["order"] + "/api/orders/checkout", headers={**sv, "Idempotency-Key": key}, timeout=15,
                      json={"delivery_address": "KTX TDTU, phòng E2E"})
    assert o.status_code == 201, o.text
    order = o.json()
    assert order["total_price"] == 95000
    again = requests.post(u["order"] + "/api/orders/checkout", headers={**sv, "Idempotency-Key": key}, timeout=15,
                          json={"delivery_address": "KTX TDTU, phòng E2E"})
    assert again.status_code == 200 and again.json()["id"] == order["id"]
    # giá đổi sau khi đặt không ảnh hưởng đơn
    requests.patch(u["restaurant"] + f"/api/menu-items/{items[0]}", headers=owner, json={"price": 50000}, timeout=10)

    # chủ quán nhận thông báo, xác nhận, hoàn thành; người khác không xem được đơn
    noti = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()
    assert noti["unread"] == 1 and "đơn mới" in noti["items"][0]["message"]
    assert requests.get(u["order"] + f"/api/orders/{order['id']}", headers=sv2, timeout=10).status_code == 403
    for st in ("confirmed", "completed"):
        assert requests.patch(u["order"] + f"/api/orders/{order['id']}/status", headers=owner, timeout=10,
                              json={"status": st}).status_code == 200
    assert requests.get(u["notification"] + "/api/notifications/me", headers=sv, timeout=10).json()["unread"] == 2

    # đánh giá + thống kê
    rv = requests.post(u["review"] + "/api/reviews", headers=sv, timeout=10,
                       json={"order_id": order["id"], "rating": 5, "comment": "Rất ngon"})
    assert rv.status_code == 201, rv.text
    assert requests.post(u["review"] + "/api/reviews", headers=sv2, timeout=10,
                         json={"order_id": order["id"], "rating": 1}).status_code == 403
    assert requests.get(u["review"] + f"/api/reviews/restaurant/{rid}/summary", timeout=10).json()["average"] == 5.0
    stats = requests.get(u["order"] + "/api/admin/orders/stats", headers=admin, timeout=10).json()
    assert stats["revenue"] == 95000 and stats["by_status"]["completed"] == 1
    assert requests.get(u["order"] + f"/internal/orders/{order['id']}", timeout=10).status_code == 403

    # ---- restart toàn hệ thống: dữ liệu và token vẫn còn
    c.manage("stop")
    c.manage("start")
    o2 = requests.get(u["order"] + f"/api/orders/{order['id']}", headers=sv, timeout=10).json()
    assert o2["status"] == "completed" and o2["total_price"] == 95000 and o2["items"][0]["price"] in (40000, 15000)
    assert requests.get(u["review"] + f"/api/reviews/restaurant/{rid}/summary", timeout=10).json()["count"] == 1

    # ---- Notification sập: đơn vẫn tạo được, sau khi bật lại worker tự gửi bù đúng 1 lần
    pid = c.pids()["notification"]
    os.killpg(pid, signal.SIGTERM) if os.name != "nt" else subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"])
    time.sleep(1.5)
    requests.post(u["order"] + "/api/cart/items", headers=sv, json={"restaurant_id": rid, "item_id": items[1]}, timeout=10)
    o3 = requests.post(u["order"] + "/api/orders/checkout", headers=sv, json={"delivery_address": "Thư viện TDTU"}, timeout=20)
    assert o3.status_code == 201, o3.text
    failed = requests.get(u["order"] + "/api/admin/outbox", headers=admin, params={"status": "failed"}, timeout=10).json()
    assert any(f["order_id"] == o3.json()["id"] for f in failed)
    c.manage("stop")
    c.manage("start")
    deadline = time.time() + 30
    while time.time() < deadline:
        msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
        if sum(o3.json()["id"][:8].upper() in m["message"] for m in msgs) >= 1:
            break
        time.sleep(1)
    msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
    assert sum(o3.json()["id"][:8].upper() in m["message"] for m in msgs) == 1
    requests.post(u["order"] + "/api/admin/outbox/retry", headers=admin, timeout=10)
    msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
    assert sum(o3.json()["id"][:8].upper() in m["message"] for m in msgs) == 1     # không nhân đôi


def test_negative_security_on_real_services(cluster):
    u = cluster.url
    assert requests.post(u["auth"] + "/api/users/register", timeout=10, json={"name": "Hacker", "email": "h@e2e.tdtu.vn",
                         "password": "matkhau123", "role": "admin"}).status_code == 422
    assert requests.get(u["order"] + "/api/orders/me", headers=H("sai.token.x"), timeout=10).status_code == 401
    assert requests.post(u["notification"] + "/internal/notifications/events", json={}, timeout=10).status_code == 403
    assert requests.post(u["restaurant"] + "/internal/quote", json={}, timeout=10).status_code == 403
    assert requests.get(u["restaurant"] + "/api/restaurants", params={"page": 0}, timeout=10).status_code == 422
