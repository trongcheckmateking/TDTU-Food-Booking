"""Cấu hình chung, đọc từ biến môi trường và tệp .env ở thư mục gốc dự án.

Không có giá trị bí mật mặc định: JWT_SECRET và INTERNAL_KEY phải được cấu hình
(chạy `python manage.py init-env` để sinh tệp .env cho máy local).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def load_env(path: Path | None = None) -> None:
    """Nạp KEY=VALUE từ .env (không ghi đè biến môi trường đã có)."""
    global _loaded
    if _loaded and path is None:
        return
    env_file = path or Path(os.environ.get("TDTU_ENV_FILE", ROOT / ".env"))
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    _loaded = True


def get(name: str, default: str | None = None) -> str | None:
    load_env()
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def require(name: str, min_length: int = 1) -> str:
    value = get(name)
    if not value or len(value) < min_length:
        raise RuntimeError(
            f"Thiếu cấu hình {name} (tối thiểu {min_length} ký tự). "
            "Chạy `python manage.py init-env` để tạo tệp .env cho máy local."
        )
    return value


def get_int(name: str, default: int) -> int:
    try:
        return int(get(name, str(default)))
    except ValueError:
        raise RuntimeError(f"Cấu hình {name} phải là số nguyên")


def data_dir() -> Path:
    raw = get("DATA_DIR", "data")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def service_url(name: str) -> str:
    defaults = {"AUTH": 8001, "RESTAURANT": 8002, "ORDER": 8003, "NOTIFICATION": 8004, "REVIEW": 8005}
    return get(f"{name}_URL", f"http://127.0.0.1:{defaults[name]}").rstrip("/")


def cors_origins() -> list[str]:
    raw = get("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def jwt_secret() -> str:
    return require("JWT_SECRET", 32)


def internal_key() -> str:
    return require("INTERNAL_KEY", 24)


def http_timeout() -> float:
    try:
        return float(get("HTTP_TIMEOUT", "5"))
    except ValueError:
        return 5.0
