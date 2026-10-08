"""Sinh Postman collection + environment từ OpenAPI (docs/openapi/*.json).

  python manage.py export-openapi && python scripts/build_postman.py
Thư mục "0. Luồng demo" chạy theo thứ tự trên dữ liệu seed (có test tự kiểm tra), ví dụ:
  npx newman run docs/postman/TDTU_FoodBooking.postman_collection.json \
      -e docs/postman/TDTU_FoodBooking.local.postman_environment.json --folder "0. Luồng demo"
Các thư mục còn lại liệt kê mọi endpoint của từng service. Không lưu token thật: token được lấy khi chạy.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "postman"
SERVICES = ["auth", "restaurant", "order", "notification", "review"]
SAMPLE = {"name": "Tên mẫu", "email": "sv.moi@student.tdtu.edu.vn", "password": "matkhau123", "role": "sinh_vien",
          "address": "19 Nguyễn Hữu Thọ, Q7", "price": 30000, "quantity": 1, "rating": 5, "comment": "Ngon",
          "delivery_address": "KTX TDTU, phòng B305", "status": "cancelled", "reason": "Lý do mẫu",
          "restaurant_id": "{{restaurant_id}}", "item_id": "{{item_id}}", "order_id": "{{order_id}}"}


def token_for(path: str, tags: list[str]) -> str | None:
    if path.startswith("/internal") or path in ("/api/users/register", "/api/users/login", "/", "/health"):
        return None
    if "admin" in tags or path.startswith("/api/admin") or path.startswith("/api/users/{"):
        return "token_admin"
    if "owner" in tags or "/owner" in path or path.startswith("/api/menu-items/{mid}"):
        return "token_owner"
    if path == "/api/users":
        return "token_admin"
    return "token_sv"


def sample_body(schema: dict, components: dict) -> dict:
    if "$ref" in schema:
        schema = components[schema["$ref"].split("/")[-1]]
    body = {}
    for name in schema.get("required", list(schema.get("properties", {}))[:3]):
        body[name] = SAMPLE.get(name, "giá trị")
    return body


def req(name, method, svc, path, token=None, body=None, tests=None, headers=None, prerequest=None):
    item = {"name": name, "request": {
        "method": method, "header": [{"key": k, "value": v} for k, v in (headers or {}).items()],
        "url": {"raw": "{{" + svc + "_url}}" + path, "host": ["{{" + svc + "_url}}"],
                "path": [p for p in path.split("?")[0].split("/") if p]}}}
    if "?" in path:
        q = path.split("?", 1)[1]
        item["request"]["url"]["query"] = [dict(zip(("key", "value"), kv.split("=", 1))) for kv in q.split("&")]
    if token:
        item["request"]["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + token + "}}", "type": "string"}]}
    else:
        item["request"]["auth"] = {"type": "noauth"}
    if body is not None:
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, ensure_ascii=False, indent=2),
                                   "options": {"raw": {"language": "json"}}}
    events = []
    if tests:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": tests.strip().splitlines()}})
    if prerequest:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": prerequest.strip().splitlines()}})
    if events:
        item["event"] = events
    return item


def demo_flow() -> dict:
    login = lambda var: f"""
pm.test("đăng nhập 200", () => pm.response.to.have.status(200));
pm.collectionVariables.set("{var}", pm.response.json().access_token);"""
    items = [
        req("1. Đăng nhập sinh viên", "POST", "auth", "/api/users/login",
            body={"email": "{{sv_email}}", "password": "{{demo_password}}"}, tests=login("token_sv")),
        req("2. Đăng nhập chủ quán", "POST", "auth", "/api/users/login",
            body={"email": "{{owner_email}}", "password": "{{demo_password}}"}, tests=login("token_owner")),
        req("3. Đăng nhập admin", "POST", "auth", "/api/users/login",
            body={"email": "{{admin_email}}", "password": "{{admin_password}}"}, tests=login("token_admin")),
        req("4. Danh sách quán, chọn quán của chủ quán demo", "GET", "restaurant", "/api/restaurants?q=Cơm Tấm",
            tests="""
pm.test("200", () => pm.response.to.have.status(200));
const r = pm.response.json().items.find(x => x.accepting_orders);
pm.test("có quán đang nhận đơn", () => pm.expect(r).to.be.ok);
pm.collectionVariables.set("restaurant_id", r.id);"""),
        req("5. Menu, chọn món còn bán", "GET", "restaurant", "/api/restaurants/{{restaurant_id}}/menu", tests="""
const m = pm.response.json().find(x => x.status === "available");
pm.test("có món còn bán", () => pm.expect(m).to.be.ok);
pm.collectionVariables.set("item_id", m.id); pm.collectionVariables.set("item_price", m.price);"""),
        req("6. Xóa giỏ cũ", "DELETE", "order", "/api/cart", token="token_sv",
            tests='pm.test("204", () => pm.response.to.have.status(204));'),
        req("7. Thêm 2 phần vào giỏ", "POST", "order", "/api/cart/items", token="token_sv",
            body={"restaurant_id": "{{restaurant_id}}", "item_id": "{{item_id}}", "quantity": 2}, tests="""
