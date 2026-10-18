"""Auth Service - bảng USERS và các model vào/ra."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, StrictBool, ValidationInfo, field_validator

from common.validators import STRICT, text

from .banks import ACCOUNT, check_bin, normalize_holder

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
    updated_at    TEXT NOT NULL,
    terms_accepted_at TEXT,                        -- lúc đồng ý Điều khoản + Chính sách quyền riêng tư (bằng chứng đồng ý)
    erased_at     TEXT,                            -- lúc xóa dữ liệu cá nhân theo yêu cầu (tên/email/SĐT đã ẩn danh)
    avatar_url    TEXT,                            -- /avatars/<tên ngẫu nhiên>.jpg|png|webp (tệp trong DATA_DIR/avatars)
    -- tài khoản nhận tiền của chủ quán: sinh viên chuyển khoản trước bằng mã VietQR tạo từ 3 cột này
    bank_bin      TEXT,                            -- mã ngân hàng 6 số của Napas (banks.py)
    bank_account  TEXT,                            -- số tài khoản 6-19 chữ số
    bank_holder   TEXT                             -- tên chủ tài khoản, in hoa không dấu
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
-- Đăng nhập sai liên tiếp theo cặp (email, IP): quá ngưỡng thì khóa tạm, chống dò mật khẩu
CREATE TABLE IF NOT EXISTS login_attempts (
    key          TEXT PRIMARY KEY,                 -- email|ip
    fails        INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    locked_until TEXT
);
"""

PHONE = r"^0\d{9}$"


def _password_rules(v: str) -> str:
    if not v.strip():
        raise ValueError("mật khẩu không được chỉ chứa khoảng trắng")
    if len(v.encode("utf-8")) > 72:
        raise ValueError("mật khẩu tối đa 72 byte (khoảng 24 ký tự tiếng Việt có dấu)")
    if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
        raise ValueError("mật khẩu phải có cả chữ và số")
    return v


def _payout_field(v: str | None, field: str) -> str | None:
    if field == "bank_bin":
        return check_bin(v)
    if field == "bank_holder":
        return normalize_holder(v)
    return v


class RegisterIn(BaseModel):
    model_config = STRICT
    name: text(2, 100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["sinh_vien", "chu_quan"] = "sinh_vien"     # không cho tự đăng ký admin
    phone: str | None = Field(default=None, pattern=PHONE)
    accept_terms: StrictBool = Field(description="Phải là true: đồng ý Điều khoản sử dụng và Chính sách quyền riêng tư")
    # bắt buộc với chủ quán: sinh viên thanh toán trước bằng mã VietQR vào tài khoản này
    bank_bin: str | None = Field(default=None, validate_default=True, pattern=r"^[0-9]{6}$",
                                 description="Chủ quán: mã ngân hàng 6 số lấy từ GET /api/banks")
    bank_account: str | None = Field(default=None, validate_default=True, pattern=ACCOUNT,
                                     description="Chủ quán: số tài khoản nhận tiền (6-19 chữ số)")
    bank_holder: str | None = Field(default=None, validate_default=True, max_length=60,
                                    description="Chủ quán: tên chủ tài khoản, tự đổi sang in hoa không dấu")

    _pw = field_validator("password")(_password_rules)

    @field_validator("bank_bin", "bank_account", "bank_holder")
    @classmethod
    def _payout_for_owner(cls, v: str | None, info: ValidationInfo) -> str | None:
        owner = info.data.get("role") == "chu_quan"
        if owner and not v:
            raise ValueError("chủ quán cần khai báo tài khoản ngân hàng nhận tiền")
        if not owner and v is not None:
            raise ValueError("chỉ tài khoản chủ quán khai báo tài khoản nhận tiền")
        return _payout_field(v, info.field_name) if v else v

    @field_validator("accept_terms")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("cần đồng ý Điều khoản sử dụng và Chính sách quyền riêng tư")
        return v

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


class PayoutIn(BaseModel):
    model_config = STRICT
    bank_bin: str = Field(pattern=r"^[0-9]{6}$", description="Mã ngân hàng 6 số lấy từ GET /api/banks")
    bank_account: str = Field(pattern=ACCOUNT, description="Số tài khoản nhận tiền (6-19 chữ số)")
    bank_holder: str = Field(min_length=2, max_length=60, description="Tên chủ tài khoản, tự đổi sang in hoa không dấu")
    password: str = Field(min_length=1, max_length=200, description="Mật khẩu hiện tại: đổi nơi nhận tiền cần xác nhận lại")

    @field_validator("bank_bin", "bank_holder")
    @classmethod
    def _check(cls, v: str, info: ValidationInfo) -> str:
        return _payout_field(v, info.field_name)


class PayoutOut(BaseModel):
    user_id: str
    bank_bin: str
    bank_name: str
    bank_account: str
    bank_holder: str


class BankOut(BaseModel):
    bin: str = Field(description="Mã ngân hàng 6 số của Napas, dùng trong mã VietQR")
    code: str
    name: str


class PasswordChange(BaseModel):
    model_config = STRICT
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=72)

    _pw = field_validator("new_password")(_password_rules)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    phone: str | None = None
    status: UserStatus
    created_at: str
    terms_accepted_at: str | None = Field(None, description="Lúc đồng ý Điều khoản sử dụng và Chính sách quyền riêng tư")
    erased_at: str | None = Field(None, description="Lúc xóa dữ liệu cá nhân theo yêu cầu (null = chưa xóa)")
    avatar_url: str | None = Field(None, description="Ảnh đại diện: /avatars/<tệp> trên Auth Service, null = chưa có")
    bank_bin: str | None = Field(None, description="Chủ quán: mã ngân hàng nhận tiền")
    bank_name: str | None = Field(None, description="Chủ quán: tên ngân hàng nhận tiền")
    bank_account: str | None = Field(None, description="Chủ quán: số tài khoản nhận tiền")
    bank_holder: str | None = Field(None, description="Chủ quán: tên chủ tài khoản")


class EraseOut(BaseModel):
    user: UserOut
    services: dict[str, dict] = Field(description="Kết quả từng service: đơn / đánh giá đã ẩn danh, quán đã gỡ, "
                                                  "thông báo đã xóa")


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
