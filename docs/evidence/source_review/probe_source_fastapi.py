"""Tái hiện điểm yếu của bản FastAPI nguồn (TDTU_FoodBooking_Code.zip). Chỉ dùng dữ liệu giả."""
import json, threading, uuid, datetime, requests, jwt

A, R, O, N, V = (f"http://127.0.0.1:{p}" for p in (8001, 8002, 8003, 8004, 8005))
out = []


def rec(name, reproduced, detail):
    out.append({"case": name, "reproduced": reproduced, "detail": detail})
    print(("TÁI HIỆN " if reproduced else "KHÔNG    ") + name + " :: " + detail)


def H(t): return {"Authorization": f"Bearer {t}"}


def acc(role, email=None, pw="123456"):
    email = email or f"{role}{uuid.uuid4().hex[:6]}@student.tdtu.edu.vn"
    requests.post(f"{A}/api/users/register", json={"name": "Test", "email": email, "password": pw, "role": role})
    r = requests.post(f"{A}/api/users/login", json={"email": email, "password": pw}).json()
    return r["access_token"], r["user"]

sv, svu = acc("sinh_vien"); cq, cqu = acc("chu_quan")
adm = requests.post(f"{A}/api/users/login", json={"email": "admin@tdtu.edu.vn", "password": "admin123"}).json()["access_token"]

