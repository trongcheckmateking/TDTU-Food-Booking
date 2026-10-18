"""Máy chủ giao diện web (cổng 8000): phục vụ HTML/CSS/JS tĩnh, /config.js chứa địa chỉ 5 service, /qr/*.svg mã QR."""
from __future__ import annotations

import io
import json
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import segno
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from common import config

STATIC = Path(__file__).resolve().parent / "static"
mimetypes.add_type("application/manifest+json", ".webmanifest")      # Windows không biết đuôi này (PWA)
app = FastAPI(title="TDTU Food Booking - Web UI", docs_url=None, redoc_url=None, openapi_url=None)

# Mã QR in dán ở quán / bảng tin: mở thẳng form đăng ký với vai trò chọn sẵn
QR_TARGETS = {"sinh-vien": "index.html?dang-ky=sinh-vien", "chu-quan": "index.html?dang-ky=chu-quan"}


def public_web_url(request: Request) -> str:
    """Địa chỉ mã QR trỏ tới: PUBLIC_WEB_URL nếu đặt; nếu không, địa chỉ đang truy cập khi nó nằm trong CORS_ORIGINS
    (không tin header Host tùy ý), còn lại dùng origin đầu tiên trong CORS_ORIGINS."""
    configured = config.get("PUBLIC_WEB_URL")
    if configured:
        return configured.rstrip("/")
    allowed = [o.rstrip("/") for o in config.cors_origins()] or ["http://127.0.0.1:8000"]
    current = str(request.base_url).rstrip("/")
    return current if current in allowed else allowed[0]


@lru_cache(maxsize=32)
def qr_svg_bytes(url: str) -> bytes:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", border=2, dark="#0e1f45", light="#ffffff", omitsize=True, xmldecl=False)
    return buf.getvalue()


SERVICES = ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW")


def public_service_urls() -> dict[str, str]:
    """Địa chỉ trình duyệt dùng để gọi 5 service (qua gateway: https://<tên miền>/svc/<service>)."""
    return {n.lower(): config.get(f"PUBLIC_{n}_URL", config.service_url(n)).rstrip("/") for n in SERVICES}


def _origin(url: str) -> str | None:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None


@lru_cache(maxsize=1)
def content_security_policy() -> str:
    """CSP cho trang: chỉ chạy script của chính trang (không có script nhúng), chỉ gọi API tới 5 service đã cấu hình,
    không cho trang khác nhúng (chống clickjacking). Ảnh: của trang, ảnh quán ở Restaurant, ảnh đại diện ở Auth, data:/blob: (xem trước
    ảnh trước khi tải lên). Không cho ảnh từ máy chủ lạ: máy chủ đó sẽ biết IP của sinh viên xem trang."""
    urls = public_service_urls()
    apis = sorted({o for o in map(_origin, urls.values()) if o})
    connect = " ".join(["'self'", *apis])
    img = " ".join(["'self'", "data:", "blob:", *sorted({o for o in (_origin(urls["restaurant"]), _origin(urls["auth"])) if o})])
    return ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"img-src {img}; font-src 'self'; connect-src {connect}; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    """Header bảo mật cho mọi phản hồi + CSP cho trang HTML. HTML / JS / CSS: trình duyệt luôn hỏi lại máy chủ
    (ETag -> 304 nếu không đổi), không dùng bản cũ sau khi cập nhật."""
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Content-Security-Policy"] = content_security_policy()
    path = request.url.path
    if (path == "/" or path.endswith((".html", ".js", ".css"))) and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/config.js", include_in_schema=False)
def config_js():
    web = (config.get("PUBLIC_WEB_URL") or "").rstrip("/")
    contact = config.get("CONTACT_EMAIL") or ""
    body = f"window.APP_CONFIG = {json.dumps({'services': public_service_urls(), 'web': web, 'contact': contact})};"
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ mã VietQR chuyển khoản vào tài khoản chủ quán
VIETQR_RULES = {"bin": re.compile(r"^[0-9]{6}$"), "acc": re.compile(r"^[0-9]{6,19}$"),
                "amount": re.compile(r"^[1-9][0-9]{0,8}$"), "note": re.compile(r"^[A-Za-z0-9 ]{1,25}$")}


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (đa thức 0x1021, khởi tạo 0xFFFF) mà chuẩn EMVCo QR dùng cho trường 63."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def vietqr_payload(bin_: str, account: str, amount: int | None = None, note: str | None = None) -> str:
    """Chuỗi VietQR (chuẩn EMVCo của Napas) chuyển nhanh 24/7 tới số tài khoản: app ngân hàng nào quét cũng điền sẵn
    ngân hàng, số tài khoản, số tiền, nội dung chuyển khoản."""
    beneficiary = _tlv("00", bin_) + _tlv("01", account)
    merchant = _tlv("00", "A000000727") + _tlv("01", beneficiary) + _tlv("02", "QRIBFTTA")
    s = _tlv("00", "01") + _tlv("01", "12" if amount else "11") + _tlv("38", merchant) + _tlv("53", "704")
    if amount:
        s += _tlv("54", str(amount))
    s += _tlv("58", "VN")
    if note:
        s += _tlv("62", _tlv("08", note))
    s += "6304"
    return s + f"{crc16_ccitt(s.encode('ascii')):04X}"


@lru_cache(maxsize=64)
def qr_png_bytes(data: str) -> bytes:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=3, dark="#0e1f45", light="#ffffff")
    return buf.getvalue()


@app.get("/qr/vietqr.{fmt}", include_in_schema=False)
def vietqr_image(fmt: str, bin: str = "", acc: str = "", amount: str = "", note: str = ""):
    """Mã VietQR để sinh viên quét bằng app ngân hàng; dữ liệu lấy từ đơn (tài khoản quán chụp lúc đặt).
    .svg để hiện trên trang, .png để lưu vào thư viện ảnh rồi mở bằng app ngân hàng trên cùng điện thoại."""
    if fmt not in ("svg", "png"):
        return Response(json.dumps({"detail": "Không có mã QR này", "code": "NOT_FOUND"}, ensure_ascii=False),
                        status_code=404, media_type="application/json")
    params = {"bin": bin, "acc": acc, "amount": amount, "note": note}
    errors = [{"field": k, "message": "không đúng định dạng"} for k, v in params.items()
              if (v or k in ("bin", "acc")) and not VIETQR_RULES[k].match(v)]
    if errors:
        return Response(json.dumps({"detail": "Thông tin mã VietQR không hợp lệ", "code": "VALIDATION_ERROR",
                                    "errors": errors}, ensure_ascii=False), status_code=422, media_type="application/json")
    payload = vietqr_payload(bin, acc, int(amount) if amount else None, " ".join(note.split()) or None)
    body, kind = (qr_svg_bytes(payload), "image/svg+xml") if fmt == "svg" else (qr_png_bytes(payload), "image/png")
    return Response(body, media_type=kind, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/qr/{kind}.svg", include_in_schema=False)
def qr_svg(kind: str, request: Request):
    target = QR_TARGETS.get(kind)
    if not target:
        return Response(json.dumps({"detail": "Không có mã QR này", "code": "NOT_FOUND"}), status_code=404,
                        media_type="application/json")
    return Response(qr_svg_bytes(f"{public_web_url(request)}/{target}"), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/health", include_in_schema=False)
def health():
    return {"service": "web", "status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "assets" / "favicon.png", media_type="image/png")


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
