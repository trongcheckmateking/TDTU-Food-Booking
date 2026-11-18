# Tóm tắt dự án – phục vụ thuyết trình

## Bài toán

Sinh viên TDTU đặt đồ ăn từ các quán gần trường; chủ quán nhận và xử lý đơn; quản trị viên kiểm soát tài khoản,
quán và nội dung. Hệ thống xây dựng theo kiến trúc hướng dịch vụ (SOA): 5 dịch vụ độc lập giao tiếp qua REST.

## Tác nhân và chức năng

| Tác nhân | Chức năng chính |
| --- | --- |
| Sinh viên | Đăng ký (xác nhận email bằng mã OTP 6 số) / đăng nhập (có màn hướng dẫn nhận món), đặt món và thanh toán trước bằng mã VietQR (tiền vào thẳng tài khoản quán), rồi tới quán đọc mã đơn 3 số (như Grab, be), cài app lên điện thoại, tìm quán, xem menu và đánh giá, giỏ hàng, đặt món, theo dõi/hủy đơn, nhận thông báo, đánh giá quán, xem bảng tin món mới, quét QR để vào app |
| Chủ quán | Khai báo tài khoản ngân hàng nhận tiền khi đăng ký (mã QR riêng của quán), xác nhận đã nhận tiền / hoàn tiền, đăng ký quán (chờ duyệt), quản lý menu/giá/trạng thái món, mở/tạm đóng quán, xác nhận/hoàn thành/hủy đơn, xem đánh giá; món mới/đổi giá tự lên bảng tin; đăng ký qua mã QR, in QR dán tại quán |
| Admin | Khóa/mở khóa, đổi vai trò tài khoản; duyệt/khóa quán; hủy đơn (sinh viên không tự hủy), thống kê; ẩn đánh giá vi phạm; gửi lại thông báo lỗi; in áp phích mã QR giới thiệu app; bảng điều khiển có biểu đồ tỉ lệ, quản lý riêng sinh viên / chủ quán |

## 5 dịch vụ

| Dịch vụ | Cổng | Ngôn ngữ · CSDL | Dữ liệu sở hữu | Điểm kỹ thuật |
| --- | --- | --- | --- | --- |
| Auth | 8001 | Python/FastAPI · SQLite | users, otp_codes, login_attempts | JWT có phiên bản (khóa/đổi vai trò/đăng xuất thu hồi token ngay), OAuth2 form `/api/users/token`, bcrypt, xác nhận email bằng OTP (chỉ lưu HMAC, khóa mã khi sai 5 lần), bảo vệ admin cuối |
| Restaurant | 8002 | Node.js/Express · SQLite | restaurants, menu_items, menu_updates | Quy trình duyệt quán, xóa mềm, báo giá nội bộ cho Order |
| Order | 8003 | Java/Spring Boot · H2 | carts, cart_items, orders, order_items, notification_outbox | Giỏ 1 quán, checkout nguyên tử + chống trùng, ảnh chụp giá, máy trạng thái an toàn đồng thời, thanh toán trước (chụp tài khoản nhận tiền, hết hạn tự hủy, hoàn tiền), outbox, `notification_status` của đơn |
| Notification | 8004 | Go/Gin/GORM · PostgreSQL | notifications, email_logs | Nhận sự kiện nội bộ, chọn người nhận theo sự kiện, chống trùng; gửi email OTP qua nhà cung cấp (idempotency, ánh xạ lỗi), nhận webhook có ký HMAC |
| Review | 8005 | PHP · SQLite | reviews | Chỉ đơn completed, 1 đơn 1 đánh giá ở mức DB, điểm TB + phân bố sao, kiểm duyệt |
| Mock Email Provider | 9000 | Python/FastAPI · bộ nhớ | thư đã gửi (trong bộ nhớ) | Nhà cung cấp email **giả lập** (Unit 20): API key, Idempotency-Key, giới hạn tần suất, giả lập lỗi 500 / 429 / chậm, webhook ký HMAC |

