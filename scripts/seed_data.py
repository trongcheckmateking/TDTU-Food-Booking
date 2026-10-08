"""Dữ liệu demo (giả) cho cả 5 service, nạp QUA REST API của hệ thống đang chạy.

Vì mỗi service dùng ngôn ngữ và CSDL riêng (SQLite, H2, PostgreSQL), seed không ghi thẳng vào DB của service khác:
mọi bản ghi đi qua đúng API công khai (đăng ký, tạo quán, duyệt, giỏ hàng, checkout, đổi trạng thái, đánh giá),
nên dữ liệu demo cũng chính là một lần chạy thử luồng nghiệp vụ. Ngoại lệ duy nhất: tài khoản admin demo được tạo
bằng công cụ quản trị của Auth (không có API đăng ký admin).

Chạy lại không tạo trùng: tài khoản/quán/món đã có được giữ nguyên; đơn demo chỉ tạo khi sinh viên demo chưa có đơn.
"""
from __future__ import annotations

import requests

from common import config

DEMO_PASSWORD = "Demo@123"
ADMIN_PASSWORD = "Admin@123"
ADMIN = ("admin@demo.tdtu.vn", "Quản trị viên Demo")
USERS = [  # email, họ tên, vai trò, số điện thoại
    ("chuquan1@demo.tdtu.vn", "Trần Thị Ba", "chu_quan", "0901000011"),
    ("chuquan2@demo.tdtu.vn", "Lê Văn Hà", "chu_quan", "0901000012"),
    ("sv1@demo.tdtu.vn", "Nguyễn Văn An", "sinh_vien", "0901000021"),
    ("sv2@demo.tdtu.vn", "Phạm Thị Bình", "sinh_vien", "0901000022"),
    ("sv3.bikhoa@demo.tdtu.vn", "Võ Minh Khóa", "sinh_vien", None),     # bị admin khóa sau khi tạo
]
# khóa, chủ quán, tên, địa chỉ, mô tả, giờ mở, giờ đóng, trạng thái cuối
RESTAURANTS = [
    ("R1", "chuquan1", "Cơm Tấm Cô Ba", "19 Nguyễn Hữu Thọ, Tân Phong, Q7", "Cơm tấm sườn nướng than", "06:30", "21:00", "active"),
    ("R2", "chuquan2", "Bún Bò Huế O Hà", "Hẻm 15 Nguyễn Hữu Thọ, Q7", "Bún bò chuẩn vị Huế", "06:00", "14:00", "active"),
    ("R3", "chuquan1", "Trà Sữa Mây", "Cổng B TDTU, Q7", "Trà sữa, trà trái cây", "09:00", "22:00", "pending"),
    ("R4", "chuquan2", "Bánh Mì 24h", "Ký túc xá TDTU, Q7", "Bánh mì các loại", "00:00", "23:59", "closed"),
]
ITEMS = {  # quán -> [(tên, giá, mô tả, trạng thái)]
    "R1": [("Cơm tấm sườn bì chả", 35000, "Món đặc trưng", "available"), ("Cơm tấm sườn trứng", 32000, None, "available"),
           ("Canh chua cá lóc", 28000, None, "sold_out"), ("Trà đá", 3000, None, "available"),
           ("Món thử nghiệm (ẩn)", 50000, "Chỉ chủ quán thấy", "hidden")],
    "R2": [("Bún bò đặc biệt", 45000, "Giò, chả cua, bò viên", "available"), ("Bún bò thường", 35000, None, "available"),
           ("Nước sâm", 10000, None, "available")],
    "R3": [("Trà sữa trân châu", 30000, None, "available")],
    "R4": [("Bánh mì thịt", 20000, None, "available")],
}
# sinh viên, quán, [(món, số lượng)], trạng thái cuối, địa chỉ, đánh giá (sao, nhận xét) hoặc None
ORDERS = [
    ("sv1", "R1", [("Cơm tấm sườn bì chả", 2), ("Trà đá", 2)], "completed", "KTX TDTU, phòng B305", (5, "Sườn mềm, giao nhanh.")),
    ("sv2", "R1", [("Cơm tấm sườn trứng", 1)], "completed", "Thư viện TDTU", (4, "Ngon, hơi ít rau.")),
    ("sv1", "R1", [("Cơm tấm sườn bì chả", 1)], "cancelled", "KTX TDTU, phòng B305", None),
    ("sv2", "R2", [("Bún bò đặc biệt", 1)], "completed", "Nhà thi đấu TDTU", None),
    ("sv1", "R2", [("Bún bò đặc biệt", 1), ("Nước sâm", 1)], "confirmed", "Tòa A TDTU", None),
    ("sv2", "R2", [("Bún bò thường", 2)], "pending", "KTX TDTU, phòng C210", None),
]


