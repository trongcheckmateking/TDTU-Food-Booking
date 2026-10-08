# Quyết định hợp nhất

**Kiến trúc cuối:** mỗi service một ngôn ngữ, đúng phân công của nhóm (yêu cầu "mỗi dịch vụ là một ngôn ngữ khác nhau"):

| Service | Thành viên | Ngôn ngữ cuối | Nguồn chính | CSDL |
| --- | --- | --- | --- | --- |
| Auth :8001 | TV1 | Python / FastAPI | `Code.zip` (bản FastAPI) | SQLite |
| Restaurant :8002 | TV2 | Node.js / Express 5 | `TV2_Restaurant_Service` | SQLite (`node:sqlite`) thay cho tệp JSON |
| Order :8003 | TV3 | Java / Spring Boot 3.5.6 | `TV3_Order_Service` | H2 dạng tệp (thay H2 trong bộ nhớ) |
| Notification :8004 | TV4 | Go / Gin + GORM | `TV4_Notification_Service` | PostgreSQL (giữ như TV4) |
| Review :8005 | TV5 | PHP thuần | `TV5_Review_Service` | SQLite qua PDO (giữ như TV5) |

Cả 5 service dùng **chung một hợp đồng API** (tài liệu `API.md`, OpenAPI trong `docs/openapi/`) đã được hoàn thiện ở bản
hợp nhất trước: cùng đường dẫn, cùng định dạng JSON, cùng mã lỗi. Nghiệp vụ bổ sung (duyệt quán, giỏ hàng, outbox,
khóa tài khoản…) được viết lại bằng chính ngôn ngữ của từng service. Giao diện web và công cụ vận hành (`manage.py`)
viết bằng Python vì phục vụ chung cả hệ thống.

Lựa chọn của nhóm khi có phương án: giữ **Spring Boot** cho Order (TV3) và **PostgreSQL** cho Notification (TV4).

## Theo từng service

### Auth (Python/FastAPI) — giữ bản FastAPI, đã sửa ở bản hợp nhất trước
| Thành phần | Quyết định | Lý do |
| --- | --- | --- |
| `sqlite3` + Pydantic, gói `common/` | Giữ | `common/` nay chỉ phục vụ Auth (cấu hình, DB, lỗi, gọi REST) |
| Secret mặc định, admin tự tạo | Sửa: `.env` bắt buộc, `init-env` sinh khóa; admin chỉ qua `create-admin`/seed | Không còn bí mật trong mã |
| Khóa tài khoản, thu hồi token | `status`, `token_version` | Khóa/đổi vai trò/đăng xuất có hiệu lực ngay ở mọi service |
| Đổi vai trò chủ quán còn quán | Chặn 409, hỏi Restaurant (Node) qua `/internal/owners/{id}/restaurant-count` | Tránh quán mồ côi |

### Restaurant (Node.js/Express) — giữ ngôn ngữ và framework của TV2
| Thành phần TV2 | Quyết định | Lý do / cách làm |
| --- | --- | --- |
| Express 5.1.0 | Giữ | |
| Lưu tệp `data/*.json` | Thay bằng SQLite qua `node:sqlite` (có sẵn trong Node 22, không cần build native) | Ghi đồng thời an toàn, có giao dịch, có khóa ngoại món → quán |
| Trạng thái `open` | Đổi thành `pending/active/closed/locked` | Có duyệt quán (DFD Restaurant), quán khóa không nhận đơn |
| Xóa quán bị chặn khi còn món (409) | Đổi thành xóa mềm `deleted_at` | Không phá lịch sử đơn |
| Đổi `restaurant_id` của món | Không cho: trường lạ bị 422 | Lỗ hổng chuyển món sang quán khác |
| Không xác thực | Thêm xác thực qua Auth `/me`, kiểm tra chủ quán của quán | |
| Báo giá cho Order | Thêm `POST /internal/quote` | Order không tin giá từ client |
| Kiểm tra dữ liệu | Viết bộ kiểm tra chặt `src/validate.js` | Cùng luật với Pydantic của Auth |
| Test | Thêm `test/restaurant.test.js` (`node --test`, Auth giả) | |

### Order (Java/Spring Boot) — giữ ngôn ngữ, framework, gói `com.tdtu.order_service` của TV3
| Thành phần TV3 | Quyết định | Lý do / cách làm |
| --- | --- | --- |
| `OrderStatus` + `canChangeTo` + `OrderStatusTest` | Giữ nguyên | Luật chuyển trạng thái đúng |
| `Cart/CartItem`, giỏ 1 quán, đổi quán khi giỏ trống | Giữ ý tưởng, bảng `carts/cart_items` | Thêm 409 `CART_OTHER_RESTAURANT` |
| Admin chỉ hủy đơn lỗi | Giữ | Admin không xử lý thay chủ quán |
| Bộ lọc đơn (trạng thái, quán, người dùng, ngày) | Giữ, thêm phân trang | |
| H2 trong bộ nhớ, `ddl-auto` | Đổi: H2 dạng tệp + `schema.sql` | Dữ liệu còn sau khi tắt; bảng đúng ERD (CHECK, UNIQUE) |
| Spring Data JPA | Đổi sang `JdbcTemplate` (spring-boot-starter-jdbc) | Cần `SELECT … FOR UPDATE`, `UPDATE … WHERE status=<cũ>` và đọc ngay sau ghi trong cùng giao dịch; viết SQL tường minh rõ ràng hơn, khởi động nhanh hơn |
| `double` cho tiền | Đổi `long` (VND) | Không sai số |
| `MockAuthClient/RealAuthClient` | Thay bằng `AuthClient` gọi Auth `/me` | Bỏ chế độ giả lập trong bản chạy thật |
| `RestaurantClient` | Gọi `/internal/quote` với `X-Internal-Key` | Giá do server lấy |
| `NotificationClient` gọi thẳng | Thay bằng outbox (`OutboxService`) + luồng gửi lại | Notification sập không làm mất thông báo |
| Checkout | Viết lại: báo giá lại, giao dịch, ảnh chụp tên/giá, `Idempotency-Key` | Chống bấm lặp, giỏ chỉ xóa khi thành công |
| springdoc-openapi | Bỏ; phục vụ `openapi.json` chung + Swagger UI | Một hợp đồng chung cho 5 service, bớt phụ thuộc |
| `SampleDataLoader`, `admin.html` riêng | Bỏ | Dữ liệu demo nạp qua API (`manage.py seed`); giao diện chung ở cổng 8000 |
| Test | Giữ `OrderStatusTest`, thêm `JsonTest`, `OrderFlowTest` (Spring Boot thật + server giả) | |

