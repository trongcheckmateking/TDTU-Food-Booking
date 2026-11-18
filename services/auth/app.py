"""Auth Service (cổng 8001): đăng ký (xác nhận email bằng mã OTP), đăng nhập JWT, hồ sơ, quản lý tài khoản.

Chạy: python -m uvicorn services.auth.app:app --port 8001 (từ thư mục gốc, hoặc dùng manage.py start)

Endpoint dùng `def` (không `async def`): sqlite3 và bcrypt là thao tác chặn (blocking), FastAPI chạy hàm `def` trong
threadpool nên không chặn event loop (Unit 3).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import bcrypt
import jwt
from fastapi import Depends, Query, Request, Security
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from common import config
from common.app import create_app
from common.db import Database, now_iso, new_id, paginate, row, transaction
from common.errors import ApiError
from common.http import call
from common.security import bearer, require_internal
from common.validators import Page, PageSize

from .banks import BANKS, bank_name
from .models import (SCHEMA, BankOut, EraseOut, LoginIn, OtpResendIn, OtpResendOut, OtpVerifyIn, PasswordChange,
                     PayoutIn, PayoutOut, ProfileUpdate, RegisterIn, RegisterOut, RoleUpdate, StatusUpdate, TokenOut,
                     UserOut, UserPage)

log = logging.getLogger("tdtu.auth")
db = Database("auth.db", SCHEMA)
ISSUER = "tdtu-food-booking-auth"
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=4))

def _migrate() -> None:
    """Nâng cấp DB cũ (idempotent, an toàn khi nhiều worker cùng khởi động)."""
    conn = db.connect()
    try:
        for col in ("terms_accepted_at", "erased_at", "avatar_url", "bank_bin", "bank_account", "bank_holder"):
            if col not in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError as e:      # worker khác vừa thêm cột
                    if "duplicate column" not in str(e):
                        raise
        if "email_verified_at" not in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:
            try:
                with transaction(conn):
                    conn.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
                    # Tài khoản có từ trước khi có OTP coi như đã xác nhận. Chỉ chạy ĐÚNG LÚC vừa thêm cột (cùng giao
                    # dịch); chạy ở mỗi lần khởi động thì người chưa nhập mã OTP cũng bị coi là đã xác nhận.
                    conn.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")
            except sqlite3.OperationalError as e:          # worker khác vừa thêm cột (và đã chạy UPDATE)
                if "duplicate column" not in str(e):
                    raise
    finally:
        conn.close()


def _startup() -> None:
    config.jwt_secret()
    _migrate()
    threading.Thread(target=_replay_erasures_loop, name="erasure-replay", daemon=True).start()


app = create_app("auth", "Auth Service", "Đăng ký, đăng nhập JWT, hồ sơ, phân quyền và quản lý tài khoản.", db,
                 on_startup=_startup)
conn_dep = db.dependency


def token_hours() -> int:
    return max(1, config.get_int("TOKEN_HOURS", 8))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str | bytes) -> bool:
    data = password.encode("utf-8")
    if len(data) > 72:
        return False
    try:
        return bcrypt.checkpw(data, hashed if isinstance(hashed, bytes) else hashed.encode())
    except ValueError:
        return False


# ------------------------------------------------------------------ chống dò mật khẩu
def login_limits() -> tuple[int, int, int]:
    """(số lần sai tối đa, cửa sổ đếm giây, thời gian khóa giây) - mặc định 5 lần / 15 phút, khóa 15 phút."""
    return (max(1, config.get_int("LOGIN_MAX_FAILS", 5)), max(60, config.get_int("LOGIN_WINDOW_SECONDS", 900)),
            max(60, config.get_int("LOGIN_LOCK_SECONDS", 900)))


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def attempt_key(email: str, request: Request) -> str:
    """Theo cặp email + IP: kẻ xấu ở máy khác không khóa được tài khoản của người khác.
    IPv6 gộp theo dải /64 (một máy thường có cả dải, đổi địa chỉ trong dải không né được khóa)."""
    host = request.client.host if request.client else "-"
    try:
        if ipaddress.ip_address(host).version == 6:
            host = str(ipaddress.ip_network(f"{host}/64", strict=False))
    except ValueError:
        pass
    return f"{email}|{host}"


def reserve_attempt(conn: sqlite3.Connection, key: str) -> None:
    """Tính 1 lần thử TRƯỚC khi kiểm tra mật khẩu, trong giao dịch ghi (BEGIN IMMEDIATE): gửi hàng chục yêu cầu song
    song cũng chỉ được tối đa LOGIN_MAX_FAILS lần thử mỗi cửa sổ. Đang bị khóa -> 429. Đăng nhập đúng thì xóa bộ đếm."""
    max_fails, window, lock = login_limits()
    now = datetime.now(timezone.utc)
    with transaction(conn):
        r = conn.execute("SELECT fails, window_start, locked_until FROM login_attempts WHERE key=?", (key,)).fetchone()
        if r and r["locked_until"] and r["locked_until"] > _iso(now):
            wait = int((datetime.strptime(r["locked_until"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        - now).total_seconds()) + 1
            raise ApiError(429, "TOO_MANY_ATTEMPTS",
                           f"Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau {max(1, round(wait / 60))} phút",
                           headers={"Retry-After": str(wait)})
        fresh = not r or r["window_start"] < _iso(now - timedelta(seconds=window))
        fails = 1 if fresh else r["fails"] + 1
        start = _iso(now) if fresh else r["window_start"]
        locked = _iso(now + timedelta(seconds=lock)) if fails >= max_fails else None
        conn.execute("INSERT INTO login_attempts (key,fails,window_start,locked_until) VALUES (?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET fails=excluded.fails, window_start=excluded.window_start, "
                     "locked_until=excluded.locked_until", (key, fails, start, locked))
        # dọn bản ghi cũ để bảng không phình
        conn.execute("DELETE FROM login_attempts WHERE window_start < ? AND (locked_until IS NULL OR locked_until < ?)",
                     (_iso(now - timedelta(days=1)), _iso(now)))


def public(u: dict) -> dict:
    out = {k: u.get(k) for k in ("id", "name", "email", "role", "phone", "status", "created_at", "terms_accepted_at",
                                 "erased_at", "avatar_url", "bank_bin", "bank_account", "bank_holder",
                                 "email_verified_at")}
    out["bank_name"] = bank_name(u.get("bank_bin"))
    return out


def token_response(u: dict) -> dict:
    return {"access_token": issue_token(u), "token_type": "bearer", "expires_in": token_hours() * 3600, "user": public(u)}


def issue_token(u: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": u["id"], "role": u["role"], "ver": u["token_version"], "iss": ISSUER,
               "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=token_hours())).timestamp())}
    return jwt.encode(payload, config.jwt_secret(), algorithm="HS256")


def load_user(conn: sqlite3.Connection, user_id: str) -> dict:
    u = row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    if not u:
        raise ApiError(404, "USER_NOT_FOUND", "Không tìm thấy người dùng")
    return u


# Unit 18: OAuth2 password flow - nút Authorize của Swagger nhập email + mật khẩu, gọi POST /api/users/token.
# Giữ thêm HTTPBearer (dán token có sẵn) để Swagger có cả 2 cách; mã lỗi không đổi.
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/users/token", auto_error=False,
                              description="Đăng nhập bằng email (ô username) và mật khẩu: Swagger gọi POST /api/users/token")


def current_user(token: Annotated[str | None, Security(oauth2)],
                 creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
                 conn: sqlite3.Connection = Depends(conn_dep)) -> dict:
    token = token or (creds.credentials if creds else None)
    if not token:
        raise ApiError(401, "UNAUTHORIZED", "Cần đăng nhập (thiếu Bearer token)")
    try:
        payload = jwt.decode(token, config.jwt_secret(), algorithms=["HS256"], issuer=ISSUER,
                             options={"require": ["sub", "exp", "iat", "ver", "iss"]})
        uuid.UUID(str(payload["sub"]))
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "Phiên đăng nhập đã hết hạn")
    except (jwt.PyJWTError, ValueError, TypeError):
        raise ApiError(401, "TOKEN_INVALID", "Token không hợp lệ")
    u = row(conn.execute("SELECT * FROM users WHERE id=?", (payload["sub"],)).fetchone())
    if not u or payload["ver"] != u["token_version"]:
        raise ApiError(401, "TOKEN_REVOKED", "Phiên đăng nhập đã bị thu hồi, vui lòng đăng nhập lại")
    if u["status"] != "active":
        raise ApiError(403, "ACCOUNT_LOCKED", "Tài khoản đã bị khóa, liên hệ quản trị viên")
    return u


def admin_only(u: dict = Depends(current_user)) -> dict:
    if u["role"] != "admin":
        raise ApiError(403, "FORBIDDEN", "Chỉ admin được thực hiện thao tác này")
    return u


# ------------------------------------------------------------------ mã OTP xác nhận email
@dataclass(frozen=True)
class OtpSettings:
    ttl: int                # giây mã còn hiệu lực
    max_attempts: int       # số lần nhập sai tối đa của một mã
    resend_seconds: int     # khoảng cách tối thiểu giữa 2 lần gửi mã
    per_hour: int           # số mã tối đa mỗi user trong 60 phút (tính cả mã lúc đăng ký)


def otp_enabled() -> bool:
    return (config.get("OTP_ENABLED", "false") or "").strip().lower() in ("1", "true", "yes", "on")


def otp_settings() -> OtpSettings:
    return OtpSettings(ttl=max(60, config.get_int("OTP_TTL_SECONDS", 300)),
                       max_attempts=max(1, config.get_int("OTP_MAX_ATTEMPTS", 5)),
                       resend_seconds=max(0, config.get_int("OTP_RESEND_SECONDS", 60)),
                       per_hour=max(1, config.get_int("OTP_RESEND_PER_HOUR", 5)))


def otp_hash(otp_id: str, code: str) -> str:
    """Chỉ lưu HMAC của mã (khóa JWT_SECRET, gắn với id của mã): lộ DB cũng không biết mã."""
    return hmac.new(config.jwt_secret().encode(), f"otp:{otp_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def new_otp(conn: sqlite3.Connection, user_id: str) -> tuple[str, str]:
    """Tạo mã mới và vô hiệu mã cũ của user. GỌI BÊN TRONG transaction. Trả (otp_id, mã) - mã chỉ để gửi email."""
    otp_id, now = new_id(), datetime.now(timezone.utc)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    conn.execute("UPDATE otp_codes SET used_at=? WHERE user_id=? AND purpose='verify_email' AND used_at IS NULL",
                 (_iso(now), user_id))
    conn.execute("INSERT INTO otp_codes (id,user_id,purpose,code_hash,expires_at,attempts,used_at,created_at) "
                 "VALUES (?,?,'verify_email',?,?,0,NULL,?)",
                 (otp_id, user_id, otp_hash(otp_id, code), _iso(now + timedelta(seconds=otp_settings().ttl)), _iso(now)))
    return otp_id, code


def send_otp(user: dict, otp_id: str, code: str) -> bool:
    """Nhờ Notification gửi email mã (sau khi đã commit). Notification / provider lỗi -> False, không ném lỗi:
    đăng ký vẫn thành công, người dùng bấm gửi lại mã. Log không bao giờ có mã."""
    body = {"to": user["email"], "template": "otp", "purpose": "verify_email", "code": code, "user_id": user["id"],
            "expires_in_seconds": otp_settings().ttl, "idempotency_key": f"otp-{otp_id}"}
    try:
        call("POST", f"{config.service_url('NOTIFICATION')}/internal/notifications/email", "Notification Service",
             internal=True, json=body)
        return True
    except ApiError as e:
        log.warning("Chưa gửi được mã xác nhận email cho user %s (otp %s): %s", user["id"], otp_id, e.code)
        return False


def _otp_error(status: int, code: str, message: str, **extra) -> ApiError:
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return ApiError(status, code, message, extra=extra or None, headers=headers)


def _resend_block(conn: sqlite3.Connection, user_id: str, s: OtpSettings, now: datetime) -> ApiError | None:
    """Giới hạn gửi mã (dùng chung cho resend-otp và đăng ký lại tài khoản chưa xác nhận). GỌI TRONG transaction.
    Trả lỗi 429 nếu gửi quá sớm / quá nhiều trong 1 giờ, None nếu được gửi mã mới."""
    last = conn.execute("SELECT MAX(created_at) FROM otp_codes WHERE user_id=? AND purpose='verify_email'",
                        (user_id,)).fetchone()[0]
    hour_ago = _iso(now - timedelta(hours=1))
    recent = conn.execute("SELECT COUNT(*), MIN(created_at) FROM otp_codes WHERE user_id=? AND "
                          "purpose='verify_email' AND created_at > ?", (user_id, hour_ago)).fetchone()
    waited = (now - _parse_iso(last)).total_seconds() if last else None
    if waited is not None and waited < s.resend_seconds:
        wait = max(1, math.ceil(s.resend_seconds - waited))
        return _otp_error(429, "OTP_RESEND_TOO_SOON", f"Vui lòng chờ {wait} giây rồi gửi lại mã", retry_after=wait)
    if recent[0] >= s.per_hour:
        wait = max(1, math.ceil((_parse_iso(recent[1]) + timedelta(hours=1) - now).total_seconds()))
        return _otp_error(429, "OTP_RESEND_LIMIT",
                          f"Đã gửi {s.per_hour} mã trong 1 giờ, vui lòng thử lại sau {max(1, round(wait / 60))} phút",
                          retry_after=wait)
    return None


def _reclaimable(u: dict | None) -> bool:
    """Tài khoản đăng ký nhưng CHƯA nhập mã OTP: cho đăng ký lại cùng email (cập nhật thông tin, gửi mã mới)."""
    return bool(u) and u["status"] == "active" and u["role"] != "admin" and not u.get("email_verified_at") \
        and not u.get("erased_at")


def _require_otp() -> OtpSettings:
    if not otp_enabled():
        raise ApiError(404, "OTP_DISABLED", "Hệ thống không bật xác nhận email bằng mã OTP")
    return otp_settings()


# ------------------------------------------------------------------ người dùng
@app.post("/api/users/register", response_model=RegisterOut, status_code=201, tags=["auth"],
          summary="Đăng ký tài khoản sinh viên hoặc chủ quán",
          description="Bật OTP (OTP_ENABLED=true): tài khoản chưa xác nhận email, mã 6 số được gửi qua email "
                      "(verification_required=true); Notification / nhà cung cấp email lỗi thì đăng ký vẫn thành công "
                      "với otp_sent=false, người dùng bấm gửi lại mã. Email đã đăng ký nhưng CHƯA xác nhận "
                      "thì đăng ký lại được (cập nhật thông tin, gửi mã mới, theo giới hạn gửi lại mã).",
          responses={409: {"description": "EMAIL_EXISTS (email đã xác nhận / tài khoản bị khóa)"},
                     429: {"description": "OTP_RESEND_TOO_SOON / OTP_RESEND_LIMIT khi đăng ký lại quá sớm"}})
def register(data: RegisterIn, conn: sqlite3.Connection = Depends(conn_dep)):
    uid, ts, otp = new_id(), now_iso(), otp_enabled()
    otp_id = code = None
    error: ApiError | None = None
    try:
        with transaction(conn):          # user + mã OTP trong CÙNG giao dịch
            old = row(conn.execute("SELECT * FROM users WHERE email=?", (data.email,)).fetchone()) if otp else None
            if _reclaimable(old):
                # Đăng ký rồi tải lại trang trước khi nhập mã: chưa ai chứng minh sở hữu email nên ghi đè thông tin
                # (mật khẩu mới) và gửi mã mới. Không raise trong transaction (giữ quy ước ghi lỗi rồi raise sau).
                error = _resend_block(conn, old["id"], otp_settings(), datetime.now(timezone.utc))
                if not error:
                    uid = old["id"]
                    conn.execute("UPDATE users SET name=?, password_hash=?, role=?, phone=?, bank_bin=?, bank_account=?, "
                                 "bank_holder=?, terms_accepted_at=?, updated_at=?, token_version=token_version+1 "
                                 "WHERE id=? AND email_verified_at IS NULL",
                                 (data.name, hash_password(data.password), data.role, data.phone, data.bank_bin,
                                  data.bank_account, data.bank_holder, ts, ts, uid))
                    otp_id, code = new_otp(conn, uid)
                    log.info("Đăng ký lại tài khoản chưa xác nhận email: user %s", uid)
            else:
                conn.execute("INSERT INTO users (id,name,email,password_hash,role,phone,status,token_version,created_at,"
                         "updated_at,terms_accepted_at,bank_bin,bank_account,bank_holder,email_verified_at) "
                         "VALUES (?,?,?,?,?,?, 'active', 0, ?, ?, ?, ?, ?, ?, ?)",
                         (uid, data.name, data.email, hash_password(data.password), data.role, data.phone, ts, ts, ts,
                          data.bank_bin, data.bank_account, data.bank_holder, None if otp else ts))
                if otp:
                    otp_id, code = new_otp(conn, uid)
    except sqlite3.IntegrityError as e:
        if "users.email" in str(e):
            raise ApiError(409, "EMAIL_EXISTS", "Email đã được sử dụng")
        raise
    if error:
        raise error
    user = load_user(conn, uid)
    sent = send_otp(user, otp_id, code) if otp else None          # gọi mạng SAU khi commit
    return {**public(user), "verification_required": otp, "otp_sent": sent,
            "resend_after": otp_settings().resend_seconds if otp else None}


def _login(email: str, password: str, request: Request, conn: sqlite3.Connection) -> dict:
    key = attempt_key(email, request)
    reserve_attempt(conn, key)
    u = row(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    if not u:
        check_password(password, _DUMMY_HASH)              # giữ thời gian phản hồi tương đương
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu")
    if not check_password(password, u["password_hash"]):
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu")
    conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))
    if u["status"] != "active":
        raise ApiError(403, "ACCOUNT_LOCKED", "Tài khoản đã bị khóa, liên hệ quản trị viên")
    # chỉ báo chưa xác nhận khi đã ĐÚNG mật khẩu (không lộ email nào đã đăng ký); admin luôn được coi là đã xác nhận
    if otp_enabled() and u["role"] != "admin" and not u.get("email_verified_at"):
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "Email chưa được xác nhận. Nhập mã OTP đã gửi tới email của bạn",
                       extra={"email": u["email"]})
    return token_response(u)


@app.post("/api/users/login", response_model=TokenOut, tags=["auth"],
          summary="Đăng nhập, nhận access_token. Sai 5 lần trong 15 phút (cùng email + IP) thì khóa tạm 15 phút (429)",
          responses={403: {"description": "ACCOUNT_LOCKED, hoặc EMAIL_NOT_VERIFIED (kèm email) khi chưa nhập mã OTP"}})
def login(data: LoginIn, request: Request, conn: sqlite3.Connection = Depends(conn_dep)):
    return _login(data.email, data.password, request, conn)


@app.post("/api/users/token", response_model=TokenOut, tags=["auth"],
          summary="Đăng nhập dạng form OAuth2 (username = email): dùng cho nút Authorize của Swagger (Unit 18)",
          description="Cùng logic, giới hạn và mã lỗi với POST /api/users/login (JSON, giao diện web dùng).")
def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request,
          conn: sqlite3.Connection = Depends(conn_dep)):
    try:
        data = LoginIn(email=form.username, password=form.password)
    except ValidationError as e:
        errors = [{"field": "username" if err["loc"][0] == "email" else str(err["loc"][0]), "message": err["msg"]}
                  for err in e.errors()]
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ", extra={"errors": errors})
    return _login(data.email, data.password, request, conn)


@app.post("/api/users/verify-otp", response_model=TokenOut, tags=["auth"],
          summary="Nhập mã OTP xác nhận email: đúng thì xác nhận và đăng nhập luôn (trả token như login)",
          responses={400: {"description": "OTP_INVALID (+remaining_attempts) / OTP_EXPIRED"},
                     403: {"description": "ACCOUNT_LOCKED"}, 404: {"description": "OTP_DISABLED"},
                     409: {"description": "ALREADY_VERIFIED"}, 429: {"description": "OTP_LOCKED: sai quá số lần"}})
def verify_otp(data: OtpVerifyIn, conn: sqlite3.Connection = Depends(conn_dep)):
    s = _require_otp()
    now = datetime.now(timezone.utc)
    error: ApiError | None = None
    user_id = None
    # Ghi kết quả vào biến, chỉ raise SAU khi ra khỏi khối transaction: raise bên trong sẽ ROLLBACK và mất lần đếm sai.
    with transaction(conn):              # BEGIN IMMEDIATE: các lần thử đồng thời xếp hàng, đếm đúng từng lần
        u = row(conn.execute("SELECT * FROM users WHERE email=?", (data.email,)).fetchone())
        otp = None
        if u and u["status"] == "active" and not u.get("email_verified_at") and u["role"] != "admin":
            otp = row(conn.execute("SELECT * FROM otp_codes WHERE user_id=? AND purpose='verify_email' AND used_at IS NULL "
                                   "ORDER BY created_at DESC LIMIT 1", (u["id"],)).fetchone())
        if not u:
            error = ApiError(400, "OTP_EXPIRED", "Mã xác nhận không còn hiệu lực, vui lòng gửi lại mã")
        elif u["status"] != "active":
            error = ApiError(403, "ACCOUNT_LOCKED", "Tài khoản đã bị khóa, liên hệ quản trị viên")
        elif u.get("email_verified_at") or u["role"] == "admin":
            error = ApiError(409, "ALREADY_VERIFIED", "Email đã được xác nhận, hãy đăng nhập")
        elif not otp:
            error = ApiError(400, "OTP_EXPIRED", "Mã xác nhận không còn hiệu lực, vui lòng gửi lại mã")
        elif otp["attempts"] >= s.max_attempts:
            error = ApiError(429, "OTP_LOCKED", "Nhập sai quá nhiều lần, vui lòng gửi lại mã mới")
        elif otp["expires_at"] <= _iso(now):
            error = ApiError(400, "OTP_EXPIRED", "Mã xác nhận đã hết hạn, vui lòng gửi lại mã")
        else:
            # cộng lần thử TRƯỚC khi so mã: yêu cầu đồng thời không vượt quá số lần cho phép
            n = conn.execute("UPDATE otp_codes SET attempts=attempts+1 WHERE id=? AND used_at IS NULL AND attempts<?",
                             (otp["id"], s.max_attempts)).rowcount
            if n == 0:
                error = ApiError(429, "OTP_LOCKED", "Nhập sai quá nhiều lần, vui lòng gửi lại mã mới")
            elif hmac.compare_digest(otp_hash(otp["id"], data.code), otp["code_hash"]):
                conn.execute("UPDATE otp_codes SET used_at=? WHERE id=?", (_iso(now), otp["id"]))
                conn.execute("UPDATE users SET email_verified_at=?, updated_at=? WHERE id=? AND email_verified_at IS NULL",
                             (_iso(now), _iso(now), u["id"]))
                user_id = u["id"]
            else:
                remaining = s.max_attempts - (otp["attempts"] + 1)
                error = (ApiError(429, "OTP_LOCKED", "Nhập sai quá nhiều lần, vui lòng gửi lại mã mới") if remaining <= 0
                         else ApiError(400, "OTP_INVALID", f"Mã xác nhận không đúng, còn {remaining} lần thử",
                                       extra={"remaining_attempts": remaining}))
    if error:
        raise error
    log.info("User %s đã xác nhận email bằng mã OTP", user_id)
    return token_response(load_user(conn, user_id))


@app.post("/api/users/resend-otp", response_model=OtpResendOut, status_code=202, tags=["auth"],
          summary="Gửi lại mã OTP (mã cũ hết hiệu lực)",
          description="Luôn trả 202 với email chưa đăng ký / đã xác nhận (otp_sent=false, không gửi) để không lộ email "
                      "nào đã đăng ký. Cách lần gửi trước tối thiểu OTP_RESEND_SECONDS giây, tối đa OTP_RESEND_PER_HOUR "
                      "mã mỗi giờ (tính cả mã lúc đăng ký).",
          responses={404: {"description": "OTP_DISABLED"},
                     429: {"description": "OTP_RESEND_TOO_SOON / OTP_RESEND_LIMIT (+retry_after, header Retry-After)"}})
def resend_otp(data: OtpResendIn, conn: sqlite3.Connection = Depends(conn_dep)):
    s = _require_otp()
    now = datetime.now(timezone.utc)
    error: ApiError | None = None
    user = otp_id = code = None
    with transaction(conn):              # không raise bên trong: giữ nguyên quy tắc ghi kết quả rồi raise sau
        u = row(conn.execute("SELECT * FROM users WHERE email=?", (data.email,)).fetchone())
        if u and u["status"] == "active" and u["role"] != "admin" and not u.get("email_verified_at"):
            error = _resend_block(conn, u["id"], s, now)
            if not error:
                user = u
                otp_id, code = new_otp(conn, u["id"])
    if error:
        raise error
    if not user:
        return {"detail": "Nếu email đã đăng ký và chưa xác nhận, mã mới đã được gửi", "otp_sent": False,
                "resend_after": s.resend_seconds}
    sent = send_otp(user, otp_id, code)
    return {"detail": "Đã gửi mã xác nhận mới" if sent else "Chưa gửi được email, vui lòng thử lại sau ít phút",
            "otp_sent": sent, "resend_after": s.resend_seconds}


@app.get("/api/users/me", response_model=UserOut, tags=["auth"],
         summary="Hồ sơ người đang đăng nhập (các service khác gọi API này để xác thực)")
def me(u: dict = Depends(current_user)):
    return public(u)


@app.patch("/api/users/me", response_model=UserOut, tags=["auth"], summary="Cập nhật họ tên, số điện thoại")
def update_me(data: ProfileUpdate, u: dict = Depends(current_user), conn: sqlite3.Connection = Depends(conn_dep)):
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise ApiError(422, "VALIDATION_ERROR", "Họ tên không được để trống")
    if changes:
        with transaction(conn):
            sets = ", ".join(f"{k}=?" for k in changes)
            conn.execute(f"UPDATE users SET {sets}, updated_at=? WHERE id=?", (*changes.values(), now_iso(), u["id"]))
    return public(load_user(conn, u["id"]))


@app.post("/api/users/logout", status_code=204, tags=["auth"],
          summary="Đăng xuất: thu hồi mọi token hiện có của tài khoản")
def logout(u: dict = Depends(current_user), conn: sqlite3.Connection = Depends(conn_dep)):
    with transaction(conn):
        conn.execute("UPDATE users SET token_version = token_version + 1 WHERE id=?", (u["id"],))


@app.post("/api/users/me/password", response_model=TokenOut, tags=["auth"],
          summary="Đổi mật khẩu: các phiên đăng nhập khác bị thu hồi, trả token mới cho phiên hiện tại")
def change_password(data: PasswordChange, request: Request, u: dict = Depends(current_user),
                    conn: sqlite3.Connection = Depends(conn_dep)):
    key = attempt_key("pw:" + u["email"], request)        # đoán mật khẩu cũ bằng token lấy cắp cũng bị giới hạn
    reserve_attempt(conn, key)
    if not check_password(data.current_password, u["password_hash"]):
        raise ApiError(400, "WRONG_PASSWORD", "Mật khẩu hiện tại không đúng")
    if data.new_password == data.current_password:
        raise ApiError(400, "SAME_PASSWORD", "Mật khẩu mới phải khác mật khẩu hiện tại")
    with transaction(conn):
        conn.execute("UPDATE users SET password_hash=?, token_version=token_version+1, updated_at=? WHERE id=?",
                     (hash_password(data.new_password), now_iso(), u["id"]))
        conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))
    fresh = load_user(conn, u["id"])
    return {"access_token": issue_token(fresh), "token_type": "bearer", "expires_in": token_hours() * 3600,
            "user": public(fresh)}


# ------------------------------------------------------------------ tài khoản nhận tiền của chủ quán (VietQR)
@app.get("/api/banks", response_model=list[BankOut], tags=["auth"],
         summary="Ngân hàng nhận tiền qua mã VietQR (cho form đăng ký chủ quán)")
def list_banks():
    return BANKS


@app.put("/api/users/me/payout", response_model=UserOut, tags=["auth"],
         summary="Chủ quán đổi tài khoản nhận tiền (cần nhập lại mật khẩu)",
         description="Đơn đã đặt giữ nguyên tài khoản lúc đặt; đơn mới dùng tài khoản này. Nhập sai mật khẩu bị tính vào "
                     "giới hạn chống dò mật khẩu như đổi mật khẩu.")
def set_payout(data: PayoutIn, request: Request, u: dict = Depends(current_user),
               conn: sqlite3.Connection = Depends(conn_dep)):
    if u["role"] != "chu_quan":
        raise ApiError(403, "FORBIDDEN", "Chỉ tài khoản chủ quán có tài khoản nhận tiền")
    key = attempt_key("pw:" + u["email"], request)        # token bị lấy cắp cũng không đổi được nơi nhận tiền
    reserve_attempt(conn, key)
    if not check_password(data.password, u["password_hash"]):
        raise ApiError(400, "WRONG_PASSWORD", "Mật khẩu hiện tại không đúng")
    with transaction(conn):
        conn.execute("UPDATE users SET bank_bin=?, bank_account=?, bank_holder=?, updated_at=? WHERE id=?",
                     (data.bank_bin, data.bank_account, data.bank_holder, now_iso(), u["id"]))
        conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))
    return public(load_user(conn, u["id"]))


@app.get("/internal/users/{user_id}/payout", response_model=PayoutOut, tags=["internal"],
         dependencies=[Depends(require_internal)],
         summary="Tài khoản nhận tiền của chủ quán (Order chụp vào đơn lúc đặt để tạo mã VietQR)",
         responses={404: {"description": "PAYOUT_MISSING: không phải chủ quán hoặc chưa khai báo"}})
def internal_payout(user_id: uuid.UUID, conn: sqlite3.Connection = Depends(conn_dep)):
    u = row(conn.execute("SELECT * FROM users WHERE id=?", (str(user_id),)).fetchone())
    if not u or u["role"] != "chu_quan" or u.get("erased_at") or not (u.get("bank_bin") and u.get("bank_account")):
        raise ApiError(404, "PAYOUT_MISSING", "Chủ quán chưa khai báo tài khoản nhận tiền")
    return {"user_id": u["id"], "bank_bin": u["bank_bin"], "bank_name": bank_name(u["bank_bin"]) or u["bank_bin"],
            "bank_account": u["bank_account"], "bank_holder": u["bank_holder"] or ""}


# ------------------------------------------------------------------ ảnh đại diện
AVATAR_MAX_BYTES = 1024 * 1024                  # trình duyệt đã thu nhỏ còn 512×512 JPEG (~50 KB)
AVATAR_FILE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
AVATAR_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def avatar_dir():
    d = config.data_dir() / "avatars"
    d.mkdir(exist_ok=True)
    return d


def _image_ext(data: bytes) -> str | None:
    """Nhận dạng ảnh theo nội dung (không tin Content-Type): JPEG, PNG, WebP."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def remove_avatar_file(url: str | None) -> None:
    name = (url or "").rsplit("/", 1)[-1]
    if (url or "").startswith("/avatars/") and AVATAR_FILE.match(name):
        (avatar_dir() / name).unlink(missing_ok=True)


