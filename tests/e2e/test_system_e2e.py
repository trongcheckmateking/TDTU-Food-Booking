"""E2E với 5 service THẬT khởi động bằng đúng lệnh `manage.py start` mà người dùng chạy
(Python/uvicorn, Node.js, java -jar, Go binary, php -S; SQLite + H2 + PostgreSQL trên đĩa).

Dùng cổng trống, thư mục tạm và schema PostgreSQL riêng nên không đụng dữ liệu demo/dev. Kiểm tra: luồng nghiệp
vụ đầy đủ, dữ liệu còn sau restart, Notification sập không làm mất đơn và worker tự gửi lại không trùng, CORS.
"""
from __future__ import annotations

import json
import os
import re
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
EMAIL_API_KEY = "e2e-email-api-key-" + "k" * 16


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cluster:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.ports = {n: free_port() for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW", "WEB", "MOCK_EMAIL")}
        # bỏ EMAIL_SMTP_*: .env thật có thể bật gửi thư qua SMTP, test KHÔNG được gửi thư thật (dùng hộp thư mock)
        env = {k: v for k, v in os.environ.items()
               if k not in ("JWT_SECRET", "INTERNAL_KEY", "DATA_DIR", "OUTBOX_INTERVAL", "CORS_ORIGINS", "HTTP_TIMEOUT")
               and not k.startswith("EMAIL_SMTP_")}
        from tests.conftest import _pg_url
        self.schema = "pytest_e2e_" + uuid.uuid4().hex[:8]
        env.update({"NOTIFICATION_DB_URL": _pg_url() or "", "NOTIFICATION_DB_SCHEMA": self.schema,
                    "TDTU_ENV_FILE": str(tmp / ".env"), "TDTU_RUN_DIR": str(tmp / "run"), "TDTU_LOG_DIR": str(tmp / "logs"),
                    "DATA_DIR": str(tmp / "data"), "OUTBOX_INTERVAL": "2", "WEB_PORT": str(self.ports["WEB"]),
                    "CORS_ORIGINS": f"http://127.0.0.1:{self.ports['WEB']}", "LOG_LEVEL": "WARNING"})
        for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW", "MOCK_EMAIL"):
            env[f"{n}_URL"] = f"http://127.0.0.1:{self.ports[n]}"
        # OTP bật như .env.example; khóa email cố định để test đọc hộp thư mock (biến môi trường thắng .env của init-env)
        env.update({"OTP_ENABLED": "true", "EMAIL_API_KEY": EMAIL_API_KEY, "EMAIL_WEBHOOK_SECRET": "e2e-webhook-secret-" + "s" * 16,
                    "EMAIL_PROVIDER_URL": env["MOCK_EMAIL_URL"],
                    "EMAIL_WEBHOOK_URL": env["NOTIFICATION_URL"] + "/internal/webhooks/email-status"})
        self.env = env
        self.url = {n.lower(): f"http://127.0.0.1:{p}" for n, p in self.ports.items()}

    def manage(self, *args, check=True, extra_env=None):
        r = subprocess.run([sys.executable, str(ROOT / "manage.py"), *args], env={**self.env, **(extra_env or {})},
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
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


def read_otp(c, email):
    r = requests.get(c.url["mock_email"] + "/api/emails", headers={"X-API-Key": EMAIL_API_KEY}, params={"to": email}, timeout=10)
    assert r.status_code == 200 and r.json()["items"], r.text
    return re.search(r"\b(\d{6})\b", r.json()["items"][0]["content"]).group(1)


def register(c, email, role):
    """Đăng ký; bật OTP thì đăng nhập bị chặn tới khi nhập mã từ hộp thư MockMail (xác nhận xong là có token)."""
    body = {"name": "Người Dùng E2E", "email": email, "password": "matkhau123", "role": role, "accept_terms": True}
    if role == "chu_quan":                               # chủ quán khai báo tài khoản nhận tiền (VietQR)
        body.update(bank_bin="970436", bank_account="0071000123456", bank_holder="Chủ Quán Thử Nghiệm")
    r = requests.post(c.url["auth"] + "/api/users/register", timeout=10, json=body)
    assert r.status_code == 201, r.text
    if not r.json()["verification_required"]:
        return login(c, email)
    assert r.json()["otp_sent"] is True, r.text
    blocked = requests.post(c.url["auth"] + "/api/users/login", json={"email": email, "password": "matkhau123"}, timeout=10)
    assert blocked.status_code == 403 and blocked.json()["code"] == "EMAIL_NOT_VERIFIED", blocked.text
    v = requests.post(c.url["auth"] + "/api/users/verify-otp", json={"email": email, "code": read_otp(c, email)}, timeout=10)
    assert v.status_code == 200, v.text
    return H(v.json()["access_token"])


def test_status_and_docs(cluster):
    r = cluster.manage("status")
    assert r.stdout.count("OK") == 7, r.stdout              # 5 service + mock_email + giao diện
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

    # thanh toán trước: mã VietQR vào tài khoản quán -> sinh viên báo đã chuyển -> quán xác nhận nhận tiền
    pay = order["payment"]
    assert (pay["status"], pay["amount"], pay["account"]) == ("unpaid", 95000, "0071000123456")
    qr = requests.get(u["web"] + "/qr/vietqr.svg", timeout=10, params={"bin": pay["bank_bin"], "acc": pay["account"],
                                                                         "amount": pay["amount"], "note": pay["note"]})
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
    assert requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["unread"] == 0
    assert requests.post(u["order"] + f"/api/orders/{order['id']}/payment/claim", headers=sv, timeout=10).status_code == 200

    # chủ quán nhận thông báo, xác nhận tiền, nhận đơn, hoàn thành; người khác không xem được đơn
    noti = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()
    assert noti["unread"] == 1 and "đơn mới" in noti["items"][0]["message"]
    assert requests.post(u["order"] + f"/api/orders/{order['id']}/payment/confirm", headers=owner,
                         timeout=10).json()["payment"]["status"] == "paid"
    assert requests.get(u["order"] + f"/api/orders/{order['id']}", headers=sv2, timeout=10).status_code == 403
    for st in ("confirmed", "completed"):
        assert requests.patch(u["order"] + f"/api/orders/{order['id']}/status", headers=owner, timeout=10,
                              json={"status": st}).status_code == 200
    assert requests.get(u["notification"] + "/api/notifications/me", headers=sv, timeout=10).json()["unread"] == 3

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
    for who, step in ((sv, "claim"), (owner, "confirm")):
        assert requests.post(u["order"] + f"/api/orders/{o3.json()['id']}/payment/{step}", headers=who,
                             timeout=20).status_code == 200
    failed = requests.get(u["order"] + "/api/admin/outbox", headers=admin, params={"status": "failed"}, timeout=10).json()
    assert any(f["order_id"] == o3.json()["id"] for f in failed)
    c.manage("stop")
    c.manage("start")
    deadline = time.time() + 30
    while time.time() < deadline:
        msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
        if sum(f"#{o3.json()['pickup_code']}" in m["message"] for m in msgs) >= 1:
            break
        time.sleep(1)
    msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
    assert sum(f"#{o3.json()['pickup_code']}" in m["message"] for m in msgs) == 1
    requests.post(u["order"] + "/api/admin/outbox/retry", headers=admin, timeout=10)
    msgs = requests.get(u["notification"] + "/api/notifications/me", headers=owner, timeout=10).json()["items"]
    assert sum(f"#{o3.json()['pickup_code']}" in m["message"] for m in msgs) == 1     # không nhân đôi


def test_otp_email_delivered_via_signed_webhook(cluster):
    """Unit 20 qua `manage.py start`: Auth -> Notification -> MockMail nhận thư; ~1 giây sau MockMail gọi webhook có ký
    HMAC -> email_logs chuyển delivered (admin xem ở /api/admin/email-logs); hộp thư bounce* -> failed."""
    c, u = cluster, cluster.url
    admin = login(c, "admin@e2e.tdtu.vn", "Admin@E2E123")
    tag = uuid.uuid4().hex[:6]
    me = requests.get(u["auth"] + "/api/users/me", headers=register(c, f"otp{tag}@student.tdtu.edu.vn", "sinh_vien"),
                      timeout=10).json()
    assert me["email_verified_at"]
    bounce = requests.post(u["auth"] + "/api/users/register", timeout=10, json={
        "name": "Hộp Thư Lỗi", "email": f"bounce{tag}@student.tdtu.edu.vn", "password": "matkhau123", "accept_terms": True}).json()

    def status_of(uid):
        items = requests.get(u["notification"] + "/api/admin/email-logs", headers=admin, params={"user_id": uid},
                             timeout=10).json()["items"]
        return items[0] if items else None
    deadline = time.time() + 15
    while time.time() < deadline:
        a, b = status_of(me["id"]), status_of(bounce["id"])
        if a and b and a["status"] == "delivered" and b["status"] == "failed":
            break
        time.sleep(0.5)
    assert a["status"] == "delivered" and a["provider_message_id"].startswith("msg_"), a
    assert b["status"] == "failed" and "mailbox_not_found" in b["last_error"], b
    # webhook giả mạo (không có chữ ký đúng) bị từ chối
    fake = requests.post(u["notification"] + "/internal/webhooks/email-status", timeout=10, data=json.dumps(
        {"message_id": a["provider_message_id"], "status": "failed", "reason": None, "timestamp": "x"}),
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "sha256=" + "0" * 64})
    assert fake.status_code == 401 and fake.json()["code"] == "INVALID_SIGNATURE"
    assert status_of(me["id"])["status"] == "delivered"


def test_negative_security_on_real_services(cluster):
    u = cluster.url
    assert requests.post(u["auth"] + "/api/users/register", timeout=10, json={"name": "Hacker", "email": "h@e2e.tdtu.vn",
                         "password": "matkhau123", "role": "admin", "accept_terms": True}).status_code == 422
    assert requests.get(u["order"] + "/api/orders/me", headers=H("sai.token.x"), timeout=10).status_code == 401
    assert requests.post(u["notification"] + "/internal/notifications/events", json={}, timeout=10).status_code == 403
    assert requests.post(u["restaurant"] + "/internal/quote", json={}, timeout=10).status_code == 403
    assert requests.get(u["restaurant"] + "/api/restaurants", params={"page": 0}, timeout=10).status_code == 422
