"""Xác thực cho Restaurant, Order, Notification, Review.

Người dùng: gửi `Authorization: Bearer <token>`; service gọi Auth `GET /api/users/me`
để lấy danh tính + vai trò + trạng thái hiện tại (tài khoản bị khóa bị từ chối ngay).
Service nội bộ: gửi `X-Internal-Key` (so sánh hằng thời gian).
"""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .errors import ApiError
from .http import call

ROLES = ("sinh_vien", "chu_quan", "admin")
bearer = HTTPBearer(auto_error=False, description="Token lấy từ POST /api/users/login của Auth Service")
internal_header = APIKeyHeader(name="X-Internal-Key", auto_error=False,
                               description="Khóa nội bộ, chỉ dùng giữa các service")


@dataclass(frozen=True)
class AuthUser:
    id: str
    role: str
    name: str
    email: str
    phone: str | None = None


def _parse_user(data: dict) -> AuthUser:
    try:
        uid = str(uuid.UUID(str(data["id"])))
        role = data["role"]
        if role not in ROLES or data.get("status", "active") != "active":
            raise ValueError
        return AuthUser(id=uid, role=role, name=str(data.get("name", "")), email=str(data.get("email", "")),
                        phone=data.get("phone"))
    except (KeyError, ValueError, TypeError):
        raise ApiError(502, "UPSTREAM_BAD_RESPONSE", "Auth Service trả thông tin người dùng không đúng định dạng")


def verify_token(token: str) -> AuthUser:
    status, data = call("GET", f"{config.service_url('AUTH')}/api/users/me", "Auth Service",
                        token=token, allow=(401, 403))
    if status == 401:
        raise ApiError(401, data.get("code", "TOKEN_INVALID") if isinstance(data, dict) else "TOKEN_INVALID",
                       "Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    if status == 403:
        raise ApiError(403, data.get("code", "ACCOUNT_LOCKED") if isinstance(data, dict) else "ACCOUNT_LOCKED",
                       data.get("detail", "Tài khoản đã bị khóa") if isinstance(data, dict) else "Tài khoản đã bị khóa")
    return _parse_user(data)


def current_user(creds: HTTPAuthorizationCredentials | None = Security(bearer)) -> AuthUser:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise ApiError(401, "UNAUTHORIZED", "Cần đăng nhập (thiếu Bearer token)")
    return verify_token(creds.credentials)


def optional_user(creds: HTTPAuthorizationCredentials | None = Security(bearer)) -> AuthUser | None:
    if creds is None or not creds.credentials:
        return None
    return verify_token(creds.credentials)


def require_roles(*roles: str):
    def checker(user: AuthUser = Depends(current_user)) -> AuthUser:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này")
        return user
    return checker


def require_internal(key: str | None = Security(internal_header)) -> None:
    if not key or not hmac.compare_digest(key.encode(), config.internal_key().encode()):
        raise ApiError(403, "INTERNAL_ONLY", "API nội bộ, chỉ service tin cậy được gọi")


def bearer_token(creds: HTTPAuthorizationCredentials | None = Security(bearer)) -> str | None:
    return creds.credentials if creds else None
