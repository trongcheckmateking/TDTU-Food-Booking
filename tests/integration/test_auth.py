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
    base = {"name": "Người Dùng", "email": system.email("a@student.tdtu.edu.vn"), "password": "matkhau123",
            "accept_terms": True}
    without_terms = {k: v for k, v in base.items() if k != "accept_terms"}
    cases = [
        {**base, "role": "admin"},                         # không tự đăng ký admin
        {**base, "status": "active"},                      # trường lạ bị chặn
        {**base, "name": "    "},                          # chỉ khoảng trắng
        {**base, "password": "ệ" * 24 + "1"},              # 73 byte > giới hạn bcrypt
        {**base, "password": "        "},
        {**base, "password": "abc123"},                    # dưới 8 ký tự
        {**base, "password": "chiconchu"},                 # không có số
        {**base, "password": "12345678"},                  # không có chữ
        {**base, "email": "khong-phai-email"},
        {**base, "phone": "123"},
        without_terms,                                      # chưa đồng ý điều khoản
        {**base, "accept_terms": False},
        {**base, "accept_terms": "true"},                  # phải là boolean JSON
    ]
    for body in cases:
        r = system.auth.post("/api/users/register", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["code"] == "VALIDATION_ERROR"
    pw72 = "ệ" * 23 + "123"                                                            # đúng 72 byte
    ok = system.auth.post("/api/users/register", json={**base, "password": pw72})
    assert ok.status_code == 201
    assert system.login(base["email"], pw72)


def test_duplicate_email_case_insensitive(system):
    system.register(system.email("dup@student.tdtu.edu.vn"))
    r = system.auth.post("/api/users/register", json={"name": "Khác", "email": system.email("dup@student.tdtu.edu.vn").upper(),
                                                      "password": "matkhau123", "accept_terms": True})
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_EXISTS"


def test_login_errors(system):
    x = system.email("x@student.tdtu.edu.vn")
    system.register(x)
    for body in ({"email": x, "password": "sai"}, {"email": system.email("none@student.tdtu.edu.vn"), "password": "x"}):
        r = system.auth.post("/api/users/login", json=body)
        assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    assert system.auth.post("/api/users/login", json={"email": x, "password": "ệ" * 30}).status_code == 401


def test_login_lockout_after_repeated_failures(system):
    y, z = system.email("lock.y@student.tdtu.edu.vn"), system.email("lock.z@student.tdtu.edu.vn")
    system.register(y)
    system.register(z)
    for _ in range(5):                                    # 5 lần sai liên tiếp
        r = system.auth.post("/api/users/login", json={"email": y, "password": "sai12345"})
        assert r.status_code == 401
    r = system.auth.post("/api/users/login", json={"email": y, "password": "matkhau123"})
    assert r.status_code == 429 and r.json()["code"] == "TOO_MANY_ATTEMPTS", "đúng mật khẩu cũng phải chờ"
    assert int(r.headers["Retry-After"]) > 0
    assert system.login(z)                                # tài khoản khác không bị ảnh hưởng
    # đăng nhập đúng xóa bộ đếm: 4 lần sai, đúng 1 lần, rồi 4 lần sai nữa vẫn chưa bị khóa
    for _ in range(4):
        assert system.auth.post("/api/users/login", json={"email": z, "password": "sai12345"}).status_code == 401
    assert system.login(z)
    for _ in range(4):
        assert system.auth.post("/api/users/login", json={"email": z, "password": "sai12345"}).status_code == 401
    assert system.login(z)
    # email không tồn tại cũng bị đếm (không lộ email nào có tài khoản)
    ghost = system.email("ghost@student.tdtu.edu.vn")
    codes = [system.auth.post("/api/users/login", json={"email": ghost, "password": "x"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_login_lockout_holds_under_parallel_guesses(system):
    """30 lần đoán gửi cùng lúc: lần thử được giữ chỗ trước khi kiểm tra mật khẩu nên chỉ đúng 5 lần được thử."""
    from concurrent.futures import ThreadPoolExecutor

    import requests
    v = system.email("lock.par@student.tdtu.edu.vn")
    system.register(v)
    url = system.c.url["auth"] + "/api/users/login"

    def guess(_):
        with requests.Session() as s:
            s.trust_env = False
            return s.post(url, json={"email": v, "password": "sai12345"}, timeout=60).status_code

    with ThreadPoolExecutor(30) as ex:
        codes = list(ex.map(guess, range(30)))
    assert codes.count(401) == 5 and codes.count(429) == 25, codes


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


PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000040000000308020000003b963991000000104944415478"
                    "9c6310f5980b470c383900de4b0bb9545d06570000000049454e44ae426082")


def test_avatar_upload_replace_serve_and_remove(system):
    h = system.user(system.email("avatar@student.tdtu.edu.vn"))
    up = lambda data, ctype="image/png": system.auth.request("PUT", "/api/users/me/avatar",
                                                             headers={**h, "Content-Type": ctype}, content=data)
    assert system.auth.request("PUT", "/api/users/me/avatar", content=PNG,
                               headers={"Content-Type": "image/png"}).status_code == 401
    assert up(b"<svg onload=alert(1)>", "image/png").json()["code"] == "UNSUPPORTED_MEDIA_TYPE"   # kiểm tra theo nội dung
    assert up(PNG + b"0" * (1024 * 1024)).status_code == 413
    first = up(PNG).json()["avatar_url"]
    assert first.startswith("/avatars/") and first.endswith(".png")
    got = system.auth.get(first)
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png" and got.headers["x-content-type-options"] == "nosniff"
    second = up(PNG).json()["avatar_url"]
    assert second != first and system.auth.get(first).status_code == 404                     # ảnh cũ bị xóa
    assert system.auth.get("/api/users/me", headers=h).json()["avatar_url"] == second
    assert system.auth.get("/avatars/..%2Fauth.db").status_code == 404
    assert system.auth.delete("/api/users/me/avatar", headers=h).json()["avatar_url"] is None
    assert system.auth.get(second).status_code == 404


def test_change_password_revokes_other_sessions(system):
    email = system.email("doimk@student.tdtu.edu.vn")
    h = system.user(email)
    other = system.login(email)                                                                # thiết bị thứ 2
    change = lambda cur, new: system.auth.post("/api/users/me/password", headers=h,
                                               json={"current_password": cur, "new_password": new})
    assert change("sai12345", "matkhau456").json()["code"] == "WRONG_PASSWORD"
    assert change("matkhau123", "chiconchu").status_code == 422                                 # thiếu số
    assert change("matkhau123", "matkhau123").json()["code"] == "SAME_PASSWORD"
    r = change("matkhau123", "matkhau456")
    assert r.status_code == 200, r.text
    assert system.auth.get("/api/users/me", headers=other).status_code == 401                 # phiên khác bị thu hồi
    assert system.auth.get("/api/users/me", headers={"Authorization": "Bearer " + r.json()["access_token"]}).status_code == 200
    assert system.auth.post("/api/users/login", json={"email": email, "password": "matkhau123"}).status_code == 401
    assert system.login(email, "matkhau456")


def test_owner_registers_with_payout_account(system):
    """Chủ quán phải khai báo ngân hàng + số tài khoản + tên chủ tài khoản: mã VietQR của quán tạo từ đó."""
    banks = system.auth.get("/api/banks").json()
    assert {"bin": "970436", "code": "VCB", "name": "Vietcombank"} in banks and len({b["bin"] for b in banks}) == len(banks)
    base = {"name": "Chủ Quán", "email": system.email("cq@test.tdtu.vn"), "password": "matkhau123", "role": "chu_quan",
            "accept_terms": True}
    bank = {"bank_bin": "970436", "bank_account": "0071000123456", "bank_holder": "  Trần   Thị Bé "}
    for body, field in (({**base}, "bank_bin"), ({**base, **bank, "bank_bin": "999999"}, "bank_bin"),
                        ({**base, **bank, "bank_account": "12a456"}, "bank_account"),
                        ({**base, **bank, "bank_account": "12345"}, "bank_account"),
                        ({**base, **bank, "bank_holder": "Trần 3"}, "bank_holder"),
                        ({**base, **bank, "role": "sinh_vien"}, "bank_bin")):        # sinh viên không khai báo
        r = system.auth.post("/api/users/register", json=body)
        assert r.status_code == 422 and field in {e["field"] for e in r.json()["errors"]}, (body, r.text)
    u = system.auth.post("/api/users/register", json={**base, **bank}).json()
    assert (u["bank_bin"], u["bank_name"], u["bank_account"], u["bank_holder"]) == (
        "970436", "Vietcombank", "0071000123456", "TRAN THI BE")
    sv = system.register(system.email("svbank@student.tdtu.edu.vn"))
    assert sv["bank_account"] is None and sv["bank_name"] is None


def test_payout_change_needs_password_and_internal_lookup_needs_key(system):
    from tests.conftest import INTERNAL
    email = system.email("cq2@test.tdtu.vn")
    h = system.user(email, "chu_quan")
    uid = system.auth.get("/api/users/me", headers=h).json()["id"]
    new = {"bank_bin": "970422", "bank_account": "0123456789", "bank_holder": "Nguyễn Đạt"}
    r = system.auth.put("/api/users/me/payout", headers=h, json={**new, "password": "sai12345"})
    assert r.status_code == 400 and r.json()["code"] == "WRONG_PASSWORD"
    assert system.auth.put("/api/users/me/payout", headers=h, json=new).status_code == 422
    r = system.auth.put("/api/users/me/payout", headers=h, json={**new, "password": "matkhau123"})
    assert r.status_code == 200 and r.json()["bank_holder"] == "NGUYEN DAT"
    sv = system.user(system.email("svpay@student.tdtu.edu.vn"))
    assert system.auth.put("/api/users/me/payout", headers=sv, json={**new, "password": "matkhau123"}).status_code == 403
    assert system.auth.get(f"/internal/users/{uid}/payout").status_code == 403
    got = system.auth.get(f"/internal/users/{uid}/payout", headers=INTERNAL).json()
    assert got == {"user_id": uid, "bank_bin": "970422", "bank_name": "MB Bank", "bank_account": "0123456789",
                   "bank_holder": "NGUYEN DAT"}
    sv_id = system.auth.get("/api/users/me", headers=sv).json()["id"]
    r = system.auth.get(f"/internal/users/{sv_id}/payout", headers=INTERNAL)
    assert r.status_code == 404 and r.json()["code"] == "PAYOUT_MISSING"


# ------------------------------------------------------------------ xác nhận email bằng mã OTP (Unit 20)
# Auth bật OTP chạy riêng (fixture otp_auth); gửi mã qua Notification THẬT -> mock provider THẬT.
# Không dùng time.sleep để chờ hết hạn / hết thời gian chờ gửi lại: sửa expires_at / created_at trong DB.
PW = "matkhau123"


def otp_register(system, otp_auth, local="sv.otp@student.tdtu.edu.vn", **kw):
    email = system.email(local)
    body = {"name": "Sinh Viên OTP", "email": email, "password": PW, "accept_terms": True, **kw}
    r = otp_auth.client.post("/api/users/register", json=body)
    assert r.status_code == 201, r.text
    return email, r.json()


def otp_login(otp_auth, email, pw=PW):
    return otp_auth.client.post("/api/users/login", json={"email": email, "password": pw})


def verify(otp_auth, email, code):
    return otp_auth.client.post("/api/users/verify-otp", json={"email": email, "code": code})


def resend(otp_auth, email):
    return otp_auth.client.post("/api/users/resend-otp", json={"email": email})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10 ** 6:06d}"


def age_codes(otp_auth, email, seconds: int):
    """Lùi created_at mọi mã của user `seconds` giây (giả lập thời gian trôi qua)."""
    conn = otp_auth.db()
    conn.execute("UPDATE otp_codes SET created_at = strftime('%Y-%m-%dT%H:%M:%SZ', created_at, ?) "
                 "WHERE user_id = (SELECT id FROM users WHERE email=?)", (f"-{seconds} seconds", email))
    conn.close()


def otp_rows(otp_auth, email):
    conn = otp_auth.db()
    rows = [dict(r) for r in conn.execute("SELECT o.* FROM otp_codes o JOIN users u ON u.id=o.user_id WHERE u.email=? "
                                          "ORDER BY o.created_at", (email,))]
    conn.close()
    return rows


def otp_admin(otp_auth, system, verified=False):
    """Admin trong DB của Auth bật OTP (giống create-admin), mặc định email_verified_at = NULL."""
    import bcrypt
    email = system.email("admin.otp@test.tdtu.vn")
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = otp_auth.db()
    conn.execute("INSERT INTO users (id,name,email,password_hash,role,status,token_version,created_at,updated_at,"
                 "email_verified_at) VALUES (?,?,?,?, 'admin', 'active', 0, ?, ?, ?)",
                 (str(uuid.uuid4()), "Admin OTP", email, bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)).decode(), ts, ts,
                  ts if verified else None))
    conn.close()
    return email


