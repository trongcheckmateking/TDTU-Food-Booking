# Thay đổi cho bài cuối kỳ SOA (CS504070)

Nhánh `fix/final-soa`, tách từ `4cd81a6` (bản giữa kỳ đã đẩy lên GitHub). Mỗi giai đoạn là một commit `phaseN: …`.
Kết quả kiểm thử thật của bản này: [`TEST_REPORT.md`](TEST_REPORT.md), mục "Bản cuối kỳ SOA".

## Tóm tắt theo giai đoạn

| Giai đoạn | Commit | Nội dung |
| --- | --- | --- |
| 0 | `43415e5` | Bảng tra lệnh `docs/COMMANDS.md` |
| 1 | `4e86b92` | **Sửa lỗi:** đơn tiền mặt ghi sự kiện `order_created_cash`, Notification không nhận tên này (422) nên chủ quán không được báo. Đổi thành `order_created`; cuối `schema.sql` sửa các dòng outbox cũ chưa gửi được và cho gửi lại ngay (chạy lại nhiều lần không sao) |
| 2 | `bba5da7` | Nhà cung cấp email giả lập **MockMail** (`services/mock_email`, Python/FastAPI, cổng 9000): khóa API, `Idempotency-Key` bắt buộc, giới hạn tần suất (429 + `Retry-After`), giả lập lỗi 500 / chậm / bounce, webhook kết quả giao thư ký HMAC và gửi lại 2/4/8 giây. Đưa vào `manage.py` (start/stop/status), `.env.example`, Docker Compose, gateway |
| 3 | `a96b775` | Notification (Go): `POST /internal/notifications/email` (chống trùng theo `idempotency_key`, gọi nhà cung cấp ngoài giao dịch, ánh xạ lỗi), webhook `POST /internal/webhooks/email-status` (kiểm chữ ký HMAC trên thân thô), `GET /api/admin/email-logs`, bảng `email_logs`; xóa dữ liệu cá nhân xóa cả `email_logs` |
| 4 | `2cbeaa8` | Auth (Python): **xác nhận email bằng OTP** (`otp_codes` chỉ lưu HMAC, `users.email_verified_at`, `verify-otp`, `resend-otp`, login 403 `EMAIL_NOT_VERIFIED`, đếm lần thử trước khi so mã trong `BEGIN IMMEDIATE`); Unit 18 (`POST /api/users/token` form OAuth2, `OAuth2PasswordBearer`, `WWW-Authenticate: Bearer`); Unit 17 (`UserBase`); Unit 9 (`Annotated` Query) |
| 5 | `ec9f1cb` | Giao diện: ô nhập mã OTP sau đăng ký và khi đăng nhập tài khoản chưa xác nhận, đếm ngược gửi lại mã, báo số lần thử còn lại, giao diện điện thoại |
| 6 | `17c830f` | Order: `notification_status` trên API trả một đơn; nhiều checkout đồng thời cùng `Idempotency-Key` trả lại đúng đơn (200) thay vì 409. Smoke test có bước OTP và đơn tiền mặt; e2e có OTP qua webhook thật; `scripts/demo_concurrency.py` |
| 7 | `153024a` | `X-Request-ID` xuyên 5 service + MockMail: nhận / sinh, trả lại, chuyển tiếp, log `rid=` (Python contextvar, Node AsyncLocalStorage, Java MDC, Go middleware, PHP hằng) |
| 8 | `9ea466a` | Sơ đồ kiến trúc microservices (`ARCH_0`) và luồng OTP (`ARCH_1`), ERD mới; cập nhật mọi tài liệu; Postman thư mục OTP + MockMail; `export-openapi` xuất cả MockMail; đóng gói loại `backups/` |
| 9 | commit chứa tệp này | Chạy lại toàn bộ kiểm thử, `TEST_REPORT.md`, tệp này |

## Các mức trần điểm đã gỡ

| Mức trần (theo đề) | Trước | Sau | Bằng chứng |
| --- | --- | --- | --- |
| Không có OTP → tối đa 7.0 | Chưa có OTP | **Đã gỡ**: OTP 6 số qua email (MockMail), khóa khi sai, gửi lại có giới hạn | `services/auth/app.py` (`register`, `verify_otp`, `resend_otp`), `services/notification/email.go`, `services/mock_email/app.py`; 15 test trong `tests/integration/test_auth.py`, test Go `TestIntegrationEmail*`, e2e `test_otp_email_delivered_via_signed_webhook`, 2 test giao diện |
| Không có sơ đồ kiến trúc microservices → tối đa 8.0 | Chỉ có ERD / DFD / use case | **Đã gỡ** | `docs/diagrams/arch/ARCH_0_microservices.png`, `ARCH_1_otp_flow.png`, chèn trong `ARCHITECTURE.md` |
| Không xử lý transaction / concurrency → tối đa 7.5 | Đã có | Bổ sung: đếm lần thử OTP bằng UPDATE có điều kiện, checkout đồng thời cùng khóa trả lại đúng đơn, demo chạy được trước lớp | `scripts/demo_concurrency.py`, `muoiLuongCungIdempotencyKeyDungMot201ConLaiCungDon`, `test_otp_parallel_wrong_codes_counted_exactly` |
| Chỉ là monolith → tối đa 6.5 | Không phải monolith | Giữ nguyên: 5 service, 5 ngôn ngữ, 5 CSDL riêng | `ARCH_0_microservices`, `test_contract.py` |

