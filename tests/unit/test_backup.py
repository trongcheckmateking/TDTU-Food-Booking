"""Unit test công cụ sao lưu / khôi phục (scripts/backup.py) với dữ liệu tạm; PostgreSQL được thay bằng hàm giả,
Order Service bằng HTTP server giả. Diễn tập thật trên 5 service: xem docs/DEPLOY.md, mục Sao lưu."""
import io
import json
import os
import socket
import sqlite3
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("TDTU_ENV_FILE", os.path.join(os.path.dirname(__file__), "no-such.env"))

from scripts import backup  # noqa: E402

KEY = "test-internal-key-" + "y" * 16


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, out = tmp_path / "data", tmp_path / "backups"
    (data / "uploads").mkdir(parents=True)
    (data / "avatars").mkdir()
    (data / "avatars" / ("a" * 32 + ".jpg")).write_bytes(bytes([0xFF, 0xD8, 0xFF]) + b" anh dai dien")
    for name in ("auth.db", "restaurant.db", "review.db"):
        c = sqlite3.connect(data / name)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (v TEXT)")
        c.execute("INSERT INTO t VALUES (?)", (name,))
        c.commit()
        c.close()
    (data / "order.mv.db").write_bytes(b"H2 order data")
    (data / "uploads" / "anh.png").write_bytes(b"\x89PNG anh quan")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("BACKUP_DIR", str(out))
    monkeypatch.setenv("BACKUP_KEEP", "2")
    monkeypatch.setenv("INTERNAL_KEY", KEY)
    for s in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW"):
        monkeypatch.setenv(f"{s}_URL", f"http://127.0.0.1:{closed_port()}")     # mọi service "đang dừng"
        monkeypatch.delenv(f"{s}_DATA_DIR", raising=False)
    pg = {"restored": None}
    monkeypatch.setattr(backup, "dump_postgres", lambda dest: dest.write_bytes(b"PGDMP fake") or "pg_dump (giả)")
    monkeypatch.setattr(backup, "restore_postgres", lambda src: pg.update(restored=src.read_bytes()))
    return type("Env", (), {"data": data, "out": out, "pg": pg})


def read(db: Path) -> list[str]:
    c = sqlite3.connect(db)
    try:
        return [r[0] for r in c.execute("SELECT v FROM t ORDER BY rowid")]
    finally:
        c.close()


def test_create_contains_every_service_and_prunes(env):
    first = backup.create()
    m = backup.verify(first)
    assert set(m["items"]) == {"auth", "restaurant", "order", "notification", "review", "uploads", "avatars"}
    assert list(m["items"]["avatars"]["files"]) == ["a" * 32 + ".jpg"]
    assert m["items"]["order"]["method"].startswith("chép tệp")              # Order dừng -> chép thẳng tệp H2
    assert list(m["items"]["uploads"]["files"]) == ["anh.png"]
    with tarfile.open(first) as tar:
        names = set(tar.getnames())
    assert {"manifest.json", "auth.db", "restaurant.db", "review.db", "order.mv.db", "notification.dump",
            "uploads/anh.png"} <= names
    backup.create()
    backup.create()
    left = backup.list_backups()
    assert len(left) == 2 and first not in left                               # BACKUP_KEEP=2: bản cũ nhất bị xóa
    assert not list(env.out.glob(".tmp-*")) and not list(env.out.glob("*.part"))


def test_sqlite_copy_includes_wal_writes(env):
    c = sqlite3.connect(env.data / "auth.db")                                 # ghi còn nằm trong WAL, chưa checkpoint
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("INSERT INTO t VALUES ('moi ghi')")
    c.commit()
    m = backup.create()
    c.close()
    with tarfile.open(m) as tar:
        tar.extract("auth.db", env.out / "x", filter="data")
    assert read(env.out / "x" / "auth.db") == ["auth.db", "moi ghi"]


def test_h2_backup_through_order_internal_endpoint(env, monkeypatch):
    seen = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("order.mv.db", b"H2 tu BACKUP TO")
    payload = buf.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["key"], seen["path"] = self.headers.get("X-Internal-Key"), self.path
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ORDER_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        archive = backup.create()
    finally:
        srv.shutdown()
    assert seen == {"key": KEY, "path": "/internal/backup"}
    m = backup.verify(archive)
    assert m["items"]["order"]["method"] == "H2 BACKUP TO"
    with tarfile.open(archive) as tar:
        assert tar.extractfile("order.mv.db").read() == b"H2 tu BACKUP TO"


def test_verify_rejects_tampered_or_foreign_archives(env, tmp_path):
    good = backup.create()
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(good) as src, tarfile.open(bad, "w:gz") as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read() if member.isfile() else None
            if member.name == "review.db":
                data = data[:-1] + bytes([data[-1] ^ 1])
            dst.addfile(member, io.BytesIO(data) if data is not None else None)
    with pytest.raises(backup.BackupError, match="SHA-256"):
        backup.verify(bad)
    other = tmp_path / "other.tar.gz"
    with tarfile.open(other, "w:gz") as t:
        info = tarfile.TarInfo("manifest.json")
        raw = json.dumps({"app": "khac", "format": 1}).encode()
        info.size = len(raw)
        t.addfile(info, io.BytesIO(raw))
    with pytest.raises(backup.BackupError, match="Không phải"):
        backup.verify(other)
    (tmp_path / "junk.tar.gz").write_bytes(b"not a tar")
    with pytest.raises(backup.BackupError, match="hỏng"):
        backup.verify(tmp_path / "junk.tar.gz")


