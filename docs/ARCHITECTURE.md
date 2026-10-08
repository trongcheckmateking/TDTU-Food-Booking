# Kiến trúc

## Tổng quan: 5 service, 5 ngôn ngữ

```
 Trình duyệt ──HTTP──> Web UI :8000 (Python, HTML/CSS/JS tĩnh + /config.js)
      │
      │  fetch + Bearer token (CORS)
      ▼
 ┌──────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌───────────────────┐ ┌──────────────┐
 │ Auth :8001   │ │ Restaurant :8002 │ │ Order :8003      │ │ Notification :8004│ │ Review :8005 │
 │ Python       │ │ Node.js          │ │ Java             │ │ Go                │ │ PHP          │
 │ FastAPI      │ │ Express 5        │ │ Spring Boot 3.5  │ │ Gin + GORM        │ │ thuần + PDO  │
 │ SQLite       │ │ SQLite node:sqlite│ │ H2 (tệp)         │ │ PostgreSQL        │ │ SQLite       │
 │ auth.db      │ │ restaurant.db    │ │ order.mv.db      │ │ bảng notifications│ │ review.db    │
 └─────▲────────┘ └──────▲───────────┘ └──┬───┬───▲───────┘ └─────────▲─────────┘ └──────┬───────┘
       │ /api/users/me   │ /internal/quote │   │   │ /internal/orders/{id}                  │
       └── 4 service còn lại xác thực token ─┘  │   └───────────────────────────────────────┘
                                               └── outbox ──> /internal/notifications/events
```

| Service | Thành viên | Ngôn ngữ / framework | CSDL | Mã nguồn |
| --- | --- | --- | --- | --- |
| Auth | TV1 | Python 3.11+ / FastAPI, Pydantic, PyJWT, bcrypt | SQLite | `services/auth`, `common/` |
| Restaurant | TV2 | Node.js 22+ / Express 5 | SQLite qua `node:sqlite` (có sẵn trong Node) | `services/restaurant` |
| Order | TV3 | Java 17+ / Spring Boot 3.5.6 (Web, JDBC) | H2 dạng tệp (`DATA_DIR/order.mv.db`) | `services/order` |
| Notification | TV4 | Go 1.22+ / Gin 1.10, GORM 1.25 | PostgreSQL 14+ | `services/notification` |
| Review | TV5 | PHP 8.1+ (không framework, `php -S`) | SQLite qua PDO | `services/review` |

- Mỗi service là một tiến trình độc lập ở cổng riêng, sở hữu CSDL riêng. Không service nào đọc CSDL của service khác;
  dữ liệu khác service chỉ lấy qua REST JSON. ID là UUID dạng chuỗi ở mọi service.
- Các service khác ngôn ngữ nhưng dùng **cùng một hợp đồng**: cùng tệp `.env`, cùng định dạng lỗi, cùng quy tắc ánh xạ
  lỗi khi gọi nhau, cùng CORS, cùng phân trang, cùng `/health`, `/docs`, `/redoc`, `/openapi.json`.
  Hợp đồng được kiểm bằng test hộp đen trên tiến trình thật (`tests/integration/test_contract.py`).
- `web/server.py` (Python) phục vụ giao diện và sinh `/config.js` chứa địa chỉ các service.
- `manage.py` (Python) là công cụ vận hành chung: kiểm tra môi trường, build, chạy/dừng 6 tiến trình, seed qua API.

Sơ đồ chi tiết: `docs/diagrams/dfd/DFD_1_tong_the.png` (luồng dữ liệu), `docs/diagrams/erd/ERD_0_tong_the.png` (dữ liệu).

## Hợp đồng chung giữa các service

