# Đánh giá mã nguồn đầu vào

Ngày đánh giá: 07/10/2026. Bằng chứng chạy thử nằm trong `docs/evidence/source_review/`.
Ký hiệu: **[Tái hiện]** = đã chạy và quan sát được lỗi; **[Đọc mã]** = kết luận từ đọc mã, chưa chạy được.

## 1. Nguồn đã nhận

| Nguồn | Nội dung | SHA-256 (rút gọn) |
| --- | --- | --- |
| `TDTU_FoodBooking_Code.zip` | 5 service Python/FastAPI + `admin/admin.html` + script chạy + `test_flow.py` (34 tệp) | `595bcb60…` |
| `TDTU_ban_sua_4_service.zip` | Restaurant (Node.js), Order (Java), Notification (Go), Review (PHP) đã vá + `SUA_DOI.patch` + `kiem_thu_ghep_noi.py` (116 tệp) | `63361e00…` |
| `TDTU_FoodBooking_SoDo.zip` | 19 sơ đồ PNG/SVG (Use Case, DFD 0/1/2, ERD) + `gen_diagrams.py` (43 tệp) | `ce6c71ff…` |
| Ảnh đính kèm | Bảng đặc điểm FastAPI | – |
| Tài liệu trước đó trong phiên | `Tong_quan_du_an_ban_giao.docx` (quy ước, ERD 7 bảng), `Ke_hoach_lam_viec_TDTU_Food_Booking.pdf` (phân công TV1–TV5) | – |

Ba ZIP được giải nén vào thư mục riêng, không có đường dẫn tuyệt đối hoặc `../` trong archive.

**Giới hạn của ảnh:** ảnh chỉ là bảng so sánh đặc điểm FastAPI (tối ưu cho API, async, Pydantic, Swagger/ReDoc,
không có ORM, không có trang admin tích hợp). Ảnh không phải đề giữa kỳ, không có danh sách chức năng, thang điểm
hay yêu cầu đa ngôn ngữ. Các mô tả tốc độ trong ảnh không phải số đo của dự án này.

## 2. `TDTU_FoodBooking_Code.zip` – 5 service FastAPI

**Kiến trúc:** 5 ứng dụng FastAPI độc lập (cổng 8001–8005), mỗi service một tệp SQLite, `sqlite3` thuần, Pydantic v2,
bcrypt, PyJWT, `requests` gọi chéo. Bản sao `db.py`, `auth_client.py` lặp trong từng service.

**Đã có:** đăng ký/đăng nhập/JWT; CRUD quán, menu; đơn hàng dùng đơn `pending` làm giỏ; chuyển trạng thái;
thông báo theo sự kiện từ Order; đánh giá + điểm trung bình; API admin cho cả 5 service; trang `admin.html`.

**Chạy thực tế:** khởi động 5 service, `test_flow.py` đạt 28/28 bước (`code_test_flow.txt`) **[Tái hiện]**.

**Lỗi/rủi ro** (script `probe_source_fastapi.py`, kết quả `probe_source_fastapi.txt`):

