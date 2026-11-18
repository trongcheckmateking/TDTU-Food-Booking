"""Mock Email Provider "MockMail" (cổng 9000): dịch vụ gửi email BÊN THỨ BA giả lập cho Unit 20.

Notification Service gọi `POST /api/send` để gửi mã OTP; provider nhận thư (202), lưu trong bộ nhớ, rồi khoảng 1 giây
sau gọi webhook có ký HMAC về Notification để báo đã giao (delivered) hay không giao được (failed).

- Xác thực bằng header X-API-Key (EMAIL_API_KEY, thiếu hoặc dưới 16 ký tự thì không khởi động).
- Idempotency-Key bắt buộc: gửi lại cùng khóa + cùng nội dung -> trả lại đúng kết quả cũ (Idempotent-Replay: true);
  cùng khóa + nội dung khác -> 409; cùng khóa đang xử lý -> 409.
- Giới hạn MOCK_EMAIL_RATE_PER_MINUTE yêu cầu / phút / API key -> 429 + Retry-After.
- Giả lập sự cố: người nhận có phần trước @ bắt đầu bằng "fail" -> 500; "bounce" -> webhook báo failed;
  POST /api/_control/mode đổi cả provider sang fail500 / rate429 / slow (chờ 10 giây) / ok.
- Gửi THƯ THẬT: đặt EMAIL_SMTP_HOST + EMAIL_SMTP_USER + EMAIL_SMTP_PASSWORD trong .env (ví dụ Gmail + mật khẩu ứng
  dụng) thì mỗi thư được gửi qua SMTP tới đúng địa chỉ người nhận; kết quả SMTP quyết định webhook delivered / failed.
  Khi đó nội dung thư (có mã OTP) KHÔNG được lưu trong bộ nhớ, và các quy ước giả lập fail* / bounce* bị tắt.
  Không cấu hình SMTP thì vẫn là chế độ giả lập như trước (dùng cho test, demo không cần mạng).
- Dữ liệu chỉ trong bộ nhớ (mất khi khởi động lại), bảo vệ bằng threading.Lock.
- Log không ghi nội dung thư (có mã OTP), chỉ ghi message_id và email đã che (sv***@domain).
Chỉ dùng common.config (không dùng common.app.create_app): provider là hệ thống bên ngoài, không theo hợp đồng nội bộ.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import smtplib
import ssl
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Literal

import requests
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from common import config

log = logging.getLogger("mock_email")
PROVIDER = "MockMail"
MODES = ("ok", "fail500", "rate429", "slow")
SLOW_SECONDS = 10
WEBHOOK_DELAY = 1.0
WEBHOOK_RETRY_DELAYS = (2, 4, 8)           # 404 / 5xx / lỗi mạng -> thử lại sau 2, 4, 8 giây
RID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


# ---------------------------------------------------------------------------- cấu hình
def api_key() -> str:
    return config.require("EMAIL_API_KEY", 16)


def rate_per_minute() -> int:
    try:
        return max(1, int(config.get("MOCK_EMAIL_RATE_PER_MINUTE", "30")))
    except ValueError:
        return 30


def smtp_settings() -> dict | None:
    """Cấu hình gửi thư thật; None = chế độ giả lập. Cần đủ HOST + USER + PASSWORD."""
    host = (config.get("EMAIL_SMTP_HOST") or "").strip()
    user = (config.get("EMAIL_SMTP_USER") or "").strip()
    password = config.get("EMAIL_SMTP_PASSWORD") or ""
    if not (host and user and password):
        return None
    security = (config.get("EMAIL_SMTP_SECURITY") or "starttls").strip().lower()
    try:
        port = int(config.get("EMAIL_SMTP_PORT") or (465 if security == "ssl" else 587))
    except ValueError:
        port = 587
    return {"host": host, "port": port, "user": user, "password": password, "security": security,
            "from": (config.get("EMAIL_SMTP_FROM") or user).strip()}


def webhook_url() -> str | None:
    return config.get("EMAIL_WEBHOOK_URL")


def webhook_secret() -> str | None:
    return config.get("EMAIL_WEBHOOK_SECRET")


# ---------------------------------------------------------------------------- trạng thái trong bộ nhớ
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.emails: list[dict] = []                       # theo thứ tự nhận
        self.idem: dict[tuple[str, str], dict] = {}        # (api key, Idempotency-Key) -> {state, hash, result}
        self.hits: dict[str, deque] = {}                   # api key -> thời điểm các yêu cầu trong 60 giây
        self.mode = "ok"
        self.threads: list[threading.Thread] = []          # luồng gửi webhook (test chờ bằng wait_webhooks)


STATE = State()


def reset_state() -> None:
    """Xóa toàn bộ dữ liệu trong bộ nhớ (dùng cho test)."""
    global STATE
    STATE = State()


def wait_webhooks(timeout: float = 5) -> None:
    """Chờ các luồng webhook đang chạy kết thúc (dùng cho test)."""
    deadline = time.monotonic() + timeout
    for t in list(STATE.threads):
        t.join(max(0.0, deadline - time.monotonic()))


# ---------------------------------------------------------------------------- tiện ích
class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, headers: dict | None = None, **extra):
        super().__init__(detail)
        self.status, self.code, self.detail, self.headers, self.extra = status, code, detail, headers or {}, extra


def mask_email(addr: str) -> str:
    """sv1.abc@student.tdtu.edu.vn -> sv***@student.tdtu.edu.vn (log không lộ địa chỉ đầy đủ)."""
    local, _, domain = addr.partition("@")
    return f"{local[:2]}***@{domain}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sign(secret: str, body: bytes) -> str:
    """Giá trị header X-Webhook-Signature: sha256=<hex HMAC-SHA256(secret, BODY THÔ)>."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def new_rid() -> str:
    return uuid.uuid4().hex