def test_otp_register_sends_code_and_blocks_login(system, otp_auth):
    email, u = otp_register(system, otp_auth)
    assert (u["verification_required"], u["otp_sent"], u["resend_after"], u["email_verified_at"]) == (True, True, 60, None)
    assert "password_hash" not in u
    mails = system.emails(email)
    assert len(mails) == 1 and mails[0]["subject"] == "TDTU Food - Mã xác nhận email" and mails[0]["tag"] == "otp"
    assert "5 phút" in mails[0]["content"]
    r = otp_login(otp_auth, email)
    assert r.status_code == 403 and r.json()["code"] == "EMAIL_NOT_VERIFIED" and r.json()["email"] == email, r.text
    r = otp_login(otp_auth, email, "saimatkhau9")                    # sai mật khẩu: không lộ tình trạng xác nhận
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    # provider báo đã giao thư qua webhook có ký HMAC -> email_logs chuyển delivered
    admin = system.admin()
    status = None
    for _ in range(50):
        logs = system.notification.get("/api/admin/email-logs", headers=admin, params={"user_id": u["id"]}).json()
        status = logs["items"][0]["status"] if logs["items"] else None
        if status == "delivered":
            break
        time.sleep(0.1)
    assert status == "delivered", logs


def test_otp_verify_returns_token_only_once(system, otp_auth):
    email, u = otp_register(system, otp_auth)
    code = system.read_otp(email)
    for bad in ({"email": email, "code": "12345"}, {"email": email, "code": 123456}, {"email": email, "code": "12a456"},
                {"email": email, "code": code, "x": 1}, {"email": "khong-phai-email", "code": code}):
        assert otp_auth.client.post("/api/users/verify-otp", json=bad).status_code == 422, bad
    r = verify(otp_auth, email.upper(), code)                           # email không phân biệt hoa thường
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["token_type"] == "bearer" and tok["access_token"] and tok["user"]["id"] == u["id"]
    me = otp_auth.client.get("/api/users/me", headers={"Authorization": "Bearer " + tok["access_token"]}).json()
    assert me["email_verified_at"]
    r = verify(otp_auth, email, code)
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_VERIFIED"
    assert otp_login(otp_auth, email).status_code == 200