class Api:
    def __init__(self):
        self.s = requests.Session()
        self.s.trust_env = False                    # gọi thẳng localhost, bỏ qua proxy hệ thống
        self.url = {n.lower(): config.service_url(n) for n in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW")}

    def call(self, method: str, svc: str, path: str, token: dict | None = None, ok=(200, 201, 204), **kw):
        r = self.s.request(method, self.url[svc] + path, headers=token or {}, timeout=30, **kw)
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {svc}{path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def login(self, email: str, password: str) -> dict:
        tok = self.call("POST", "auth", "/api/users/login", json={"email": email, "password": password})["access_token"]
        return {"Authorization": f"Bearer {tok}"}


def seed() -> dict:
    from services.auth.admin_tools import create_admin
    api = Api()
    counts = {"users": 0, "restaurants": 0, "menu_items": 0, "orders": 0, "reviews": 0}
    counts["users"] += create_admin(ADMIN[0], ADMIN[1], ADMIN_PASSWORD)
    admin = api.login(ADMIN[0], ADMIN_PASSWORD)

    tokens, ids = {}, {}
    for email, name, role, phone in USERS:
        body = {"name": name, "email": email, "password": DEMO_PASSWORD, "role": role}
        if phone:
            body["phone"] = phone
        r = api.s.post(api.url["auth"] + "/api/users/register", json=body, timeout=30)
        if r.status_code == 201:
            counts["users"] += 1
        elif r.status_code != 409:
            raise RuntimeError(f"Đăng ký {email}: {r.status_code} {r.text[:200]}")
        key = email.split("@")[0].split(".")[0]
        if email.startswith("sv3"):
            continue
        tokens[key] = api.login(email, DEMO_PASSWORD)
        ids[key] = api.call("GET", "auth", "/api/users/me", tokens[key])["id"]

    # quán + món (giữ nguyên nếu đã có theo tên)
    rid, menu = {}, {}
    for key, owner, name, addr, desc, op, cl, final in RESTAURANTS:
        mine = {r["name"]: r for r in api.call("GET", "restaurant", "/api/restaurants/mine", tokens[owner])}
        if name in mine:
            rid[key] = mine[name]["id"]
        else:
            r = api.call("POST", "restaurant", "/api/restaurants", tokens[owner],
                         json={"name": name, "address": addr, "description": desc, "open_time": op, "close_time": cl})
            rid[key] = r["id"]
            counts["restaurants"] += 1
        existing = {m["name"]: m for m in api.call("GET", "restaurant", f"/api/restaurants/{rid[key]}/menu",
                                                   tokens[owner], params={"all": "true"})}
        for iname, price, idesc, st in ITEMS[key]:
            if iname not in existing:
                existing[iname] = api.call("POST", "restaurant", f"/api/restaurants/{rid[key]}/menu", tokens[owner],
                                           json={"name": iname, "price": price, "description": idesc,
                                                 "status": "available"})
                counts["menu_items"] += 1
            menu[(key, iname)] = (existing[iname]["id"], st)
        if final in ("active", "closed"):
            api.call("PATCH", "restaurant", f"/api/admin/restaurants/{rid[key]}/status", admin, json={"status": "active"})

    # đơn demo: chỉ tạo khi sinh viên demo chưa có đơn nào
    owner_of = {r[0]: r[1] for r in RESTAURANTS}
    if all(api.call("GET", "order", "/api/orders/me", tokens[s])["total"] == 0 for s in ("sv1", "sv2")):
        for student, key, lines, final, addr, review in ORDERS:
            api.call("DELETE", "order", "/api/cart", tokens[student])
            for iname, qty in lines:
                api.call("POST", "order", "/api/cart/items", tokens[student],
                         json={"restaurant_id": rid[key], "item_id": menu[(key, iname)][0], "quantity": qty})
            o = api.call("POST", "order", "/api/orders/checkout", tokens[student], json={"delivery_address": addr})
            counts["orders"] += 1
            steps = {"pending": [], "confirmed": ["confirmed"], "completed": ["confirmed", "completed"],
                     "cancelled": ["cancelled"]}[final]
            for st in steps:
                actor = tokens[student] if st == "cancelled" else tokens[owner_of[key]]
                body = {"status": st, "reason": "Đổi ý, đặt nhầm món"} if st == "cancelled" else {"status": st}
                api.call("PATCH", "order", f"/api/orders/{o['id']}/status", actor, json=body)
            if review:
                api.call("POST", "review", "/api/reviews", tokens[student],
                         json={"order_id": o["id"], "rating": review[0], "comment": review[1]})
                counts["reviews"] += 1
        api.call("PATCH", "notification", "/api/notifications/me/read-all", tokens["sv2"])

    # trạng thái cuối của món và quán (sau khi đặt đơn demo, để đơn cũ vẫn hợp lệ)
    for (key, iname), (mid, st) in menu.items():
        if st != "available":
            api.call("PATCH", "restaurant", f"/api/menu-items/{mid}", tokens[owner_of[key]], json={"status": st})
    api.call("PATCH", "restaurant", f"/api/restaurants/{rid['R4']}", tokens["chuquan2"], json={"status": "closed"})

    # khóa tài khoản sv3
    page = api.call("GET", "auth", "/api/users", admin, params={"q": "sv3.bikhoa"})
    for u in page["items"]:
        if u["status"] != "locked":
            api.call("PATCH", "auth", f"/api/users/{u['id']}/status", admin, json={"status": "locked"})
    return counts
