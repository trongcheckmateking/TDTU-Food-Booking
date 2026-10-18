"""Xóa dữ liệu cá nhân theo yêu cầu (Chính sách quyền riêng tư, mục 8): Auth khóa tài khoản rồi điều phối Order,
Restaurant, Review, Notification ẩn danh / gỡ dữ liệu của người đó. Chạy trên 5 service thật."""
import time

from tests.conftest import INTERNAL

ERASED = "Người dùng đã xóa"


def test_admin_erases_student_everywhere(world):
    s, w = world.s, world
    sv_id = s.me(w.sv)
    done = s.place_order(w.sv, w.rid, [(w.item1, 1)])
    for st in ("confirmed", "completed"):
        assert s.order.patch(f"/api/orders/{done['id']}/status", headers=w.owner, json={"status": st}).status_code == 200
    assert s.review.post("/api/reviews", headers=w.sv, json={"order_id": done["id"], "rating": 5,
                                                             "comment": "Ngon"}).status_code == 201
    pending = s.place_order(w.sv, w.rid, [(w.item2, 2)])
    from tests.integration.test_auth import PNG
    avatar = s.auth.request("PUT", "/api/users/me/avatar", headers={**w.sv, "Content-Type": "image/png"},
                            content=PNG).json()["avatar_url"]
    s.order.post("/api/cart/items", headers=w.sv, json={"restaurant_id": w.rid, "item_id": w.item1, "quantity": 1})

    assert s.auth.post(f"/api/users/{sv_id}/erase", headers=w.sv).status_code == 403          # chỉ admin
    assert s.auth.post("/api/users/khong-phai-uuid/erase", headers=w.admin).status_code == 422

    # còn đơn đang xử lý -> 409, nhưng tài khoản đã bị khóa để không phát sinh đơn mới
    r = s.auth.post(f"/api/users/{sv_id}/erase", headers=w.admin)
    assert r.status_code == 409 and r.json()["code"] == "USER_HAS_ACTIVE_ORDERS", r.text
    assert s.auth.get("/api/users/me", headers=w.sv).status_code == 401                      # token đã bị thu hồi
    assert s.auth.post("/api/users/login", json={"email": w.emails["sv"], "password": "matkhau123"}).status_code == 403

    assert s.order.patch(f"/api/orders/{pending['id']}/status", headers=w.owner,
                         json={"status": "cancelled", "reason": "Khách yêu cầu xóa tài khoản"}).status_code == 200
    # đơn đã trả tiền bị hủy: quán chưa hoàn tiền thì chưa xóa được (sinh viên còn chờ nhận lại tiền)
    r = s.auth.post(f"/api/users/{sv_id}/erase", headers=w.admin)
    assert r.status_code == 409 and "hoàn tiền" in r.json()["detail"], r.text
    assert s.order.post(f"/api/orders/{pending['id']}/payment/refunded", headers=w.owner).status_code == 200
    r = s.auth.post(f"/api/users/{sv_id}/erase", headers=w.admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["name"] == ERASED and body["user"]["phone"] is None and body["user"]["status"] == "locked"
    assert body["user"]["email"].endswith(".invalid") and body["user"]["erased_at"]
    assert body["user"]["avatar_url"] is None and s.auth.get(avatar).status_code == 404       # ảnh đại diện bị xóa
    assert body["services"]["order"]["orders_anonymized"] == 2 and body["services"]["order"]["carts_deleted"] == 1
    assert body["services"]["review"]["reviews_anonymized"] == 1
    assert body["services"]["notification"]["notifications_deleted"] >= 2
    assert body["services"]["restaurant"]["restaurants_removed"] == 0

    # chủ quán vẫn thấy đơn và số tiền, nhưng không còn tên / số điện thoại / chỗ nhận của người đặt
    o = s.order.get(f"/api/orders/{done['id']}", headers=w.owner).json()
    assert o["customer_name"] == ERASED and o["customer_phone"] is None and o["delivery_address"] == "(đã xóa)"
    assert o["total_price"] == 35000 and o["status"] == "completed"
    reviews = s.review.get(f"/api/reviews/restaurant/{w.rid}").json()
    assert [x["reviewer_name"] for x in reviews["items"]] == [ERASED] and reviews["summary"]["average"] == 5.0

    # email cũ không đăng nhập được, admin không mở khóa / đổi vai trò được nữa; gọi lại an toàn
    assert s.auth.post("/api/users/login", json={"email": w.emails["sv"], "password": "matkhau123"}).status_code == 401
    assert s.auth.patch(f"/api/users/{sv_id}/status", headers=w.admin, json={"status": "active"}).json()["code"] == "USER_ERASED"
    assert s.auth.patch(f"/api/users/{sv_id}/role", headers=w.admin, json={"role": "chu_quan"}).json()["code"] == "USER_ERASED"
    again = s.auth.post(f"/api/users/{sv_id}/erase", headers=w.admin)
    assert again.status_code == 200 and again.json()["user"]["erased_at"] == body["user"]["erased_at"]
    # email cũ đăng ký lại được như người mới
    s.register(w.emails["sv"])


def test_admin_erases_owner_removes_restaurants(world):
    s, w = world.s, world
    owner_id = s.me(w.owner)
    r = s.auth.post(f"/api/users/{owner_id}/erase", headers=w.admin)
    assert r.status_code == 200, r.text
    assert r.json()["services"]["restaurant"]["restaurants_removed"] == 1
    assert s.restaurant.get(f"/api/restaurants/{w.rid}").status_code == 404
    assert s.restaurant.get(f"/internal/owners/{owner_id}/restaurant-count", headers=INTERNAL).json()["count"] == 0


def test_erase_guards(world):
    s, w = world.s, world
    admin_id = s.me(w.admin)
    assert s.auth.post(f"/api/users/{admin_id}/erase", headers=w.admin).json()["code"] == "SELF_ACTION"
    for svc in ("order", "restaurant", "review", "notification"):
        assert s.clients[svc].post(f"/internal/users/{admin_id}/erase").status_code == 403, svc
    # một service sập -> báo lỗi, Auth chưa ẩn danh gì (gọi lại sau khi service chạy lại)
    sv2_id = s.me(w.sv2)
    s.fault("review", "down")
    r = s.auth.post(f"/api/users/{sv2_id}/erase", headers=w.admin)
    assert r.status_code == 503, r.text
    s.fault("review", None)
    assert s.auth.get(f"/api/users/{sv2_id}", headers=w.admin).json()["erased_at"] is None
    assert s.auth.post(f"/api/users/{sv2_id}/erase", headers=w.admin).status_code == 200


def test_erasure_reapplied_after_restoring_older_backup(world):
    """Mỗi lần xóa được ghi vào erasures.log (ngoài auth.db). Khôi phục bản sao lưu cũ hơn lần xóa làm tài khoản
    "sống lại"; Auth khởi động lại phải tự xóa lại người đó."""
    s, w, c = world.s, world, world.s.c
    sv2_id = s.me(w.sv2)
    assert s.auth.post(f"/api/users/{sv2_id}/erase", headers=w.admin).status_code == 200
    assert sv2_id in (c.data / "erasures.log").read_text(encoding="utf-8")

    conn = c.auth_db()                                   # giả lập auth.db từ bản sao lưu trước lần xóa
    conn.execute("UPDATE users SET name='Sinh Viên Hai', email=?, status='active', erased_at=NULL WHERE id=?",
                 (w.emails["sv2"], sv2_id))
    conn.close()
    assert s.auth.get(f"/api/users/{sv2_id}", headers=w.admin).json()["erased_at"] is None

    c.procs["auth"].terminate()
    c.procs["auth"].wait(15)
    c.start("auth")
    c.wait_ready(["auth"])
    deadline = time.time() + 30
    u = {}
    while time.time() < deadline:
        u = s.auth.get(f"/api/users/{sv2_id}", headers=w.admin).json()
        if u.get("erased_at"):
            break
        time.sleep(0.5)
    assert u.get("erased_at") and u["name"] == ERASED and u["status"] == "locked", u
    assert s.auth.post("/api/users/login", json={"email": w.emails["sv2"], "password": "matkhau123"}).status_code == 401