def test_otp_wrong_attempts_then_locked(system, otp_auth):
    email, _ = otp_register(system, otp_auth)
    code = system.read_otp(email)
    for left in (4, 3, 2, 1):
        r = verify(otp_auth, email, wrong(code))
        assert (r.status_code, r.json()["code"], r.json()["remaining_attempts"]) == (400, "OTP_INVALID", left), r.text
    r = verify(otp_auth, email, wrong(code))
    assert r.status_code == 429 and r.json()["code"] == "OTP_LOCKED"
    r = verify(otp_auth, email, code)                                   # đúng mã nhưng mã đã bị khóa
    assert r.status_code == 429 and r.json()["code"] == "OTP_LOCKED"
    assert otp_rows(otp_auth, email)[-1]["attempts"] == 5
    age_codes(otp_auth, email, 61)                                       # gửi mã mới thì nhập lại được
    assert resend(otp_auth, email).json()["otp_sent"] is True
    assert verify(otp_auth, email, system.read_otp(email)).status_code == 200


def test_otp_expired(system, otp_auth):
    email, _ = otp_register(system, otp_auth)
    conn = otp_auth.db()
    conn.execute("UPDATE otp_codes SET expires_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 seconds') "
                 "WHERE user_id = (SELECT id FROM users WHERE email=?)", (email,))
    conn.close()
    r = verify(otp_auth, email, system.read_otp(email))
    assert r.status_code == 400 and r.json()["code"] == "OTP_EXPIRED", r.text
    assert otp_rows(otp_auth, email)[-1]["attempts"] == 0              # mã hết hạn không tính lần thử


