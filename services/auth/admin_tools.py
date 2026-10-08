"""Công cụ quản trị của Auth Service (chạy offline trên DB của chính Auth): tạo tài khoản admin.

Không có API đăng ký admin; admin đầu tiên chỉ tạo được bằng lệnh `python manage.py create-admin`.
"""
from __future__ import annotations

import sqlite3

from common.db import new_id, now_iso

from .app import db, hash_password
from .models import RegisterIn


def create_admin(email: str, name: str, password: str) -> bool:
    """Tạo admin; trả False nếu email đã tồn tại. Dữ liệu sai -> ValueError (cùng luật với API đăng ký)."""
    try:
        data = RegisterIn(name=name, email=email, password=password)
    except Exception as e:  # pydantic.ValidationError
        raise ValueError(f"Dữ liệu không hợp lệ: {e}") from None
    db.init()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO users (id,name,email,password_hash,role,phone,status,token_version,created_at,"
                     "updated_at) VALUES (?,?,?,?, 'admin', NULL, 'active', 0, ?, ?)",
                     (new_id(), data.name, data.email, hash_password(data.password), now_iso(), now_iso()))
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()
