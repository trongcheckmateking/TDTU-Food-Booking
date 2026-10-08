# Tài liệu API – TDTU Food Booking

5 service viết bằng 5 ngôn ngữ (Auth: Python, Restaurant: Node.js, Order: Java, Notification: Go, Review: PHP) nhưng
dùng **chung một hợp đồng** dưới đây; hợp đồng được kiểm bằng test hộp đen trên tiến trình thật
(`tests/integration/test_contract.py`). Mỗi service có Swagger UI tại `/docs`, ReDoc tại `/redoc`, đặc tả tại `/openapi.json` (bản xuất sẵn trong `docs/openapi/`).
Trong Swagger, bấm **Authorize** và dán `access_token` lấy từ `POST /api/users/login` để thử các API cần đăng nhập.
Postman: `docs/postman/` (thư mục "0. Luồng demo" chạy được ngay trên dữ liệu seed).

## Quy ước chung

| Mục | Quy ước |
| --- | --- |
| Định dạng | JSON (UTF-8), trả object/mảng trực tiếp, không bọc `data` |
| ID | UUID dạng chuỗi |
| Thời gian | ISO 8601 UTC, ví dụ `2026-10-05T03:00:00Z` (giao diện hiển thị theo giờ máy) |
| Tiền | Số nguyên VND (`35000`), không dùng số thực |
| Vai trò | `sinh_vien`, `chu_quan`, `admin` |
| Trạng thái quán | `pending` (chờ duyệt), `active`, `closed` (tạm đóng), `locked` (admin khóa); xóa = xóa mềm |
| Trạng thái món | `available`, `sold_out` (hiện nhưng không đặt được), `hidden` (ẩn với khách) |
| Trạng thái đơn | `pending → confirmed → completed`, `pending/confirmed → cancelled` |
| Xác thực | `Authorization: Bearer <token>`; các service hỏi Auth `GET /api/users/me` |
| API nội bộ | Đường dẫn `/internal/...`, header `X-Internal-Key` (giá trị `INTERNAL_KEY` trong `.env`) |
| Danh sách | Phân trang `?page=1&page_size=20` (tối đa 100), trả `{items, total, page, page_size}` |
| Chống trùng checkout | Header `Idempotency-Key: <chuỗi bất kỳ ≤ 100 ký tự>`; gửi lại cùng key trả lại đơn cũ (HTTP 200, header `Idempotent-Replay: true`) |

## Định dạng lỗi

```json
{"detail": "Giỏ đang có món của quán khác. Hãy xóa giỏ trước khi chọn quán mới.", "code": "CART_OTHER_RESTAURANT"}
```

Lỗi dữ liệu vào (422) có thêm `errors: [{"field": "price", "message": "..."}]`.

| HTTP | Ý nghĩa | Mã thường gặp |
| --- | --- | --- |
| 400 | Yêu cầu không hợp lệ theo nghiệp vụ | `CART_EMPTY`, `SELF_ACTION` |
| 401 | Chưa đăng nhập / token sai, hết hạn, bị thu hồi | `UNAUTHORIZED`, `TOKEN_INVALID`, `TOKEN_EXPIRED`, `TOKEN_REVOKED`, `INVALID_CREDENTIALS` |
| 403 | Không đủ quyền, tài khoản bị khóa, gọi API nội bộ sai khóa | `FORBIDDEN`, `NOT_OWNER`, `ACCOUNT_LOCKED`, `RESTAURANT_LOCKED`, `INTERNAL_ONLY`, `ORDER_NOT_OWNED` |
| 404 | Không tìm thấy (kể cả quán chưa duyệt/bị khóa với khách) | `RESTAURANT_NOT_FOUND`, `ITEM_NOT_FOUND`, `ORDER_NOT_FOUND` |
| 409 | Xung đột trạng thái | `EMAIL_EXISTS`, `CART_OTHER_RESTAURANT`, `RESTAURANT_NOT_ACCEPTING`, `ITEMS_UNAVAILABLE`, `ITEM_SOLD_OUT`, `INVALID_TRANSITION`, `STATUS_CHANGED`, `CART_CHANGED`, `REVIEW_EXISTS`, `ORDER_NOT_COMPLETED`, `LAST_ADMIN`, `OWNER_HAS_RESTAURANTS` |
| 422 | Dữ liệu sai kiểu/định dạng, trường lạ | `VALIDATION_ERROR`, `QUANTITY_LIMIT` |
| 502 | Service khác trả lỗi / sai định dạng | `UPSTREAM_ERROR`, `UPSTREAM_BAD_RESPONSE`, `UPSTREAM_REJECTED` |
| 503 | Không kết nối được / quá thời gian chờ service khác | `UPSTREAM_UNAVAILABLE` |

