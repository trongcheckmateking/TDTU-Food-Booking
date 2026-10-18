"""Sao lưu / khôi phục dữ liệu của 5 service (mỗi service một cơ sở dữ liệu) và ảnh tải lên.

  python manage.py backup                  tạo 1 bản vào BACKUP_DIR (mặc định backups/), giữ BACKUP_KEEP bản mới nhất
  python manage.py backup --loop           chạy liên tục, mỗi BACKUP_INTERVAL_HOURS giờ một bản (container sao lưu)
  python manage.py backup --list           liệt kê các bản sao lưu
  python manage.py backup --verify TỆP     kiểm tra tệp sao lưu (manifest + SHA-256 từng tệp)
  python manage.py restore TỆP --yes       khôi phục khi 5 service đã dừng; dữ liệu đang có được chuyển sang
                                           thư mục truoc-khoi-phuc-<thời điểm>/ cạnh dữ liệu, không bị xóa

Lấy bản sao nhất quán khi service vẫn đang chạy:
  - SQLite (Auth, Restaurant, Review): API backup của SQLite.
  - H2 (Order): GET /internal/backup của Order Service (lệnh BACKUP TO); Order đã dừng thì chép thẳng tệp.
  - PostgreSQL (Notification): pg_dump -Fc. Lấy pg_dump từ PG_DUMP, PATH, hoặc chạy trong image Docker PG_DOCKER_IMAGE.
  - Ảnh quán / món: thư mục uploads của Restaurant; ảnh đại diện: thư mục avatars của Auth.
Chỉ dùng thư viện chuẩn của Python để chạy được trong container sao lưu tối giản (PostgreSQL client + python3).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from common import config  # noqa: E402  (config chỉ dùng thư viện chuẩn)

PREFIX = "tdtu-backup-"
FORMAT = 1
SQLITE = {"auth": "auth.db", "restaurant": "restaurant.db", "review": "review.db"}
ORDER_FILE = "order.mv.db"
PG_FILE = "notification.dump"
SERVICES = ("auth", "restaurant", "order", "notification", "review")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")       # tên ảnh trong manifest: không có thư mục, không ..
ERASURES = "erasures.log"
FOLDERS = {"uploads": "restaurant", "avatars": "auth"}   # thư mục ảnh -> service sở hữu (nằm trong DATA_DIR của service)                     # nhật ký yêu cầu xóa dữ liệu của Auth (chỉ có ID), xem services/auth/app.py
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # gọi nội bộ không đi qua proxy


class BackupError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[sao lưu {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _path(raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def data_dir(service: str) -> Path:
    """Thư mục dữ liệu của một service: <SERVICE>_DATA_DIR (Docker: mỗi service một volume), mặc định DATA_DIR."""
    return _path(config.get(f"{service.upper()}_DATA_DIR") or config.get("DATA_DIR", "data"))


def backup_dir() -> Path:
    p = _path(config.get("BACKUP_DIR", "backups"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with NO_PROXY.open(url, timeout=timeout) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def running_services() -> list[str]:
    return [s for s in SERVICES if http_ok(config.service_url(s.upper()) + "/health")]


# ------------------------------------------------------------------ từng loại cơ sở dữ liệu
def dump_sqlite(src: Path, dest: Path) -> None:
    if not src.is_file():
        raise BackupError(f"Không thấy {src}")
    s = sqlite3.connect(src.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
        ok = d.execute("PRAGMA quick_check").fetchone()[0]
        if ok != "ok":
            raise BackupError(f"Bản sao {dest.name} không toàn vẹn: {ok}")
    finally:
        d.close()
        s.close()


def _h2_in_use(path: Path) -> bool:
    """Order (Java) giữ khóa trên tệp H2 khi đang chạy; chép tệp đang được ghi sẽ ra bản hỏng."""
    try:
        with open(path, "r+b") as f:
            if os.name == "nt":
                return False                       # Windows: khóa bắt buộc, lệnh chép sẽ tự báo lỗi
            import fcntl
            try:
                fcntl.lockf(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.lockf(f, fcntl.LOCK_UN)
            return False
    except PermissionError:
        return True


def dump_h2(dest: Path) -> str:
    req = urllib.request.Request(config.service_url("ORDER") + "/internal/backup",
                                 headers={"X-Internal-Key": config.internal_key()})
    with tempfile.TemporaryDirectory() as tmp:
        tmpzip = Path(tmp) / "order.zip"
        try:
            with NO_PROXY.open(req, timeout=600) as r, open(tmpzip, "wb") as out:
                shutil.copyfileobj(r, out)
        except urllib.error.HTTPError as e:
            raise BackupError(f"Order Service từ chối sao lưu (HTTP {e.code})")
        except (urllib.error.URLError, OSError):
            src = data_dir("order") / ORDER_FILE
            if not src.is_file():
                raise BackupError("Order Service không chạy và không thấy " + ORDER_FILE)
            if _h2_in_use(src):
                raise BackupError("Không gọi được Order Service nhưng tệp H2 đang được dùng: kiểm tra ORDER_URL")
            try:
                shutil.copy2(src, dest)
            except OSError as e:
                raise BackupError(f"Không chép được {src.name} (Order Service còn chạy?): {e}")
            return "chép tệp (Order Service đang dừng)"
        with zipfile.ZipFile(tmpzip) as z:
            member = next((n for n in z.namelist() if n.endswith(".mv.db")), None)
            if not member:
                raise BackupError("Bản sao của Order không có tệp .mv.db")
            with z.open(member) as f, open(dest, "wb") as out:
                shutil.copyfileobj(f, out)
    return "H2 BACKUP TO"


def pg_params() -> dict:
    u = urlsplit(config.require("NOTIFICATION_DB_URL", 10))
    q = parse_qs(u.query)
    return {"host": u.hostname or "127.0.0.1", "port": str(u.port or 5432), "user": unquote(u.username or ""),
            "password": unquote(u.password or ""), "dbname": unquote(u.path.lstrip("/")),
            "sslmode": q.get("sslmode", ["prefer"])[0]}


def pg_command(tool: str, args: list[str]) -> tuple[list[str], dict]:
    """pg_dump / pg_restore: đường dẫn trong PG_DUMP / PG_RESTORE, có trong PATH, hoặc chạy bằng Docker."""
    p = pg_params()
    env = {**os.environ, "PGPASSWORD": p["password"], "PGSSLMODE": p["sslmode"]}   # mật khẩu không nằm trên dòng lệnh
    local = config.get(tool.upper()) or shutil.which(tool)
    if local:
        return [local, "-h", p["host"], "-p", p["port"], "-U", p["user"], *args], env
    docker = shutil.which("docker")
    if not docker:
        raise BackupError(f"Không tìm thấy {tool}: cài PostgreSQL client, đặt {tool.upper()}=<đường dẫn>, hoặc cài Docker")
    host = "host.docker.internal" if p["host"] in ("127.0.0.1", "localhost", "::1") else p["host"]
    image = config.get("PG_DOCKER_IMAGE", "postgres:16")
    return [docker, "run", "--rm", "-i", "--add-host=host.docker.internal:host-gateway", "-e", "PGPASSWORD",
            "-e", "PGSSLMODE", image, tool, "-h", host, "-p", p["port"], "-U", p["user"], *args], env


def dump_postgres(dest: Path) -> str:
    args = ["-Fc", "--no-owner", "--no-privileges", "-d", pg_params()["dbname"]]
    schema = config.get("NOTIFICATION_DB_SCHEMA")
    if schema:
        args += ["-n", schema]
    cmd, env = pg_command("pg_dump", args)
    with open(dest, "wb") as out:
        r = subprocess.run(cmd, env=env, stdout=out, stderr=subprocess.PIPE, timeout=1800)
    if r.returncode != 0 or dest.stat().st_size == 0:
        raise BackupError("pg_dump lỗi: " + r.stderr.decode("utf-8", "replace").strip()[-500:])
    return "pg_dump" + (" (Docker)" if Path(cmd[0]).stem.lower() == "docker" else "")


def restore_postgres(src: Path) -> None:
    cmd, env = pg_command("pg_restore", ["--clean", "--if-exists", "--no-owner", "--no-privileges",
                                         "--single-transaction", "-d", pg_params()["dbname"]])
    with open(src, "rb") as f:
        r = subprocess.run(cmd, env=env, stdin=f, capture_output=True, timeout=1800)
    if r.returncode != 0:
        raise BackupError("pg_restore lỗi: " + r.stderr.decode("utf-8", "replace").strip()[-500:])


def sync_erasures() -> int:
    """Gộp nhật ký yêu cầu xóa dữ liệu ở thư mục dữ liệu của Auth với bản chép trong BACKUP_DIR (cả 2 nơi giữ hợp).
    Mất cả ổ dữ liệu rồi khôi phục ở máy mới thì Auth vẫn biết cần xóa lại ai. Trả về số dòng."""
    places = [data_dir("auth") / ERASURES, backup_dir() / ERASURES]
    lines: list[str] = []
    for f in places:
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip() and line not in lines:
                    lines.append(line)
    if lines:
        text = "\n".join(lines) + "\n"
        for f in places:
            if f.parent.is_dir() and (not f.is_file() or f.read_text(encoding="utf-8") != text):
                f.write_text(text, encoding="utf-8")
    return len(lines)


# ------------------------------------------------------------------ tạo / kiểm tra / dọn
def _clean_leftovers(folder: Path) -> None:
    """Dọn tệp dở dang của lần trước bị dừng giữa chừng."""
    for p in folder.glob(f"{PREFIX}*.part"):
        p.unlink(missing_ok=True)
    for p in folder.glob(".tmp-*"):
        shutil.rmtree(p, ignore_errors=True)


def create() -> Path:
    folder = backup_dir()
    _clean_leftovers(folder)
    while True:                                   # tên theo giây: 2 lần chạy trong cùng 1 giây thì chờ sang giây sau
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        if not (folder / f"{PREFIX}{stamp}.tar.gz").exists():
            break
        time.sleep(0.2)
    work = folder / f".tmp-{stamp}"
    work.mkdir()
    items: dict[str, dict] = {}
    t0 = time.time()
    try:
        for service, name in SQLITE.items():
            dump_sqlite(data_dir(service) / name, work / name)
            items[service] = {"file": name, "method": "sqlite backup"}
        items["order"] = {"file": ORDER_FILE, "method": dump_h2(work / ORDER_FILE)}
        items["notification"] = {"file": PG_FILE, "method": dump_postgres(work / PG_FILE)}
        for v in items.values():
            v["bytes"] = (work / v["file"]).stat().st_size
            v["sha256"] = sha256(work / v["file"])
        for sub, service in FOLDERS.items():
            files = {}
            src = data_dir(service) / sub
            if src.is_dir():
                (work / sub).mkdir()
                for f in sorted(src.iterdir()):
                    if f.is_file() and SAFE_NAME.match(f.name):
                        shutil.copy2(f, work / sub / f.name)
                        files[f.name] = sha256(work / sub / f.name)
            items[sub] = {"dir": sub, "files": files}
        manifest = {"format": FORMAT, "app": "tdtu-food-booking", "created_at": stamp, "host": socket.gethostname(),
                    "items": items}
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        final = folder / f"{PREFIX}{stamp}.tar.gz"
        part = final.with_name(final.name + ".part")
        with tarfile.open(part, "w:gz", compresslevel=6) as tar:
            for p in sorted(work.iterdir()):
                tar.add(p, arcname=p.name)
        os.chmod(part, 0o600)                      # có dữ liệu cá nhân + mã băm mật khẩu: chỉ người vận hành đọc
        os.replace(part, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sync_erasures()
    size = final.stat().st_size
    log(f"Đã tạo {final.name} ({size / 1048576:.1f} MB, {len(items['uploads']['files'])} ảnh quán, "
        f"{len(items['avatars']['files'])} ảnh đại diện, {time.time() - t0:.1f} giây)")
    prune()
    return final


def list_backups() -> list[Path]:
    return sorted(backup_dir().glob(f"{PREFIX}*.tar.gz"))


def prune() -> None:
    keep = max(1, config.get_int("BACKUP_KEEP", 7))
    old = list_backups()[:-keep]
    for p in old:
        p.unlink(missing_ok=True)
        log(f"Xóa bản cũ {p.name} (giữ {keep} bản mới nhất)")


def _extract(archive: Path, dest: Path) -> dict:
    """Giải nén vào dest rồi kiểm tra manifest và SHA-256 từng tệp. Trả về manifest."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest, filter="data")
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    except (tarfile.TarError, OSError, ValueError) as e:
        raise BackupError(f"Tệp sao lưu hỏng hoặc không đúng định dạng: {e}")
    if manifest.get("app") != "tdtu-food-booking" or manifest.get("format") != FORMAT:
        raise BackupError("Không phải tệp sao lưu TDTU Food (hoặc khác phiên bản định dạng)")
    items = manifest["items"]
    missing = [s for s in SERVICES if s not in items] + ([] if "uploads" in items else ["uploads"])
    if missing:
        raise BackupError("Thiếu dữ liệu của: " + ", ".join(missing))
    for s in SERVICES:
        f = dest / items[s]["file"]
        if not f.is_file() or sha256(f) != items[s]["sha256"]:
            raise BackupError(f"Tệp {items[s]['file']} sai mã kiểm tra SHA-256 (bị sửa hoặc hỏng)")
    for folder in FOLDERS:                        # avatars có từ bản 16/10/2026; bản sao lưu cũ hơn không có
        for name, digest in items.get(folder, {}).get("files", {}).items():
            if not SAFE_NAME.match(name):
                raise BackupError(f"Tên ảnh không hợp lệ trong manifest: {name!r}")
            f = dest / folder / name
            if not f.is_file() or sha256(f) != digest:
                raise BackupError(f"Ảnh {folder}/{name} sai mã kiểm tra SHA-256")
    return manifest


