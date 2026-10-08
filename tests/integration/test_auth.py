"""Auth: đăng ký, đăng nhập, JWT, khóa tài khoản, vai trò, admin cuối cùng."""
import time
import uuid

import jwt

from services.auth.app import ISSUER
from tests.conftest import JWT_SECRET


def test_register_login_me_and_profile(system):
    t = system.tag
    u = system.register(f"An.Nguyen.{t.upper()}@Student.TDTU.edu.vn", name="  Nguyễn Văn An  ", phone="0901234567")
    assert u["email"] == f"an.nguyen.{t}@student.tdtu.edu.vn" and u["name"] == "Nguyễn Văn An" and u["status"] == "active"
    assert "password_hash" not in u
    h = system.login(f"AN.NGUYEN.{t}@student.tdtu.edu.vn")
    me = system.auth.get("/api/users/me", headers=h).json()
    assert me["id"] == u["id"] and me["role"] == "sinh_vien"
    r = system.auth.patch("/api/users/me", headers=h, json={"phone": "0912345678"})
    assert r.status_code == 200 and r.json()["phone"] == "0912345678"


def test_register_validation(system):
    base = {"name": "Người Dùng", "email": system.email("a@student.tdtu.edu.vn"), "password": "matkhau123"}
    cases = [
        {**base, "role": "admin"},                         # không tự đăng ký admin
        {**base, "status": "active"},                      # trường lạ bị chặn
        {**base, "name": "    "},                          # chỉ khoảng trắng
        {**base, "password": "ệ" * 25},                    # 75 byte > giới hạn bcrypt
        {**base, "password": "      "},
        {**base, "email": "khong-phai-email"},
        {**base, "phone": "123"},
    ]
    for body in cases:
        r = system.auth.post("/api/users/register", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["code"] == "VALIDATION_ERROR"
    ok = system.auth.post("/api/users/register", json={**base, "password": "ệ" * 24})    # đúng 72 byte
    assert ok.status_code == 201
    assert system.login(base["email"], "ệ" * 24)


def test_duplicate_email_case_insensitive(system):
    system.register(system.email("dup@student.tdtu.edu.vn"))
    r = system.auth.post("/api/users/register", json={"name": "Khác", "email": system.email("dup@student.tdtu.edu.vn").upper(),
                                                      "password": "matkhau123"})
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_EXISTS"


def test_login_errors(system):
    x = system.email("x@student.tdtu.edu.vn")
    system.register(x)
    for body in ({"email": x, "password": "sai"}, {"email": system.email("none@student.tdtu.edu.vn"), "password": "x"}):
        r = system.auth.post("/api/users/login", json=body)
        assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    assert system.auth.post("/api/users/login", json={"email": x, "password": "ệ" * 30}).status_code == 401


def _token(sub, **over):
    now = int(time.time())
    payload = {"sub": sub, "role": "sinh_vien", "ver": 0, "iss": ISSUER, "iat": now, "exp": now + 3600, **over}
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, JWT_SECRET, algorithm="HS256")


