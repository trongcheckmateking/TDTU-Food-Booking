"""Order: giỏ hàng, checkout, chống trùng, giá chụp, trạng thái, đồng thời, outbox thông báo."""
import threading
import uuid

from tests.conftest import INTERNAL


def add(s, h, rid, iid, q=1):
    return s.order.post("/api/cart/items", headers=h, json={"restaurant_id": rid, "item_id": iid, "quantity": q})


def checkout(s, h, key=None, address="KTX TDTU B305"):
    hh = dict(h)
    if key:
        hh["Idempotency-Key"] = key
    return s.order.post("/api/orders/checkout", headers=hh, json={"delivery_address": address})


def test_cart_operations(world):
    s = world.s
    assert s.order.get("/api/cart", headers=world.sv).json()["items"] == []
    assert add(s, world.sv, world.rid, world.item1, 2).json()["total_price"] == 70000
    c = add(s, world.sv, world.rid, world.item1, 1).json()
    assert c["items"][0]["quantity"] == 3 and c["total_price"] == 105000
    c = s.order.patch(f"/api/cart/items/{world.item1}", headers=world.sv, json={"quantity": 1}).json()
    assert c["total_price"] == 35000
    add(s, world.sv, world.rid, world.item2, 2)
    c = s.order.delete(f"/api/cart/items/{world.item1}", headers=world.sv).json()
    assert [x["item_id"] for x in c["items"]] == [world.item2]
    assert s.order.delete(f"/api/cart/items/{world.item1}", headers=world.sv).status_code == 404
    assert s.order.delete("/api/cart", headers=world.sv).status_code == 204
    assert s.order.get("/api/cart", headers=world.sv).json()["item_count"] == 0
    assert s.order.get("/api/cart", headers=world.owner).status_code == 403     # chỉ sinh viên có giỏ


def test_cart_single_restaurant_and_switch_when_empty(world):
    s = world.s
    rid2, (other,) = s.make_restaurant(world.owner2, world.admin, name="Quán Hai", items=(("Bún bò", 40000),))
    add(s, world.sv, world.rid, world.item1)
    r = add(s, world.sv, rid2, other)
    assert r.status_code == 409 and r.json()["code"] == "CART_OTHER_RESTAURANT"
    s.order.delete(f"/api/cart/items/{world.item1}", headers=world.sv)            # xóa món cuối -> giỏ trống
    r = add(s, world.sv, rid2, other)
    assert r.status_code == 200 and r.json()["restaurant"]["id"] == rid2


def test_cart_validation_and_availability(world):
    s = world.s
    for q in (0, 51, True, 1.5, "2"):
        assert add(s, world.sv, world.rid, world.item1, q).status_code == 422, q
    assert s.order.post("/api/cart/items", headers=world.sv, json={"restaurant_id": "x", "item_id": world.item1}).status_code == 422
    rid2, (other,) = s.make_restaurant(world.owner2, world.admin, name="Quán Hai", items=(("Bún", 1000),))
    r = add(s, world.sv, world.rid, other)                                         # món của quán khác
    assert r.status_code == 409 and r.json()["code"] == "ITEM_NOT_FOUND"
    s.restaurant.patch(f"/api/menu-items/{world.item2}", headers=world.owner, json={"status": "sold_out"})
    assert add(s, world.sv, world.rid, world.item2).json()["code"] == "ITEM_SOLD_OUT"
    s.restaurant.patch(f"/api/menu-items/{world.item2}", headers=world.owner, json={"status": "hidden"})
    assert add(s, world.sv, world.rid, world.item2).json()["code"] == "ITEM_HIDDEN"
    s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"status": "closed"})
    assert add(s, world.sv, world.rid, world.item1).json()["code"] == "RESTAURANT_NOT_ACCEPTING"
    assert add(s, world.sv, world.rid, world.item1, 50).status_code == 409
    s.restaurant.patch(f"/api/restaurants/{world.rid}", headers=world.owner, json={"status": "active"})
    assert add(s, world.sv, world.rid, world.item1, 50).status_code == 200
    r = add(s, world.sv, world.rid, world.item1, 1)
    assert r.status_code == 422 and r.json()["code"] == "QUANTITY_LIMIT"


def test_checkout_snapshot_and_history_survives_menu_changes(world):
    s = world.s
    add(s, world.sv, world.rid, world.item1, 2)
    add(s, world.sv, world.rid, world.item2, 3)
    r = checkout(s, world.sv)
    assert r.status_code == 201
    o = r.json()
    assert o["total_price"] == 2 * 35000 + 3 * 3000 and o["status"] == "pending"
    assert o["customer_name"] == "Sinh Viên Một" and o["customer_phone"] == "0901234567" and o["restaurant_name"] == "Quán Test"
    names = {i["item_name"]: (i["price"], i["line_total"]) for i in o["items"]}
    assert names == {"Cơm sườn": (35000, 70000), "Trà đá": (3000, 9000)}
    assert s.order.get("/api/cart", headers=world.sv).json()["item_count"] == 0           # giỏ được xóa sau khi đặt
    # đổi giá, xóa món, xóa quán: đơn cũ vẫn đọc và xử lý được
    s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"price": 99000, "name": "Tên mới"})
    s.restaurant.delete(f"/api/menu-items/{world.item2}", headers=world.owner)
    s.restaurant.delete(f"/api/restaurants/{world.rid}", headers=world.owner)
    again = s.order.get(f"/api/orders/{o['id']}", headers=world.sv).json()
    assert again["total_price"] == 79000 and {i["item_name"] for i in again["items"]} == {"Cơm sườn", "Trà đá"}
    assert s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": "confirmed"}).status_code == 200
    assert s.order.get(f"/api/orders/{o['id']}", headers=world.owner).json()["status"] == "confirmed"