def verify(archive: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        m = _extract(archive, Path(tmp))
    log(f"{archive.name}: hợp lệ (tạo lúc {m['created_at']}, {len(m['items']['uploads']['files'])} ảnh quán, "
        f"{len(m['items'].get('avatars', {}).get('files', {}))} ảnh đại diện)")
    return m


def _move_aside(path: Path, aside: Path) -> None:
    if path.exists():
        aside.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(aside / path.name))


def restore(archive: Path, force: bool = False) -> None:
    running = running_services()
    if running and not force:
        raise BackupError("Các service đang chạy: " + ", ".join(running)
                          + ". Dừng trước khi khôi phục (python manage.py stop, hoặc docker compose stop "
                            "auth restaurant order notification review).")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        m = _extract(archive, src)
        log(f"Khôi phục {archive.name} (tạo lúc {m['created_at']})")
        restore_postgres(src / PG_FILE)           # trước tiên: lỗi ở đây thì tệp trên đĩa chưa bị đụng tới
        for service, name in [*SQLITE.items(), ("order", ORDER_FILE)]:
            d = data_dir(service)
            d.mkdir(parents=True, exist_ok=True)
            aside = d / f"truoc-khoi-phuc-{stamp}"
            for suffix in ("", "-wal", "-shm", "-journal"):
                _move_aside(d / (name + suffix), aside)
            if service == "order":
                _move_aside(d / "order.trace.db", aside)
            shutil.copy2(src / name, d / name)
        for folder, service in FOLDERS.items():
            if folder not in m["items"]:
                continue                               # bản sao lưu cũ chưa có thư mục này: giữ nguyên
            d = data_dir(service)
            _move_aside(d / folder, d / f"truoc-khoi-phuc-{stamp}")
            (d / folder).mkdir()
            for name in m["items"][folder]["files"]:   # chỉ chép ảnh có trong manifest (đã kiểm tra)
                shutil.copy2(src / folder / name, d / folder / name)
    sync_erasures()
    log(f"Xong. Dữ liệu cũ nằm trong truoc-khoi-phuc-{stamp}/ cạnh từng cơ sở dữ liệu. Khởi động lại các service; Auth tự áp dụng lại các yêu cầu xóa dữ liệu ghi trong {ERASURES}.")