Tiêu chí 9–10 (tài liệu API, kiểm thử tự động, Docker Compose, idempotency, API Gateway, logging / tracing, E2E, kiểm thử
đồng thời): bảng đối chiếu đầy đủ ở [`REQUIREMENTS.md`](REQUIREMENTS.md), mục "Đối chiếu tiêu chí cuối kỳ".

## Thay đổi hợp đồng API (thêm, không đổi cái cũ)

| Service | Thêm |
| --- | --- |
| Auth | `POST /api/users/token`, `POST /api/users/verify-otp`, `POST /api/users/resend-otp`; `register` trả thêm `verification_required`, `otp_sent`, `resend_after`; `UserOut.email_verified_at`; login 403 `EMAIL_NOT_VERIFIED` (chỉ khi bật OTP); 401 có `WWW-Authenticate: Bearer` |
| Notification | `POST /internal/notifications/email`, `POST /internal/webhooks/email-status`, `GET /api/admin/email-logs` |
| Order | `notification_status` trên các API trả một đơn; checkout trùng khóa đồng thời trả 200 + `Idempotent-Replay` |
| Mọi service | Header `X-Request-ID` (nhận, trả lại, chuyển tiếp) |
| Mới | MockMail: `POST /api/send`, `GET /api/emails`, `POST /api/_control/mode`, `GET /health` |
| Cấu hình | `OTP_*`, `EMAIL_*`, `MOCK_EMAIL_*` trong `.env.example`; `.env` cũ được `manage.py` tự bổ sung |

## Chỗ làm khác đề bài / cần biết

| Mục | Đề bài | Đã làm | Lý do |
| --- | --- | --- | --- |
| Tình huống 2 của `demo_concurrency.py` | 2 lệnh `confirmed` và `cancelled` cùng lúc trên đơn `pending` | 2 lệnh `completed` và `cancelled` cùng lúc trên đơn `confirmed` | `confirmed → cancelled` là bước hợp lệ (quán hủy đơn đã nhận): khi 2 yêu cầu lệch nhau vài mili giây thì cả hai thành công đúng luật (đo 10 lần: 3 lần), demo không ổn định. Cặp mới có 2 trạng thái cuối nên luôn đúng 1 thành công (10/10 lần) |
| Checkout đồng thời cùng `Idempotency-Key` | – | Các request tới sau trả lại đúng đơn (200) thay vì 409 | Giống hành vi khi gửi lại tuần tự; test cũ chấp nhận 200/201/409 nên không phải sửa |
| Swagger của Auth | `OAuth2PasswordBearer` | Thêm `OAuth2PasswordBearer`, **giữ** `HTTPBearer` | 4 service còn lại và người dùng vẫn dán token có sẵn; mã lỗi không đổi |
| `UserBase` (Unit 17) | Model dùng chung | Chỉ gồm `name`, `email` | Giữ OpenAPI của Auth giống hệt từng byte cho các trường cũ (thứ tự trường, mô tả) |
| `verify-otp` với email chưa đăng ký | – | 400 `OTP_EXPIRED` | Không lộ email nào đã đăng ký |
| `.env` của người dùng | – | `manage.py` tự thêm các biến `OTP_*`, `EMAIL_*`, `MOCK_EMAIL_*` còn thiếu vào cuối `.env` | Để `.env` cũ chạy được bản mới; không sửa / xóa dòng nào đang có |

## Chưa làm / chưa kiểm được

- Email chỉ gửi qua MockMail giả lập, không gửi thư thật; muốn dùng thật cần nhà cung cấp có cùng kiểu API (xem `DEPLOY.md`).
- Chưa chạy trên máy chủ Linux thật với tên miền + Let's Encrypt (chỉ Docker Desktop trên Windows, chứng chỉ tự ký).
- Ảnh chụp Swagger, slide, tập dượt demo: nhóm tự làm (xem dưới).
- Giáo trình dùng FastAPI cho mọi service; dự án chỉ Auth (và MockMail) dùng FastAPI, 4 service còn lại dùng Node.js,
  Java, Go, PHP: **cần hỏi giảng viên** cách chấm phần này.
- Các mục khác chưa kiểm được: `TEST_REPORT.md`, mục "Chưa kiểm được".

## Lệnh demo

```bash
python manage.py stop
python manage.py reset-demo --yes          # XÓA dữ liệu, start 7 tiến trình, seed
python manage.py status                    # 7 dòng OK
python scripts/smoke_test.py               # cả luồng qua API, có OTP và đơn tiền mặt
python scripts/demo_concurrency.py         # đồng thời: ĐẠT
python -m pytest tests/unit tests/integration tests/e2e -q
```

Kịch bản trình bày từng bước (OTP, OAuth2 Swagger, chịu lỗi, đồng thời, truy vết, Docker): [`DEMO.md`](DEMO.md).

## Việc nhóm cần tự làm trước buổi bảo vệ

1. Chụp màn hình Swagger của 5 service (+ MockMail), đặc biệt nút Authorize OAuth2 của Auth và các endpoint OTP.
2. Làm slide: chèn `ARCH_0_microservices.png`, `ARCH_1_otp_flow.png`, bảng "Các mức trần điểm đã gỡ" ở trên.
3. Tập dượt `DEMO.md` ít nhất một lần trên máy sẽ dùng để trình bày (kể cả lệnh PowerShell lấy `$key`).
4. Hỏi giảng viên việc 4 service không dùng FastAPI.
5. Đọc lại lời giải thích "gọi Auth mỗi request thay vì RS256" và "vì sao `def` chứ không `async def`" trong
   `ARCHITECTURE.md` để trả lời vấn đáp.
