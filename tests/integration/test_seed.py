"""Dữ liệu demo (`python manage.py seed`) nạp qua REST API nên phải luôn khớp quy tắc nghiệp vụ hiện tại
(ví dụ: sinh viên không tự hủy đơn, admin hủy giúp; đơn phải thanh toán trước). Chạy seed trên 5 service thật."""
from tests.conftest import SERVICES


def test_seed_demo_data_follows_business_rules(cluster, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(cluster.data))                 # admin demo tạo thẳng trong auth.db của cụm test
    for s in SERVICES:
        monkeypatch.setenv(f"{s.upper()}_URL", cluster.url[s])
    from scripts.seed_data import seed
    counts = seed()
    assert counts == {"users": 6, "restaurants": 4, "menu_items": 10, "orders": 7, "reviews": 2}, counts
    import requests
    s = requests.Session()
    s.trust_env = False
    tok = s.post(cluster.url["auth"] + "/api/users/login", json={"email": "admin@demo.tdtu.vn", "password": "Admin@123"}).json()
    h = {"Authorization": "Bearer " + tok["access_token"]}
    cancelled = s.get(cluster.url["order"] + "/api/admin/orders", headers=h, params={"status": "cancelled"}).json()["items"]
    demo = [o for o in cancelled if o["cancel_reason"] == "Sinh viên nhờ hủy: đặt nhầm món"]
    assert demo and all(o["cancelled_by"] == "admin" and o["payment"]["status"] == "refund_due" for o in demo)
    every = s.get(cluster.url["order"] + "/api/admin/orders", headers=h, params={"page_size": 100}).json()["items"]
    pays = [o["payment"]["status"] for o in every if o["restaurant_name"] in ("Cơm Tấm Cô Ba", "Bún Bò Huế O Hà")]
    assert pays.count("claimed") == 1 and "unpaid" not in pays          # 1 đơn chờ quán xác nhận tiền (tab Chờ tiền)
    owner = s.post(cluster.url["auth"] + "/api/users/login", json={"email": "chuquan1@demo.tdtu.vn", "password": "Demo@123"})
    assert owner.json()["user"]["bank_holder"] == "TAI KHOAN DEMO"
    assert all(len(o["pickup_code"]) == 3 for o in s.get(cluster.url["order"] + "/api/admin/orders", headers=h).json()["items"])
    assert seed()["orders"] == 0                                        # chạy lại không tạo trùng
