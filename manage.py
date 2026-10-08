#!/usr/bin/env python3
"""Công cụ vận hành TDTU Food Booking - 5 service, 5 ngôn ngữ (chạy được trên Windows, Linux, macOS).

  python manage.py init-env        Tạo .env với khóa bí mật + mật khẩu PostgreSQL ngẫu nhiên (không ghi đè)
  python manage.py doctor          Kiểm tra Python, Node.js, Java, Go, PHP, PostgreSQL và các bản build
  python manage.py pg-setup        Tạo user + database PostgreSQL cho Notification (cần psql và quyền superuser)
  python manage.py build           Cài/biên dịch: npm (Restaurant), go build (Notification), mvn package (Order)
  python manage.py init-db         Tạo schema Auth (các service còn lại tự tạo bảng khi khởi động)
  python manage.py create-admin    Tạo tài khoản admin thật (hỏi email, mật khẩu)
  python manage.py start           Khởi động 5 service + giao diện web, chờ đến khi sẵn sàng
  python manage.py seed            Nạp dữ liệu demo QUA REST API (hệ thống phải đang chạy; chạy lại không trùng)
  python manage.py stop            Dừng đúng các tiến trình do lệnh start tạo ra
  python manage.py status          Kiểm tra health của từng service
  python manage.py reset-demo --yes  XÓA dữ liệu (SQLite, H2, bảng PostgreSQL) rồi start + seed lại
  python manage.py test-services   Chạy test riêng của từng service (node --test, go test, php, JUnit)
  python manage.py export-openapi  Xuất OpenAPI của 5 service vào docs/openapi/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):          # tránh lỗi in tiếng Việt trên console/pipe Windows
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
RUN_DIR = Path(os.environ.get("TDTU_RUN_DIR", ROOT / ".run"))     # nơi lưu PID của các tiến trình đã start
LOG_DIR = Path(os.environ.get("TDTU_LOG_DIR", ROOT / "logs"))
PID_FILE = RUN_DIR / "pids.json"
SERVICES = ["auth", "restaurant", "order", "notification", "review"]
IS_WIN = os.name == "nt"
SVC = ROOT / "services"
NOTI_BIN = SVC / "notification" / "bin" / ("notification-service.exe" if IS_WIN else "notification-service")
LANG = {"auth": "Python/FastAPI", "restaurant": "Node.js/Express", "order": "Java/Spring Boot",
        "notification": "Go/Gin + PostgreSQL", "review": "PHP"}


def env_path() -> Path:
    return Path(os.environ.get("TDTU_ENV_FILE", ROOT / ".env"))


# ---------------------------------------------------------------------------- cấu hình
def cmd_init_env(args) -> None:
    target = env_path()
    if target.exists() and not args.force:
        print(f"Đã có {target.name}, giữ nguyên (dùng --force để tạo lại khóa mới).")
        return
    pg_pw = secrets.token_urlsafe(18).replace("-", "x").replace("_", "y")
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    text = text.replace("JWT_SECRET=", f"JWT_SECRET={secrets.token_urlsafe(48)}", 1)
    text = text.replace("INTERNAL_KEY=", f"INTERNAL_KEY={secrets.token_urlsafe(32)}", 1)
    text = text.replace("POSTGRES_PASSWORD=", f"POSTGRES_PASSWORD={pg_pw}", 1)
    text = text.replace("<POSTGRES_PASSWORD>", pg_pw)
    target.write_text(text, encoding="utf-8")
    print(f"Đã tạo {target} (JWT_SECRET, INTERNAL_KEY, mật khẩu PostgreSQL ngẫu nhiên).")


def ensure_env() -> None:
    if not env_path().exists() and not os.environ.get("JWT_SECRET"):
        cmd_init_env(argparse.Namespace(force=False))
    from common import config
    config.load_env()


def cfg(name: str, default: str | None = None) -> str | None:
    from common import config
    return config.get(name, default)


def ports() -> dict[str, int]:
    from common import config
    result = {s: urlparse(config.service_url(s.upper())).port for s in SERVICES}
    result["web"] = int(config.get("WEB_PORT", "8000"))
    return result


def child_env() -> dict:
    return {**os.environ, "TDTU_ROOT": str(ROOT), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def run(cmd: list[str], cwd: Path, check: bool = True, secret: str | None = None, **kw) -> subprocess.CompletedProcess:
    shown = " ".join(str(c) for c in cmd)
    if secret:
        shown = shown.replace(secret, "***")            # không in mật khẩu ra màn hình / log
    print("  $", shown, f"  (trong {cwd.relative_to(ROOT) if cwd != ROOT else '.'})")
    r = subprocess.run(cmd, cwd=cwd, env=child_env(), **kw)
    if check and r.returncode != 0:
        sys.exit(f"Lệnh thất bại (mã {r.returncode}).")
    return r


# ---------------------------------------------------------------------------- doctor / build
def version_of(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=child_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "") + (r.stderr or "")
    return out.strip().splitlines()[0] if r.returncode == 0 and out.strip() else None


def pg_target() -> tuple[str, int] | None:
    url = cfg("NOTIFICATION_DB_URL")
    if not url:
        return None
    u = urlparse(url)
    return u.hostname or "127.0.0.1", u.port or 5432


def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def java_major() -> int | None:
    try:
        r = subprocess.run([which("java") or "java", "-version"], capture_output=True, text=True, timeout=30)
    except OSError:
        return None
    m = re.search(r'version "(\d+)', r.stderr + r.stdout)
    return int(m.group(1)) if m else None


def cmd_doctor(_=None) -> int:
    ensure_env()
    rows, problems = [], 0

    def row(name, ok, info, fix=""):
        nonlocal problems
        problems += 0 if ok else 1
        rows.append((name, "OK " if ok else "THIẾU", info, "" if ok else fix))

    row("Python (Auth, web)", sys.version_info >= (3, 11), sys.version.split()[0], "Cài Python 3.11+")
    node = version_of([which("node") or "node", "--version"])
    nmaj = int(re.sub(r"\D.*", "", node.lstrip("v"))) if node else 0
    row("Node.js (Restaurant)", nmaj >= 22, node or "không có", "Cài Node.js 22 LTS+ (cần node:sqlite)")
    row("  node_modules", (SVC / "restaurant" / "node_modules" / "express").is_dir(), "express", "python manage.py build")
    jmaj = java_major() if which("java") else None
    row("Java (Order)", (jmaj or 0) >= 17, f"Java {jmaj}" if jmaj else "không có", "Cài JDK 17+ (Temurin)")
    jar = SVC / "order" / "target" / "order-service.jar"
    row("  order-service.jar", jar.is_file(), str(jar.relative_to(ROOT)),
        "python manage.py build (cần Maven: mvn, hoặc mvnw đi kèm)")
    go = version_of([which("go") or "go", "version"])
    row("Go (Notification)", bool(go) or NOTI_BIN.is_file(), go or "không có (chỉ cần khi build)", "Cài Go 1.22+")
    row("  notification-service", NOTI_BIN.is_file(), str(NOTI_BIN.relative_to(ROOT)), "python manage.py build")
    php = which("php")
    php_v = version_of([php, "-r", "echo PHP_VERSION;"]) if php else None
    exts = version_of([php, "-r", "echo implode(',', get_loaded_extensions());"]) if php else ""
    need = [e for e in ("pdo_sqlite", "curl", "mbstring") if e not in (exts or "").split(",")]
    php_ok = bool(php_v) and tuple(int(x) for x in re.findall(r"\d+", php_v)[:2]) >= (8, 1)
    row("PHP (Review)", php_ok, php_v or "không có", "Cài PHP 8.1+")
    row("  PHP extensions", bool(php_v) and not need, "pdo_sqlite, curl, mbstring" if not need else "thiếu " + ", ".join(need),
        "Bật extension trong php.ini (extension=pdo_sqlite, curl, mbstring)")
    pg = pg_target()
    row("PostgreSQL (Notification)", bool(pg) and tcp_open(*pg), f"{pg[0]}:{pg[1]}" if pg else "chưa cấu hình",
        "Cài/chạy PostgreSQL 14+ rồi `python manage.py pg-setup` (hoặc docker compose, xem README)")
    width = max(len(r[0]) for r in rows)
    for name, st, info, fix in rows:
        print(f"  {name:<{width}}  {st}  {info}" + (f"  -> {fix}" if fix else ""))
    print("Mọi thứ sẵn sàng." if not problems else f"Có {problems} mục cần xử lý.")
    return problems


def cmd_build(args) -> None:
    ensure_env()
    only = set(args.only.split(",")) if args.only else {"restaurant", "notification", "order"}
    if "restaurant" in only:
        npm = which("npm", "npm.cmd")
        if not npm:
            sys.exit("Không tìm thấy npm (cài Node.js 22+).")
        lock = (SVC / "restaurant" / "package-lock.json").is_file()
        run([npm, "ci" if lock else "install", "--no-audit", "--no-fund"], SVC / "restaurant")
    if "notification" in only:
        go = which("go")
        if go:
            NOTI_BIN.parent.mkdir(exist_ok=True)
            run([go, "build", "-o", str(NOTI_BIN), "."], SVC / "notification")
        elif NOTI_BIN.is_file():
            print("  (không có Go, dùng bản đã build sẵn:", NOTI_BIN.name + ")")
        else:
            sys.exit("Không tìm thấy Go để build Notification Service (cài Go 1.22+).")
    if "order" in only:
        jar = SVC / "order" / "target" / "order-service.jar"
        if jar.is_file() and not args.force:
            print("  Đã có", jar.relative_to(ROOT), "(dùng --force để build lại)")
        else:
            mvn = which("mvn", "mvn.cmd")
            wrapper = SVC / "order" / ("mvnw.cmd" if IS_WIN else "mvnw")
            if not mvn and wrapper.is_file():
                mvn = str(wrapper)
            if not mvn:
                sys.exit("Không tìm thấy Maven (mvn) để build Order Service. Cài Maven 3.9+ hoặc dùng IDE.")
            run([mvn, "-q", "-DskipTests", "package"], SVC / "order")
    print("Build xong.")


def cmd_pg_setup(args) -> None:
    """Tạo role + database cho Notification theo NOTIFICATION_DB_URL, dùng psql với user quản trị PostgreSQL."""
    ensure_env()
    url = cfg("NOTIFICATION_DB_URL")
    if not url:
        sys.exit("Chưa có NOTIFICATION_DB_URL trong .env (chạy `python manage.py init-env`).")
    u = urlparse(url)
    user, pw, dbname = u.username, u.password or "", u.path.lstrip("/")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user or "") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dbname):
        sys.exit("Tên user/database trong NOTIFICATION_DB_URL chỉ được gồm chữ, số, dấu gạch dưới.")
    psql = which("psql", "psql.exe")
    if not psql:
        sys.exit("Không tìm thấy psql. Tự chạy trong pgAdmin/psql:\n"
                 f"  CREATE ROLE {user} LOGIN PASSWORD '<mật khẩu trong .env>';\n  CREATE DATABASE {dbname} OWNER {user};")
    base = [psql, "-h", u.hostname or "127.0.0.1", "-p", str(u.port or 5432), "-U", args.admin_user, "-v", "ON_ERROR_STOP=1"]
    pw_sql = pw.replace("'", "''")
    role_sql = (f"DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{user}') THEN "
                f"CREATE ROLE {user} LOGIN PASSWORD '{pw_sql}'; ELSE ALTER ROLE {user} LOGIN PASSWORD '{pw_sql}'; END IF; END$$;")
    print(f"Tạo user '{user}' và database '{dbname}' (psql sẽ hỏi mật khẩu của '{args.admin_user}' nếu cần)...")
    run([*base, "-d", "postgres", "-c", role_sql], ROOT, secret=pw_sql)
    exists = subprocess.run([*base, "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{dbname}'"],
                            capture_output=True, text=True, env=child_env())
    if exists.stdout.strip() != "1":
        run([*base, "-d", "postgres", "-c", f"CREATE DATABASE {dbname} OWNER {user}"], ROOT)
    print("PostgreSQL sẵn sàng cho Notification Service.")


# ---------------------------------------------------------------------------- dữ liệu
def cmd_init_db(_=None) -> None:
    ensure_env()
    from services.auth.app import db
    db.init()
    print(f"  schema Auth OK: {db.path}")
    print("  Restaurant, Order, Review, Notification tự tạo bảng khi khởi động (CREATE TABLE IF NOT EXISTS).")


def cmd_create_admin(args) -> None:
    ensure_env()
    import getpass
    from services.auth.admin_tools import create_admin
    email = args.email or input("Email admin: ").strip()
    name = args.name or input("Họ tên: ").strip()
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Mật khẩu (6–72 byte): ")
    try:
        created = create_admin(email, name, pw)
    except ValueError as e:
        sys.exit(str(e))
    print("Đã tạo admin" if created else "Email đã tồn tại:", email.lower())
    if not created:
        sys.exit(1)


def cmd_seed(_=None) -> None:
    ensure_env()
    p = ports()
    down = [s for s in SERVICES if not http_ok(f"http://127.0.0.1:{p[s]}/health")]
    if down:
        sys.exit(f"Các service chưa chạy: {', '.join(down)}. Seed nạp dữ liệu qua REST API, "
                 "hãy chạy `python manage.py start` trước.")
    from scripts.seed_data import seed
    counts = seed()
    print("Đã nạp dữ liệu demo:", counts)
    print("Tài khoản demo: admin@demo.tdtu.vn / Admin@123 ; chuquan1@, chuquan2@, sv1@, sv2@demo.tdtu.vn / Demo@123")


# ---------------------------------------------------------------------------- tiến trình
def read_pids() -> dict:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def alive(pid: int) -> bool:
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 1.5) -> bool:
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # gọi thẳng localhost, bỏ qua proxy
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def service_command(name: str, host: str, port: int) -> tuple[list[str], Path, dict]:
    """Lệnh chạy từng service bằng runtime của nó (cwd = thư mục service)."""
    extra = {"BIND_HOST": host}
    if name == "auth":
        return ([sys.executable, "-m", "uvicorn", "services.auth.app:app", "--host", host, "--port", str(port),
                 "--app-dir", str(ROOT), "--log-level", "info"], ROOT, extra)
    if name == "web":
        return ([sys.executable, "-m", "uvicorn", "web.server:app", "--host", host, "--port", str(port),
                 "--app-dir", str(ROOT), "--log-level", "warning"], ROOT, extra)
    if name == "restaurant":
        node = which("node")
        if not node:
            raise RuntimeError("Không tìm thấy Node.js (cài Node.js 22+).")
        if not (SVC / "restaurant" / "node_modules" / "express").is_dir():
            raise RuntimeError("Restaurant chưa cài thư viện: chạy `python manage.py build`.")
        return [node, "--disable-warning=ExperimentalWarning", "src/server.js"], SVC / "restaurant", extra
    if name == "order":
        java = which("java")
        jar = Path(os.environ.get("ORDER_JAR", SVC / "order" / "target" / "order-service.jar"))
        if not java:
            raise RuntimeError("Không tìm thấy Java (cài JDK 17+).")
        if not jar.is_file():
            raise RuntimeError(f"Chưa có {jar.name}: chạy `python manage.py build` (cần Maven).")
        return [java, "-Xms64m", "-Xmx384m", "-jar", str(jar)], SVC / "order", extra
    if name == "notification":
        if not NOTI_BIN.is_file():
            raise RuntimeError("Chưa build Notification: chạy `python manage.py build` (cần Go).")
        return [str(NOTI_BIN)], SVC / "notification", extra
    if name == "review":
        php = which("php")
        if not php:
            raise RuntimeError("Không tìm thấy PHP (cài PHP 8.1+).")
        if not IS_WIN:
            extra["PHP_CLI_SERVER_WORKERS"] = "4"   # php -S nhiều worker (không hỗ trợ trên Windows)
        return [php, "-S", f"{host}:{port}", "public/index.php"], SVC / "review", extra
    raise ValueError(name)


def cmd_start(args) -> None:
    ensure_env()
    running = {k: v for k, v in read_pids().items() if alive(v)}
    if running:
        sys.exit(f"Đang có tiến trình chạy: {running}. Chạy `python manage.py stop` trước.")
    p = ports()
    busy = [f"{n}:{p[n]}" for n in [*SERVICES, "web"] if tcp_open("127.0.0.1", p[n], 0.3)]
    if busy:
        sys.exit(f"Cổng đang bị chiếm: {', '.join(busy)}. Tắt chương trình đang dùng cổng hoặc đổi *_URL trong .env.")
    pg = pg_target()
    if not pg or not tcp_open(*pg):
        sys.exit("Không kết nối được PostgreSQL cho Notification "
                 f"({'%s:%s' % pg if pg else 'chưa có NOTIFICATION_DB_URL'}). Xem `python manage.py doctor`.")
    try:
        plans = {n: service_command(n, args.host, p[n]) for n in [*SERVICES, "web"]}
    except RuntimeError as e:
        sys.exit(str(e))
    cmd_init_db()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pids = {}
    for name, (cmd, cwd, extra) in plans.items():
        log = open(LOG_DIR / f"{name}.log", "a", encoding="utf-8")
        kwargs = {"cwd": cwd, "stdout": log, "stderr": subprocess.STDOUT, "env": {**child_env(), **extra}}
        if IS_WIN:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        pids[name] = subprocess.Popen(cmd, **kwargs).pid
    PID_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")
    deadline = time.time() + args.timeout
    pending = {n: f"http://127.0.0.1:{p[n]}/health" for n in pids}
    while pending and time.time() < deadline:
        for n, url in list(pending.items()):
            if http_ok(url):
                pending.pop(n)
            elif not alive(pids[n]):
                break
        if any(not alive(pids[n]) for n in pending):
            break
        time.sleep(0.5)
    if pending:
        print("Không khởi động được:", ", ".join(pending), f"- xem log trong {LOG_DIR}")
        for n in pending:
            f = LOG_DIR / f"{n}.log"
            if f.is_file():
                print(f"--- {f.name} (cuối) ---\n" + "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]))
        cmd_stop(None)
        sys.exit(1)
    print("Đã khởi động. Giao diện: http://127.0.0.1:%d" % p["web"])
    for s in SERVICES:
        print(f"  {s:13s} {LANG[s]:22s} http://127.0.0.1:{p[s]}/docs")


def cmd_stop(_) -> None:
    pids = read_pids()
    if not pids:
        print("Không có tiến trình nào do manage.py khởi động.")
        return
    for pid in pids.values():
        if not alive(pid):
            continue
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.time() + 15
    while time.time() < deadline and any(alive(p) for p in pids.values()):
        time.sleep(0.3)
    for pid in pids.values():
        if alive(pid) and not IS_WIN:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    PID_FILE.unlink(missing_ok=True)
    print("Đã dừng:", ", ".join(pids))


def cmd_status(_) -> None:
    ensure_env()
    p = ports()
    bad = 0
    for name in [*SERVICES, "web"]:
        ok = http_ok(f"http://127.0.0.1:{p[name]}/health")
        bad += not ok
        print(f"  {name:13s} {LANG.get(name, 'Python (giao diện)'):22s} :{p[name]}  {'OK' if ok else 'KHÔNG PHẢN HỒI'}")
    sys.exit(1 if bad else 0)


def cmd_reset_demo(args) -> None:
    if not args.yes:
        sys.exit("Lệnh này XÓA toàn bộ dữ liệu (SQLite, H2, bảng PostgreSQL). Chạy lại với --yes để xác nhận.")
    if any(alive(p) for p in read_pids().values()):
        sys.exit("Hãy dừng hệ thống (`python manage.py stop`) trước khi reset.")
    ensure_env()
    from common import config
    d = config.data_dir()
    for f in ("auth.db", "restaurant.db", "review.db", "order.mv.db", "order.trace.db"):
        for suffix in ("", "-wal", "-shm"):
            (d / f"{f}{suffix}").unlink(missing_ok=True)
    if NOTI_BIN.is_file():
        run([str(NOTI_BIN), "--reset-db"], SVC / "notification")
    print(f"Đã xóa dữ liệu trong {d} và bảng notifications.")
    cmd_start(argparse.Namespace(host="127.0.0.1", timeout=180))
    cmd_seed()


def cmd_test_services(_=None) -> None:
    """Test riêng của từng service bằng công cụ của ngôn ngữ đó."""
    ensure_env()
    results = {}
    npm = which("npm", "npm.cmd")
    results["restaurant (node --test)"] = run([npm, "test"], SVC / "restaurant", check=False).returncode if npm else None
    php = which("php")
    results["review (php tests/run.php)"] = run([php, "tests/run.php"], SVC / "review", check=False).returncode if php else None
    go = which("go")
    if go:
        test_db = os.environ.get("NOTIFICATION_TEST_DB_URL") or cfg("NOTIFICATION_TEST_DB_URL") or cfg("NOTIFICATION_DB_URL")
        os.environ["NOTIFICATION_TEST_DB_URL"] = test_db or ""
        results["notification (go test)"] = run([go, "test", "-count=1", "."], SVC / "notification", check=False).returncode
    else:
        results["notification (go test)"] = None
    mvn = which("mvn", "mvn.cmd")
    results["order (mvn test)"] = run([mvn, "-q", "test"], SVC / "order", check=False).returncode if mvn else None
    print("\nKết quả test từng service:")
    for k, v in results.items():
        print(f"  {k:30s} {'ĐẠT' if v == 0 else ('BỎ QUA (thiếu công cụ)' if v is None else 'LỖI')}")
    sys.exit(1 if any(v not in (0, None) for v in results.values()) else 0)


def cmd_export_openapi(_) -> None:
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("INTERNAL_KEY", "x" * 24)
    out = ROOT / "docs" / "openapi"
    out.mkdir(parents=True, exist_ok=True)
    from services.auth.app import app
    (out / "auth.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
    sources = {"restaurant": SVC / "restaurant" / "openapi.json",
               "order": SVC / "order" / "src" / "main" / "resources" / "openapi.json",
               "notification": SVC / "notification" / "openapi.json", "review": SVC / "review" / "openapi.json"}
    for s, src in sources.items():
        shutil.copyfile(src, out / f"{s}.json")
    for s in SERVICES:
        print("  ", out / f"{s}.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="Vận hành TDTU Food Booking (5 service, 5 ngôn ngữ)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("init-env"); e.add_argument("--force", action="store_true"); e.set_defaults(fn=cmd_init_env)
    sub.add_parser("doctor").set_defaults(fn=lambda a: sys.exit(1 if cmd_doctor(a) else 0))
    b = sub.add_parser("build"); b.add_argument("--only", help="restaurant,notification,order")
    b.add_argument("--force", action="store_true", help="build lại Order dù đã có jar"); b.set_defaults(fn=cmd_build)
    g = sub.add_parser("pg-setup"); g.add_argument("--admin-user", default="postgres"); g.set_defaults(fn=cmd_pg_setup)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    c = sub.add_parser("create-admin"); c.add_argument("--email"); c.add_argument("--name")
    c.set_defaults(fn=cmd_create_admin)
    s = sub.add_parser("start"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--timeout", type=int, default=180); s.set_defaults(fn=cmd_start)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    r = sub.add_parser("reset-demo"); r.add_argument("--yes", action="store_true"); r.set_defaults(fn=cmd_reset_demo)
    sub.add_parser("test-services").set_defaults(fn=cmd_test_services)
    sub.add_parser("export-openapi").set_defaults(fn=cmd_export_openapi)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