pm.test("200", () => pm.response.to.have.status(200));
pm.test("tạm tính = 2 x giá", () => pm.expect(pm.response.json().total_price).to.eql(2 * Number(pm.collectionVariables.get("item_price"))));"""),
        req("8. Checkout (Idempotency-Key)", "POST", "order", "/api/orders/checkout", token="token_sv",
            headers={"Idempotency-Key": "{{checkout_key}}"}, body={"delivery_address": "KTX TDTU, phòng B305"},
            prerequest='pm.collectionVariables.set("checkout_key", pm.variables.replaceIn("{{$guid}}"));', tests="""
pm.test("201", () => pm.response.to.have.status(201));
pm.test("đơn pending, có ảnh chụp tên món", () => { const o = pm.response.json();
  pm.expect(o.status).to.eql("pending"); pm.expect(o.items[0].item_name).to.be.a("string"); });
pm.collectionVariables.set("order_id", pm.response.json().id);"""),
        req("9. Gửi lại cùng Idempotency-Key -> cùng đơn", "POST", "order", "/api/orders/checkout", token="token_sv",
            headers={"Idempotency-Key": "{{checkout_key}}"}, body={"delivery_address": "KTX TDTU, phòng B305"}, tests="""
pm.test("200 replay", () => pm.response.to.have.status(200));
pm.test("cùng đơn", () => pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get("order_id")));"""),
        req("10. Chủ quán xác nhận", "PATCH", "order", "/api/orders/{{order_id}}/status", token="token_owner",
            body={"status": "confirmed"}, tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("11. Chủ quán hoàn thành", "PATCH", "order", "/api/orders/{{order_id}}/status", token="token_owner",
            body={"status": "completed"}, tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("12. Sinh viên xem thông báo chưa đọc", "GET", "notification", "/api/notifications/me?status=unread",
            token="token_sv", tests="""
pm.test("có thông báo hoàn thành", () => pm.expect(pm.response.json().items.some(n => n.type === "order_completed")).to.be.true);"""),
        req("13. Sinh viên đánh giá", "POST", "review", "/api/reviews", token="token_sv",
            body={"order_id": "{{order_id}}", "rating": 5, "comment": "Ngon, giao nhanh"},
            tests='pm.test("201", () => pm.response.to.have.status(201));'),
        req("14. Điểm trung bình quán", "GET", "review", "/api/reviews/restaurant/{{restaurant_id}}/summary",
            tests='pm.test("có điểm", () => pm.expect(pm.response.json().count).to.be.above(0));'),
        req("15. Admin thống kê", "GET", "order", "/api/admin/orders/stats", token="token_admin",
            tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("16. Không có token -> 401", "GET", "order", "/api/orders/me", tests="""
pm.test("401", () => pm.response.to.have.status(401));
pm.test("mã lỗi", () => pm.expect(pm.response.json().code).to.eql("UNAUTHORIZED"));"""),
    ]
    return {"name": "0. Luồng demo", "item": items}


def service_folders() -> list[dict]:
    folders = []
    for svc in SERVICES:
        spec = json.loads((ROOT / "docs" / "openapi" / f"{svc}.json").read_text(encoding="utf-8"))
        comps = spec.get("components", {}).get("schemas", {})
        items = []
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                p = (path.replace("{rid}", "{{restaurant_id}}").replace("{mid}", "{{item_id}}")
                     .replace("{item_id}", "{{item_id}}").replace("{oid}", "{{order_id}}")
                     .replace("{user_id}", "{{user_id}}").replace("{owner_id}", "{{user_id}}")
                     .replace("{nid}", "{{notification_id}}").replace("{review_id}", "{{review_id}}"))
                body = None
                rb = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
                if rb:
                    body = sample_body(rb, comps)
                headers = {"X-Internal-Key": "{{internal_key}}"} if path.startswith("/internal") else None
                items.append(req(f"{method.upper()} {path} – {op.get('summary', '')}", method.upper(), svc, p,
                                 token=token_for(path, op.get("tags", [])), body=body, headers=headers))
        folders.append({"name": f"{SERVICES.index(svc) + 1}. {spec['info']['title']}", "item": items})
    return folders


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    collection = {
        "info": {"name": "TDTU Food Booking", "description": "Sinh từ OpenAPI bằng scripts/build_postman.py",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [demo_flow(), *service_folders()],
        "variable": [{"key": k, "value": ""} for k in ("token_sv", "token_owner", "token_admin", "restaurant_id",
                                                       "item_id", "item_price", "order_id", "checkout_key", "user_id",
                                                       "notification_id", "review_id")],
    }
    env = {"name": "TDTU Food Booking - local", "values": [
        {"key": k, "value": v, "enabled": True} for k, v in {
            "auth_url": "http://127.0.0.1:8001", "restaurant_url": "http://127.0.0.1:8002",
            "order_url": "http://127.0.0.1:8003", "notification_url": "http://127.0.0.1:8004",
            "review_url": "http://127.0.0.1:8005", "sv_email": "sv1@demo.tdtu.vn", "owner_email": "chuquan1@demo.tdtu.vn",
            "admin_email": "admin@demo.tdtu.vn", "demo_password": "Demo@123", "admin_password": "Admin@123",
            "internal_key": ""}.items()]}
    (OUT / "TDTU_FoodBooking.postman_collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "TDTU_FoodBooking.local.postman_environment.json").write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Đã tạo", OUT)


if __name__ == "__main__":
    main()
