"""Kiểm tra ghép nối: gửi đúng các request mà code từng service gửi sang service khác."""
import json, uuid, socket, requests

A, R, V = "http://127.0.0.1:8001", "http://127.0.0.1:8002", "http://127.0.0.1:8005"
out = []


def log(tag, ok, msg):
    out.append((tag, ok, msg))
    print(("PASS " if ok else "FAIL ") + f"[{tag}] {msg}")


# ---- Chuẩn bị: tài khoản thật từ Auth
def acc(email, role):
    requests.post(f"{A}/api/users/register", json={"name": "Test", "email": email, "password": "123456", "role": role})
    r = requests.post(f"{A}/api/users/login", json={"email": email, "password": "123456"}).json()
    return r["access_token"], r["user"]

sv_tok, sv = acc(f"sv{uuid.uuid4().hex[:6]}@student.tdtu.edu.vn", "sinh_vien")
cq_tok, cq = acc(f"cq{uuid.uuid4().hex[:6]}@gmail.com", "chu_quan")
me = requests.get(f"{A}/api/users/me", headers={"Authorization": f"Bearer {sv_tok}"}).json()
print("Auth /api/users/me trả về:", json.dumps(me, ensure_ascii=False))

# ================= Restaurant Service =================
r = requests.post(f"{R}/api/restaurants", json={"owner_id": "ai-cung-duoc", "name": "Quán giả", "address": "x",
                  "open_time": "07:00", "close_time": "22:00", "image_url": "x", "status": "open"})
log("Restaurant", r.status_code != 201, f"Tạo quán KHÔNG cần token, owner_id tự khai: HTTP {r.status_code}")
fake = r.json()
d = requests.delete(f"{R}/api/restaurants/{fake['id']}")
log("Restaurant", d.status_code not in (200, 204), f"Xóa quán của người khác KHÔNG cần token: HTTP {d.status_code}")

# Chủ quán thật tạo quán (owner_id = UUID từ Auth) + món
rest = requests.post(f"{R}/api/restaurants", json={"owner_id": cq["id"], "name": "Cơm Tấm Test", "address": "Q7",
                     "open_time": "07:00", "close_time": "22:00", "image_url": "x", "status": "open"}).json()
item = requests.post(f"{R}/api/menu-items", json={"restaurant_id": rest["id"], "name": "Cơm sườn", "description": "x",
                     "image_url": "x", "status": "available", "price": 35000}).json()

# ================= Order -> Auth (RealAuthClient) =================
role_map = {"student": 1, "sinh_vien": 1, "user": 1, "owner": 1, "restaurant_owner": 1, "chu_quan": 1, "seller": 1, "admin": 1}
try:
    uuid.UUID(str(me["id"])); ok_id = True
except ValueError:
    ok_id = False
log("Order→Auth", ok_id and me["role"] in role_map, f"GET /api/users/me: id UUID={ok_id}, role '{me['role']}' Order hiểu được")

# ================= Order -> Restaurant (RealRestaurantClient) =================
g = requests.get(f"{R}/api/restaurants/{rest['id']}")
try:
    uuid.UUID(str(g.json()["owner_id"])); own_ok = True
except ValueError:
    own_ok = False
log("Order→Restaurant", g.status_code == 200 and own_ok and g.json()["status"] == "open",
    f"GET /api/restaurants/{{id}}: HTTP {g.status_code}, owner_id là UUID={own_ok}, status='{g.json()['status']}'")
sample = requests.get(f"{R}/api/restaurants").json()[0]
try:
    uuid.UUID(sample["owner_id"]); s_ok = True
except ValueError:
    s_ok = False
log("Order→Restaurant", s_ok, f"Quán mẫu trong restaurants.json có owner_id='{sample['owner_id']}' (Order sẽ trả 502 vì không phải UUID)")
m = requests.get(f"{R}/api/restaurants/{rest['id']}/menu-items/{item['id']}")
log("Order→Restaurant", m.status_code == 200,
    f"GET /api/restaurants/{{rid}}/menu-items/{{iid}} (Order gọi để lấy giá món): HTTP {m.status_code} {m.text[:60]}")
m2 = requests.get(f"{R}/api/menu-items/{item['id']}")
print(f"      (Restaurant thực tế có GET /api/menu-items/{{id}}: HTTP {m2.status_code})")

# ================= Order -> Notification (RealNotificationClient) =================
def port_open(p):
    s = socket.socket(); s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()
log("Order→Notification", False,
    "Order POST http://localhost:8004/api/notifications, nhưng Notification chạy cổng 8080, đường dẫn /notifications "
    "(sai cả cổng lẫn đường dẫn; Order chỉ ghi log WARN nên lỗi bị im lặng)")
log("Order→Notification", False,
    "Kể cả sửa đúng địa chỉ: bảng notifications có FK sang bảng users/orders riêng của Notification "
    "(chỉ có 1 user mẫu) → mọi thông báo cho user thật lỗi FK → HTTP 500 (đã thử trên PostgreSQL)")

# ================= Review -> Auth / Order (Call_Auth_Order.php) =================
rv = requests.post(f"{V}/api/reviews", headers={"Authorization": f"Bearer {sv_tok}"},
                   json={"order_id": 1, "rating": 5, "comment": "ngon"})
log("Review→Auth", rv.status_code == 201, f"POST /api/reviews với token thật: HTTP {rv.status_code} {rv.text}")
log("Review→Auth", "data" in me and isinstance(me.get("data", {}).get("id"), int),
    "Review đòi Auth trả {\"data\": {\"id\": <số nguyên>, \"role\": \"student\"}}, Auth thật trả "
    f"id='{me['id'][:8]}…' (UUID, không bọc data), role='{me['role']}'")
rv2 = requests.post(f"{V}/api/reviews", headers={"Authorization": f"Bearer {sv_tok}"},
                    json={"order_id": str(uuid.uuid4()), "rating": 5})
log("Review", rv2.status_code != 422, f"Gửi order_id dạng UUID (như Order thật sinh ra): HTTP {rv2.status_code} {rv2.text}")
rl = requests.get(f"{V}/api/reviews", params={"restaurant_id": rest["id"]})
log("Review", rl.status_code == 200, f"Xem đánh giá theo restaurant_id UUID của Restaurant: HTTP {rl.status_code} {rl.text}")

# ================= CORS cho trang admin.html (mở từ trình duyệt) =================
for name, url in [("Auth", A + "/"), ("Restaurant", R + "/api/restaurants"), ("Review", V + "/health")]:
    h = requests.get(url, headers={"Origin": "null"}).headers.get("Access-Control-Allow-Origin")
    log("CORS", bool(h), f"{name}: Access-Control-Allow-Origin = {h}")

print("\nTổng: %d PASS, %d FAIL" % (sum(o[1] for o in out), sum(not o[1] for o in out)))
json.dump(out, open("/home/claude/run/probe.json", "w"), ensure_ascii=False, indent=1)