def test_jwt_rejections(system):
    u = system.register(system.email("j@student.tdtu.edu.vn"))
    sid = u["id"]
    cases = {
        "TOKEN_EXPIRED": _token(sid, exp=int(time.time()) - 10),
        "missing ver": _token(sid, ver=None),
        "wrong issuer": _token(sid, iss="khac"),
        "bad sub": _token("khong-phai-uuid"),
        "unknown user": _token(str(uuid.uuid4())),
        "wrong secret": jwt.encode({"sub": sid, "ver": 0, "iss": ISSUER, "iat": 1, "exp": 4102444800},
                                   "sai-secret-" + "z" * 32, algorithm="HS256"),
        "alg none": jwt.encode({"sub": sid, "ver": 0, "iss": ISSUER, "iat": 1, "exp": 4102444800}, None, algorithm="none"),
        "rác": "abc.def.ghi",
    }
    for name, tok in cases.items():
        r = system.auth.get("/api/users/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, name
    assert system.auth.get("/api/users/me").status_code == 401
    assert system.auth.get("/api/users/me", headers={"Authorization": f"Bearer {_token(sid)}"}).status_code == 200


def test_logout_revokes_tokens(system):
    h = system.user(system.email("lo@student.tdtu.edu.vn"))
    assert system.auth.post("/api/users/logout", headers=h).status_code == 204
    r = system.auth.get("/api/users/me", headers=h)
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOKED"


def test_lock_unlock_blocks_everywhere(world):
    s = world.s
    sv_id = s.auth.get("/api/users/me", headers=world.sv).json()["id"]
    assert s.auth.patch(f"/api/users/{sv_id}/status", headers=world.admin, json={"status": "locked"}).json()["status"] == "locked"
    # token cũ bị thu hồi ở mọi service
    assert s.auth.get("/api/users/me", headers=world.sv).status_code == 401
    assert s.order.get("/api/orders/me", headers=world.sv).status_code == 401
    r = s.auth.post("/api/users/login", json={"email": world.emails["sv"], "password": "matkhau123"})
    assert r.status_code == 403 and r.json()["code"] == "ACCOUNT_LOCKED"
    for svc, path in (("restaurant", "/api/restaurants/mine"), ("notification", "/api/notifications/me"),
                      ("review", "/api/reviews/me")):
        assert getattr(s, svc).get(path, headers=world.sv).status_code == 401, svc
    s.auth.patch(f"/api/users/{sv_id}/status", headers=world.admin, json={"status": "active"})
    assert s.login(world.emails["sv"])


def test_locked_user_existing_token_from_other_service_is_403_when_version_matches(world):
    """Khóa trực tiếp trong DB (không tăng token_version): Auth vẫn trả 403 ACCOUNT_LOCKED, 4 service còn lại
    (Node, Java, Go, PHP) chuyển tiếp đúng 403 ACCOUNT_LOCKED."""
    s = world.s
    conn = s.c.auth_db()
    conn.execute("UPDATE users SET status='locked' WHERE email=?", (world.emails["sv2"],))
    conn.close()
    for svc, path in (("order", "/api/orders/me"), ("restaurant", "/api/restaurants/mine"),
                      ("notification", "/api/notifications/me"), ("review", "/api/reviews/me")):
        r = getattr(s, svc).get(path, headers=world.sv2)
        assert r.status_code == 403 and r.json()["code"] == "ACCOUNT_LOCKED", (svc, r.text)


def test_admin_only_and_self_protection(world):
    s = world.s
    sv_id = s.auth.get("/api/users/me", headers=world.sv).json()["id"]
    assert s.auth.get(f"/api/users/{sv_id}", headers=world.admin).json()["email"] == world.emails["sv"]
    assert s.auth.get(f"/api/users/{sv_id}", headers=world.sv).status_code == 403
    assert s.auth.get(f"/api/users/{uuid.uuid4()}", headers=world.admin).status_code == 404
    assert s.auth.get("/api/users", headers=world.sv).status_code == 403
    page = s.auth.get("/api/users", headers=world.admin, params={"role": "chu_quan", "q": s.tag}).json()
    assert page["total"] == 2 and all(u["role"] == "chu_quan" for u in page["items"])
    me = s.auth.get("/api/users/me", headers=world.admin).json()
    assert s.auth.patch(f"/api/users/{me['id']}/status", headers=world.admin, json={"status": "locked"}).status_code == 400
    assert s.auth.patch(f"/api/users/{me['id']}/role", headers=world.admin, json={"role": "sinh_vien"}).status_code == 400


import pytest


@pytest.mark.parametrize("action", [{"path": "status", "body": {"status": "locked"}},
                                    {"path": "role", "body": {"role": "sinh_vien"}}], ids=["lock", "demote"])
def test_last_admin_never_lost_under_concurrency(world, action):
    """2 admin khóa/hạ nhau cùng lúc: giao dịch BEGIN IMMEDIATE + kiểm tra số admin trong giao dịch
    đảm bảo luôn còn ít nhất 1 admin hoạt động (request thua trả 409 LAST_ADMIN hoặc 401 do token bị thu hồi).
    Các admin do test khác tạo được tạm khóa trong DB để chỉ còn đúng 2 admin hoạt động, khôi phục sau test."""
    import threading
    s = world.s
    conn = s.c.auth_db()
    a_email = s.email("admin@test.tdtu.vn")
    others = [r[0] for r in conn.execute("SELECT id FROM users WHERE role='admin' AND status='active' AND email<>?",
                                         (a_email,))]
    conn.executemany("UPDATE users SET status='locked' WHERE id=?", [(i,) for i in others])
    conn.close()
    _active_admins = lambda c: c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'").fetchone()[0]
    try:
        a = s.login(a_email)
        email_b = f"b{uuid.uuid4().hex[:6]}@test.tdtu.vn"
        b = s.admin(email_b)
        a_id = s.auth.get("/api/users/me", headers=a).json()["id"]
        b_id = s.auth.get("/api/users/me", headers=b).json()["id"]
        codes = []
        def go(actor, target):
            r = s.auth.patch(f"/api/users/{target}/{action['path']}", headers=actor, json=action["body"])
            codes.append((r.status_code, r.json().get("code")))
        ts = [threading.Thread(target=go, args=(a, b_id)), threading.Thread(target=go, args=(b, a_id))]
        [t.start() for t in ts]; [t.join() for t in ts]
        conn = s.c.auth_db()
        assert _active_admins(conn) >= 1, codes
        conn.close()
        assert sum(c == 200 for c, _ in codes) <= 1, codes
    finally:
        conn = s.c.auth_db()           # khôi phục admin gốc và các admin của test khác
        conn.execute("UPDATE users SET role='admin', status='active' WHERE email=?", (a_email,))
        conn.executemany("UPDATE users SET status='active' WHERE id=?", [(i,) for i in others])
        conn.close()


def test_self_action_blocked(world):
    s = world.s
    me = s.auth.get("/api/users/me", headers=world.admin).json()["id"]
    for path, body in (("status", {"status": "locked"}), ("role", {"role": "chu_quan"})):
        r = s.auth.patch(f"/api/users/{me}/{path}", headers=world.admin, json=body)
        assert r.status_code == 400 and r.json()["code"] == "SELF_ACTION"


def test_demote_owner_with_restaurants_blocked(world):
    s = world.s
    owner_id = s.auth.get("/api/users/me", headers=world.owner).json()["id"]
    r = s.auth.patch(f"/api/users/{owner_id}/role", headers=world.admin, json={"role": "sinh_vien"})
    assert r.status_code == 409 and r.json()["code"] == "OWNER_HAS_RESTAURANTS"
    owner2_id = s.auth.get("/api/users/me", headers=world.owner2).json()["id"]
    assert s.auth.patch(f"/api/users/{owner2_id}/role", headers=world.admin, json={"role": "sinh_vien"}).status_code == 200
    s.fault("restaurant", "down")
    sv_id = s.auth.get("/api/users/me", headers=s.login(world.emails["owner2"])).json()["id"]
    assert s.auth.patch(f"/api/users/{sv_id}/role", headers=world.admin, json={"role": "chu_quan"}).status_code == 200
    r = s.auth.patch(f"/api/users/{sv_id}/role", headers=world.admin, json={"role": "sinh_vien"})
    assert r.status_code == 503 and r.json()["code"] == "UPSTREAM_UNAVAILABLE"
