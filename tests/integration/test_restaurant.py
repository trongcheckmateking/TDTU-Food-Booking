"""Restaurant: duyệt quán, quyền chủ quán, khóa, món ẩn/hết, kiểm tra dữ liệu, báo giá nội bộ."""
from tests.conftest import INTERNAL


def public_ids(s):
    """Mọi id quán công khai (duyệt qua tất cả các trang)."""
    ids, page = [], 1
    while True:
        r = s.restaurant.get("/api/restaurants", params={"page": page, "page_size": 100}).json()
        ids += [x["id"] for x in r["items"]]
        if page * 100 >= r["total"]:
            return ids
        page += 1


def test_new_restaurant_pending_until_approved(world):
    s = world.s
    r = s.restaurant.post("/api/restaurants", headers=world.owner2, json={"name": "Quán Mới", "address": "Cổng B TDTU, Q7"})
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["accepting_orders"] is False
    rid = r.json()["id"]
    assert rid not in public_ids(s)
    assert s.restaurant.get(f"/api/restaurants/{rid}").status_code == 404           # khách không thấy
    assert s.restaurant.get(f"/api/restaurants/{rid}", headers=world.owner2).status_code == 200
    r = s.restaurant.patch(f"/api/restaurants/{rid}", headers=world.owner2, json={"status": "active"})
    assert r.status_code == 409 and r.json()["code"] == "RESTAURANT_PENDING"          # không tự duyệt
    assert s.restaurant.patch(f"/api/admin/restaurants/{rid}/status", headers=world.owner2,
                              json={"status": "active"}).status_code == 403
    assert s.restaurant.patch(f"/api/admin/restaurants/{rid}/status", headers=world.admin,
                              json={"status": "active"}).json()["status"] == "active"
    assert rid in public_ids(s)


def test_owner_id_from_token_and_role_checks(world):
    s = world.s
    body = {"name": "Quán Giả", "address": "Đâu đó, Q7", "owner_id": "00000000-0000-4000-8000-000000000001"}
    assert s.restaurant.post("/api/restaurants", headers=world.owner, json=body).status_code == 422   # trường giả mạo
    assert s.restaurant.post("/api/restaurants", headers=world.sv, json={"name": "X Y", "address": "Q7 abc"}).status_code == 403
    assert s.restaurant.post("/api/restaurants", headers=world.admin, json={"name": "X Y", "address": "Q7 abc"}).status_code == 403
    assert s.restaurant.post("/api/restaurants", json={"name": "X Y", "address": "Q7 abc"}).status_code == 401
    me = s.auth.get("/api/users/me", headers=world.owner).json()
    assert s.restaurant.get(f"/api/restaurants/{world.rid}").json()["owner_id"] == me["id"]


def test_cross_owner_forbidden(world):
    s = world.s
    assert s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner2, json={"name": "Chiếm quán"}).status_code == 403
    assert s.restaurant.post(f"/api/restaurants/{world.rid}/menu", headers=world.owner2, json={"name": "M", "price": 1}).status_code == 403
    assert s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner2, json={"price": 1}).status_code == 403
    assert s.restaurant.delete(f"/api/menu-items/{world.item1}", headers=world.owner2).status_code == 403
    assert s.restaurant.delete(f"/api/restaurants/{world.rid}", headers=world.owner2).status_code == 403
    # không chuyển được món sang quán khác
    r = s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"restaurant_id": world.rid})
    assert r.status_code == 422


def test_menu_validation(world):
    s = world.s
    url = f"/api/restaurants/{world.rid}/menu"
    bad = [{"name": "A", "price": 1.5}, {"name": "A", "price": "1000"}, {"name": "A", "price": True},
           {"name": "A", "price": -1}, {"name": "   ", "price": 1000}, {"name": "A", "price": 100_000_001},
           {"name": "A", "price": 1000, "status": "deleted"}]
    for body in bad:
        assert s.restaurant.post(url, headers=world.owner, json=body).status_code == 422, body
    r = s.restaurant.post(url, headers={**world.owner, "Content-Type": "application/json"}, content=b'{"name":"Inf","price":1e309}')
    assert r.status_code == 422
    r = s.restaurant.post(url, headers={**world.owner, "Content-Type": "application/json"}, content=b'{"name":')
    assert r.status_code == 422 and r.json()["detail"] == "JSON gửi lên không hợp lệ"
    assert s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"open_time": "25:00"}).status_code == 422
    assert s.restaurant.get("/api/restaurants/khong-phai-uuid").status_code == 422
    assert s.restaurant.get("/api/restaurants", params={"page_size": 101}).status_code == 422