def check_api_key(request: Request) -> str:
    given = request.headers.get("x-api-key") or ""
    if not given or not hmac.compare_digest(given.encode(), api_key().encode()):
        raise ApiError(401, "INVALID_API_KEY", "API key không hợp lệ")
    return given


def field_errors(e: ValidationError) -> list[dict]:
    out = []
    for err in e.errors():
        loc = [str(x) for x in err.get("loc", ()) if x not in ("body",)]
        msg = "trường không được phép" if err.get("type") == "extra_forbidden" else err.get("msg", "không hợp lệ")
        out.append({"field": ".".join(loc) or "body", "message": msg})
    return out


def parse_body(raw: bytes, model: type[BaseModel]) -> BaseModel:
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ", errors=[{"field": "body", "message": "JSON không hợp lệ"}])
    if not isinstance(data, dict):
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ", errors=[{"field": "body", "message": "phải là JSON object"}])
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ", errors=field_errors(e))


# ---------------------------------------------------------------------------- mô hình dữ liệu
class SendIn(BaseModel):
    """Giống ProviderEmailRequest của Unit 20: trường nội dung tên là `content`."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    to: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    tag: str | None = Field(default=None, max_length=50)


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["ok", "fail500", "rate429", "slow"]


# ---------------------------------------------------------------------------- gửi thư thật (SMTP)
def send_smtp(settings: dict, to: str, subject: str, content: str) -> str | None:
    """Gửi một thư qua SMTP. Trả None nếu thành công, hoặc mã lý do ngắn (không chứa nội dung thư / mật khẩu)."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings["from"], to, subject
    msg.set_content(content)
    try:
        if settings["security"] == "ssl":
            smtp = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(settings["host"], settings["port"], timeout=20)
        with smtp:
            if settings["security"] != "ssl" and settings["security"] != "none":
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings["user"], settings["password"])
            smtp.send_message(msg)
        return None
    except smtplib.SMTPAuthenticationError:
        return "smtp_auth_failed"
    except smtplib.SMTPRecipientsRefused:
        return "mailbox_not_found"
    except (smtplib.SMTPException, OSError) as e:
        return "smtp_" + type(e).__name__.lower()


