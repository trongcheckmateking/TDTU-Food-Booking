"""Unit test máy chủ giao diện (:8000): mã QR đăng ký, /config.js, header bảo mật và CSP."""
import io
import os

import segno
from fastapi.testclient import TestClient

os.environ.setdefault("TDTU_ENV_FILE", os.path.join(os.path.dirname(__file__), "no-such.env"))

from web.server import app, content_security_policy  # noqa: E402

client = TestClient(app, base_url="http://testserver")


def qr_svg(url: str) -> bytes:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", border=2, dark="#0e1f45", light="#ffffff", omitsize=True, xmldecl=False)
    return buf.getvalue()


def test_qr_points_to_register_form_with_role(monkeypatch):
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://testserver")
    for kind in ("sinh-vien", "chu-quan"):
        r = client.get(f"/qr/{kind}.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.content == qr_svg(f"http://testserver/index.html?dang-ky={kind}")


def test_qr_ignores_host_header_outside_cors_origins(monkeypatch):
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
    r = client.get("/qr/sinh-vien.svg", headers={"Host": "evil.example"})
    assert r.content == qr_svg("http://127.0.0.1:8000/index.html?dang-ky=sinh-vien")
    r = client.get("/qr/sinh-vien.svg", headers={"Host": "x" * 3000})
    assert r.status_code == 200


def test_qr_uses_public_web_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_WEB_URL", "http://192.168.1.10:8000/")
    r = client.get("/qr/chu-quan.svg")
    assert r.content == qr_svg("http://192.168.1.10:8000/index.html?dang-ky=chu-quan")
    assert '"web": "http://192.168.1.10:8000"' in client.get("/config.js").text


def test_pages_and_scripts_always_revalidated():
    for path in ("/index.html", "/student.html", "/owner.html", "/admin.html", "/assets/app.js", "/assets/style.css"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path
    assert client.get("/config.js").headers["cache-control"] == "no-store"
    assert "no-cache" not in client.get("/assets/brand/logo.png").headers.get("cache-control", "")


def test_unknown_qr_is_404():
    r = client.get("/qr/admin.svg")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


SERVICES = ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW")


def csp_directives(csp: str) -> dict[str, list[str]]:
    out = {}
    for part in csp.split(";"):
        name, *values = part.split()
        out[name] = values
    return out


def test_security_headers_on_every_response():
    for path in ("/index.html", "/assets/app.js", "/config.js", "/qr/sinh-vien.svg", "/health", "/qr/admin.svg"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert r.headers["x-frame-options"] == "DENY", path
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert "camera=()" in r.headers["permissions-policy"], path
        assert r.headers["cross-origin-opener-policy"] == "same-origin", path
    assert "content-security-policy" not in client.get("/assets/app.js").headers


def test_csp_dev_mode_allows_only_the_five_service_ports(monkeypatch):
    for n in SERVICES:
        monkeypatch.delenv(f"PUBLIC_{n}_URL", raising=False)
        monkeypatch.delenv(f"{n}_URL", raising=False)
    content_security_policy.cache_clear()
    try:
        for page in ("/index.html", "/student.html", "/owner.html", "/admin.html", "/qr.html"):
            d = csp_directives(client.get(page).headers["content-security-policy"])
            assert d["script-src"] == ["'self'"], page          # không cho script nhúng / eval
            assert d["object-src"] == ["'none'"] and d["frame-ancestors"] == ["'none'"]
            assert d["connect-src"] == ["'self'"] + [f"http://127.0.0.1:{p}" for p in range(8001, 8006)]
            assert d["img-src"] == ["'self'", "data:", "blob:", "http://127.0.0.1:8001", "http://127.0.0.1:8002"]  # không có https:/http:
    finally:
        content_security_policy.cache_clear()


def test_csp_behind_gateway_uses_single_origin(monkeypatch):
    for n in SERVICES:
        monkeypatch.setenv(f"PUBLIC_{n}_URL", f"https://food.example.edu.vn/svc/{n.lower()}/")
    monkeypatch.setenv("CONTACT_EMAIL", "tdtufood@example.edu.vn")
    content_security_policy.cache_clear()
    try:
        d = csp_directives(client.get("/index.html").headers["content-security-policy"])
        assert d["connect-src"] == ["'self'", "https://food.example.edu.vn"]
        assert d["img-src"] == ["'self'", "data:", "blob:", "https://food.example.edu.vn"]
        cfg = client.get("/config.js").text
        assert '"auth": "https://food.example.edu.vn/svc/auth"' in cfg
        assert '"contact": "tdtufood@example.edu.vn"' in cfg
    finally:
        content_security_policy.cache_clear()


def test_pages_have_no_inline_scripts_or_handlers():
    import re
    from pathlib import Path
    for page in (Path(__file__).resolve().parents[2] / "web" / "static").glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), page.name
        assert not re.search(r"\son[a-z]+\s*=\s*[\"']", html), page.name
        assert "javascript:" not in html, page.name


def test_pwa_files_served_for_install():
    """Cài lên điện thoại như app: manifest đúng MIME, biểu tượng có thật, service worker không bị lưu đệm cũ."""
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json")
    data = m.json()
    assert data["display"] == "standalone" and data["start_url"].startswith("/index.html")
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["cache-control"] == "no-cache"
    assert "javascript" in sw.headers["content-type"]
    assert client.get("/offline.html").status_code == 200
    for page in ("/index.html", "/student.html", "/owner.html", "/admin.html"):
        assert 'rel="manifest"' in client.get(page).text, page


# ------------------------------------------------------------------ VietQR thanh toán trước
def test_crc16_matches_emvco_check_value():
    from web.server import crc16_ccitt
    assert crc16_ccitt(b"123456789") == 0x29B1                  # giá trị kiểm tra chuẩn của CRC-16/CCITT-FALSE


def parse_tlv(s: str) -> dict[str, str]:
    out, i = {}, 0
    while i < len(s):
        tag, n = s[i:i + 2], int(s[i + 2:i + 4])
        out[tag] = s[i + 4:i + 4 + n]
        i += 4 + n
    return out


def test_vietqr_payload_has_bank_account_amount_and_note():
    from web.server import crc16_ccitt, vietqr_payload
    p = vietqr_payload("970436", "0071000123456", 35000, "TDTU 047 AB12")
    f = parse_tlv(p)
    assert f["00"] == "01" and f["01"] == "12"                  # mã dùng một lần, có số tiền
    mai = parse_tlv(f["38"])
    assert mai["00"] == "A000000727" and mai["02"] == "QRIBFTTA"   # Napas, chuyển nhanh tới số tài khoản
    assert parse_tlv(mai["01"]) == {"00": "970436", "01": "0071000123456"}
    assert (f["53"], f["54"], f["58"]) == ("704", "35000", "VN")
    assert parse_tlv(f["62"]) == {"08": "TDTU 047 AB12"}
    assert f["63"] == f"{crc16_ccitt(p[:-4].encode()):04X}"
    static = parse_tlv(vietqr_payload("970415", "113366668888"))
    assert static["01"] == "11" and "54" not in static and "62" not in static


def test_vietqr_svg_endpoint_validates_input():
    from web.server import vietqr_payload
    ok = client.get("/qr/vietqr.svg", params={"bin": "970436", "acc": "0071000123456", "amount": "35000",
                                               "note": "TDTU 047 AB12"})
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("image/svg+xml")
    assert ok.content == qr_svg(vietqr_payload("970436", "0071000123456", 35000, "TDTU 047 AB12"))
    assert ok.headers["cache-control"] == "private, max-age=3600"
    png = client.get("/qr/vietqr.png", params={"bin": "970436", "acc": "0071000123456", "amount": "35000"})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == bytes([0x89]) + b"PNG"
    assert client.get("/qr/vietqr.gif", params={"bin": "970436", "acc": "0071000123456"}).status_code == 404
    for bad in ({"bin": "97043", "acc": "0071000123456"}, {"bin": "970436", "acc": "12345"},
                {"bin": "970436", "acc": "0071000123456", "amount": "0"},
                {"bin": "970436", "acc": "0071000123456", "amount": "-5"},
                {"bin": "970436", "acc": "0071000123456", "note": "<script>"},
                {"bin": "970436", "acc": "0071000123456", "note": "x" * 26}, {}):
        r = client.get("/qr/vietqr.svg", params=bad)
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR", bad