def _save_avatar(user_id: str, data: bytes, ext: str) -> dict:
    name = f"{uuid.uuid4().hex}.{ext}"            # tên ngẫu nhiên, không đoán được
    tmp = avatar_dir() / (name + ".part")
    tmp.write_bytes(data)
    tmp.replace(avatar_dir() / name)
    conn = db.connect()
    try:
        old = row(conn.execute("SELECT avatar_url FROM users WHERE id=?", (user_id,)).fetchone())
        with transaction(conn):
            conn.execute("UPDATE users SET avatar_url=?, updated_at=? WHERE id=?", (f"/avatars/{name}", now_iso(), user_id))
        remove_avatar_file(old and old["avatar_url"])
        return public(load_user(conn, user_id))
    finally:
        conn.close()


@app.put("/api/users/me/avatar", response_model=UserOut, tags=["auth"],
         summary="Đổi ảnh đại diện: gửi thẳng nội dung ảnh JPEG/PNG/WebP (tối đa 1 MB), ảnh cũ bị xóa",
         openapi_extra={"requestBody": {"required": True, "content": {
             t: {"schema": {"type": "string", "format": "binary"}} for t in AVATAR_TYPES.values()}}})
async def set_avatar(request: Request, u: dict = Depends(current_user)):
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > AVATAR_MAX_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Ảnh đại diện tối đa 1 MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > AVATAR_MAX_BYTES:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Ảnh đại diện tối đa 1 MB")
    ext = _image_ext(bytes(data[:16]))
    if not ext:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Ảnh đại diện phải là ảnh JPEG, PNG hoặc WebP")
    return await run_in_threadpool(_save_avatar, u["id"], bytes(data), ext)