# ---------------------------------------------------------------------------- webhook
def deliver_webhook(email: dict, rid: str, content: str | None = None) -> None:
    """Báo kết quả giao thư cho Notification: delivered, hoặc failed (bounce / SMTP lỗi).
    Có cấu hình SMTP: gửi thư thật rồi báo theo kết quả; không thì giả lập (bounce* -> failed)."""
    smtp = smtp_settings()
    if smtp and content is not None:
        reason = send_smtp(smtp, email["to"], email["subject"], content)
        status = "failed" if reason else "delivered"
        if reason:
            log.warning("Gửi SMTP %s tới %s thất bại: %s rid=%s", email["message_id"], mask_email(email["to"]), reason, rid)
        else:
            log.info("Đã gửi SMTP %s tới %s rid=%s", email["message_id"], mask_email(email["to"]), rid)
    else:
        time.sleep(WEBHOOK_DELAY)
        bounce = email["to"].split("@", 1)[0].lower().startswith("bounce")
        status, reason = ("failed", "mailbox_not_found") if bounce else ("delivered", None)
    with STATE.lock:
        email["status"] = status
    url, secret = webhook_url(), webhook_secret()
    if not url or not secret:
        log.info("Bỏ qua webhook %s (chưa cấu hình EMAIL_WEBHOOK_URL / EMAIL_WEBHOOK_SECRET) rid=%s", email["message_id"], rid)
        return
    body = json.dumps({"message_id": email["message_id"], "status": status, "reason": reason,
                       "timestamp": now_iso()}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-Webhook-Signature": sign(secret, body), "X-Request-ID": rid}
    session = requests.Session()
    session.trust_env = False
    for attempt, delay in enumerate((0, *WEBHOOK_RETRY_DELAYS), start=1):
        if delay:
            time.sleep(delay)
        try:
            r = session.post(url, data=body, headers=headers, timeout=5)   # data=<bytes đã ký>, KHÔNG dùng json=
            if r.status_code != 404 and r.status_code < 500:
                log.info("Webhook %s -> %s: HTTP %s (lần %d) rid=%s", email["message_id"], status, r.status_code, attempt, rid)
                return
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = type(e).__name__
        log.warning("Webhook %s lỗi %s (lần %d) rid=%s", email["message_id"], err, attempt, rid)
    log.error("Bỏ webhook %s sau %d lần thử rid=%s", email["message_id"], 1 + len(WEBHOOK_RETRY_DELAYS), rid)


def start_webhook(email: dict, rid: str, content: str | None = None) -> None:
    t = threading.Thread(target=deliver_webhook, args=(email, rid, content), name="mock-email-webhook", daemon=True)
    STATE.threads.append(t)
    t.start()


# ---------------------------------------------------------------------------- ứng dụng
@asynccontextmanager
async def lifespan(_: FastAPI):
    api_key()                                  # thiếu EMAIL_API_KEY (dưới 16 ký tự) -> dừng ngay khi khởi động
    yield


logging.basicConfig(level=config.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
app = FastAPI(title="Mock Email Provider (MockMail)", version="1.0.0", lifespan=lifespan,
              description="Dịch vụ gửi email bên thứ ba GIẢ LẬP cho TDTU Food (Unit 20). Dữ liệu chỉ nằm trong bộ nhớ.",
              swagger_ui_parameters={"persistAuthorization": True})


@app.middleware("http")
async def request_id_and_log(request: Request, call_next):
    raw = request.headers.get("x-request-id") or ""
    rid = raw if RID_RE.match(raw) else new_rid()
    request.state.rid = rid
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Lỗi không mong đợi tại %s %s rid=%s", request.method, request.url.path, rid)
        response = JSONResponse({"detail": "Có lỗi nội bộ", "code": "INTERNAL_ERROR"}, status_code=500)
    response.headers["X-Request-ID"] = rid
    if request.url.path != "/health":
        log.info("%s %s %s %dms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000, rid)
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, e: ApiError):
    return JSONResponse({"detail": e.detail, "code": e.code, **e.extra}, status_code=e.status, headers=e.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, e: RequestValidationError):
    errors = [{"field": ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query")) or "body",
               "message": err.get("msg", "không hợp lệ")} for err in e.errors()]
    return JSONResponse({"detail": "Dữ liệu không hợp lệ", "code": "VALIDATION_ERROR", "errors": errors}, status_code=422)


@app.get("/health", tags=["health"], summary="Provider còn sống")
def health():
    return {"service": "mock_email", "status": "ok"}


def _rate_limit(key: str) -> None:
    limit, now = rate_per_minute(), time.monotonic()
    with STATE.lock:
        q = STATE.hits.setdefault(key, deque())
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, math.ceil(60 - (now - q[0])))
            raise ApiError(429, "RATE_LIMITED", f"Vượt giới hạn {limit} yêu cầu/phút", headers={"Retry-After": str(retry)},
                           retry_after=retry)
        q.append(now)


@app.post("/api/send", status_code=202, tags=["email"], summary="Gửi một email (bất đồng bộ: trả 202 rồi giao sau)",
          responses={400: {"description": "IDEMPOTENCY_KEY_REQUIRED"}, 401: {"description": "INVALID_API_KEY"},
                     409: {"description": "IDEMPOTENCY_CONFLICT / IDEMPOTENCY_IN_PROGRESS"},
                     422: {"description": "VALIDATION_ERROR"}, 429: {"description": "RATE_LIMITED (+ Retry-After)"},
                     500: {"description": "PROVIDER_ERROR (người nhận fail..., chế độ fail500)"}},
          openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
              "schema": SendIn.model_json_schema(),
              "example": {"to": "sv1@student.tdtu.edu.vn", "subject": "TDTU Food - Mã xác nhận email",
                          "content": "Mã xác nhận của bạn là 042917, có hiệu lực 5 phút.", "tag": "otp"}}}},
                        "parameters": [{"name": "Idempotency-Key", "in": "header", "required": True,
                                        "schema": {"type": "string", "minLength": 1, "maxLength": 120}}]})