def test_otp_resend_too_soon_then_new_code_replaces_old(system, otp_auth):
    email, _ = otp_register(system, otp_auth)
    old = system.read_otp(email)
    r = resend(otp_auth, email)
    assert r.status_code == 429 and r.json()["code"] == "OTP_RESEND_TOO_SOON", r.text
    assert 1 <= r.json()["retry_after"] <= 60 and r.headers["Retry-After"] == str(r.json()["retry_after"])
    age_codes(otp_auth, email, 61)
    r = resend(otp_auth, email)
    assert r.status_code == 202 and r.json()["otp_sent"] is True and r.json()["resend_after"] == 60, r.text
    new = system.read_otp(email)
    assert len(system.emails(email)) == 2
    rows = otp_rows(otp_auth, email)
    assert len(rows) == 2 and rows[0]["used_at"] and rows[1]["used_at"] is None     # mã cũ bị vô hiệu
    if new != old:                                                      # (xác suất trùng 1/1.000.000)
        r = verify(otp_auth, email, old)
        assert r.status_code == 400 and r.json()["code"] == "OTP_INVALID", r.text
    assert verify(otp_auth, email, new).status_code == 200


def test_otp_resend_hourly_limit_counts_registration_code(system, otp_auth):
    email, _ = otp_register(system, otp_auth)                          # mã 1 (lúc đăng ký)
    for _ in range(4):                                                  # mã 2..5
        age_codes(otp_auth, email, 61)
        assert resend(otp_auth, email).status_code == 202
    age_codes(otp_auth, email, 61)
    r = resend(otp_auth, email)                                         # mã thứ 6 trong 1 giờ
    assert r.status_code == 429 and r.json()["code"] == "OTP_RESEND_LIMIT", r.text
    assert 0 < r.json()["retry_after"] <= 3600 and r.headers["Retry-After"] == str(r.json()["retry_after"])
    age_codes(otp_auth, email, 3600)                                    # sau 1 giờ được gửi lại
    assert resend(otp_auth, email).status_code == 202
    assert len(system.emails(email)) == 6


