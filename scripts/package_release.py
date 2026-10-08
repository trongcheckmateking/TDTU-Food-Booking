"""Đóng gói bản bàn giao: TDTU_FoodBooking_Final.zip (một thư mục gốc TDTU_FoodBooking_Final/).

  python scripts/package_release.py [--out ../TDTU_FoodBooking_Final.zip]
Loại bỏ: .env thật, dữ liệu, log, PID, cache, venv, node_modules, target/ (Java), bin/ (Go), .git, DB/WAL/SHM/H2,
tệp build (.jar, .exe, .class), tệp hệ điều hành. Người nhận build lại bằng `python manage.py build`.
Quét nội dung: khóa bí mật trong .env hiện tại, private key, JWT thật; dừng nếu phát hiện.
In SHA-256 của tệp ZIP.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "TDTU_FoodBooking_Final"
EXCLUDE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".idea",
                ".vscode", "data", "logs", ".run", "target", "bin"}
EXCLUDE_FILES = [".env", "*.pyc", "*.pyo", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.log", ".DS_Store",
                 "Thumbs.db", "*.dot", "*.tmp", "*.swp", "*.mv.db", "*.trace.db", "*.jar", "*.exe", "*.class"]
TEXT_EXT = {".py", ".md", ".txt", ".json", ".js", ".html", ".css", ".sh", ".ps1", ".ini", ".example", ".svg", ".gitignore",
            ".java", ".go", ".php", ".xml", ".properties", ".sql", ".yml", ".mod", ".sum", ".cmd", ""}
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def collect() -> list[Path]:
    files = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.is_file() and not any(fnmatch.fnmatch(p.name, pat) for pat in EXCLUDE_FILES):
            files.append(p)
    return files


def secrets_from_env() -> list[str]:
    env = ROOT / ".env"
    vals = []
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and line.split("=", 1)[0].strip() in ("JWT_SECRET", "INTERNAL_KEY", "POSTGRES_PASSWORD"):
                v = line.split("=", 1)[1].strip()
                if len(v) >= 16:
                    vals.append(v)
    return vals


def scan(files: list[Path]) -> list[str]:
    problems, secrets = [], secrets_from_env()
    for p in files:
        if p.suffix.lower() not in TEXT_EXT:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        rel = p.relative_to(ROOT)
        for s in secrets:
            if s in text:
                problems.append(f"{rel}: chứa giá trị khóa bí mật của .env")
        if ("PRIVATE" + " KEY-----") in text:
            problems.append(f"{rel}: chứa private key")
        if JWT_RE.search(text):
            problems.append(f"{rel}: chứa chuỗi giống JWT")
        if p.name == ".env.example" and re.search(r"^(JWT_SECRET|INTERNAL_KEY|POSTGRES_PASSWORD)=\S", text, re.M):
            problems.append(f"{rel}: .env.example không được chứa giá trị khóa")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / f"{NAME}.zip"))
    args = ap.parse_args()
    files = collect()
    problems = scan(files)
    if problems:
        print("DỪNG: phát hiện nội dung nhạy cảm:\n  " + "\n  ".join(problems))
        sys.exit(1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, f"{NAME}/{p.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        if bad:
            sys.exit(f"ZIP lỗi tại {bad}")
        count = len(z.namelist())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.with_suffix(".zip.sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"Đã tạo {out} ({count} tệp, {out.stat().st_size / 1024:.0f} KB)")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