def test_restore_brings_back_data_and_keeps_current_aside(env):
    archive = backup.create()
    c = sqlite3.connect(env.data / "restaurant.db")
    c.execute("INSERT INTO t VALUES ('sau sao luu')")
    c.commit()
    c.close()
    (env.data / "order.mv.db").write_bytes(b"H2 da doi")
    (env.data / "uploads" / "anh-moi.png").write_bytes(b"moi")
    (env.data / "avatars" / ("b" * 32 + ".jpg")).write_bytes(b"anh dai dien moi")

    backup.restore(archive)
    assert read(env.data / "restaurant.db") == ["restaurant.db"]
    assert (env.data / "order.mv.db").read_bytes() == b"H2 order data"
    assert sorted(p.name for p in (env.data / "uploads").iterdir()) == ["anh.png"]
    assert env.pg["restored"] == b"PGDMP fake"
    aside = next(env.data.glob("truoc-khoi-phuc-*"))
    assert read(aside / "restaurant.db") == ["restaurant.db", "sau sao luu"]
    assert (aside / "order.mv.db").read_bytes() == b"H2 da doi"
    assert (aside / "uploads" / "anh-moi.png").is_file()
    assert sorted(p.name for p in (env.data / "avatars").iterdir()) == ["a" * 32 + ".jpg"]
    assert (aside / "avatars" / ("b" * 32 + ".jpg")).is_file()


def test_restore_refuses_while_services_run(env, monkeypatch):
    archive = backup.create()

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("REVIEW_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        with pytest.raises(backup.BackupError, match="review"):
            backup.restore(archive)
        assert env.pg["restored"] is None                                    # chưa đụng tới dữ liệu
    finally:
        srv.shutdown()


def test_cli_requires_yes_for_restore(env, capsys):
    archive = backup.create()
    assert backup.main(["restore", str(archive)]) == 2
    assert "--yes" in capsys.readouterr().out
    assert backup.main(["verify", str(env.out / "khong-co.tar.gz")]) == 1


def test_pg_command_falls_back_to_docker(monkeypatch):
    monkeypatch.setenv("NOTIFICATION_DB_URL", "postgres://tdtu:mat%40khau@127.0.0.1:5433/noti?sslmode=disable")
    monkeypatch.delenv("PG_DUMP", raising=False)
    monkeypatch.setattr(backup.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    cmd, env = backup.pg_command("pg_dump", ["-Fc"])
    assert cmd[:3] == ["/usr/bin/docker", "run", "--rm"] and "host.docker.internal" in cmd and "5433" in cmd
    assert "mat@khau" not in " ".join(cmd) and env["PGPASSWORD"] == "mat@khau" and env["PGSSLMODE"] == "disable"
    monkeypatch.setenv("PG_DUMP", "/opt/pg/bin/pg_dump")
    cmd, _ = backup.pg_command("pg_dump", ["-Fc"])
    assert cmd[:3] == ["/opt/pg/bin/pg_dump", "-h", "127.0.0.1"]


def test_erasure_journal_kept_next_to_backups_and_restored(env):
    (env.data / "erasures.log").write_text("id-a\t2026-10-16T01:00:00Z\n", encoding="utf-8")
    archive = backup.create()
    assert (env.out / "erasures.log").read_text(encoding="utf-8") == "id-a\t2026-10-16T01:00:00Z\n"
    if os.name != "nt":
        assert (archive.stat().st_mode & 0o777) == 0o600            # có dữ liệu cá nhân: chỉ chủ sở hữu đọc
    (env.out / "erasures.log").write_text("id-a\t2026-10-16T01:00:00Z\nid-b\t2026-10-16T02:00:00Z\n",
                                          encoding="utf-8")
    (env.data / "erasures.log").unlink()                            # mất ổ dữ liệu, khôi phục ở máy mới
    backup.restore(archive)
    assert (env.data / "erasures.log").read_text(encoding="utf-8").splitlines() == [
        "id-a\t2026-10-16T01:00:00Z", "id-b\t2026-10-16T02:00:00Z"]


def test_manifest_upload_names_cannot_escape(env, tmp_path):
    good = backup.create()
    for bad_name in ("../auth.db", "..", ".hidden", "a/b.png"):
        bad = tmp_path / "bad.tar.gz"
        with tarfile.open(good) as src, tarfile.open(bad, "w:gz") as dst:
            for member in src.getmembers():
                data = src.extractfile(member).read() if member.isfile() else None
                if member.name == "manifest.json":
                    m = json.loads(data)
                    m["items"]["uploads"]["files"][bad_name] = "0" * 64
                    data = json.dumps(m).encode()
                    member.size = len(data)
                dst.addfile(member, io.BytesIO(data) if data is not None else None)
        with pytest.raises(backup.BackupError, match="Tên ảnh không hợp lệ"):
            backup.verify(bad)