# 1. JWT secret mặc định cố định
forged = jwt.encode({"sub": svu["id"], "role": "sinh_vien", "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)},
                    "tdtu-food-booking-secret", algorithm="HS256")
r = requests.get(f"{A}/api/users/me", headers=H(forged))
rec("JWT ký bằng secret mặc định trong mã được chấp nhận", r.status_code == 200, f"HTTP {r.status_code}")

# 2. Email khác hoa/thường tạo 2 tài khoản
base = f"Dup{uuid.uuid4().hex[:5]}@Student.TDTU.edu.vn"
r1 = requests.post(f"{A}/api/users/register", json={"name": "An A", "email": base, "password": "123456"})
r2 = requests.post(f"{A}/api/users/register", json={"name": "Bình B", "email": base.lower(), "password": "123456"})
rec("Email chỉ khác hoa/thường đăng ký được 2 lần", r1.status_code == 201 and r2.status_code == 201, f"HTTP {r1.status_code}/{r2.status_code}")

# 3. Mật khẩu Unicode > 72 byte
r = requests.post(f"{A}/api/users/register", json={"name": "Uyên", "email": f"u{uuid.uuid4().hex[:5]}@student.tdtu.edu.vn", "password": "ệ" * 30})
rec("Mật khẩu 30 ký tự 'ệ' (90 byte) gây lỗi 500", r.status_code == 500, f"HTTP {r.status_code}")

# 4. Quán + menu
rest = requests.post(f"{R}/api/restaurants", headers=H(cq), json={"name": "Quán Probe", "address": "19 Nguyễn Hữu Thọ, Q7"}).json()
it = requests.post(f"{R}/api/restaurants/{rest['id']}/menu", headers=H(cq), json={"name": "Cơm", "price": 30000}).json()
hid = requests.post(f"{R}/api/restaurants/{rest['id']}/menu", headers=H(cq), json={"name": "Món ẩn", "price": 1}).json()
requests.put(f"{R}/api/menu-items/{hid['id']}", headers=H(cq), json={"status": "hidden"})
r = requests.get(f"{R}/api/restaurants/{rest['id']}/menu?all=true")
rec("Khách không đăng nhập xem được món ẩn qua ?all=true", any(m["status"] == "hidden" for m in r.json()), f"{len(r.json())} món")
r = requests.post(f"{R}/api/restaurants/{rest['id']}/menu", headers={**H(cq), "Content-Type": "application/json"}, data='{"name": "Inf", "price": 1e309}')
rec("Giá vô hạn (1e309) được chấp nhận", r.status_code == 201, f"HTTP {r.status_code} {r.text[:80]}")
r = requests.post(f"{R}/api/restaurants/{rest['id']}/menu", headers=H(cq), json={"name": "   ", "price": 1})
rec("Tên món chỉ có khoảng trắng được chấp nhận", r.status_code == 201, f"HTTP {r.status_code}")

# 5. Quán bị khóa vẫn xem chi tiết công khai
requests.patch(f"{R}/api/admin/restaurants/{rest['id']}/status", headers=H(adm), json={"status": "locked"})
r = requests.get(f"{R}/api/restaurants/{rest['id']}")
rec("Quán bị khóa vẫn xem chi tiết công khai", r.status_code == 200, f"HTTP {r.status_code}")
requests.patch(f"{R}/api/admin/restaurants/{rest['id']}/status", headers=H(adm), json={"status": "active"})

# 6. Số lượng boolean
r = requests.post(f"{O}/api/orders", headers=H(sv), json={"restaurant_id": rest["id"], "delivery_address": "KTX TDTU",
                  "items": [{"item_id": it["id"], "quantity": True}]})
rec("quantity=true được hiểu là 1", r.status_code == 201, f"HTTP {r.status_code}")

# 7. item_name không được lưu
o = requests.post(f"{O}/api/orders", headers=H(sv), json={"restaurant_id": rest["id"], "delivery_address": "KTX TDTU",
                  "items": [{"item_id": it["id"], "quantity": 1}]}).json()
rec("order_items.item_name luôn null", all(i.get("item_name") is None for i in o["items"]), json.dumps(o["items"][0], ensure_ascii=False)[:90])

# 8. Admin được xác nhận đơn (mọi chuyển trạng thái)
r = requests.patch(f"{O}/api/orders/{o['id']}/status", headers=H(adm), json={"status": "confirmed"})
rec("Admin được chuyển pending→confirmed (không chỉ hủy)", r.status_code == 200, f"HTTP {r.status_code}")

# 9. Cập nhật trạng thái đồng thời
res = []
def go(st): res.append(requests.patch(f"{O}/api/orders/{o['id']}/status", headers=H(cq), json={"status": st}).status_code)
ts = [threading.Thread(target=go, args=(s,)) for s in ("completed", "cancelled")]
[t.start() for t in ts]; [t.join() for t in ts]
final = requests.get(f"{O}/api/orders/{o['id']}", headers=H(cq)).json()["status"]
rec("2 request đổi trạng thái đồng thời cùng thành công", res.count(200) == 2, f"mã {res}, trạng thái cuối {final}")

# 10. Notification event với quán không tồn tại -> 500
r = requests.post(f"{N}/api/notifications/events", headers={"X-Internal-Key": "tdtu-internal-key"},
                  json={"event": "order_created", "order_id": str(uuid.uuid4()), "user_id": svu["id"], "restaurant_id": str(uuid.uuid4())})
rec("Sự kiện notification với quán không tồn tại gây 500", r.status_code == 500, f"HTTP {r.status_code}")
r = requests.post(f"{N}/api/notifications/events", headers={"X-Internal-Key": "tdtu-internal-key"},
                  json={"event": "order_created", "order_id": o["id"], "user_id": svu["id"], "restaurant_id": rest["id"]})
r2 = requests.post(f"{N}/api/notifications/events", headers={"X-Internal-Key": "tdtu-internal-key"},
                   json={"event": "order_created", "order_id": o["id"], "user_id": svu["id"], "restaurant_id": rest["id"]})
rec("Gửi lại cùng sự kiện tạo thông báo trùng", r.status_code == 201 and r2.status_code == 201, f"HTTP {r.status_code}/{r2.status_code}")
rec("Khóa nội bộ mặc định 'tdtu-internal-key' dùng được", r.status_code == 201, "")

json.dump(out, open("/home/claude/final_work/evidence/probe_source_fastapi.json", "w"), ensure_ascii=False, indent=1)