async def send(request: Request):
    key = check_api_key(request)
    idem = (request.headers.get("idempotency-key") or "").strip()
    if not idem:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Thiếu header Idempotency-Key")
    if len(idem) > 120:
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ",
                       errors=[{"field": "Idempotency-Key", "message": "tối đa 120 ký tự"}])
    body = parse_body(await request.body(), SendIn)
    # phần còn lại có khóa và time.sleep (chế độ slow): chạy trong threadpool để không chặn event loop
    return await run_in_threadpool(_send_sync, request.state.rid, key, idem, body)


def _send_sync(rid: str, key: str, idem: str, body: SendIn):
    _rate_limit(key)
    if STATE.mode == "rate429":
        raise ApiError(429, "RATE_LIMITED", "Provider đang giới hạn tần suất", headers={"Retry-After": "60"}, retry_after=60)
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    slot = (key, idem)
    with STATE.lock:
        prev = STATE.idem.get(slot)
        if prev is not None:
            if prev["state"] == "processing":
                raise ApiError(409, "IDEMPOTENCY_IN_PROGRESS", "Yêu cầu cùng Idempotency-Key đang được xử lý")
            if prev["hash"] != fingerprint:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key đã dùng cho một email có nội dung khác")
            return JSONResponse(prev["result"], status_code=202, headers={"Idempotent-Replay": "true"})
        real = smtp_settings() is not None          # gửi thật: không giả lập địa chỉ fail* / bounce*
        fail = STATE.mode == "fail500" or (not real and str(body.to).split("@", 1)[0].lower().startswith("fail"))
        if fail:                                    # lỗi: không lưu kết quả idempotency, gửi lại sẽ thử lại thật
            log.warning("Từ chối gửi tới %s (giả lập lỗi provider) rid=%s", mask_email(str(body.to)), rid)
            raise ApiError(500, "PROVIDER_ERROR", "Provider gặp lỗi khi gửi email")
        STATE.idem[slot] = {"state": "processing", "hash": fingerprint, "result": None}
        slow = STATE.mode == "slow"
    try:
        if slow:
            time.sleep(SLOW_SECONDS)
        message_id = "msg_" + uuid.uuid4().hex
        result = {"message_id": message_id, "status": "accepted", "provider": PROVIDER}
        # gửi thật: nội dung (có mã OTP) chỉ đi qua SMTP, không giữ lại trong hộp thư của provider
        email = {"message_id": message_id, "to": str(body.to), "subject": body.subject,
                 "content": "[đã gửi qua SMTP, không lưu nội dung]" if real else body.content,
                 "tag": body.tag, "status": "accepted", "idempotency_key": idem, "created_at": now_iso()}
        with STATE.lock:
            STATE.emails.append(email)
            STATE.idem[slot] = {"state": "done", "hash": fingerprint, "result": result}
    except BaseException:
        with STATE.lock:
            STATE.idem.pop(slot, None)
        raise
    log.info("Nhận email %s tới %s (tag=%s) rid=%s", message_id, mask_email(email["to"]), body.tag, rid)
    start_webhook(email, rid, body.content if real else None)
    return JSONResponse(result, status_code=202)


@app.get("/api/emails", tags=["email"], summary="Hộp thư đã gửi (chỉ để demo / test lấy mã OTP), mới nhất trước")
def list_emails(request: Request, to: str | None = None, limit: str = "20"):
    check_api_key(request)
    try:
        n = int(limit)
    except ValueError:
        n = 0
    if not 1 <= n <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "Dữ liệu không hợp lệ", errors=[{"field": "limit", "message": "phải từ 1 đến 100"}])
    with STATE.lock:
        items = [dict(e) for e in reversed(STATE.emails) if to is None or e["to"].lower() == to.strip().lower()]
    return {"items": items[:n]}


@app.post("/api/_control/mode", tags=["control"], summary="Đổi chế độ giả lập: ok / fail500 / rate429 / slow")
async def set_mode(request: Request):
    check_api_key(request)
    body = parse_body(await request.body(), ModeIn)
    with STATE.lock:
        STATE.mode = body.mode
    log.info("Đổi chế độ provider -> %s rid=%s", body.mode, request.state.rid)
    return {"mode": body.mode}


def custom_openapi():
    """Thêm nút Authorize (X-API-Key) cho Swagger: các endpoint đọc header thủ công để giữ thứ tự 401 -> 400 -> 422."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["APIKeyHeader"] = {
        "type": "apiKey", "in": "header", "name": "X-API-Key", "description": "Giá trị EMAIL_API_KEY trong .env"}
    for path, ops in schema.get("paths", {}).items():
        if path.startswith("/api/"):
            for op in ops.values():
                op["security"] = [{"APIKeyHeader": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
