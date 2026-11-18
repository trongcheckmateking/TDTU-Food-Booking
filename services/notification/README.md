# Notification Service – Go / Gin / GORM / PostgreSQL (TV4)

Cổng 8004. Nhận sự kiện đơn hàng (nội bộ, chống trùng), thông báo của tôi, đánh dấu đã đọc, admin xem/xóa.
Gửi email mã OTP qua nhà cung cấp bên thứ ba (MockMail, Unit 20) và nhận webhook kết quả giao thư có ký HMAC.
CSDL: PostgreSQL theo `NOTIFICATION_DB_URL` (tạo user/DB: `python manage.py pg-setup` hoặc `docker-compose.postgres.yml`).

```bash
go build -o bin/notification-service .     # Go 1.22+ (Windows: bin/notification-service.exe)
./bin/notification-service                  # đọc .env ở thư mục gốc dự án
NOTIFICATION_TEST_DB_URL=postgres://... go test -count=1 .
```
Mã: `main.go` (router), `handlers.go` (sự kiện, thông báo), `email.go` (gửi email, webhook, nhật ký email),
`store.go` (schema), `auth.go`, `errors.go`, `config.go`, `requestid.go`.

## Gửi email OTP (Unit 20)

| Endpoint | Xác thực | Ghi chú |
| --- | --- | --- |
| `POST /internal/notifications/email` | `X-Internal-Key` | Auth gọi sau khi đăng ký / gửi lại mã. Body kiểm tra chặt (trường lạ → 422) |
| `POST /internal/webhooks/email-status` | Chữ ký HMAC (`X-Webhook-Signature`) | Provider báo `delivered` / `failed`. Không dùng `X-Internal-Key` vì provider không giữ khóa nội bộ |
| `GET /api/admin/email-logs?status=&user_id=&page=&page_size=` | Admin | Nhật ký gửi email, không có mã OTP |

Cấu hình: `EMAIL_PROVIDER_URL`, `EMAIL_API_KEY` (thiếu một trong hai → 503 `EMAIL_NOT_CONFIGURED`),
`EMAIL_PROVIDER_TIMEOUT` (giây, mặc định 3, phải nhỏ hơn `HTTP_TIMEOUT` của Auth), `EMAIL_WEBHOOK_SECRET`
(trống → mọi webhook bị 401).

Ánh xạ lỗi khi gọi provider: lỗi mạng / quá thời gian chờ → 503 `EMAIL_PROVIDER_UNAVAILABLE`; 401/403 → 502
`EMAIL_PROVIDER_AUTH`; 429 → 503 `EMAIL_PROVIDER_RATE_LIMITED` + `Retry-After` của provider (mặc định 60); 5xx → 502
`EMAIL_PROVIDER_ERROR`; 2xx sai dạng → 502 `EMAIL_PROVIDER_BAD_RESPONSE`; 409 → 409 `EMAIL_IN_PROGRESS`; 4xx khác → 400
`EMAIL_REJECTED`.

Chống gửi trùng: `email_logs.idempotency_key` UNIQUE (Auth dùng `otp-<otp_id>`). Đã `sent`/`delivered` → 200
`{..., "replay": true}`, không gọi provider lần nữa; đang `sending` dưới 30 giây → 409; `failed` hoặc `sending` quá
30 giây → giành lại bằng UPDATE có điều kiện rồi gửi lại trên chính dòng đó. Gọi provider nằm ngoài transaction.

Webhook chỉ cho `sent → delivered` hoặc `sent → failed` (lý do lưu ở `last_error`); cùng trạng thái → 200; trạng thái
cuối khác → 200 `{"received": true, "ignored": true}`; không tìm thấy `message_id` → 404 (provider thử lại).

Mã OTP chỉ nằm trong body gửi provider: không lưu vào `email_logs`, không ghi log (log chỉ có user_id, message_id,
email đã che `sv***@domain`). Xóa dữ liệu cá nhân (`/internal/users/{id}/erase`) xóa cả `email_logs` của tài khoản.