def test_otp_resend_unknown_or_verified_is_202_without_sending(system, otp_auth):
    ghost = system.email("khongco@student.tdtu.edu.vn")
    r = resend(otp_auth, ghost)
    assert (r.status_code, r.json()["otp_sent"]) == (202, False) and system.emails(ghost) == []
    email, _ = otp_register(system, otp_auth)
    assert verify(otp_auth, email, system.read_otp(email)).status_code == 200
    age_codes(otp_auth, email, 61)
    r = resend(otp_auth, email)
    assert (r.status_code, r.json()["otp_sent"]) == (202, False) and len(system.emails(email)) == 1
    assert r.json()["detail"] == resend(otp_auth, ghost).json()["detail"]       # cùng câu trả lời: không lộ email


def test_otp_register_ok_when_notification_down(system, otp_auth):
    system.fault("notification", "down")
    email, u = otp_register(system, otp_auth)
    assert (u["verification_required"], u["otp_sent"]) == (True, False), u
    system.fault("notification", "500")
    email2, u2 = otp_register(system, otp_auth, local="sv.otp2@student.tdtu.edu.vn")
    assert u2["otp_sent"] is False
    system.fault("notification", None)
    assert system.emails(email) == []
    age_codes(otp_auth, email, 61)
    r = resend(otp_auth, email)
    assert r.json()["otp_sent"] is True, r.text
    assert verify(otp_auth, email, system.read_otp(email)).status_code == 200


def test_otp_provider_500_and_timeout(system, otp_auth):
    system.mock_mode("fail500")
    email, u = otp_register(system, otp_auth)
    assert u["otp_sent"] is False and system.emails(email) == []
    system.mock_mode("ok")
    system.fault("mock_email", "timeout")                                # provider treo: Notification bỏ sau 1 giây
    t0 = time.time()
    email2, u2 = otp_register(system, otp_auth, local="sv.otp.cham@student.tdtu.edu.vn")
    took = time.time() - t0
    system.fault("mock_email", None)
    assert u2["otp_sent"] is False and took < 3, took                   # 1s (provider) < 2s (HTTP_TIMEOUT của Auth)
    admin = system.admin()
    logs = system.notification.get("/api/admin/email-logs", headers=admin, params={"user_id": u2["id"]}).json()["items"]
    assert logs and logs[0]["status"] == "failed" and "EMAIL_PROVIDER_UNAVAILABLE" in logs[0]["last_error"], logs
    age_codes(otp_auth, email, 61)
    assert resend(otp_auth, email).json()["otp_sent"] is True


