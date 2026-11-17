# Mock Email Provider "MockMail" – Python / FastAPI (cổng 9000)

Dịch vụ gửi email **bên thứ ba giả lập** (Unit 20). Notification Service gọi provider này để gửi mã OTP xác nhận
email; provider nhận thư (202) rồi khoảng 1 giây sau gọi **webhook có ký HMAC** về Notification để báo đã giao
(`delivered`) hoặc không giao được (`failed`). Dữ liệu chỉ nằm trong bộ nhớ, mất khi khởi động lại.

```bash
python -m uvicorn services.mock_email.app:app --port 9000      # chạy từ thư mục gốc; manage.py start tự chạy
python -m pytest tests/unit/test_mock_email.py                 # test riêng
```

Cấu hình (`.env` ở thư mục gốc, `init-env` tự sinh khóa): `EMAIL_API_KEY` (bắt buộc, từ 16 ký tự, thiếu thì không khởi
động), `EMAIL_WEBHOOK_URL` (trống = không gửi webhook), `EMAIL_WEBHOOK_SECRET`, `MOCK_EMAIL_RATE_PER_MINUTE` (30).

| Endpoint | Ghi chú |
| --- | --- |
| `POST /api/send` | Header `X-API-Key`, `Idempotency-Key` (1–120 ký tự). Body `{to, subject, content, tag?}`, trường lạ → 422. 202 `{"message_id": "msg_<hex>", "status": "accepted", "provider": "MockMail"}` |
| `GET /api/emails?to=&limit=` | Hộp thư đã gửi, mới nhất trước (chỉ để demo / test lấy mã OTP) |
| `POST /api/_control/mode` | `{"mode": "ok" \| "fail500" \| "rate429" \| "slow"}` (slow: chờ 10 giây rồi mới nhận) |
| `GET /health` | `{"service": "mock_email", "status": "ok"}` |

Mã lỗi của `POST /api/send`: 401 `INVALID_API_KEY`, 400 `IDEMPOTENCY_KEY_REQUIRED`, 422 `VALIDATION_ERROR`,
409 `IDEMPOTENCY_CONFLICT` (cùng khóa, khác nội dung) / `IDEMPOTENCY_IN_PROGRESS`, 429 `RATE_LIMITED` (+ `Retry-After`),
500 `PROVIDER_ERROR` (người nhận có phần trước `@` bắt đầu bằng `fail`, hoặc chế độ `fail500`; lỗi không được nhớ
theo Idempotency-Key). Gửi lại cùng khóa + cùng nội dung → 202 với kết quả cũ và header `Idempotent-Replay: true`.

Webhook: `POST {EMAIL_WEBHOOK_URL}` với body thô `{"message_id", "status", "reason", "timestamp"}` và header
`X-Webhook-Signature: sha256=<hex HMAC-SHA256(EMAIL_WEBHOOK_SECRET, body)>`. Người nhận bắt đầu bằng `bounce` →
`failed` (`reason: "mailbox_not_found"`). Nhận 404, 5xx hoặc lỗi mạng thì thử lại sau 2, 4, 8 giây.

Lấy mã OTP khi demo: mở `http://127.0.0.1:9000/docs` → **Authorize** (dán `EMAIL_API_KEY`) → `GET /api/emails`.
Log không ghi nội dung thư, chỉ ghi `message_id` và email đã che (`sv***@domain`).
