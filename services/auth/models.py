"""Auth Service - bảng USERS và các model vào/ra."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from common.validators import STRICT, text

Role = Literal["sinh_vien", "chu_quan", "admin"]
UserStatus = Literal["active", "locked"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,            -- luôn lưu chữ thường
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('sinh_vien','chu_quan','admin')),
    phone         TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','locked')),
    token_version INTEGER NOT NULL DEFAULT 0,      -- tăng khi khóa/đổi vai trò/đăng xuất -> token cũ hết hiệu lực
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
"""

PHONE = r"^0\d{9}$"


def _password_rules(v: str) -> str:
    if not v.strip():
        raise ValueError("mật khẩu không được chỉ chứa khoảng trắng")
    if len(v.encode("utf-8")) > 72:
        raise ValueError("mật khẩu tối đa 72 byte (khoảng 24 ký tự tiếng Việt có dấu)")
    return v


class RegisterIn(BaseModel):
    model_config = STRICT
    name: text(2, 100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    role: Literal["sinh_vien", "chu_quan"] = "sinh_vien"     # không cho tự đăng ký admin
    phone: str | None = Field(default=None, pattern=PHONE)

    _pw = field_validator("password")(_password_rules)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class LoginIn(BaseModel):
    model_config = STRICT
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class ProfileUpdate(BaseModel):
    model_config = STRICT
    name: text(2, 100) | None = None
    phone: str | None = Field(default=None, pattern=PHONE)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    phone: str | None = None
    status: UserStatus
    created_at: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class RoleUpdate(BaseModel):
    model_config = STRICT
    role: Role


class StatusUpdate(BaseModel):
    model_config = STRICT
    status: UserStatus


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