def test_otp_parallel_wrong_codes_counted_exactly(system, otp_auth):
    import threading
    email, _ = otp_register(system, otp_auth)
    bad = wrong(system.read_otp(email))
    results = []

    def guess():
        results.append(verify(otp_auth, email, bad).status_code)
    threads = [threading.Thread(target=guess) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [400] * 4 + [429] * 6, results
    assert otp_rows(otp_auth, email)[-1]["attempts"] == 5


def test_otp_code_not_in_db_or_logs(system, otp_auth):
    import re as _re
    email, u = otp_register(system, otp_auth)
    code = system.read_otp(email)
    verify(otp_auth, email, wrong(code))
    assert verify(otp_auth, email, code).status_code == 200
    pattern = _re.compile(rf"\b{code}\b")
    conn = otp_auth.db()
    dump = " ".join(str(v) for t in ("users", "otp_codes") for r in conn.execute(f"SELECT * FROM {t}") for v in tuple(r))
    conn.close()
    assert not pattern.search(dump), "mã OTP không được lưu trong DB của Auth"
    assert len(otp_rows(otp_auth, email)[0]["code_hash"]) == 64
    for log in (otp_auth.log, system.c.tmp / "notification.log", system.c.tmp / "mock_email.log", system.c.tmp / "auth.log"):
        assert not pattern.search(log.read_text(encoding="utf-8", errors="replace")), f"mã OTP xuất hiện trong {log.name}"


def test_otp_admin_always_verified_and_disabled_endpoints(system, otp_auth):
    email = otp_admin(otp_auth, system)                                 # email_verified_at = NULL
    r = otp_login(otp_auth, email)
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin", r.text
    assert verify(otp_auth, email, "123456").json()["code"] == "ALREADY_VERIFIED"
    # Auth chính của cụm tắt OTP: đăng ký xác nhận luôn, 2 API OTP trả 404
    u = system.register(system.email("tatotp@student.tdtu.edu.vn"))
    assert (u["verification_required"], u["otp_sent"], u["resend_after"]) == (False, None, None) and u["email_verified_at"]
    for path, body in (("/api/users/verify-otp", {"email": u["email"], "code": "123456"}),
                       ("/api/users/resend-otp", {"email": u["email"]})):
        r = system.auth.post(path, json=body)
        assert r.status_code == 404 and r.json()["code"] == "OTP_DISABLED", r.text


def test_token_endpoint_form_login(system, otp_auth):
    email = system.email("form@student.tdtu.edu.vn")
    system.register(email)
    r = system.auth.post("/api/users/token", content={"username": email.upper(), "password": PW})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer", r.text
    assert system.auth.get("/api/users/me", headers={"Authorization": "Bearer " + r.json()["access_token"]}).status_code == 200
    r = system.auth.post("/api/users/token", content={"username": email, "password": "saimatkhau9"})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    r = system.auth.post("/api/users/token", content={"username": "khong-phai-email", "password": PW})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "username", r.text
    assert system.auth.post("/api/users/token", json={"username": email, "password": PW}).status_code == 422  # phải là form
    pending, _ = otp_register(system, otp_auth, local="form.otp@student.tdtu.edu.vn")
    r = otp_auth.client.post("/api/users/token", content={"username": pending, "password": PW})
    assert r.status_code == 403 and r.json()["code"] == "EMAIL_NOT_VERIFIED"
    spec = system.auth.get("/openapi.json").json()["components"]["securitySchemes"]
    assert any(v.get("type") == "oauth2" and v["flows"]["password"]["tokenUrl"] == "/api/users/token" for v in spec.values())


def test_401_has_www_authenticate_header(system):
    for r in (system.auth.get("/api/users/me"),
              system.auth.get("/api/users/me", headers={"Authorization": "Bearer abc.def.ghi"}),
              system.auth.post("/api/users/login", json={"email": system.email("x@student.tdtu.edu.vn"), "password": "a"})):
        assert r.status_code == 401 and r.headers.get("WWW-Authenticate") == "Bearer", (r.status_code, r.headers)
    assert "WWW-Authenticate" not in system.auth.get("/api/users", headers=system.user(
        system.email("w@student.tdtu.edu.vn"))).headers                 # 403 không có header này


def test_erase_deletes_otp_codes(system, otp_auth):
    email, u = otp_register(system, otp_auth)
    assert len(otp_rows(otp_auth, email)) == 1
    admin_email = otp_admin(otp_auth, system, verified=True)
    admin = {"Authorization": "Bearer " + otp_login(otp_auth, admin_email).json()["access_token"]}
    r = otp_auth.client.post(f"/api/users/{u['id']}/erase", headers=admin)
    assert r.status_code == 200, r.text
    conn = otp_auth.db()
    assert conn.execute("SELECT COUNT(*) FROM otp_codes WHERE user_id=?", (u["id"],)).fetchone()[0] == 0
    conn.close()
    assert r.json()["services"]["notification"]["emails_deleted"] >= 1
