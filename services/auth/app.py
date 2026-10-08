"""Auth Service (cổng 8001): đăng ký, đăng nhập, hồ sơ, quản lý tài khoản.

Chạy: python -m uvicorn services.auth.app:app --port 8001 (từ thư mục gốc, hoặc dùng manage.py start)
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt
from fastapi import Depends, Query, Security
from fastapi.security import HTTPAuthorizationCredentials

from common import config
from common.app import create_app
from common.db import Database, now_iso, new_id, paginate, row, transaction
from common.errors import ApiError
from common.http import call
from common.security import bearer
from common.validators import Page, PageSize

from .models import (SCHEMA, LoginIn, ProfileUpdate, RegisterIn, RoleUpdate, StatusUpdate, TokenOut, UserOut,
                     UserPage)

db = Database("auth.db", SCHEMA)
ISSUER = "tdtu-food-booking-auth"
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=4))

app = create_app("auth", "Auth Service", "Đăng ký, đăng nhập JWT, hồ sơ, phân quyền và quản lý tài khoản.", db,
                 on_startup=lambda: config.jwt_secret())
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


def public(u: dict) -> dict:
    return {k: u[k] for k in ("id", "name", "email", "role", "phone", "status", "created_at")}


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


def current_user(creds: HTTPAuthorizationCredentials | None = Security(bearer),
                 conn: sqlite3.Connection = Depends(conn_dep)) -> dict:
    if creds is None or not creds.credentials:
        raise ApiError(401, "UNAUTHORIZED", "Cần đăng nhập (thiếu Bearer token)")
    try:
        payload = jwt.decode(creds.credentials, config.jwt_secret(), algorithms=["HS256"], issuer=ISSUER,
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


# ------------------------------------------------------------------ người dùng
@app.post("/api/users/register", response_model=UserOut, status_code=201, tags=["auth"],
          summary="Đăng ký tài khoản sinh viên hoặc chủ quán")
def register(data: RegisterIn, conn: sqlite3.Connection = Depends(conn_dep)):
    uid, ts = new_id(), now_iso()
    try:
        with transaction(conn):
            conn.execute("INSERT INTO users (id,name,email,password_hash,role,phone,status,token_version,created_at,"
                         "updated_at) VALUES (?,?,?,?,?,?, 'active', 0, ?, ?)",
                         (uid, data.name, data.email, hash_password(data.password), data.role, data.phone, ts, ts))
    except sqlite3.IntegrityError as e:
        if "users.email" in str(e):
            raise ApiError(409, "EMAIL_EXISTS", "Email đã được sử dụng")
        raise
    return public(load_user(conn, uid))


@app.post("/api/users/login", response_model=TokenOut, tags=["auth"], summary="Đăng nhập, nhận access_token")
def login(data: LoginIn, conn: sqlite3.Connection = Depends(conn_dep)):
    u = row(conn.execute("SELECT * FROM users WHERE email=?", (data.email,)).fetchone())
    if not u:
        check_password(data.password, _DUMMY_HASH)          # giữ thời gian phản hồi tương đương
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu")
    if not check_password(data.password, u["password_hash"]):
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu")
    if u["status"] != "active":
        raise ApiError(403, "ACCOUNT_LOCKED", "Tài khoản đã bị khóa, liên hệ quản trị viên")
    return {"access_token": issue_token(u), "token_type": "bearer", "expires_in": token_hours() * 3600,
            "user": public(u)}


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


# ------------------------------------------------------------------ admin
@app.get("/api/users", response_model=UserPage, tags=["admin"], summary="Danh sách tài khoản (admin)")
def list_users(role: Literal["sinh_vien", "chu_quan", "admin"] | None = None,
               status: Literal["active", "locked"] | None = None,
               q: str | None = Query(None, max_length=100), page: Page = 1, page_size: PageSize = 20,
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
    if target["status"] == data.status:
        return public(target)
    with transaction(conn):
        if data.status == "locked" and target["role"] == "admin" and _active_admins(conn) <= 1:
            raise ApiError(409, "LAST_ADMIN", "Không thể khóa admin cuối cùng")
        conn.execute("UPDATE users SET status=?, token_version=token_version+1, updated_at=? WHERE id=?",
                     (data.status, now_iso(), target["id"]))
    return public(load_user(conn, target["id"]))
