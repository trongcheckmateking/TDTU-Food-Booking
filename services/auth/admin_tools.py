"""Công cụ quản trị của Auth Service (chạy offline trên DB của chính Auth): tạo tài khoản admin.

Không có API đăng ký admin; admin đầu tiên chỉ tạo được bằng lệnh `python manage.py create-admin`
(trong Docker: `docker compose exec auth python -m services.auth.admin_tools --email ... --name ...`).
"""
from __future__ import annotations

import sqlite3

from common.db import new_id, now_iso

from .app import _migrate, db, hash_password
from .models import RegisterIn


def create_admin(email: str, name: str, password: str) -> bool:
    """Tạo admin; trả False nếu email đã tồn tại. Dữ liệu sai -> ValueError (cùng luật với API đăng ký)."""
    try:
        # người vận hành tạo admin cho chính mình nên cũng là người đồng ý điều khoản
        data = RegisterIn(name=name, email=email, password=password, accept_terms=True)
    except Exception as e:  # pydantic.ValidationError
        raise ValueError(f"Dữ liệu không hợp lệ: {e}") from None
    db.init()
    _migrate()
    conn = db.connect()
    ts = now_iso()
    try:
        conn.execute("INSERT INTO users (id,name,email,password_hash,role,phone,status,token_version,created_at,"
                     "updated_at,terms_accepted_at) VALUES (?,?,?,?, 'admin', NULL, 'active', 0, ?, ?, ?)",
                     (new_id(), data.name, data.email, hash_password(data.password), ts, ts, ts))
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def main() -> None:
    import argparse
    import getpass
    import os
    import sys

    ap = argparse.ArgumentParser(description="Tạo tài khoản admin (mật khẩu lấy từ ADMIN_PASSWORD hoặc hỏi khi chạy)")
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")         # cửa sổ lệnh Windows (cp1252) không in được tiếng Việt
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Mật khẩu (từ 8 ký tự, có cả chữ và số): ")
    try:
        created = create_admin(a.email, a.name, pw)
    except ValueError as e:
        sys.exit(str(e))
    print("Đã tạo admin" if created else "Email đã tồn tại:", a.email.lower())
    sys.exit(0 if created else 1)


if __name__ == "__main__":
    main()