Mỗi dịch vụ một ngôn ngữ, chung một hợp đồng REST (cùng định dạng lỗi, xác thực qua Auth, khóa nội bộ, CORS, phân trang,
X-Request-ID). Sơ đồ kiến trúc: `diagrams/arch/ARCH_0_microservices.png`, luồng OTP: `diagrams/arch/ARCH_1_otp_flow.png`.
Giao diện HTML/CSS/JS thuần; công cụ vận hành `manage.py` (Python) build và chạy cả 5 runtime bằng một lệnh.

## Điểm nhấn khi trình bày

0. **Đa ngôn ngữ thật:** 5 tiến trình 5 runtime, test hộp đen chứng minh cùng hợp đồng (lỗi, xác thực, upstream sập).
1. **Ranh giới dữ liệu:** mỗi dịch vụ một DB; quan hệ xuyên dịch vụ là tham chiếu logic, kiểm tra qua API (ERD nét đứt).
2. **Không tin client:** giá, chủ quán, người viết đánh giá đều lấy từ server/token, không lấy từ dữ liệu gửi lên.
3. **Chịu lỗi:** Notification sập không làm mất đơn (`notification_status = failed`, gửi lại thì `sent`, không trùng) và
   không chặn đăng ký (`otp_sent = false`, bấm Gửi lại mã); nhà cung cấp email lỗi / chậm được ánh xạ 502 / 503 có timeout.
4. **Đồng thời:** 2 thao tác cùng lúc trên một đơn hoặc một đánh giá chỉ có 1 thành công; 10 lần bấm Đặt hàng cùng
   Idempotency-Key chỉ tạo 1 đơn; 10 lần nhập sai mã OTP song song chỉ đếm đúng 5 (`scripts/demo_concurrency.py`).
5. **Truy vết:** một X-Request-ID đi qua Order → Auth, Restaurant, Notification, có trong log của cả 4 service.
6. **Kiểm thử:** test tích hợp, E2E với 5 tiến trình thật (kể cả khởi động lại và sự cố Notification), test giao diện bằng trình duyệt.
7. **Sẵn sàng chạy thử với người dùng thật (bước 2):** Docker cho 5 dịch vụ + gateway Nginx (HTTPS, một tên miền,
   chặn API nội bộ, giới hạn tần suất); sao lưu tự động 5 CSDL khác nhau (SQLite, H2, PostgreSQL) và diễn tập khôi phục;
   chống dò mật khẩu; CSP chặt; trang Điều khoản / Quyền riêng tư; xóa dữ liệu cá nhân theo yêu cầu do Auth điều phối
   qua 4 dịch vụ (một ví dụ "giao dịch" xuyên dịch vụ: Order có quyền từ chối, gọi lại an toàn, tự áp dụng lại sau khi
   khôi phục bản sao lưu cũ). Hướng dẫn: `DEPLOY.md`.

## Quá trình hợp nhất

Mỗi thành viên giữ ngôn ngữ của mình: Auth giữ FastAPI (TV1), Restaurant giữ Node.js/Express (TV2), Order giữ Spring Boot
(TV3), Notification giữ Go + PostgreSQL (TV4), Review giữ PHP (TV5). Hợp đồng API chung được hoàn thiện từ bản FastAPI;
nghiệp vụ tốt của từng bản được giữ (giỏ hàng + `OrderStatus` của Java, kiểm tra đầu vào của PHP, quy tắc admin chỉ hủy đơn)
và bổ sung các nghiệp vụ trong sơ đồ còn thiếu (khóa tài khoản, duyệt quán, kiểm duyệt đánh giá, outbox).
Chi tiết: `SOURCE_REVIEW.md`, `MERGE_DECISIONS.md`.

## Giới hạn

SQLite/H2 tệp phù hợp một máy chủ chạy thử (vài trăm người dùng), chưa mở rộng ngang; chạy local cần cài 5 runtime +
PostgreSQL (hoặc dùng Docker); thanh toán là chuyển khoản trực tiếp vào tài khoản quán (VietQR, chủ quán tự xác nhận) hoặc tiền
mặt, không qua cổng thanh toán; không có giao hàng; email chỉ gửi qua nhà cung cấp giả lập (không gửi thư thật, không có SMS);
giờ mở cửa chỉ hiển thị; đã chạy trên Linux và Windows 11 trong môi trường phát triển (xem `TEST_REPORT.md`). Đối chiếu
tiêu chí cuối kỳ: `REQUIREMENTS.md`, mục cuối.