## Ví dụ luồng chính (curl)

```bash
# 1. Đăng nhập sinh viên demo
TOKEN=$(curl -s -X POST http://127.0.0.1:8001/api/users/login -H 'Content-Type: application/json' \
  -d '{"email":"sv1@demo.tdtu.vn","password":"Demo@123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Lấy ID quán và món (seed sinh UUID ngẫu nhiên): danh sách quán, rồi menu của quán
curl -s 'http://127.0.0.1:8002/api/restaurants?q=C%C6%A1m%20T%E1%BA%A5m'        # -> RID
curl -s http://127.0.0.1:8002/api/restaurants/$RID/menu                          # -> ITEM

# 3. Thêm món vào giỏ
curl -s -X POST http://127.0.0.1:8003/api/cart/items -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"restaurant_id\":\"$RID\",\"item_id\":\"$ITEM\",\"quantity\":2}"

# 4. Đặt hàng
curl -s -X POST http://127.0.0.1:8003/api/orders/checkout -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-001' -d '{"delivery_address":"KTX TDTU, phòng B305"}'
```

Phản hồi checkout (rút gọn):

```json
{"id": "…", "status": "pending", "restaurant_name": "Cơm Tấm Cô Ba", "total_price": 70000,
 "items": [{"item_id": "…201", "item_name": "Cơm tấm sườn bì chả", "quantity": 2, "price": 35000, "line_total": 70000}],
 "customer_name": "Nguyễn Văn An", "delivery_address": "KTX TDTU, phòng B305", "created_at": "2026-10-07T04:00:00Z"}
```

Ví dụ khác: chủ quán xác nhận `PATCH :8003/api/orders/{id}/status {"status":"confirmed"}`;
sinh viên đánh giá `POST :8005/api/reviews {"order_id":"…","rating":5,"comment":"Ngon"}`;
admin duyệt quán `PATCH :8002/api/admin/restaurants/{id}/status {"status":"active"}`;
admin khóa tài khoản `PATCH :8001/api/users/{id}/status {"status":"locked"}`.

## Gọi giữa các service

| Bên gọi | Bên nhận | API | Mục đích |
| --- | --- | --- | --- |
| Restaurant, Order, Notification, Review | Auth | `GET /api/users/me` (token người dùng) | Xác thực, lấy vai trò hiện tại; tài khoản khóa bị từ chối |
| Auth | Restaurant | `GET /internal/owners/{id}/restaurant-count` | Chặn đổi vai trò chủ quán còn quán |
| Order | Restaurant | `POST /internal/quote` | Kiểm tra quán nhận đơn, món thuộc quán, còn bán, giá hiện tại |
| Order | Notification | `POST /internal/notifications/events` | Gửi sự kiện đơn (qua outbox, gửi lại khi lỗi, chống trùng) |
| Review | Order | `GET /internal/orders/{id}` | Xác minh đơn của sinh viên và đã completed |

## Danh sách endpoint

<!-- BẢNG ENDPOINT SINH TỰ ĐỘNG - chạy scripts/gen_api_md.py để cập nhật -->

### Auth Service – cổng 8001

