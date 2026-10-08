"""Notification (sự kiện nội bộ, người nhận, chống trùng, quyền) và Review (điều kiện, đồng thời, điểm TB, kiểm duyệt)."""
import threading
import uuid

from tests.conftest import INTERNAL


def event(world, ev="order_created", actor="sinh_vien", key=None):
    s = world.s
    sv = s.auth.get("/api/users/me", headers=world.sv).json()["id"]
    owner = s.auth.get("/api/users/me", headers=world.owner).json()["id"]
    oid = str(uuid.uuid4())
    return {"event_key": key or f"{oid}:{ev}", "event": ev, "order_id": oid, "order_code": oid[:8].upper(),
            "student_id": sv, "owner_id": owner, "restaurant_name": "Quán Test", "actor_role": actor}


def count(world, h, **params):
    return world.s.notification.get("/api/notifications/me", headers=h, params=params).json()["total"]


def test_internal_event_requires_key_and_is_idempotent(world):
    s = world.s
    body = event(world)
    assert s.notification.post("/internal/notifications/events", json=body).status_code == 403
    assert s.notification.post("/internal/notifications/events", json=body, headers={"X-Internal-Key": "x" * 40}).status_code == 403
    assert s.notification.post("/internal/notifications/events", json=body, headers={**world.sv}).status_code == 403
    r1 = s.notification.post("/internal/notifications/events", json=body, headers=INTERNAL)
    r2 = s.notification.post("/internal/notifications/events", json=body, headers=INTERNAL)
    assert (r1.status_code, r1.json()) == (201, {"created": 1, "duplicates": 0})
    assert (r2.status_code, r2.json()) == (200, {"created": 0, "duplicates": 1})
    assert count(world, world.owner) == 1
    assert s.notification.post("/internal/notifications/events", json={**body, "event": "order_shipped"},
                               headers=INTERNAL).status_code == 422


def test_recipients_by_event_and_actor(world):
    s = world.s
    post = lambda b: s.notification.post("/internal/notifications/events", json=b, headers=INTERNAL)
    post(event(world, "order_confirmed", "chu_quan"))
    post(event(world, "order_completed", "chu_quan"))
    assert count(world, world.sv) == 2 and count(world, world.owner) == 0
    post(event(world, "order_cancelled", "sinh_vien"))
    assert count(world, world.owner) == 1
    post(event(world, "order_cancelled", "chu_quan"))
    assert count(world, world.sv) == 3
    post(event(world, "order_cancelled", "admin"))
    assert count(world, world.sv) == 4 and count(world, world.owner) == 2


def test_read_one_all_and_ownership(world):
    s = world.s
    for _ in range(3):
        s.notification.post("/internal/notifications/events", json=event(world, "order_confirmed", "chu_quan"), headers=INTERNAL)
    items = s.notification.get("/api/notifications/me", headers=world.sv).json()
    assert items["unread"] == 3
    nid = items["items"][0]["id"]
    assert s.notification.patch(f"/api/notifications/{nid}/read", headers=world.owner).status_code == 403
    assert s.notification.patch(f"/api/notifications/{nid}/read", headers=world.sv).json()["status"] == "read"
    assert count(world, world.sv, status="unread") == 2
    assert s.notification.patch("/api/notifications/me/read-all", headers=world.sv).json() == {"updated": 2}
    assert count(world, world.sv, status="unread") == 0
    assert s.notification.patch(f"/api/notifications/{uuid.uuid4()}/read", headers=world.sv).status_code == 404
    assert s.notification.get("/api/notifications/me").status_code == 401
    assert s.notification.get("/api/admin/notifications", headers=world.sv).status_code == 403
    sv_id = s.me(world.sv)
    assert s.notification.get("/api/admin/notifications", headers=world.admin, params={"user_id": sv_id}).json()["total"] == 3
    assert s.notification.delete(f"/api/admin/notifications/{nid}", headers=world.admin).status_code == 204


# ---------------------------------------------------------------- Review
def completed_order(world, student=None):
    s = world.s
    o = s.place_order(student or world.sv, world.rid, [(world.item1, 1)])
    for st in ("confirmed", "completed"):
        s.order.patch(f"/api/orders/{o['id']}/status", headers=world.owner, json={"status": st})
    return o


def review(world, h, oid, rating=5, comment=None):
    body = {"order_id": oid, "rating": rating}
    if comment is not None:
        body["comment"] = comment
    return world.s.review.post("/api/reviews", headers=h, json=body)