def test_checkout_rejects_unavailable_and_keeps_cart(world):
    s = world.s
    add(s, world.sv, world.rid, world.item1)
    s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"status": "sold_out"})
    r = checkout(s, world.sv)
    assert r.status_code == 409 and r.json()["code"] == "ITEMS_UNAVAILABLE" and r.json()["items"][0]["reason"] == "ITEM_SOLD_OUT"
    assert s.order.get("/api/cart", headers=world.sv).json()["item_count"] == 1          # giỏ còn nguyên
    s.restaurant.patch(f"/api/menu-items/{world.item1}", headers=world.owner, json={"status": "available"})
    s.fault("restaurant", "down")
    r = checkout(s, world.sv)
    assert r.status_code == 503
    s.fault("restaurant", "badjson")
    assert checkout(s, world.sv).status_code == 502
    s.fault("restaurant", None)
    assert s.order.get("/api/cart", headers=world.sv).json()["item_count"] == 1
    assert checkout(s, world.sv).status_code == 201
    assert checkout(s, world.sv).json()["code"] == "CART_EMPTY"


def test_checkout_idempotency_and_double_click(world):
    s = world.s
    add(s, world.sv, world.rid, world.item1)
    key = str(uuid.uuid4())
    first = checkout(s, world.sv, key)
    replay = checkout(s, world.sv, key)
    assert first.status_code == 201 and replay.status_code == 200 and replay.headers.get("Idempotent-Replay") == "true"
    assert replay.json()["id"] == first.json()["id"]
    # bấm nhiều lần đồng thời cùng key: đúng 1 đơn
    add(s, world.sv, world.rid, world.item1)
    key2, results = str(uuid.uuid4()), []
    ts = [threading.Thread(target=lambda: results.append(checkout(s, world.sv, key2))) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    ids = {r.json()["id"] for r in results if r.status_code in (200, 201)}
    assert len(ids) == 1, [(r.status_code, r.json()) for r in results]
    assert all(r.status_code in (200, 201, 409) for r in results)
    # đồng thời không có key: giỏ chỉ được đặt 1 lần
    add(s, world.sv, world.rid, world.item2)
    results = []
    ts = [threading.Thread(target=lambda: results.append(checkout(s, world.sv))) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(r.status_code == 201 for r in results) == 1, [(r.status_code, r.text) for r in results]
    assert s.order.get("/api/orders/me", headers=world.sv).json()["total"] == 3


def _order(world, lines=None):
    return world.s.place_order(world.sv, world.rid, lines or [(world.item1, 1)])


def test_status_rules_by_role(world):
    s = world.s
    o = _order(world)
    url = f"/api/orders/{o['id']}/status"
    assert s.order.patch(url, headers=world.sv, json={"status": "confirmed"}).status_code == 403
    assert s.order.patch(url, headers=world.admin, json={"status": "confirmed"}).json()["code"] == "FORBIDDEN"
    assert s.order.patch(url, headers=world.owner2, json={"status": "confirmed"}).status_code == 403
    assert s.order.patch(url, headers=world.sv2, json={"status": "cancelled"}).status_code == 403
    assert s.order.get(f"/api/orders/{o['id']}", headers=world.sv2).status_code == 403
    assert s.order.get(f"/api/orders/{o['id']}", headers=world.owner2).status_code == 403
    r = s.order.patch(url, headers=world.owner, json={"status": "completed"})
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TRANSITION"
    assert s.order.patch(url, headers=world.owner, json={"status": "confirmed"}).status_code == 200
    r = s.order.patch(url, headers=world.sv, json={"status": "cancelled"})
    assert r.status_code == 403                                                    # SV chỉ hủy khi pending
    assert s.order.patch(url, headers=world.owner, json={"status": "completed"}).status_code == 200
    for actor in (world.owner, world.admin):
        assert s.order.patch(url, headers=actor, json={"status": "cancelled"}).status_code == 409   # trạng thái cuối
    assert s.order.patch(url, headers=world.owner, json={"status": "shipped"}).status_code == 422


def test_cancel_by_student_and_admin(world):
    s = world.s
    o1 = _order(world)
    r = s.order.patch(f"/api/orders/{o1['id']}/status", headers=world.sv, json={"status": "cancelled", "reason": "Đổi ý"})
    assert r.json()["status"] == "cancelled" and r.json()["cancelled_by"] == "sinh_vien" and r.json()["cancel_reason"] == "Đổi ý"
    o2 = _order(world)
    s.order.patch(f"/api/orders/{o2['id']}/status", headers=world.owner, json={"status": "confirmed"})
    r = s.order.patch(f"/api/orders/{o2['id']}/status", headers=world.admin, json={"status": "cancelled", "reason": "Đơn lỗi"})
    assert r.json()["cancelled_by"] == "admin"


def test_concurrent_status_updates(world):
    s = world.s
    o = _order(world)
    s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": "confirmed"})
    res = []
    def go(st):
        res.append(s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": st}).status_code)
    ts = [threading.Thread(target=go, args=(st,)) for st in ("completed", "cancelled", "completed", "cancelled")]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert res.count(200) == 1 and all(c == 409 for c in res if c != 200), res


def test_lists_filters_and_pagination(world):
    s = world.s
    before = s.order.get("/api/admin/orders/stats", headers=world.admin).json()
    for _ in range(3):
        _order(world)
    mine = s.order.get("/api/orders/me", headers=world.sv, params={"page_size": 2}).json()
    assert mine["total"] == 3 and len(mine["items"]) == 2
    assert s.order.get("/api/orders/me", headers=world.sv2).json()["total"] == 0
    assert s.order.get("/api/orders/owner", headers=world.owner, params={"status": "pending"}).json()["total"] == 3
    assert s.order.get("/api/orders/owner", headers=world.owner2).json()["total"] == 0
    assert s.order.get("/api/orders/owner", headers=world.sv).status_code == 403
    adm = s.order.get("/api/admin/orders", headers=world.admin, params={"restaurant_id": world.rid}).json()
    assert adm["total"] == 3
    assert s.order.get("/api/admin/orders", headers=world.admin, params={"date_from": "07/10/2026"}).status_code == 422
    stats = s.order.get("/api/admin/orders/stats", headers=world.admin).json()
    assert stats["by_status"]["pending"] - before["by_status"]["pending"] == 3
    assert stats["revenue"] == before["revenue"] and stats["total"] - before["total"] == 3
    assert s.order.get("/api/admin/orders/stats", headers=world.owner).status_code == 403


def notis(world, h):
    return world.s.notification.get("/api/notifications/me", headers=h).json()["items"]


def test_notifications_flow_and_outbox_retry_without_duplicates(world):
    s = world.s
    o = _order(world)
    assert any("đơn mới" in n["message"] for n in notis(world, world.owner))
    # Notification sập: đơn vẫn đổi trạng thái, sự kiện nằm ở outbox trạng thái failed
    s.fault("notification", "down")
    assert s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": "confirmed"}).status_code == 200
    s.fault("notification", "500")
    assert s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": "completed"}).status_code == 200
    failed = [f for f in s.order.get("/api/admin/outbox", headers=world.admin, params={"status": "failed"}).json()
              if f["order_id"] == o["id"]]
    assert {f["event_key"].split(":")[1] for f in failed} == {"order_confirmed", "order_completed"}
    assert all(f["last_error"] for f in failed)
    assert len(notis(world, world.sv)) == 0
    s.fault("notification", None)
    r = s.order.post("/api/admin/outbox/retry", headers=world.admin).json()
    assert r["sent"] >= 2 and r["failed"] == 0, r
    assert s.order.post("/api/admin/outbox/retry", headers=world.admin).json() == {"sent": 0, "failed": 0}
    msgs = [n["message"] for n in notis(world, world.sv)]
    assert len(msgs) == 2 and sum("hoàn thành" in m for m in msgs) == 1
    sent = s.order.get("/api/admin/outbox", headers=world.admin, params={"status": "sent"}).json()
    assert {f["event_key"].split(":")[1] for f in sent if f["order_id"] == o["id"]} == {
        "order_created", "order_confirmed", "order_completed"}
    # Order gửi lại cùng sự kiện (mô phỏng retry sau khi đã gửi thành công) -> Notification không nhân đôi
    payload = {"event_key": f"{o['id']}:order_completed", "event": "order_completed", "order_id": o["id"],
               "order_code": o["id"][:8].upper(), "student_id": s.me(world.sv), "owner_id": s.me(world.owner),
               "restaurant_name": o["restaurant_name"], "actor_role": "chu_quan"}
    r = s.notification.post("/internal/notifications/events", json=payload, headers=INTERNAL)
    assert (r.status_code, r.json()) == (200, {"created": 0, "duplicates": 1})
    assert len(notis(world, world.sv)) == 2 and len(notis(world, world.owner)) == 1


def test_internal_order_endpoint_requires_key(world):
    s = world.s
    o = _order(world)
    assert s.order.get(f"/internal/orders/{o['id']}").status_code == 403
    assert s.order.get(f"/internal/orders/{o['id']}", headers=INTERNAL).json()["restaurant_owner_id"]
    assert s.order.get(f"/internal/orders/{uuid.uuid4()}", headers=INTERNAL).status_code == 404
