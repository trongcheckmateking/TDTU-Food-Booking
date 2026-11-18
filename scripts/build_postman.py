"""Sinh Postman collection + environment từ OpenAPI (docs/openapi/*.json).

  python manage.py export-openapi && python scripts/build_postman.py
Thư mục "0. Luồng demo" chạy theo thứ tự trên dữ liệu seed (có test tự kiểm tra), ví dụ:
  npx newman run docs/postman/TDTU_FoodBooking.postman_collection.json \
      -e docs/postman/TDTU_FoodBooking.local.postman_environment.json --folder "0. Luồng demo"
Thư mục "OTP. ..." chạy luồng xác nhận email (cần OTP_ENABLED=true, biến email_api_key = EMAIL_API_KEY trong .env).
Các thư mục còn lại liệt kê mọi endpoint của từng service và MockMail. Không lưu token / khóa thật: token được lấy khi
chạy, khóa tự điền vào environment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "postman"
SERVICES = ["auth", "restaurant", "order", "notification", "review", "mock_email"]
SAMPLE = {"name": "Tên mẫu", "email": "sv.moi@student.tdtu.edu.vn", "password": "matkhau123", "role": "sinh_vien",
          "address": "19 Nguyễn Hữu Thọ, Q7", "price": 30000, "quantity": 1, "rating": 5, "comment": "Ngon",
          "delivery_address": "KTX TDTU, phòng B305", "status": "cancelled", "reason": "Lý do mẫu",
          "restaurant_id": "{{restaurant_id}}", "item_id": "{{item_id}}", "order_id": "{{order_id}}"}


def token_for(path: str, tags: list[str]) -> str | None:
    if path.startswith("/internal") or path in ("/api/users/register", "/api/users/login", "/api/users/token",
                                                "/api/users/verify-otp", "/api/users/resend-otp", "/", "/health"):
        return None
    if "admin" in tags or path.startswith("/api/admin") or path.startswith("/api/users/{"):
        return "token_admin"
    if ("owner" in tags or "/owner" in path or path.startswith("/api/menu-items/{mid}") or path == "/api/users/me/payout"
            or re.search(r"/payment/(confirm|reject|refunded)$", path)):
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
pm.test("đơn pending, chờ thanh toán, có ảnh chụp tên món", () => { const o = pm.response.json();
  pm.expect(o.status).to.eql("pending"); pm.expect(o.payment.status).to.eql("unpaid");
  pm.expect(o.payment.account).to.be.a("string"); pm.expect(o.items[0].item_name).to.be.a("string"); });
pm.collectionVariables.set("order_id", pm.response.json().id);"""),
        req("9. Gửi lại cùng Idempotency-Key -> cùng đơn", "POST", "order", "/api/orders/checkout", token="token_sv",
            headers={"Idempotency-Key": "{{checkout_key}}"}, body={"delivery_address": "KTX TDTU, phòng B305"}, tests="""
pm.test("200 replay", () => pm.response.to.have.status(200));
pm.test("cùng đơn", () => pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get("order_id")));"""),
        req("10. Sinh viên quét VietQR, báo đã chuyển khoản", "POST", "order", "/api/orders/{{order_id}}/payment/claim",
            token="token_sv", tests='pm.test("claimed", () => pm.expect(pm.response.json().payment.status).to.eql("claimed"));'),
        req("11. Chủ quán thấy tiền vào: Đã nhận tiền", "POST", "order", "/api/orders/{{order_id}}/payment/confirm",
            token="token_owner", tests='pm.test("paid", () => pm.expect(pm.response.json().payment.status).to.eql("paid"));'),
        req("12. Chủ quán nhận đơn", "PATCH", "order", "/api/orders/{{order_id}}/status", token="token_owner",
            body={"status": "confirmed"}, tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("13. Chủ quán hoàn thành", "PATCH", "order", "/api/orders/{{order_id}}/status", token="token_owner",
            body={"status": "completed"}, tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("14. Sinh viên xem thông báo chưa đọc", "GET", "notification", "/api/notifications/me?status=unread",
            token="token_sv", tests="""
pm.test("có thông báo hoàn thành", () => pm.expect(pm.response.json().items.some(n => n.type === "order_completed")).to.be.true);"""),
        req("15. Sinh viên đánh giá", "POST", "review", "/api/reviews", token="token_sv",
            body={"order_id": "{{order_id}}", "rating": 5, "comment": "Ngon, giao nhanh"},
            tests='pm.test("201", () => pm.response.to.have.status(201));'),
        req("16. Điểm trung bình quán", "GET", "review", "/api/reviews/restaurant/{{restaurant_id}}/summary",
            tests='pm.test("có điểm", () => pm.expect(pm.response.json().count).to.be.above(0));'),
        req("17. Admin thống kê", "GET", "order", "/api/admin/orders/stats", token="token_admin",
            tests='pm.test("200", () => pm.response.to.have.status(200));'),
        req("18. Không có token -> 401", "GET", "order", "/api/orders/me", tests="""
pm.test("401", () => pm.response.to.have.status(401));
pm.test("mã lỗi", () => pm.expect(pm.response.json().code).to.eql("UNAUTHORIZED"));"""),
    ]
    return {"name": "0. Luồng demo", "item": items}


def otp_flow() -> dict:
    """Xác nhận email bằng OTP (Unit 20) + đăng nhập form OAuth2 (Unit 18). Cần hệ thống chạy với OTP_ENABLED=true và
    biến email_api_key (giá trị EMAIL_API_KEY trong .env) để đọc hộp thư MockMail. Mã chỉ lưu vào biến, không in ra."""
    reg = """
pm.test("201", () => pm.response.to.have.status(201));
const u = pm.response.json();
pm.test("chưa xác nhận, đã gửi mã", () => { pm.expect(u.verification_required).to.be.true;
  pm.expect(u.otp_sent).to.be.true; pm.expect(u.email_verified_at).to.be.null; });
pm.collectionVariables.set("otp_user_id", u.id);"""
    read_code = """
pm.test("200", () => pm.response.to.have.status(200));
const it = pm.response.json().items[0];
pm.test("có thư mã xác nhận", () => pm.expect(it).to.be.ok);
const m = /\\b(\\d{6})\\b/.exec(it.content);
pm.test("thư có mã 6 số", () => pm.expect(m).to.be.ok);
const code = m[1];                      // không console.log mã
pm.collectionVariables.set("otp_code", code);
pm.collectionVariables.set("otp_wrong", code === "000000" ? "111111" : "000000");"""
    token_form = req("8. Đăng nhập form OAuth2 (username = email) - Unit 18", "POST", "auth", "/api/users/token", tests="""
pm.test("200", () => pm.response.to.have.status(200));
pm.test("có access_token", () => pm.expect(pm.response.json().access_token).to.be.a("string"));""")
    token_form["request"]["body"] = {"mode": "urlencoded", "urlencoded": [
        {"key": "username", "value": "{{otp_email}}"}, {"key": "password", "value": "{{demo_password}}"}]}
    items = [
        req("1. Đăng ký sinh viên mới (email ngẫu nhiên)", "POST", "auth", "/api/users/register",
            body={"name": "Sinh Viên OTP", "email": "{{otp_email}}", "password": "{{demo_password}}",
                  "role": "sinh_vien", "accept_terms": True},
            prerequest='pm.collectionVariables.set("otp_email", "sv.otp." + pm.variables.replaceIn("{{$guid}}").slice(0, 8) + "@demo.tdtu.vn");',
            tests=reg),
        req("2. Đăng nhập khi chưa xác nhận -> 403 EMAIL_NOT_VERIFIED", "POST", "auth", "/api/users/login",
            body={"email": "{{otp_email}}", "password": "{{demo_password}}"}, tests="""
pm.test("403", () => pm.response.to.have.status(403));
pm.test("EMAIL_NOT_VERIFIED", () => pm.expect(pm.response.json().code).to.eql("EMAIL_NOT_VERIFIED"));"""),
        req("3. Đọc mã trong hộp thư MockMail", "GET", "mock_email", "/api/emails?to={{otp_email}}&limit=1",
            headers={"X-API-Key": "{{email_api_key}}"}, tests=read_code),
        req("4. Nhập sai mã -> 400 OTP_INVALID", "POST", "auth", "/api/users/verify-otp",
            body={"email": "{{otp_email}}", "code": "{{otp_wrong}}"}, tests="""
pm.test("400", () => pm.response.to.have.status(400));
pm.test("OTP_INVALID + số lần còn lại", () => { const j = pm.response.json();
  pm.expect(j.code).to.eql("OTP_INVALID"); pm.expect(j.remaining_attempts).to.be.a("number"); });"""),
        req("5. Nhập đúng mã -> 200, nhận token", "POST", "auth", "/api/users/verify-otp",
            body={"email": "{{otp_email}}", "code": "{{otp_code}}"}, tests="""
pm.test("200", () => pm.response.to.have.status(200));
pm.test("đã xác nhận", () => pm.expect(pm.response.json().user.email_verified_at).to.be.a("string"));"""),
        req("6. Nhập lại mã -> 409 ALREADY_VERIFIED", "POST", "auth", "/api/users/verify-otp",
            body={"email": "{{otp_email}}", "code": "{{otp_code}}"}, tests="""
pm.test("409 ALREADY_VERIFIED", () => { pm.response.to.have.status(409);
  pm.expect(pm.response.json().code).to.eql("ALREADY_VERIFIED"); });"""),
        req("7. Gửi lại mã khi đã xác nhận -> 202, không gửi", "POST", "auth", "/api/users/resend-otp",
            body={"email": "{{otp_email}}"}, tests="""
pm.test("202", () => pm.response.to.have.status(202));
pm.test("không gửi thư", () => pm.expect(pm.response.json().otp_sent).to.be.false);"""),
        token_form,
        req("9. Không có token -> 401 + WWW-Authenticate: Bearer", "GET", "auth", "/api/users/me", tests="""
pm.test("401", () => pm.response.to.have.status(401));
pm.test("WWW-Authenticate", () => pm.expect(pm.response.headers.get("WWW-Authenticate")).to.eql("Bearer"));"""),
        req("10. Đăng nhập admin", "POST", "auth", "/api/users/login",
            body={"email": "{{admin_email}}", "password": "{{admin_password}}"}, tests="""
pm.test("200", () => pm.response.to.have.status(200));
pm.collectionVariables.set("token_admin", pm.response.json().access_token);"""),
        req("11. Admin xem nhật ký email (không có mã OTP)", "GET", "notification",
            "/api/admin/email-logs?user_id={{otp_user_id}}", token="token_admin", tests="""
pm.test("200", () => pm.response.to.have.status(200));
const items = pm.response.json().items;
pm.test("có thư mã xác nhận đã gửi", () => { pm.expect(items.length).to.be.above(0);
  pm.expect(["sent", "delivered"]).to.include(items[0].status); });
pm.test("không lộ mã", () => pm.expect(JSON.stringify(items)).to.not.include(pm.collectionVariables.get("otp_code")));"""),
    ]
    return {"name": "OTP. Xác nhận email (Unit 20) + OAuth2 (Unit 18)",
            "description": "Cần OTP_ENABLED=true và biến môi trường email_api_key (= EMAIL_API_KEY trong .env).",
            "item": items}


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
                token, prerequest = token_for(path, op.get("tags", [])), None
                if path == "/internal/webhooks/email-status":     # webhook ký HMAC, không dùng X-Internal-Key
                    headers, prerequest = {}, 'pm.request.headers.upsert({key: "X-Webhook-Signature", value: "sha256=" + CryptoJS.HmacSHA256(pm.request.body.raw, pm.environment.get("email_webhook_secret") || "").toString()});'
                if svc == "mock_email":                          # nhà cung cấp email: khóa API riêng, không Bearer
                    token = None
                    headers = {"X-API-Key": "{{email_api_key}}"} if path != "/health" else None
                    if path == "/api/send":
                        headers["Idempotency-Key"] = "{{$guid}}"
                items.append(req(f"{method.upper()} {path} – {op.get('summary', '')}", method.upper(), svc, p,
                                 token=token, body=body, headers=headers, prerequest=prerequest))
        folders.append({"name": f"{SERVICES.index(svc) + 1}. {spec['info']['title']}", "item": items})
    return folders


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    collection = {
        "info": {"name": "TDTU Food Booking", "description": "Sinh từ OpenAPI bằng scripts/build_postman.py",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [demo_flow(), otp_flow(), *service_folders()],
        "variable": [{"key": k, "value": ""} for k in ("token_sv", "token_owner", "token_admin", "restaurant_id",
                                                       "item_id", "item_price", "order_id", "checkout_key", "user_id",
                                                       "notification_id", "review_id", "otp_email", "otp_user_id",
                                                       "otp_code", "otp_wrong")],
    }
    env = {"name": "TDTU Food Booking - local", "values": [
        {"key": k, "value": v, "enabled": True} for k, v in {
            "auth_url": "http://127.0.0.1:8001", "restaurant_url": "http://127.0.0.1:8002",
            "order_url": "http://127.0.0.1:8003", "notification_url": "http://127.0.0.1:8004",
            "review_url": "http://127.0.0.1:8005", "mock_email_url": "http://127.0.0.1:9000",
            "sv_email": "sv1@demo.tdtu.vn", "owner_email": "chuquan1@demo.tdtu.vn",
            "admin_email": "admin@demo.tdtu.vn", "demo_password": "Demo@123", "admin_password": "Admin@123",
            "internal_key": "", "email_api_key": "", "email_webhook_secret": ""}.items()]}
    (OUT / "TDTU_FoodBooking.postman_collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "TDTU_FoodBooking.local.postman_environment.json").write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Đã tạo", OUT)


if __name__ == "__main__":
    main()