| # | Vấn đề | Vị trí | Loại |
| --- | --- | --- | --- |
| 1 | JWT ký bằng secret mặc định viết cứng được chấp nhận | `auth_service/main.py` `SECRET = os.getenv(..., "tdtu-food-booking-secret")` | [Tái hiện] |
| 2 | Khóa nội bộ mặc định `tdtu-internal-key` dùng được | `common/auth_client.py` | [Tái hiện] |
| 3 | Tự tạo admin `admin@tdtu.edu.vn / admin123` ở mọi môi trường | `auth_service/main.py` `seed_admin()` | [Tái hiện] (log khởi động) |
| 4 | Email chỉ khác hoa/thường đăng ký được 2 tài khoản | `auth_service/main.py` `register` | [Tái hiện] |
| 5 | Mật khẩu 30 ký tự "ệ" (90 byte) gây lỗi 500 (bcrypt giới hạn 72 byte) | `auth_service/models.py` `max_length=72` đếm ký tự | [Tái hiện] |
| 6 | Không có trạng thái khóa tài khoản (DFD có "khóa / đổi vai trò") | `auth_service/models.py` | [Đọc mã] |
| 7 | Khách không đăng nhập xem được món ẩn qua `?all=true` | `restaurant_service/main.py` `get_menu` | [Tái hiện] |
| 8 | Quán bị khóa vẫn xem chi tiết công khai | `restaurant_service/main.py` `restaurant_detail` | [Tái hiện] |
| 9 | Giá `1e309` (vô hạn) và tên chỉ có khoảng trắng được chấp nhận | `restaurant_service/models.py` `price: float` | [Tái hiện] |
| 10 | `quantity: true` được hiểu là 1 | `order_service/models.py` `CartItem` | [Tái hiện] |
| 11 | `order_items.item_name` luôn null (không lưu tên món) | `order_service/main.py` `create_order` | [Tái hiện] |
| 12 | Admin được chuyển đơn sang mọi trạng thái (khác bản Java chỉ cho hủy) | `order_service/main.py` `update_status` | [Tái hiện] |
| 13 | 2 request đổi trạng thái đồng thời cùng trả 200 (ghi đè) | `order_service/main.py` đọc rồi ghi không điều kiện | [Tái hiện] |
| 14 | Một kết nối SQLite toàn cục `check_same_thread=False` dùng chung mọi request | `common/db.py`, `conn = connect(...)` đầu mỗi `main.py` | [Đọc mã] |
| 15 | `notify()` không kiểm tra HTTP status; lỗi thông báo mất dấu, không gửi lại | `order_service/main.py` `notify` | [Đọc mã] |
| 16 | `fetch()` gọi `raise_for_status()` không bắt -> lỗi 5xx của Restaurant thành 500 | `order_service/main.py` `fetch` | [Đọc mã] |
| 17 | Sự kiện thông báo với quán không tồn tại gây 500 (`.json()` trước khi kiểm tra status) | `notification_service/main.py` `handle_event` | [Tái hiện] |
| 18 | Gửi lại cùng sự kiện tạo thông báo trùng | `notification_service/main.py` | [Tái hiện] |
| 19 | Bắt mọi `IntegrityError` và báo "Đơn này đã được đánh giá" | `review_service/main.py` `create_review` | [Đọc mã] |
| 20 | Giá dùng `REAL` (số thực) cho tiền VND | các `models.py` | [Đọc mã] |
| 21 | "Giỏ" là đơn pending: chủ quán nhận "đơn mới" ngay khi sinh viên còn đang chọn món | `order_service/main.py` `add_to_cart` | [Đọc mã] |
| 22 | `admin.html` mở bằng `file://`, chưa có giao diện sinh viên/chủ quán | `admin/admin.html` | [Đọc mã] |
| 23 | Không có duyệt quán, không phân trang, đường dẫn DB phụ thuộc thư mục hiện tại | – | [Đọc mã] |

## 3. `TDTU_ban_sua_4_service.zip` – bản đa ngôn ngữ đã vá

Các tệp `SUA_DOI.patch` **đã nằm sẵn trong mã** (kiểm tra bằng `git apply --check -R`: cả 4 bản vá khớp ngược),
nên không áp dụng lại. Trước khi vá (06/10/2026), kiểm tra ghép nối bản gốc chỉ đạt 3/15 lời gọi chéo
(`multilang_original_probe_2026-10-06.json`) **[Tái hiện]**.