def test_review_conditions(world):
    s = world.s
    pending = s.place_order(world.sv, world.rid, [(world.item1, 1)])
    r = review(world, world.sv, pending["id"])
    assert r.status_code == 409 and r.json()["code"] == "ORDER_NOT_COMPLETED"
    o = completed_order(world)
    assert review(world, world.sv2, o["id"]).json()["code"] == "ORDER_NOT_OWNED"
    assert review(world, world.owner, o["id"]).status_code == 403
    assert review(world, world.sv, str(uuid.uuid4())).status_code == 404
    r = review(world, world.sv, o["id"], 4, "  Ngon, giao nhanh  ")
    assert r.status_code == 201
    body = r.json()
    assert body["restaurant_id"] == world.rid and body["reviewer_name"] == "Sinh Viên Một" and body["comment"] == "Ngon, giao nhanh"
    dup = review(world, world.sv, o["id"])
    assert dup.status_code == 409 and dup.json()["code"] == "REVIEW_EXISTS"
    forged = s.review.post("/api/reviews", headers=world.sv, json={"order_id": o["id"], "rating": 5, "restaurant_id": world.rid})
    assert forged.status_code == 422


def test_review_input_validation(world):
    o = completed_order(world)
    for rating in (0, 6, 4.5, "5", True, None):
        assert review(world, world.sv, o["id"], rating).status_code == 422, rating
    assert review(world, world.sv, o["id"], 5, "á" * 1001).status_code == 422
    assert review(world, world.sv, "khong-phai-uuid").status_code == 422
    r = review(world, world.sv, o["id"], 5, "ệ" * 1000)          # 1000 ký tự tiếng Việt hợp lệ
    assert r.status_code == 201
    r2 = review(world, world.sv, completed_order(world)["id"], 3, "    ")
    assert r2.status_code == 201 and r2.json()["comment"] is None


def test_concurrent_reviews_same_order(world):
    o = completed_order(world)
    res = []
    ts = [threading.Thread(target=lambda: res.append(review(world, world.sv, o["id"]).status_code)) for _ in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert res.count(201) == 1 and res.count(409) == 4, res


def test_summary_rounding_privacy_and_moderation(world):
    s = world.s
    empty = s.review.get(f"/api/reviews/restaurant/{world.rid}/summary").json()
    assert empty["average"] is None and empty["count"] == 0
    ids = []
    for rating in (4, 5, 5):
        o = completed_order(world)
        ids.append(review(world, world.sv, o["id"], rating).json()["id"])
    summ = s.review.get(f"/api/reviews/restaurant/{world.rid}/summary").json()
    assert summ["average"] == 4.7 and summ["count"] == 3 and summ["distribution"]["5"] == 2      # 14/3 = 4.67 -> 4.7
    pub = s.review.get(f"/api/reviews/restaurant/{world.rid}", params={"page_size": 2}).json()
    assert pub["total"] == 3 and len(pub["items"]) == 2
    assert set(pub["items"][0]) == {"id", "reviewer_name", "rating", "comment", "created_at"}     # không lộ order/user
    batch = s.review.get("/api/reviews/summary", params={"restaurant_ids": f"{world.rid},{uuid.uuid4()}"}).json()
    assert batch[0]["count"] == 3 and batch[1]["average"] is None
    assert s.review.get("/api/reviews/summary", params={"restaurant_ids": "x"}).status_code == 422
    # admin ẩn đánh giá 4 sao -> TB 5.0; đơn đó không thể đánh giá lại
    assert s.review.patch(f"/api/admin/reviews/{ids[0]}/status", headers=world.sv, json={"status": "hidden"}).status_code == 403
    h = s.review.patch(f"/api/admin/reviews/{ids[0]}/status", headers=world.admin, json={"status": "hidden", "reason": "Spam"})
    assert h.json()["status"] == "hidden" and h.json()["hidden_reason"] == "Spam"
    assert s.review.get(f"/api/reviews/restaurant/{world.rid}/summary").json() == {
        "restaurant_id": world.rid, "average": 5.0, "count": 2, "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 2}}
    mine = s.review.get("/api/reviews/me", headers=world.sv).json()
    hidden_order = next(m["order_id"] for m in mine if m["id"] == ids[0])
    assert review(world, world.sv, hidden_order).status_code == 409
    assert s.review.get("/api/admin/reviews", headers=world.admin,
                        params={"status": "hidden", "restaurant_id": world.rid}).json()["total"] == 1


def test_review_upstream_failures(world):
    s = world.s
    o = completed_order(world)
    for kind, status in (("down", 503), ("timeout", 503), ("500", 502), ("badjson", 502)):
        s.fault("order", kind)
        assert review(world, world.sv, o["id"]).status_code == status, kind
    s.fault("order", None)
    assert review(world, world.sv, o["id"]).status_code == 201
