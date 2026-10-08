"""SQLite dùng chung: mỗi request mở một kết nối riêng, giao dịch tường minh.

- Thay cho một kết nối toàn cục `check_same_thread=False` của bản nguồn.
- WAL + busy_timeout để nhiều tiến trình/luồng ghi tuần tự an toàn.
- `transaction(conn)` dùng BEGIN IMMEDIATE: khóa ghi ngay đầu giao dịch,
  rollback tự động khi có lỗi.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import config


class Database:
    def __init__(self, filename: str, schema_sql: str):
        self.filename = filename
        self.schema_sql = schema_sql

    @property
    def path(self) -> Path:
        return config.data_dir() / self.filename

    def connect(self) -> sqlite3.Connection:
        # Mỗi request một kết nối riêng. FastAPI có thể mở kết nối (dependency) và chạy endpoint ở 2 luồng khác
        # nhau của threadpool, nên tắt kiểm tra cùng luồng; kết nối không bao giờ dùng đồng thời bởi 2 request.
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def init(self) -> None:
        """Tạo schema nếu chưa có (idempotent)."""
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(self.schema_sql)
        finally:
            conn.close()

    def dependency(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def check(self) -> bool:
        try:
            conn = self.connect()
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()
        except sqlite3.Error:
            return False


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Thời điểm UTC theo ISO 8601, ví dụ 2026-10-05T03:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def paginate(conn: sqlite3.Connection, sql: str, args: list, page: int, page_size: int, order_by: str) -> dict:
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    items = rows(conn.execute(f"{sql} ORDER BY {order_by} LIMIT ? OFFSET ?", [*args, page_size, (page - 1) * page_size]))
    return {"items": items, "total": total, "page": page, "page_size": page_size}
