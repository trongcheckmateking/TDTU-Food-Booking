"""Kiểm tra nhanh hệ thống ĐANG CHẠY (kế thừa test_flow.py và kiem_thu_ghep_noi.py của bản nguồn).

Chạy sau `python manage.py start` (cần tài khoản admin; mặc định dùng admin demo của lệnh seed):
    python scripts/smoke_test.py
Biến môi trường: SMOKE_ADMIN_EMAIL, SMOKE_ADMIN_PASSWORD, *_URL, MOCK_EMAIL_URL, EMAIL_API_KEY như .env.
Thoát mã 1 nếu có bước lỗi. Tạo dữ liệu mới (tài khoản/quán có hậu tố ngẫu nhiên), không xóa dữ liệu sẵn có.
Bật OTP: đăng ký -> đăng nhập bị chặn (EMAIL_NOT_VERIFIED) -> đọc mã ở hộp thư MockMail -> xác nhận -> đăng nhập.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
from common import config  # noqa: E402

U = {n.lower(): config.service_url(n) for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW")}
MOCK = config.get("MOCK_EMAIL_URL", "http://127.0.0.1:9000").rstrip("/")
failures = 0


def step(name, cond, detail=""):
    global failures
    print(("  ĐẠT  " if cond else "  LỖI  ") + name + (f"  ({detail})" if detail and not cond else ""))
    failures += 0 if cond else 1
    return cond


def login(email, pw):
    r = requests.post(U["auth"] + "/api/users/login", json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def read_otp(email):
    """Mã mới nhất trong hộp thư của nhà cung cấp email giả lập (không in mã ra màn hình)."""
    r = requests.get(MOCK + "/api/emails", headers={"X-API-Key": config.get("EMAIL_API_KEY", "")},
                     params={"to": email}, timeout=5)
    items = r.json().get("items", []) if r.status_code == 200 else []
    m = re.search(r"\b(\d{6})\b", items[0]["content"]) if items else None
    return m.group(1) if m else None


def verify_email(email, pw, reg):
    """Bật OTP: đăng nhập trước khi xác nhận bị chặn; nhập mã trong email -> nhận token. Tắt OTP: đăng nhập luôn."""
    if not reg.get("verification_required"):
        return login(email, pw)
    r = requests.post(U["auth"] + "/api/users/login", json={"email": email, "password": pw}, timeout=10)
    step("chưa xác nhận email thì không đăng nhập được", r.status_code == 403 and r.json().get("code") == "EMAIL_NOT_VERIFIED", r.text)
    step("mã OTP đã gửi qua email", reg.get("otp_sent") is True, str(reg.get("otp_sent")))
    code = read_otp(email)
    step("đọc được mã OTP trong hộp thư MockMail", code is not None)
    r = requests.post(U["auth"] + "/api/users/verify-otp", json={"email": email, "code": code or "000000"}, timeout=10)
    step("xác nhận email bằng mã OTP", r.status_code == 200 and "access_token" in r.json(), r.text)
    return {"Authorization": "Bearer " + r.json()["access_token"]} if r.status_code == 200 else login(email, pw)


def main():
    tag = uuid.uuid4().hex[:6]
    for name, url in U.items():
        step(f"{name} /health", requests.get(url + "/health", timeout=5).status_code == 200)
    admin = login(os.environ.get("SMOKE_ADMIN_EMAIL", "admin@demo.tdtu.vn"), os.environ.get("SMOKE_ADMIN_PASSWORD", "Admin@123"))
    users = {}
    for role, key in (("chu_quan", "owner"), ("sinh_vien", "sv")):
        email = f"smoke-{key}-{tag}@student.tdtu.edu.vn"
        body = {"name": "Smoke Test", "email": email, "password": "smoke12345", "role": role, "accept_terms": True}
        if role == "chu_quan":                       # tài khoản nhận tiền giả, chỉ để thử (không chuyển tiền thật)
            body.update(bank_bin="970436", bank_account="0071000123456", bank_holder="SMOKE TEST DEMO")
        r = requests.post(U["auth"] + "/api/users/register", timeout=10, json=body)
        step(f"đăng ký {role}", r.status_code == 201, r.text)
        users[key] = verify_email(email, "smoke12345", r.json())
    r = requests.post(U["restaurant"] + "/api/restaurants", headers=users["owner"], timeout=10,
                      json={"name": f"Quán Smoke {tag}", "address": "19 Nguyễn Hữu Thọ, Q7"})
    step("chủ quán tạo quán (pending)", r.status_code == 201 and r.json()["status"] == "pending", r.text)
    rid = r.json()["id"]
    r = requests.patch(U["restaurant"] + f"/api/admin/restaurants/{rid}/status", headers=admin, json={"status": "active"}, timeout=10)
    step("admin duyệt quán", r.status_code == 200, r.text)
    item = requests.post(U["restaurant"] + f"/api/restaurants/{rid}/menu", headers=users["owner"], timeout=10,
                         json={"name": "Cơm Smoke", "price": 30000}).json()["id"]
    requests.delete(U["order"] + "/api/cart", headers=users["sv"], timeout=10)
    r = requests.post(U["order"] + "/api/cart/items", headers=users["sv"], timeout=10,
                      json={"restaurant_id": rid, "item_id": item, "quantity": 2})
    step("thêm vào giỏ", r.status_code == 200 and r.json()["total_price"] == 60000, r.text)
    r = requests.post(U["order"] + "/api/orders/checkout", headers={**users["sv"], "Idempotency-Key": tag}, timeout=15,
                      json={"delivery_address": "KTX TDTU"})
    step("checkout", r.status_code == 201 and r.json()["total_price"] == 60000, r.text)
    oid = r.json().get("id")
    pay = r.json().get("payment") or {}
    step("đơn chờ thanh toán vào tài khoản quán", pay.get("status") == "unpaid" and pay.get("account") == "0071000123456", str(pay))
    r = requests.post(U["order"] + f"/api/orders/{oid}/payment/claim", headers=users["sv"], timeout=10)
    step("sinh viên báo đã chuyển khoản", r.status_code == 200, r.text)
    r = requests.post(U["order"] + f"/api/orders/{oid}/payment/confirm", headers=users["owner"], timeout=10)
    step("chủ quán xác nhận đã nhận tiền", r.status_code == 200 and r.json()["payment"]["status"] == "paid", r.text)
    for st in ("confirmed", "completed"):
        r = requests.patch(U["order"] + f"/api/orders/{oid}/status", headers=users["owner"], json={"status": st}, timeout=10)
        step(f"chủ quán chuyển {st}", r.status_code == 200, r.text)
    n = requests.get(U["notification"] + "/api/notifications/me", headers=users["sv"], timeout=10).json()
    step("sinh viên nhận 3 thông báo", n["total"] == 3, str(n))
    r = requests.post(U["review"] + "/api/reviews", headers=users["sv"], json={"order_id": oid, "rating": 5}, timeout=10)
    step("đánh giá đơn hoàn thành", r.status_code == 201, r.text)
    s = requests.get(U["review"] + f"/api/reviews/restaurant/{rid}/summary", timeout=10).json()
    step("điểm trung bình 5.0", s["average"] == 5.0, str(s))
    # đơn tiền mặt: tới quán ngay, chủ quán được báo "có đơn mới" (sự kiện order_created)
    requests.post(U["order"] + "/api/cart/items", headers=users["sv"], timeout=10,
                  json={"restaurant_id": rid, "item_id": item, "quantity": 1})
    r = requests.post(U["order"] + "/api/orders/checkout", headers=users["sv"], timeout=15,
                      json={"delivery_address": "KTX TDTU", "payment_method": "cash"})
    cash = r.json() if r.status_code == 201 else {}
    step("đặt đơn tiền mặt", r.status_code == 201 and cash.get("payment", {}).get("status") == "cash", r.text)
    step("đơn tiền mặt đã báo chủ quán (notification_status = sent)", cash.get("notification_status") == "sent", str(cash.get("notification_status")))
    n = requests.get(U["notification"] + "/api/notifications/me", headers=users["owner"], timeout=10).json()
    step("chủ quán nhận thông báo đơn tiền mặt", any(x["order_id"] == cash.get("id") and x["type"] == "order_created"
                                                   for x in n.get("items", [])), str(n.get("total")))
    step("token sai bị từ chối", requests.get(U["order"] + "/api/orders/me", headers={"Authorization": "Bearer x"}, timeout=10).status_code == 401)
    print("KẾT QUẢ:", "ĐẠT" if not failures else f"{failures} bước lỗi")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print("Không kết nối được hệ thống:", e)
        sys.exit(1)