| Method | Đường dẫn | Quyền | Mô tả |
| --- | --- | --- | --- |
| GET | `/` | Công khai | Thông tin service |
| GET | `/health` | Công khai | Readiness: service và DB sẵn sàng |
| POST | `/api/users/register` | Công khai | Đăng ký tài khoản sinh viên hoặc chủ quán |
| POST | `/api/users/login` | Công khai | Đăng nhập, nhận access_token |
| GET | `/api/users/me` | Đã đăng nhập | Hồ sơ người đang đăng nhập (các service khác gọi API này để xác thực) |
| PATCH | `/api/users/me` | Đã đăng nhập | Cập nhật họ tên, số điện thoại |
| POST | `/api/users/logout` | Đã đăng nhập | Đăng xuất: thu hồi mọi token hiện có của tài khoản |
| GET | `/api/users` | Admin | Danh sách tài khoản (admin) |
| GET | `/api/users/{user_id}` | Admin | Chi tiết tài khoản (admin) |
| PATCH | `/api/users/{user_id}/role` | Admin | Đổi vai trò (admin). Token cũ của tài khoản bị thu hồi. |
| PATCH | `/api/users/{user_id}/status` | Admin | Khóa / mở khóa tài khoản (admin). Khóa = vô hiệu hóa, giữ nguyên lịch sử đơn. |

### Restaurant Service – cổng 8002

| Method | Đường dẫn | Quyền | Mô tả |
| --- | --- | --- | --- |
| GET | `/` | Công khai | Thông tin service |
| GET | `/health` | Công khai | Readiness: service và DB sẵn sàng |
| GET | `/api/restaurants` | Công khai | Danh sách quán công khai (active, closed), tìm theo tên/địa chỉ |
| POST | `/api/restaurants` | Chủ quán | Chủ quán tạo quán mới (trạng thái pending, chờ admin duyệt) |
| GET | `/api/restaurants/mine` | Chủ quán | Các quán của chủ quán đang đăng nhập |
| GET | `/api/restaurants/{rid}` | Công khai (token tùy chọn) | Chi tiết quán (quán pending/locked chỉ chủ quán và admin xem được) |
| PATCH | `/api/restaurants/{rid}` | Chủ quán (của mình) | Chủ quán sửa thông tin, mở/tạm đóng quán (active ↔ closed) |
| DELETE | `/api/restaurants/{rid}` | Chủ quán (của mình) / Admin | Xóa mềm quán (chủ quán hoặc admin). Lịch sử đơn không bị ảnh hưởng. |
| GET | `/api/restaurants/{rid}/menu` | Công khai (token tùy chọn); all=true: chủ quán/admin | Menu của quán. Khách thấy món available/sold_out; all=true (chủ quán, admin) thấy cả món ẩn |
| POST | `/api/restaurants/{rid}/menu` | Chủ quán (của mình) | Chủ quán thêm món |
| GET | `/api/menu-items/{mid}` | Công khai (token tùy chọn) | Chi tiết 1 món |
| PATCH | `/api/menu-items/{mid}` | Chủ quán (của mình) | Chủ quán sửa món: giá, mô tả, trạng thái (available / sold_out / hidden) |
| DELETE | `/api/menu-items/{mid}` | Chủ quán (của mình) | Xóa mềm món |
| GET | `/api/admin/restaurants` | Admin | Mọi quán (admin), lọc theo trạng thái; include_deleted để xem cả quán đã xóa |
| PATCH | `/api/admin/restaurants/{rid}/status` | Admin | Duyệt (pending→active), khóa (→locked), mở khóa (locked→active) |
| POST | `/internal/quote` | Nội bộ (X-Internal-Key) | Báo giá cho Order: kiểm tra quán nhận đơn, từng món thuộc quán, còn bán, giá hiện tại |
| GET | `/internal/owners/{owner_id}/restaurant-count` | Nội bộ (X-Internal-Key) | Số quán (chưa xóa) của 1 chủ quán, Auth dùng trước khi đổi vai trò |

### Order Service – cổng 8003