def loop() -> None:
    hours = float(config.get("BACKUP_INTERVAL_HOURS", "24"))
    deadline = time.time() + 600                  # lần đầu: chờ 5 service sẵn sàng (tối đa 10 phút)
    while len(running_services()) < len(SERVICES) and time.time() < deadline:
        time.sleep(10)
    while True:
        try:
            create()
        except Exception as e:                    # noqa: BLE001 - ghi lỗi rồi thử lại ở lần sau, không dừng container
            log(f"LỖI: {e}")
        time.sleep(max(60.0, hours * 3600))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sao lưu / khôi phục dữ liệu TDTU Food Booking")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="tạo bản sao lưu")
    c.add_argument("--loop", action="store_true", help="chạy liên tục theo BACKUP_INTERVAL_HOURS")
    sub.add_parser("list", help="liệt kê bản sao lưu")
    v = sub.add_parser("verify", help="kiểm tra tệp sao lưu")
    v.add_argument("file")
    r = sub.add_parser("restore", help="khôi phục (các service phải đang dừng)")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="xác nhận ghi đè dữ liệu hiện tại")
    r.add_argument("--force", action="store_true", help="bỏ qua kiểm tra service đang chạy")
    a = ap.parse_args(argv)
    if hasattr(os, "umask"):
        os.umask(0o077)                           # tệp / thư mục tạo ra chỉ chủ sở hữu đọc được
    try:
        if a.cmd == "create":
            loop() if a.loop else create()
        elif a.cmd == "list":
            items = list_backups()
            for p in items:
                print(f"  {p.name}  {p.stat().st_size / 1048576:8.1f} MB")
            print(f"{len(items)} bản trong {backup_dir()}")
        elif a.cmd == "verify":
            verify(_path(a.file))
        else:
            if not a.yes:
                print("Khôi phục sẽ thay dữ liệu hiện tại (dữ liệu cũ được chuyển sang thư mục truoc-khoi-phuc-...). "
                      "Chạy lại với --yes để xác nhận.")
                return 2
            restore(_path(a.file), a.force)
    except (BackupError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as e:
        log(f"LỖI: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