| Mục | Quy ước (giống nhau ở cả 5 ngôn ngữ) |
| --- | --- |
| Cấu hình | Biến môi trường, rồi tệp `.env` ở thư mục gốc (`TDTU_ENV_FILE` để đổi). Thiếu `INTERNAL_KEY` → Node/Java/Go dừng khi khởi động; PHP trả 500 `CONFIG_ERROR` cho mọi request |
| Cổng | Lấy từ `<TÊN>_URL` của chính service; địa chỉ bind `BIND_HOST` (mặc định 127.0.0.1) |
| Lỗi | `{"detail": "<tiếng Việt>", "code": "<MÃ>"}`; 422 thêm `errors: [{field, message}]`; JSON hỏng → 422 "JSON gửi lên không hợp lệ"; 404 `NOT_FOUND` |
| Dữ liệu vào | Kiểm tra chặt: trường lạ bị chặn, chuỗi cắt khoảng trắng, số nguyên phải là số nguyên JSON thật (1.5, "2", true bị từ chối) |
| Xác thực | `Authorization: Bearer` → gọi Auth `GET /api/users/me`; 401/403 của Auth được chuyển tiếp nguyên mã |
| Nội bộ | `/internal/*` (Restaurant, Order, Notification) chỉ nhận `X-Internal-Key`, so sánh hằng thời gian (`crypto.timingSafeEqual`, `MessageDigest.isEqual`, `subtle.ConstantTimeCompare`); Auth và Review chỉ gửi khóa khi gọi đi |
| Gọi service khác | Timeout `HTTP_TIMEOUT`; không kết nối/quá giờ → 503 `UPSTREAM_UNAVAILABLE`; 5xx → 502 `UPSTREAM_ERROR`; không phải JSON → 502 `UPSTREAM_BAD_RESPONSE`; 4xx ngoài dự kiến → 502 `UPSTREAM_REJECTED` |
| CORS | Chỉ origin trong `CORS_ORIGINS`; preflight cho phép `Authorization, Content-Type, Idempotency-Key` |
| Phân trang | `page` (≥1), `page_size` (1–100) → `{items, total, page, page_size}` |
| Thời gian | Chuỗi ISO 8601 UTC đến giây: `2026-10-07T03:00:00Z` |
| Tiền | VND, số nguyên (không dùng số thực) |

## Xác thực và phân quyền

1. Auth (Python) ký JWT HS256 (`sub`, `role`, `ver`, `iss`, `iat`, `exp`), hạn `TOKEN_HOURS` giờ, khóa `JWT_SECRET`.
   Chỉ Auth biết `JWT_SECRET`; 4 service còn lại không tự giải mã token.
2. Service khác nhận `Authorization: Bearer …`, gọi Auth `GET /api/users/me`. Auth kiểm tra chữ ký, hạn, issuer,
   `ver == users.token_version`, trạng thái tài khoản. Vì vậy khóa tài khoản, đổi vai trò hay đăng xuất có hiệu lực
   ngay ở mọi service, ở mọi ngôn ngữ.
3. Mỗi endpoint kiểm tra vai trò và quyền trên đối tượng (chủ quán của quán/đơn, người đặt đơn).
   Ẩn nút trên giao diện chỉ để tiện dùng; backend luôn tự kiểm tra.

## Luồng đặt món

1. Sinh viên thêm món (Order, Java): Order gọi Restaurant (Node.js) `POST /internal/quote` kiểm tra quán `active`,
   món thuộc quán, `available`, lấy giá hiện tại.
2. Checkout: Order báo giá lại toàn bộ giỏ, rồi trong **một giao dịch** (H2): khóa dòng giỏ của sinh viên bằng
   `SELECT … FOR UPDATE` (các checkout đồng thời xếp hàng), kiểm tra `Idempotency-Key`, kiểm tra giỏ không đổi, ghi
   `orders` + `order_items` (ảnh chụp tên quán, tên món, đơn giá), ghi sự kiện `order_created` vào `notification_outbox`,
   xóa giỏ. Lỗi ở bất kỳ bước nào → rollback, giỏ còn nguyên. `UNIQUE(user_id, idempotency_key)` chặn trùng ở mức CSDL.
3. Sau commit, Order gửi sự kiện sang Notification (Go). Thành công → `sent`; lỗi → `failed` + ghi lỗi, luồng nền
   (`ScheduledExecutorService`, chu kỳ `OUTBOX_INTERVAL`) gửi lại với thời gian chờ tăng dần (10 s, 20 s, 40 s … tối đa
   300 s; tối đa 10 lần); admin có nút "Gửi lại ngay". Notification chèn `ON CONFLICT DO NOTHING` theo
   `UNIQUE(event_key, user_id)` (PostgreSQL) nên gửi lại không tạo thông báo trùng.
