"""Demo xử lý đồng thời của Order Service trên hệ thống ĐANG CHẠY (dùng tài khoản của `python manage.py seed`).

    python scripts/demo_concurrency.py

Tình huống 1 - bấm "Đặt hàng" nhiều lần cùng lúc:
  a) 10 luồng checkout CÙNG Idempotency-Key  -> đúng 1 phản hồi 201, 9 phản hồi còn lại trả lại đúng đơn đó (200 replay).
  b) 10 luồng checkout KHÔNG có khóa          -> giỏ chỉ đặt được 1 lần: đúng 1 đơn, các luồng khác bị từ chối (409).
Tình huống 2 - trên một đơn tiền mặt quán đã nhận, cùng lúc bấm "Báo hoàn thành" và "Hủy":
  2 luồng PATCH trạng thái (completed và cancelled) -> đúng 1 thành công, luồng kia 409 (STATUS_CHANGED khi 2 yêu cầu
  chồng nhau: UPDATE có điều kiện chỉ cho 1 bên thắng; INVALID_TRANSITION khi tới sau: đơn đã ở trạng thái cuối).
  Không dùng cặp confirmed + cancelled từ pending: confirmed -> cancelled là bước HỢP LỆ (quán hủy đơn đã nhận), nên
  khi 2 yêu cầu lệch nhau vài mili giây thì cả hai thành công đúng luật (đo 10 lần: 3 lần như vậy) -> demo không ổn định.

Cơ chế: SELECT ... FOR UPDATE khóa giỏ của sinh viên (xếp hàng các checkout), UNIQUE(user_id, idempotency_key), và
UPDATE có điều kiện (WHERE status=<trạng thái đã đọc>) cho đổi trạng thái. In bảng kết quả, dòng cuối ĐẠT / LỖI
(mã thoát 1 nếu LỖI). Biến môi trường: DEMO_SV_EMAIL, DEMO_OWNER_EMAIL, DEMO_PASSWORD, *_URL như .env.
Tạo vài đơn mới trong dữ liệu đang chạy; đơn chuyển khoản tạo ra được sinh viên tự bỏ ngay sau khi kiểm tra.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
from common import config  # noqa: E402

AUTH, RESTAURANT, ORDER = (config.service_url(n) for n in ("AUTH", "RESTAURANT", "ORDER"))
SV = os.environ.get("DEMO_SV_EMAIL", "sv1@demo.tdtu.vn")
OWNER = os.environ.get("DEMO_OWNER_EMAIL", "chuquan1@demo.tdtu.vn")
PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo@123")
http = requests.Session()
http.trust_env = False
rows: list[tuple[str, str, bool]] = []


def login(email: str) -> dict:
    r = http.post(AUTH + "/api/users/login", json={"email": email, "password": PASSWORD}, timeout=10)
    if r.status_code != 200:
        sys.exit(f"Không đăng nhập được {email} ({r.status_code}): chạy `python manage.py seed` trước. {r.text[:200]}")
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def parallel(n: int, fn) -> list[requests.Response]:
    """Chạy fn() trên n luồng, thả cùng lúc bằng Barrier để các yêu cầu thật sự chồng lên nhau."""
    gate, out, lock = threading.Barrier(n), [], threading.Lock()

    def worker():
        gate.wait()
        r = fn()
        with lock:
            out.append(r)
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def summary(results: list[requests.Response]) -> str:
    c = Counter(f"{r.status_code} {r.json().get('code', '') if r.status_code >= 400 else ''}".strip() for r in results)
    return ", ".join(f"{k} × {v}" for k, v in sorted(c.items()))


def record(name: str, detail: str, ok: bool):
    rows.append((name, detail, ok))


def pick_item(owner: dict) -> tuple[str, str]:
    """Quán đang mở của chủ quán demo và một món còn bán."""
    for r in http.get(RESTAURANT + "/api/restaurants/mine", headers=owner, timeout=10).json():
        if r["status"] != "active":
            continue
        for m in http.get(RESTAURANT + f"/api/restaurants/{r['id']}/menu", timeout=10).json():
            if m["status"] == "available":
                return r["id"], m["id"]
    sys.exit("Chủ quán demo không có quán đang mở / món còn bán: chạy `python manage.py seed`.")


def fill_cart(sv: dict, rid: str, iid: str):
    http.delete(ORDER + "/api/cart", headers=sv, timeout=10)
    r = http.post(ORDER + "/api/cart/items", headers=sv, json={"restaurant_id": rid, "item_id": iid, "quantity": 1}, timeout=10)
    if r.status_code != 200:
        sys.exit(f"Không thêm được món vào giỏ: {r.status_code} {r.text[:200]}")


def checkout(sv: dict, key: str | None = None, method: str = "transfer") -> requests.Response:
    h = {**sv, **({"Idempotency-Key": key} if key else {})}
    return http.post(ORDER + "/api/orders/checkout", headers=h, timeout=30,
                     json={"delivery_address": "KTX TDTU (demo đồng thời)", "payment_method": method})


def drop(sv: dict, oid: str):
    """Sinh viên bỏ đơn chuyển khoản chưa thanh toán (dọn dữ liệu demo)."""
    http.patch(ORDER + f"/api/orders/{oid}/status", headers=sv, json={"status": "cancelled", "reason": "Demo đồng thời"}, timeout=10)


def scenario_same_key(sv, rid, iid):
    fill_cart(sv, rid, iid)
    key = "demo-" + uuid.uuid4().hex
    res = parallel(10, lambda: checkout(sv, key))
    created = [r for r in res if r.status_code == 201]
    replays = [r for r in res if r.status_code == 200 and r.headers.get("Idempotent-Replay") == "true"]
    ids = {r.json()["id"] for r in created + replays}
    ok = len(created) == 1 and len(replays) == 9 and len(ids) == 1
    record("1a. 10 luồng CÙNG Idempotency-Key", f"{summary(res)}; số đơn khác nhau = {len(ids)}", ok)
    for oid in ids:
        drop(sv, oid)


def scenario_no_key(sv, rid, iid):
    fill_cart(sv, rid, iid)
    res = parallel(10, lambda: checkout(sv))
    created = [r for r in res if r.status_code == 201]
    rejected = [r for r in res if r.status_code == 409]
    ok = len(created) == 1 and len(rejected) == 9
    record("1b. 10 luồng KHÔNG có khóa", f"{summary(res)}; đơn được tạo = {len(created)}", ok)
    for r in created:
        drop(sv, r.json()["id"])


def scenario_status_race(sv, owner, rid, iid):
    name = "2. Hoàn thành và Hủy cùng lúc (tiền mặt)"
    fill_cart(sv, rid, iid)
    r = checkout(sv, method="cash")
    if r.status_code != 201:
        record(name, f"không tạo được đơn tiền mặt: {r.status_code}", False)
        return
    oid = r.json()["id"]
    url = ORDER + f"/api/orders/{oid}/status"
    if http.patch(url, headers=owner, json={"status": "confirmed"}, timeout=10).status_code != 200:   # quán nhận đơn
        record(name, "quán không nhận được đơn", False)
        return
    bodies = iter([{"status": "completed"}, {"status": "cancelled", "reason": "Demo đồng thời"}])
    lock = threading.Lock()

    def patch():
        with lock:
            body = next(bodies)
        return http.patch(url, headers=owner, json=body, timeout=30)
    res = parallel(2, patch)
    won = [x for x in res if x.status_code == 200]
    lost = [x for x in res if x.status_code == 409]
    final = http.get(ORDER + f"/api/orders/{oid}", headers=owner, timeout=10).json()["status"]
    ok = len(won) == 1 and len(lost) == 1 and final == won[0].json()["status"]
    record(name, f"{summary(res)}; trạng thái cuối = {final}", ok)


def main():
    sv, owner = login(SV), login(OWNER)
    rid, iid = pick_item(owner)
    print(f"Order Service: {ORDER}   sinh viên: {SV}   chủ quán: {OWNER}\n")
    scenario_same_key(sv, rid, iid)
    scenario_no_key(sv, rid, iid)
    scenario_status_race(sv, owner, rid, iid)
    width = max(len(n) for n, _, _ in rows)
    for name, detail, ok in rows:
        print(f"  {'ĐẠT' if ok else 'LỖI'}  {name:<{width}}  {detail}")
    passed = all(ok for _, _, ok in rows)
    print("\nKẾT QUẢ:", "ĐẠT" if passed else "LỖI")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        sys.exit(f"Không kết nối được hệ thống: {e}")
