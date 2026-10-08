"""Kiểm tra nhanh hệ thống ĐANG CHẠY (kế thừa test_flow.py và kiem_thu_ghep_noi.py của bản nguồn).

Chạy sau `python manage.py start` (cần tài khoản admin; mặc định dùng admin demo của lệnh seed):
    python scripts/smoke_test.py
Biến môi trường: SMOKE_ADMIN_EMAIL, SMOKE_ADMIN_PASSWORD, *_URL như .env. Thoát mã 1 nếu có bước lỗi.
Tạo dữ liệu mới (tài khoản/quán có hậu tố ngẫu nhiên), không xóa dữ liệu sẵn có.
"""
from __future__ import annotations

import os
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


def main():
    tag = uuid.uuid4().hex[:6]
    for name, url in U.items():
        step(f"{name} /health", requests.get(url + "/health", timeout=5).status_code == 200)
    admin = login(os.environ.get("SMOKE_ADMIN_EMAIL", "admin@demo.tdtu.vn"), os.environ.get("SMOKE_ADMIN_PASSWORD", "Admin@123"))
    users = {}
    for role, key in (("chu_quan", "owner"), ("sinh_vien", "sv")):
        email = f"smoke-{key}-{tag}@student.tdtu.edu.vn"
        r = requests.post(U["auth"] + "/api/users/register", timeout=10,
                          json={"name": "Smoke Test", "email": email, "password": "smoke12345", "role": role})
        step(f"đăng ký {role}", r.status_code == 201, r.text)
        users[key] = login(email, "smoke12345")
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
    for st in ("confirmed", "completed"):
        r = requests.patch(U["order"] + f"/api/orders/{oid}/status", headers=users["owner"], json={"status": st}, timeout=10)
        step(f"chủ quán chuyển {st}", r.status_code == 200, r.text)
    n = requests.get(U["notification"] + "/api/notifications/me", headers=users["sv"], timeout=10).json()
    step("sinh viên nhận 2 thông báo", n["total"] == 2, str(n))
    r = requests.post(U["review"] + "/api/reviews", headers=users["sv"], json={"order_id": oid, "rating": 5}, timeout=10)
    step("đánh giá đơn hoàn thành", r.status_code == 201, r.text)
    s = requests.get(U["review"] + f"/api/reviews/restaurant/{rid}/summary", timeout=10).json()
    step("điểm trung bình 5.0", s["average"] == 5.0, str(s))
    step("token sai bị từ chối", requests.get(U["order"] + "/api/orders/me", headers={"Authorization": "Bearer x"}, timeout=10).status_code == 401)
    print("KẾT QUẢ:", "ĐẠT" if not failures else f"{failures} bước lỗi")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print("Không kết nối được hệ thống:", e)
        sys.exit(1)