@app.delete("/api/users/me/avatar", response_model=UserOut, tags=["auth"], summary="Gỡ ảnh đại diện")
def delete_avatar(u: dict = Depends(current_user), conn: sqlite3.Connection = Depends(conn_dep)):
    with transaction(conn):
        conn.execute("UPDATE users SET avatar_url=NULL, updated_at=? WHERE id=?", (now_iso(), u["id"]))
    remove_avatar_file(u.get("avatar_url"))
    return public(load_user(conn, u["id"]))


@app.get("/avatars/{name}", tags=["auth"], summary="Tệp ảnh đại diện (đường dẫn lấy từ avatar_url)",
         response_class=FileResponse, responses={200: {"content": {t: {} for t in AVATAR_TYPES.values()}}})
def get_avatar(name: str):
    m = AVATAR_FILE.match(name)
    path = avatar_dir() / name if m else None
    if not path or not path.is_file():
        raise ApiError(404, "NOT_FOUND", "Không tìm thấy ảnh")
    return FileResponse(path, media_type=AVATAR_TYPES[m.group(1)], headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'",
        "Cross-Origin-Resource-Policy": "cross-origin", "Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------ admin
@app.get("/api/users", response_model=UserPage, tags=["admin"], summary="Danh sách tài khoản (admin)")
def list_users(role: Annotated[Literal["sinh_vien", "chu_quan", "admin"] | None, Query()] = None,
               status: Annotated[Literal["active", "locked"] | None, Query()] = None,
               q: Annotated[str | None, Query(max_length=100)] = None, page: Page = 1, page_size: PageSize = 20,
               _: dict = Depends(admin_only), conn: sqlite3.Connection = Depends(conn_dep)):
    sql, args = "SELECT * FROM users WHERE 1=1", []
    if role:
        sql += " AND role=?"; args.append(role)
    if status:
        sql += " AND status=?"; args.append(status)
    if q and q.strip():
        sql += " AND (name LIKE ? OR email LIKE ?)"; args += [f"%{q.strip()}%", f"%{q.strip().lower()}%"]
    result = paginate(conn, sql, args, page, page_size, "created_at DESC, id")
    result["items"] = [public(u) for u in result["items"]]
    return result


@app.get("/api/users/{user_id}", response_model=UserOut, tags=["admin"], summary="Chi tiết tài khoản (admin)")
def get_user(user_id: uuid.UUID, _: dict = Depends(admin_only), conn: sqlite3.Connection = Depends(conn_dep)):
    return public(load_user(conn, str(user_id)))


def _active_admins(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'").fetchone()[0]


def ensure_not_erased(target: dict) -> None:
    if target.get("erased_at"):
        raise ApiError(409, "USER_ERASED", "Tài khoản đã bị xóa dữ liệu cá nhân, không thể thay đổi")


def _owned_restaurants(owner_id: str) -> int:
    _, data = call("GET", f"{config.service_url('RESTAURANT')}/internal/owners/{owner_id}/restaurant-count",
                   "Restaurant Service", internal=True)
    try:
        return int(data["count"])
    except (KeyError, TypeError, ValueError):
        raise ApiError(502, "UPSTREAM_BAD_RESPONSE", "Restaurant Service trả dữ liệu không đúng định dạng")


@app.patch("/api/users/{user_id}/role", response_model=UserOut, tags=["admin"],
           summary="Đổi vai trò (admin). Token cũ của tài khoản bị thu hồi.")
def change_role(user_id: uuid.UUID, data: RoleUpdate, me_: dict = Depends(admin_only),
                conn: sqlite3.Connection = Depends(conn_dep)):
    target = load_user(conn, str(user_id))
    if target["id"] == me_["id"]:
        raise ApiError(400, "SELF_ACTION", "Không thể tự đổi vai trò của chính mình")
    ensure_not_erased(target)
    if target["role"] == data.role:
        return public(target)
    if target["role"] == "chu_quan" and _owned_restaurants(target["id"]) > 0:
        raise ApiError(409, "OWNER_HAS_RESTAURANTS",
                       "Chủ quán còn quán đang quản lý, hãy xóa hoặc chuyển quán trước khi đổi vai trò")
    with transaction(conn):
        if target["role"] == "admin" and target["status"] == "active" and _active_admins(conn) <= 1:
            raise ApiError(409, "LAST_ADMIN", "Không thể hạ vai trò admin cuối cùng")
        conn.execute("UPDATE users SET role=?, token_version=token_version+1, updated_at=? WHERE id=?",
                     (data.role, now_iso(), target["id"]))
    return public(load_user(conn, target["id"]))


@app.patch("/api/users/{user_id}/status", response_model=UserOut, tags=["admin"],
           summary="Khóa / mở khóa tài khoản (admin). Khóa = vô hiệu hóa, giữ nguyên lịch sử đơn.")
def change_status(user_id: uuid.UUID, data: StatusUpdate, me_: dict = Depends(admin_only),
                  conn: sqlite3.Connection = Depends(conn_dep)):
    target = load_user(conn, str(user_id))
    if target["id"] == me_["id"]:
        raise ApiError(400, "SELF_ACTION", "Không thể tự khóa tài khoản của chính mình")
    ensure_not_erased(target)
    if target["status"] == data.status:
        return public(target)
    with transaction(conn):
        if data.status == "locked" and target["role"] == "admin" and _active_admins(conn) <= 1:
            raise ApiError(409, "LAST_ADMIN", "Không thể khóa admin cuối cùng")
        conn.execute("UPDATE users SET status=?, token_version=token_version+1, updated_at=? WHERE id=?",
                     (data.status, now_iso(), target["id"]))
    return public(load_user(conn, target["id"]))


# ------------------------------------------------------------------ xóa dữ liệu cá nhân theo yêu cầu
ERASED_NAME = "Người dùng đã xóa"
# Order trước: là nơi có thể từ chối (còn đơn đang xử lý, với vai trò người đặt hoặc chủ quán) khi chưa đổi gì ở đâu
ERASE_STEPS = (("ORDER", "Order Service"), ("RESTAURANT", "Restaurant Service"), ("REVIEW", "Review Service"),
               ("NOTIFICATION", "Notification Service"))


@app.post("/api/users/{user_id}/erase", response_model=EraseOut, tags=["admin"],
          summary="Xóa dữ liệu cá nhân theo yêu cầu của người dùng (admin)",
          description="Khóa tài khoản và thu hồi token, rồi lần lượt yêu cầu Order (ẩn danh người đặt trong đơn, xóa giỏ), "
                      "Restaurant (gỡ quán của chủ quán, xóa ảnh), Review (ẩn danh tên người viết), Notification (xóa "
                      "thông báo); cuối cùng thay họ tên, email, số điện thoại trong Auth. Từ chối 409 khi tài khoản còn "
                      "đơn đang xử lý (tài khoản vẫn bị khóa để không phát sinh đơn mới). Gọi lại nhiều lần an toàn.")
def erase_user(user_id: uuid.UUID, me_: dict = Depends(admin_only), conn: sqlite3.Connection = Depends(conn_dep)):
    target = load_user(conn, str(user_id))
    if target["id"] == me_["id"]:
        raise ApiError(400, "SELF_ACTION", "Không thể tự xóa dữ liệu tài khoản của chính mình")
    return erase_everywhere(conn, target)


def erase_everywhere(conn: sqlite3.Connection, target: dict) -> dict:
    with transaction(conn):
        if target["role"] == "admin" and target["status"] == "active" and _active_admins(conn) <= 1:
            raise ApiError(409, "LAST_ADMIN", "Không thể xóa admin cuối cùng")
        # khóa + thu hồi token trước: trong lúc xóa, tài khoản không tạo thêm đơn hay đánh giá
        conn.execute("UPDATE users SET status='locked', token_version=token_version+1, updated_at=? WHERE id=?",
                     (now_iso(), target["id"]))
    results = {}
    for name, label in ERASE_STEPS:
        status, body = call("POST", f"{config.service_url(name)}/internal/users/{target['id']}/erase", label,
                            internal=True, allow=(409,))
        if status == 409:
            detail = body.get("detail") if isinstance(body, dict) else None
            code = body.get("code") if isinstance(body, dict) else None
            raise ApiError(409, code or "ERASE_BLOCKED",
                           f"{detail or label + ' chưa xóa được dữ liệu'}. Tài khoản đã được khóa; xử lý xong rồi thực hiện lại.")
        results[name.lower()] = body
    ts = now_iso()
    with transaction(conn):
        # password_hash "!" không phải bcrypt hợp lệ -> không mật khẩu nào khớp
        conn.execute("UPDATE users SET name=?, email=?, phone=NULL, password_hash='!', status='locked', avatar_url=NULL, "
                     "bank_bin=NULL, bank_account=NULL, bank_holder=NULL, "
                     "erased_at=COALESCE(erased_at, ?), updated_at=? WHERE id=?",
                     (ERASED_NAME, f"da-xoa-{target['id']}@tdtu-food.invalid", ts, ts, target["id"]))
        conn.execute("DELETE FROM login_attempts WHERE substr(key, 1, ?) = ?",
                     (len(target["email"]) + 1, target["email"] + "|"))
        conn.execute("DELETE FROM otp_codes WHERE user_id=?", (target["id"],))
    remove_avatar_file(target.get("avatar_url"))
    _journal_erasure(target["id"], ts)
    return {"user": public(load_user(conn, target["id"])), "services": results}


# Nhật ký yêu cầu xóa: chỉ ghi ID (không có dữ liệu cá nhân), nằm cạnh auth.db nhưng không thuộc bản sao lưu nên không
# bị khôi phục đè. Khôi phục bản sao lưu cũ hơn lần xóa -> Auth khởi động lại sẽ tự xóa lại người đó ở mọi service.
_journal_lock = threading.Lock()


def erasure_log_path():
    return config.data_dir() / "erasures.log"


def _journal_erasure(user_id: str, ts: str) -> None:
    with _journal_lock, open(erasure_log_path(), "a", encoding="utf-8") as f:
        f.write(f"{user_id}\t{ts}\n")


def erased_ids() -> list[str]:
    try:
        lines = erasure_log_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out: list[str] = []
    for line in lines:
        uid = line.split("\t", 1)[0].strip()
        try:
            uid = str(uuid.UUID(uid))
        except ValueError:
            continue
        if uid not in out:
            out.append(uid)
    return out


def replay_erasures() -> int:
    """Xóa lại những tài khoản có trong nhật ký mà DB hiện tại chưa xóa. Trả về số tài khoản chưa xóa lại được."""
    pending = 0
    conn = db.connect()
    try:
        for uid in erased_ids():
            u = row(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
            if not u or u.get("erased_at"):
                continue
            try:
                erase_everywhere(conn, u)
                log.warning("Đã áp dụng lại yêu cầu xóa dữ liệu của tài khoản %s (dữ liệu khôi phục từ bản sao lưu cũ)", uid)
            except ApiError as e:
                pending += 1
                log.warning("Chưa áp dụng lại được yêu cầu xóa dữ liệu của %s: %s (%s)", uid, e.message, e.code)
    finally:
        conn.close()
    return pending


def _replay_erasures_loop(attempts: int = 40, every: float = 30.0) -> None:
    """Chạy nền khi Auth khởi động: các service khác có thể chưa sẵn sàng nên thử lại mỗi 30 giây, tối đa 20 phút."""
    for _ in range(attempts):
        try:
            if replay_erasures() == 0:
                return
        except Exception:                      # noqa: BLE001 - không để luồng nền làm sập Auth
            log.exception("Lỗi khi áp dụng lại nhật ký xóa dữ liệu")
        time.sleep(every)