| Service | Công nghệ | Điểm mạnh đáng tận dụng | Vấn đề | Chạy thực tế |
| --- | --- | --- | --- | --- |
| Restaurant | Node.js 18+, Express 5, lưu tệp JSON | Thông báo lỗi rõ; không xóa quán còn món (409) | Ghi `readFileSync/writeFileSync` mỗi request, không an toàn khi ghi đồng thời [Đọc mã]; `PATCH /api/menu-items/:id` cho đổi `restaurant_id` chỉ kiểm tra quán đích tồn tại, không kiểm tra quyền ở quán đích (`server.js`) [Đọc mã]; trạng thái `open` khác `active` của FastAPI; không có API admin | `node --check` đạt |
| Order | Java 17, Spring Boot 3.5.6, JPA, H2 in-memory | Giỏ `Cart/CartItem` riêng + checkout; lọc theo user/quán/trạng thái/ngày; `OrderStatus.canChangeTo` + test; admin chỉ hủy; Postman | H2 trong bộ nhớ: tắt app mất dữ liệu (`application.properties`) [Đọc mã]; tiền `double`; không chống checkout lặp; `MockAuthClient` dùng header `X-User-Role` (chỉ dùng cho demo) [Đọc mã]; kiểm tra chủ quán gọi Restaurant mỗi lần | Không build được: Maven Central bị chặn trong môi trường kiểm thử (`java_build.txt`) |
| Notification | Go, Gin, GORM, PostgreSQL, Docker | Docker Compose cho DB | `POST /api/notifications` công khai, ai cũng tạo được thông báo [Đọc mã]; không chống trùng; `go.mod` yêu cầu Go 1.26 | Bản gốc không build được ở đây (`go_build.txt`); lỗi khóa ngoại của `init.sql` gốc tái hiện trên PostgreSQL 16 [Tái hiện] |
| Review | PHP 8.3, PDO, MySQL (SQLite cho test) | Kiểm tra đầu vào chặt (rating số nguyên, comment ≤ 1000 ký tự, chặn trường giả mạo); phân trang; xử lý lỗi upstream 502/503; 22 test tình huống lỗi | Kết quả bọc `{"data": …}`; ID đánh giá tự tăng; điểm TB làm tròn 2 chữ số; chưa có API admin; CORS chỉ 1 origin | `php tests/run.php`: 22/22 đạt (`php_review_tests.txt`) [Tái hiện] |

Không có Auth Service trong ZIP này. README của Notification còn hướng dẫn cổng 8080 và `/notifications`, không còn khớp mã đã vá.

## 4. `TDTU_FoodBooking_SoDo.zip` – sơ đồ

- 19 sơ đồ PNG/SVG: Use Case tổng + 5 service, DFD mức 0, mức 1, mức 2 cho 5 service, ERD tổng + 5 service.
- Mô hình lõi 7 bảng `users, restaurants, menu_items, orders, order_items, notifications, reviews`; 3 tác nhân.
- `gen_diagrams.py` chạy từ thư mục giải nén bị lỗi đường dẫn (`FileNotFoundError` vì tìm `../diagrams`,
  `../scripts/actor.png`) **[Tái hiện]** (`sodo_gen_run.txt`).
- Sơ đồ có các nghiệp vụ mã chưa có: khóa tài khoản, duyệt quán, kiểm duyệt đánh giá; ERD vẽ quan hệ xuyên service
  bằng nét liền như khóa ngoại thật.

## 5. Kết luận

Theo yêu cầu "mỗi dịch vụ là một ngôn ngữ khác nhau", bản cuối giữ ngôn ngữ của từng thành viên (Python, Node.js, Java,
Go, PHP) và viết lại phần còn thiếu theo hợp đồng API của bản FastAPI (bản hoàn chỉnh nhất về nghiệp vụ). Các lỗi ghép
nối nêu ở mục 3 (đường dẫn, kiểu ID, CORS, khóa nội bộ, xác thực) được sửa trong mã của chính từng ngôn ngữ. Sơ đồ là nguồn
nghiệp vụ cho khóa tài khoản, duyệt quán, kiểm duyệt. Quyết định cụ thể ở `MERGE_DECISIONS.md`.
