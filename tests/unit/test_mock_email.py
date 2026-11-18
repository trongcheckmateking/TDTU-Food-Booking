"""Unit test Mock Email Provider (services/mock_email, Unit 20): API key, Idempotency-Key, giới hạn tần suất,
giả lập lỗi, chế độ hoạt động, webhook có ký HMAC, hộp thư lọc theo người nhận, X-Request-ID."""
import hashlib
import hmac
import json
import os
import threading

import pytest
import requests
from fastapi.testclient import TestClient

os.environ.setdefault("TDTU_ENV_FILE", os.path.join(os.path.dirname(__file__), "no-such.env"))

from services.mock_email import app as mock  # noqa: E402

KEY = "mock-email-test-key-0123456789"
SECRET = "mock-webhook-secret-0123456789"
BODY = {"to": "sv1@student.tdtu.edu.vn", "subject": "TDTU Food - Mã xác nhận email",
        "content": "Mã xác nhận của bạn là 042917, có hiệu lực 5 phút.", "tag": "otp"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EMAIL_API_KEY", KEY)
    monkeypatch.setenv("MOCK_EMAIL_RATE_PER_MINUTE", "1000")
    monkeypatch.setenv("EMAIL_WEBHOOK_URL", "")            # mặc định không gửi webhook
    monkeypatch.setenv("EMAIL_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(mock, "WEBHOOK_DELAY", 0)
    for k in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_USER", "EMAIL_SMTP_PASSWORD"):   # không bao giờ gửi thư thật khi test
        monkeypatch.delenv(k, raising=False)
    mock.reset_state()
    with TestClient(mock.app) as c:
        yield c
    mock.wait_webhooks()
    mock.reset_state()


def send(c, body=None, key=KEY, idem="otp-0001", **headers):
    h = dict(headers)
    if key is not None:
        h["X-API-Key"] = key
    if idem is not None:
        h["Idempotency-Key"] = idem
    return c.post("/api/send", json=body if body is not None else BODY, headers=h)


def emails(c, **params):
    return c.get("/api/emails", headers={"X-API-Key": KEY}, params=params).json()["items"]


def test_health_and_accept(client):
    assert client.get("/health").json() == {"service": "mock_email", "status": "ok"}
    r = send(client)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["status"] == "accepted" and out["provider"] == "MockMail" and out["message_id"].startswith("msg_")
    assert int(out["message_id"][4:], 16) >= 0
    assert [e["message_id"] for e in emails(client)] == [out["message_id"]]


def test_api_key_missing_or_wrong_401(client):
    for key in (None, "", "sai-key-0123456789"):
        r = send(client, key=key)
        assert r.status_code == 401 and r.json()["code"] == "INVALID_API_KEY", (key, r.text)
    # sai key được trả 401 trước cả khi kiểm tra body / Idempotency-Key
    assert send(client, body={"x": 1}, key="sai", idem=None).status_code == 401
    assert client.get("/api/emails").status_code == 401
    assert client.post("/api/_control/mode", json={"mode": "ok"}).status_code == 401
    assert emails(client) == []


def test_idempotency_key_required_400(client):
    for idem in (None, "", "   "):
        r = send(client, idem=idem)
        assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED", (idem, r.text)
    assert send(client, idem="k" * 121).status_code == 422
    assert send(client, idem="k" * 120).status_code == 202


def test_body_validation_422(client):
    cases = [{**BODY, "cc": "x@y.vn"}, {**BODY, "to": "khong-phai-email"}, {**BODY, "subject": ""},
             {k: v for k, v in BODY.items() if k != "content"}, {**BODY, "content": "x" * 5001}, {**BODY, "body": "x"}]
    for i, b in enumerate(cases):
        r = send(client, body=b, idem=f"k-{i}")
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR", (b, r.text)
    r = send(client, body={**BODY, "cc": "x@y.vn"}, idem="k-extra")
    assert {"field": "cc", "message": "trường không được phép"} in r.json()["errors"]
    r = client.post("/api/send", content=b"not json", headers={"X-API-Key": KEY, "Idempotency-Key": "k-raw",
                                                               "Content-Type": "application/json"})
    assert r.status_code == 422
    assert emails(client) == []


def test_replay_same_key_and_body_returns_cached_result(client):
    first = send(client)
    again = send(client)
    assert again.status_code == 202 and again.json() == first.json()
    assert again.headers.get("Idempotent-Replay") == "true" and "Idempotent-Replay" not in first.headers
    assert len(emails(client)) == 1
    other = send(client, idem="otp-0002")                   # khóa khác -> email mới
    assert other.json()["message_id"] != first.json()["message_id"] and len(emails(client)) == 2


def test_same_key_different_body_409(client):
    assert send(client).status_code == 202
    r = send(client, body={**BODY, "content": "Mã xác nhận của bạn là 111111."})
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(emails(client)) == 1


def test_same_key_in_progress_409(client, monkeypatch):
    monkeypatch.setattr(mock, "SLOW_SECONDS", 1.5)
    client.post("/api/_control/mode", json={"mode": "slow"}, headers={"X-API-Key": KEY})
    results = {}
    t = threading.Thread(target=lambda: results.setdefault("slow", send(client, idem="otp-slow")))
    t.start()
    for _ in range(100):                                    # chờ yêu cầu đầu chiếm khóa
        if mock.STATE.idem:
            break
        threading.Event().wait(0.02)
    r = send(client, idem="otp-slow")
    t.join()
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS", r.text
    assert results["slow"].status_code == 202
    assert send(client, idem="otp-slow").headers.get("Idempotent-Replay") == "true"


def test_rate_limit_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("MOCK_EMAIL_RATE_PER_MINUTE", "2")
    assert send(client, idem="r1").status_code == 202
    assert send(client, idem="r2").status_code == 202
    r = send(client, idem="r3")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    assert 1 <= int(r.headers["Retry-After"]) <= 60 and r.json()["retry_after"] == int(r.headers["Retry-After"])
    assert len(emails(client)) == 2


def test_fail_recipient_500_not_remembered(client):
    for _ in range(2):                                      # lỗi không lưu kết quả: gửi lại vẫn thử thật (vẫn 500)
        r = send(client, body={**BODY, "to": "fail@example.com"}, idem="otp-fail")
        assert r.status_code == 500 and r.json()["code"] == "PROVIDER_ERROR", r.text
        assert "Idempotent-Replay" not in r.headers
    assert send(client, body={**BODY, "to": "failure.test@example.com"}, idem="otp-fail2").status_code == 500
    assert emails(client) == []
    assert send(client, idem="otp-fail").status_code == 202   # cùng khóa, người nhận hợp lệ -> nhận bình thường


def test_control_modes(client):
    h = {"X-API-Key": KEY}
    assert client.post("/api/_control/mode", json={"mode": "fail500"}, headers=h).json() == {"mode": "fail500"}
    assert send(client, idem="m1").status_code == 500
    client.post("/api/_control/mode", json={"mode": "rate429"}, headers=h)
    r = send(client, idem="m2")
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"
    client.post("/api/_control/mode", json={"mode": "ok"}, headers=h)
    assert send(client, idem="m3").status_code == 202
    for bad in ({"mode": "down"}, {"mode": "ok", "x": 1}, {}):
        assert client.post("/api/_control/mode", json=bad, headers=h).status_code == 422, bad


def test_webhook_signed_raw_body_and_retry(client, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_URL", "http://notification.test/internal/webhooks/email-status")
    monkeypatch.setattr(mock.time, "sleep", lambda s: None)
    calls, replies = [], {"bounce@student.tdtu.edu.vn": [500, 404, 200]}

    def fake_post(self, url, data=None, headers=None, **kw):
        assert kw.get("json") is None, "webhook phải gửi data=<bytes đã ký>, không dùng json="
        payload = json.loads(data)
        calls.append({"url": url, "data": data, "headers": headers, "payload": payload})
        to = next(e["to"] for e in mock.STATE.emails if e["message_id"] == payload["message_id"])
        seq = replies.get(to)
        resp = requests.Response()
        resp.status_code = seq.pop(0) if seq else 200
        return resp

    monkeypatch.setattr(requests.Session, "post", fake_post)
    ok = send(client, idem="w1", **{"X-Request-ID": "demo-rid-0001"}).json()
    bad = send(client, body={**BODY, "to": "bounce@student.tdtu.edu.vn"}, idem="w2").json()
    mock.wait_webhooks()

    by_id = {}
    for c in calls:
        assert isinstance(c["data"], bytes)
        expected = "sha256=" + hmac.new(SECRET.encode(), c["data"], hashlib.sha256).hexdigest()
        assert c["headers"]["X-Webhook-Signature"] == expected == mock.sign(SECRET, c["data"])
        assert c["url"].endswith("/internal/webhooks/email-status")
        assert set(c["payload"]) == {"message_id", "status", "reason", "timestamp"}
        by_id.setdefault(c["payload"]["message_id"], []).append(c)
    assert len(by_id[ok["message_id"]]) == 1
    assert by_id[ok["message_id"]][0]["payload"]["status"] == "delivered"
    assert by_id[ok["message_id"]][0]["payload"]["reason"] is None
    assert by_id[ok["message_id"]][0]["headers"]["X-Request-ID"] == "demo-rid-0001"
    tries = by_id[bad["message_id"]]
    assert len(tries) == 3                                     # 500, 404 -> thử lại; 200 -> dừng
    assert tries[0]["payload"] == {**tries[0]["payload"], "status": "failed", "reason": "mailbox_not_found"}
    statuses = {e["message_id"]: e["status"] for e in emails(client)}
    assert statuses == {ok["message_id"]: "delivered", bad["message_id"]: "failed"}


def test_webhook_gives_up_after_retries_on_network_error(client, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_URL", "http://127.0.0.1:9/khong-co")
    waits = []
    monkeypatch.setattr(mock.time, "sleep", waits.append)
    attempts = []

    def boom(self, url, **kw):
        attempts.append(url)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests.Session, "post", boom)
    send(client, idem="w-net")
    mock.wait_webhooks()
    assert len(attempts) == 4 and waits == [0, 2, 4, 8]


def test_list_emails_filter_and_limit(client):
    send(client, idem="a1")
    send(client, body={**BODY, "to": "sv2@student.tdtu.edu.vn"}, idem="b1")
    send(client, idem="a2", body={**BODY, "content": "Mã mới 555555."})
    got = emails(client, to="SV1@student.tdtu.edu.vn")
    assert [e["content"] for e in got] == ["Mã mới 555555.", BODY["content"]]      # mới nhất trước
    assert len(emails(client, limit=1)) == 1 and len(emails(client)) == 3
    for bad in ("0", "101", "x"):
        assert client.get("/api/emails", headers={"X-API-Key": KEY}, params={"limit": bad}).status_code == 422


def test_request_id_echo_or_generated(client):
    assert client.get("/health", headers={"X-Request-ID": "demo-rid-0001"}).headers["X-Request-ID"] == "demo-rid-0001"
    for bad in (None, "ngan", "co dau cach!!", "x" * 129):
        h = {"X-Request-ID": bad} if bad else {}
        rid = client.get("/health", headers=h).headers["X-Request-ID"]
        assert len(rid) == 32 and int(rid, 16) >= 0, (bad, rid)
    assert len(send(client, key="sai").headers["X-Request-ID"]) == 32     # cả response lỗi cũng có header


def test_log_has_no_otp_code(client, caplog):
    caplog.set_level("INFO", logger="mock_email")
    send(client, idem="log-1")
    mock.wait_webhooks()
    text = caplog.text
    assert "042917" not in text and "sv1@student.tdtu.edu.vn" not in text and "sv***@student.tdtu.edu.vn" in text


def test_startup_requires_api_key(monkeypatch):
    for bad in ("", "ngan-qua"):
        monkeypatch.setenv("EMAIL_API_KEY", bad)
        with pytest.raises(RuntimeError):
            with TestClient(mock.app):
                pass


# ---------------------------------------------------------------------------- gửi thư thật qua SMTP (SMTP giả trong test)
class FakeSMTP:
    sent: list = []
    fail: Exception | None = None
    calls: list = []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", host, port, context is not None))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user))

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.fail, FakeSMTP.calls = [], None, []
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("EMAIL_SMTP_USER", "tdtufood@example.test")
    monkeypatch.setenv("EMAIL_SMTP_PASSWORD", "app-password-0123456789")
    monkeypatch.setattr(mock.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mock.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_smtp_settings_need_host_user_password(monkeypatch):
    for k in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_USER", "EMAIL_SMTP_PASSWORD", "EMAIL_SMTP_PORT", "EMAIL_SMTP_SECURITY",
              "EMAIL_SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert mock.smtp_settings() is None
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("EMAIL_SMTP_USER", "a@gmail.com")
    assert mock.smtp_settings() is None                              # thiếu mật khẩu
    monkeypatch.setenv("EMAIL_SMTP_PASSWORD", "x" * 16)
    s = mock.smtp_settings()
    assert (s["host"], s["port"], s["security"], s["from"]) == ("smtp.gmail.com", 587, "starttls", "a@gmail.com")
    monkeypatch.setenv("EMAIL_SMTP_SECURITY", "ssl")
    assert mock.smtp_settings()["port"] == 465


def test_smtp_sends_real_mail_to_recipient_and_keeps_no_content(client, smtp):
    r = send(client)
    assert r.status_code == 202
    mock.wait_webhooks()
    assert len(smtp.sent) == 1
    m = smtp.sent[0]
    assert m["To"] == BODY["to"] and m["From"] == "tdtufood@example.test" and m["Subject"] == BODY["subject"]
    assert "042917" in m.get_content()
    assert ("starttls",) in smtp.calls and ("login", "tdtufood@example.test") in smtp.calls
    kept = emails(client)[0]
    assert "042917" not in json.dumps(kept) and kept["status"] == "delivered"      # không giữ mã trong bộ nhớ


def test_smtp_failure_reports_failed_webhook_and_no_fake_rules(client, smtp, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_URL", "http://notification.test/internal/webhooks/email-status")
    posted = []

    class R:
        status_code = 200

    class S:
        trust_env = False

        def post(self, url, data=None, headers=None, timeout=None):
            posted.append(json.loads(data))
            return R()

    monkeypatch.setattr(mock.requests, "Session", S)
    smtp.fail = mock.smtplib.SMTPRecipientsRefused({"x": (550, b"no such user")})
    # trong chế độ gửi thật, địa chỉ bắt đầu bằng "fail" / "bounce" là địa chỉ thật, không bị giả lập lỗi
    assert send(client, body={**BODY, "to": "fail.nguyen@student.tdtu.edu.vn"}, idem="real-1").status_code == 202
    mock.wait_webhooks()
    assert posted[0]["status"] == "failed" and posted[0]["reason"] == "mailbox_not_found"
    smtp.fail = mock.smtplib.SMTPAuthenticationError(535, b"bad credentials")
    assert send(client, idem="real-2").status_code == 202
    mock.wait_webhooks()
    assert posted[1]["status"] == "failed" and posted[1]["reason"] == "smtp_auth_failed"


def test_smtp_log_has_no_code_or_password(client, smtp, caplog):
    caplog.set_level("INFO", logger="mock_email")
    send(client, idem="log-smtp")
    mock.wait_webhooks()
    assert "042917" not in caplog.text and "app-password-0123456789" not in caplog.text
    assert "sv***@student.tdtu.edu.vn" in caplog.text


def test_smtp_server_rejection_reports_code(smtp):
    smtp.fail = mock.smtplib.SMTPDataError(550, b"5.7.1 bi han che gui thu ngoai he thong")
    assert mock.send_smtp(mock.smtp_settings(), "a@gmail.com", "s", "c") == "smtp_550"