### Notification (Go/Gin/GORM/PostgreSQL) — giữ ngôn ngữ, framework, CSDL của TV4
| Thành phần TV4 | Quyết định | Lý do / cách làm |
| --- | --- | --- |
| Gin, GORM, PostgreSQL | Giữ (nhóm chọn giữ PostgreSQL) | Cần cài PostgreSQL hoặc Docker; `manage.py pg-setup` tạo user/DB |
| `POST /api/notifications` công khai, nội dung do bên gọi gửi | Thay bằng `POST /internal/notifications/events` (X-Internal-Key), Notification tự soạn nội dung theo sự kiện | Không ai giả mạo thông báo; người nhận theo luật |
| `AutoMigrate`, bảng thiếu ràng buộc | Đổi sang SQL tường minh: `UNIQUE(event_key, user_id)`, CHECK status | Gửi lại không nhân đôi |
| DSN mặc định `root/rootpassword` | Bỏ; bắt buộc `NOTIFICATION_DB_URL` từ `.env` (mật khẩu sinh ngẫu nhiên) | Không còn mật khẩu trong mã |
| CORS `*` | Chỉ origin cấu hình | |
| Đánh dấu đã đọc | Giữ, thêm `read_at`, "đọc tất cả", admin xem/xóa | |
| docker-compose (DB + app) | Thay bằng `docker-compose.postgres.yml` chỉ chạy PostgreSQL (tùy chọn) | App chạy chung với 4 service còn lại qua `manage.py` |
| Thư viện `gorm.io/*`, `golang.org/x/*` | Giữ, `go.mod` trỏ về bản mirror GitHub chính thức | Môi trường build của nhóm chặn domain vanity; mã nguồn và phiên bản giống hệt |
| Test | Thêm `notification_test.go` (unit + tích hợp PostgreSQL thật) | |

### Review (PHP) — giữ ngôn ngữ và cấu trúc của TV5
| Thành phần TV5 | Quyết định | Lý do / cách làm |
| --- | --- | --- |
| PHP thuần, `ApiError`, `jsonResponse`, `jsonBody`, lớp `Reviews`, `Call_Auth_Order` | Giữ tên và cách tổ chức | |
| `Reviews::validate` (rating số nguyên chặt, comment ≤ 1000) | Giữ | |
| Bọc `{"data": …}`, lỗi `{"error": {...}}` | Đổi sang hợp đồng chung `{detail, code}` và JSON trực tiếp | Giao diện và các service dùng chung |
| Gọi Order `/api/orders/{id}` bằng token người dùng | Đổi sang `/internal/orders/{id}` + X-Internal-Key | Order chỉ trả đơn đầy đủ cho service tin cậy |
| MySQL/SQLite tùy chọn, `config.local.php` | Chỉ SQLite (PDO), cấu hình từ `.env` chung | Một cách cấu hình cho cả hệ thống |
| Xóa đánh giá | Đổi thành ẩn (`status=hidden`) | Giữ `order_id` nên không đánh giá lại cùng đơn |
| `tests/run.php`, `tests/upstream.php` | Giữ ý tưởng, viết lại theo hợp đồng mới (44 kiểm tra) | |

## Phần dùng chung

| Thành phần | Quyết định | Lý do |
| --- | --- | --- |
| Giao diện 3 vai trò (cổng 8000) | Giữ từ bản hợp nhất trước, không đổi | Hợp đồng API không đổi nên giao diện chạy với 5 service mới |
| `manage.py` | Mở rộng: `doctor`, `build`, `pg-setup`, chạy 5 runtime, `test-services`, seed qua REST API | Một lệnh cho mọi hệ điều hành |
| Seed | Đổi từ ghi thẳng DB sang gọi REST API | Mỗi service có CSDL/ngôn ngữ riêng; dữ liệu demo đi qua đúng nghiệp vụ |
| Test liên service | Đổi từ "5 app trong 1 tiến trình" sang tiến trình thật + fault proxy | Kiểm tra thật hợp đồng giữa 5 ngôn ngữ |

## Bảng bổ sung so với 7 bảng lõi

| Bảng | Service | Lý do |
| --- | --- | --- |
| `carts`, `cart_items` | Order | Giỏ hàng trước khi đặt (thay cho đơn pending) |
| `notification_outbox` | Order | Ghi sự kiện cùng giao dịch với đơn, gửi lại khi Notification lỗi |

Các cột mới quan trọng: `users.status/token_version`, `restaurants.status_reason/deleted_at`,
`orders.customer_name/restaurant_name/restaurant_owner_id/idempotency_key/cancel_reason/cancelled_by`,
`order_items.item_name/line_total`, `notifications.event_key/type/read_at`, `reviews.reviewer_name/status/hidden_reason`.
Chi tiết ở `DATABASE.md`.