| Method | Đường dẫn | Quyền | Mô tả |
| --- | --- | --- | --- |
| GET | `/` | Công khai | Thông tin service |
| GET | `/health` | Công khai | Readiness: service và DB sẵn sàng |
| GET | `/api/cart` | Sinh viên | Xem giỏ hàng (giá và trạng thái món lấy trực tiếp từ Restaurant) |
| DELETE | `/api/cart` | Sinh viên | Xóa toàn bộ giỏ |
| POST | `/api/cart/items` | Sinh viên | Thêm món vào giỏ (giỏ chỉ chứa món của 1 quán) |
| PATCH | `/api/cart/items/{item_id}` | Sinh viên | Đổi số lượng 1 món trong giỏ |
| DELETE | `/api/cart/items/{item_id}` | Sinh viên | Xóa 1 món khỏi giỏ |
| POST | `/api/orders/checkout` | Sinh viên | Đặt hàng từ giỏ. Gửi header Idempotency-Key để bấm lại/retry không tạo đơn trùng. |
| GET | `/api/orders/me` | Đã đăng nhập | Đơn của người đang đăng nhập |
| GET | `/api/orders/owner` | Chủ quán | Đơn của các quán thuộc chủ quán đang đăng nhập |
| GET | `/api/orders/{oid}` | Người đặt / chủ quán của đơn / Admin | Chi tiết đơn (người đặt, chủ quán của đơn, admin) |
| PATCH | `/api/orders/{oid}/status` | Chủ quán của đơn; SV hủy khi pending; Admin chỉ hủy | Đổi trạng thái: chủ quán xác nhận/hoàn thành/hủy; sinh viên hủy khi pending; admin chỉ hủy |
| GET | `/api/admin/orders` | Admin | Mọi đơn (admin) có bộ lọc |
| GET | `/api/admin/orders/stats` | Admin | Thống kê đơn theo trạng thái, doanh thu |
| GET | `/api/admin/outbox` | Admin | Sự kiện thông báo chờ gửi / gửi lỗi |
| POST | `/api/admin/outbox/retry` | Admin | Gửi lại ngay các thông báo lỗi |
| GET | `/internal/orders/{oid}` | Nội bộ (X-Internal-Key) | Chi tiết đơn cho service nội bộ (Review kiểm tra điều kiện đánh giá) |

### Notification Service – cổng 8004

| Method | Đường dẫn | Quyền | Mô tả |
| --- | --- | --- | --- |
| GET | `/` | Công khai | Thông tin service |
| GET | `/health` | Công khai | Readiness: service và DB sẵn sàng |
| POST | `/internal/notifications/events` | Nội bộ (X-Internal-Key) | Order Service gửi sự kiện đơn hàng (idempotent theo event_key) |
| GET | `/api/notifications/me` | Đã đăng nhập | Thông báo của tôi; status=unread để lọc chưa đọc |
| PATCH | `/api/notifications/me/read-all` | Đã đăng nhập | Đánh dấu tất cả đã đọc |
| PATCH | `/api/notifications/{nid}/read` | Đã đăng nhập (người nhận) | Đánh dấu 1 thông báo của mình là đã đọc |
| GET | `/api/admin/notifications` | Admin | Mọi thông báo (admin) |
| DELETE | `/api/admin/notifications/{nid}` | Admin | Xóa 1 thông báo (admin) |

### Review Service – cổng 8005

| Method | Đường dẫn | Quyền | Mô tả |
| --- | --- | --- | --- |
| GET | `/` | Công khai | Thông tin service |
| GET | `/health` | Công khai | Readiness: service và DB sẵn sàng |
| POST | `/api/reviews` | Sinh viên (đơn completed của mình) | Sinh viên đánh giá đơn đã hoàn thành của mình |
| GET | `/api/reviews/me` | Đã đăng nhập | Đánh giá tôi đã viết |
| GET | `/api/reviews/summary` | Công khai | Điểm trung bình của nhiều quán một lần (restaurant_ids cách nhau bằng dấu phẩy, tối đa 50) |
| GET | `/api/reviews/restaurant/{rid}` | Công khai | Đánh giá công khai của quán (phân trang, không lộ đơn hàng/người dùng) |
| GET | `/api/reviews/restaurant/{rid}/summary` | Công khai | Điểm trung bình, số lượt và phân bố sao của quán |
| GET | `/api/admin/reviews` | Admin | Mọi đánh giá (admin), lọc theo trạng thái, số sao tối đa |
| PATCH | `/api/admin/reviews/{review_id}/status` | Admin | Ẩn / hiện lại đánh giá vi phạm (admin). Không xóa cứng để đơn không bị đánh giá lại. |