4. Đổi trạng thái: `UPDATE orders SET status=? WHERE id=? AND status=<cũ>`; nếu 0 dòng → 409 `STATUS_CHANGED`
   (2 request đồng thời chỉ 1 thành công). Sự kiện tương ứng ghi outbox trong cùng giao dịch. Luật chuyển trạng thái
   là `OrderStatus.canChangeTo` (giữ từ bản Java của TV3).
5. Review (PHP) gọi Order `GET /internal/orders/{id}` để xác minh đơn của sinh viên và đã `completed`;
   `UNIQUE(order_id)` ở SQLite chặn đánh giá trùng kể cả gửi đồng thời.

## Đồng thời theo từng runtime

| Service | Mô hình | Cách giữ đúng dữ liệu khi đồng thời |
| --- | --- | --- |
| Auth (Python) | uvicorn, handler đồng bộ chạy trong threadpool | Kết nối SQLite riêng mỗi request, WAL, `BEGIN IMMEDIATE`; kiểm tra "admin cuối cùng" trong giao dịch |
| Restaurant (Node.js) | 1 luồng, event loop; lệnh `node:sqlite` đồng bộ | Mỗi khối giao dịch chạy trọn vẹn không xen kẽ; `BEGIN IMMEDIATE` |
| Order (Java) | Tomcat nhiều luồng, Hikari pool | `SELECT … FOR UPDATE` trên giỏ, `UPDATE … WHERE status=<cũ>`, ràng buộc UNIQUE |
| Notification (Go) | goroutine mỗi request, pool kết nối PostgreSQL | `INSERT … ON CONFLICT DO NOTHING`, cập nhật có điều kiện |
| Review (PHP) | `php -S` (4 worker trên Linux/macOS, 1 trên Windows) | `UNIQUE(order_id)` + `busy_timeout`, bắt lỗi ràng buộc → 409 |

## Cấu hình

Tất cả trong `.env` (mẫu: `.env.example`): `JWT_SECRET`, `INTERNAL_KEY`, `POSTGRES_PASSWORD`, `NOTIFICATION_DB_URL`
(bắt buộc; `manage.py init-env` sinh ngẫu nhiên), `TOKEN_HOURS`, `DATA_DIR`, `*_URL` (cổng lấy từ URL), `WEB_PORT`,
`CORS_ORIGINS`, `HTTP_TIMEOUT`, `OUTBOX_INTERVAL`, `LOG_LEVEL`. Giao diện lấy địa chỉ service từ `/config.js`
(ghi đè bằng `PUBLIC_*_URL` khi truy cập từ máy khác).

## Vận hành

`manage.py start` chạy 6 tiến trình bằng đúng runtime của từng service:

| Tiến trình | Lệnh (cwd) |
| --- | --- |
| auth | `python -m uvicorn services.auth.app:app` (gốc dự án) |
| restaurant | `node --disable-warning=ExperimentalWarning src/server.js` (`services/restaurant`) |
| order | `java -jar target/order-service.jar` (`services/order`) |
| notification | `bin/notification-service` (`services/notification`) |
| review | `php -S 127.0.0.1:8005 public/index.php` (`services/review`) |
| web | `python -m uvicorn web.server:app` (gốc dự án) |

PID ghi vào `.run/pids.json`, log vào `logs/<tên>.log`; lệnh chờ `/health` của từng tiến trình (kiểm tra cả kết nối
CSDL), báo dòng log cuối nếu một tiến trình dừng sớm. `manage.py stop` chỉ dừng các PID đã ghi (cả cây tiến trình).

## Giới hạn đã biết

- SQLite/H2 dạng tệp phù hợp demo một máy; triển khai nhiều máy cần DB server cho cả 5 service.
- Outbox chỉ dùng cho thông báo; nếu Restaurant sập khi checkout, đơn không được tạo (trả 503, giỏ giữ nguyên).
- Token không làm mới tự động (hết hạn sau `TOKEN_HOURS`, đăng nhập lại).
- `php -S` là máy chủ phát triển của PHP, đủ cho demo; triển khai thật nên dùng PHP-FPM + Nginx/Apache.
- `node:sqlite` của Node.js 22 còn được Node đánh dấu "experimental" (đã tắt cảnh báo khi chạy).