def test_hidden_and_sold_out_visibility(world):
    s = world.s
    s.restaurant.patch(f"/api/menu-items/{world.item2}", headers=world.owner, json={"status": "hidden"})
    s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"status": "sold_out"})
    public = s.restaurant.get(f"/api/restaurants/{world.rid}/menu").json()
    assert [m["id"] for m in public] == [world.item1] and public[0]["status"] == "sold_out"
    assert s.restaurant.get(f"/api/restaurants/{world.rid}/menu", params={"all": "true"}).status_code == 403
    assert s.restaurant.get(f"/api/restaurants/{world.rid}/menu", params={"all": "true"}, headers=world.sv).status_code == 403
    assert len(s.restaurant.get(f"/api/restaurants/{world.rid}/menu", params={"all": "true"}, headers=world.owner).json()) == 2
    assert len(s.restaurant.get(f"/api/restaurants/{world.rid}/menu", params={"all": "true"}, headers=world.admin).json()) == 2
    assert s.restaurant.get(f"/api/menu-items/{world.item2}").status_code == 404
    assert s.restaurant.get(f"/api/menu-items/{world.item2}", headers=world.owner).status_code == 200


def test_locked_restaurant(world):
    s = world.s
    s.restaurant.patch(f"/api/admin/restaurants/{world.rid}/status", headers=world.admin,
                       json={"status": "locked", "reason": "Vi phạm"})
    assert world.rid not in public_ids(s)
    assert s.restaurant.get(f"/api/restaurants/{world.rid}").status_code == 404
    assert s.restaurant.get(f"/api/menu-items/{world.item1}").status_code == 404
    assert s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"status": "active"}).status_code == 403
    assert s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"price": 1}).status_code == 403
    detail = s.restaurant.get(f"/api/restaurants/{world.rid}", headers=world.owner).json()
    assert detail["status"] == "locked" and detail["status_reason"] == "Vi phạm"
    q = s.restaurant.post("/internal/quote", headers=INTERNAL, json={"restaurant_id": world.rid,
                                                                     "items": [{"item_id": world.item1, "quantity": 1}]}).json()
    assert q["restaurant"]["accepting_orders"] is False
    assert s.restaurant.patch(f"/api/admin/restaurants/{world.rid}/status", headers=world.admin,
                              json={"status": "active"}).json()["status_reason"] is None


def test_owner_open_close(world):
    s = world.s
    r = s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"status": "closed"})
    assert r.json()["status"] == "closed" and r.json()["accepting_orders"] is False
    assert world.rid in public_ids(s)   # vẫn công khai
    assert s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"status": "locked"}).status_code == 422


def test_soft_delete(world):
    s = world.s
    assert s.restaurant.delete(f"/api/menu-items/{world.item2}", headers=world.owner).status_code == 204
    assert world.item2 not in [m["id"] for m in s.restaurant.get(f"/api/restaurants/{world.rid}/menu").json()]
    assert s.restaurant.delete(f"/api/restaurants/{world.rid}", headers=world.owner).status_code == 204
    assert s.restaurant.get(f"/api/restaurants/{world.rid}", headers=world.owner).status_code == 404
    allr = s.restaurant.get("/api/admin/restaurants", headers=world.admin, params={"include_deleted": "true", "status": "active",
                                                                                "page_size": 100}).json()
    assert any(x["id"] == world.rid and x["deleted_at"] for x in allr["items"])


def test_internal_quote(world):
    s = world.s
    body = {"restaurant_id": world.rid, "items": [{"item_id": world.item1, "quantity": 2},
                                                  {"item_id": "00000000-0000-4000-8000-000000000999", "quantity": 1}]}
    assert s.restaurant.post("/internal/quote", json=body).status_code == 403
    assert s.restaurant.post("/internal/quote", json=body, headers={"X-Internal-Key": "sai"}).status_code == 403
    q = s.restaurant.post("/internal/quote", json=body, headers=INTERNAL).json()
    assert q["items"][0]["line_total"] == 70000 and q["items"][1]["reason"] == "ITEM_NOT_FOUND" and not q["all_available"]
    owner_id = s.auth.get("/api/users/me", headers=world.owner).json()["id"]
    assert s.restaurant.get(f"/internal/owners/{owner_id}/restaurant-count", headers=INTERNAL).json()["count"] == 1


def test_auth_upstream_errors_mapped(world):
    s = world.s
    for kind, status, code in (("down", 503, "UPSTREAM_UNAVAILABLE"), ("timeout", 503, "UPSTREAM_UNAVAILABLE"),
                               ("500", 502, "UPSTREAM_ERROR"), ("badjson", 502, "UPSTREAM_BAD_RESPONSE")):
        s.fault("auth", kind)
        r = s.restaurant.get("/api/restaurants/mine", headers=world.owner)
        assert (r.status_code, r.json()["code"]) == (status, code), kind
    s.fault("auth", None)
    assert s.restaurant.get("/api/restaurants/mine", headers=world.owner).status_code == 200
