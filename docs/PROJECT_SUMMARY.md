# Tóm tắt dự án – phục vụ thuyết trình

## Bài toán

Sinh viên TDTU đặt đồ ăn từ các quán gần trường; chủ quán nhận và xử lý đơn; quản trị viên kiểm soát tài khoản,
quán và nội dung. Hệ thống xây dựng theo kiến trúc hướng dịch vụ (SOA): 5 dịch vụ độc lập giao tiếp qua REST.

## Tác nhân và chức năng

| Tác nhân | Chức năng chính |
| --- | --- |
| Sinh viên | Đăng ký/đăng nhập, tìm quán, xem menu và đánh giá, giỏ hàng, đặt món, theo dõi/hủy đơn, nhận thông báo, đánh giá quán |
| Chủ quán | Đăng ký quán (chờ duyệt), quản lý menu/giá/trạng thái món, mở/tạm đóng quán, xác nhận/hoàn thành/hủy đơn, xem đánh giá |
| Admin | Khóa/mở khóa, đổi vai trò tài khoản; duyệt/khóa quán; hủy đơn lỗi, thống kê; ẩn đánh giá vi phạm; gửi lại thông báo lỗi |

## 5 dịch vụ

| Dịch vụ | Cổng | Ngôn ngữ · CSDL | Dữ liệu sở hữu | Điểm kỹ thuật |
| --- | --- | --- | --- | --- |
| Auth | 8001 | Python/FastAPI · SQLite | users | JWT có phiên bản (khóa/đổi vai trò/đăng xuất thu hồi token ngay), bcrypt, bảo vệ admin cuối |
| Restaurant | 8002 | Node.js/Express · SQLite | restaurants, menu_items | Quy trình duyệt quán, xóa mềm, báo giá nội bộ cho Order |
| Order | 8003 | Java/Spring Boot · H2 | carts, cart_items, orders, order_items, notification_outbox | Giỏ 1 quán, checkout nguyên tử + chống trùng, ảnh chụp giá, máy trạng thái an toàn đồng thời, outbox |
| Notification | 8004 | Go/Gin/GORM · PostgreSQL | notifications | Nhận sự kiện nội bộ, chọn người nhận theo sự kiện, chống trùng |
| Review | 8005 | PHP · SQLite | reviews | Chỉ đơn completed, 1 đơn 1 đánh giá ở mức DB, điểm TB + phân bố sao, kiểm duyệt |

Mỗi dịch vụ một ngôn ngữ, chung một hợp đồng REST (cùng định dạng lỗi, xác thực qua Auth, khóa nội bộ, CORS, phân trang).
Giao diện HTML/CSS/JS thuần; công cụ vận hành `manage.py` (Python) build và chạy cả 5 runtime bằng một lệnh.

## Điểm nhấn khi trình bày

0. **Đa ngôn ngữ thật:** 5 tiến trình 5 runtime, test hộp đen chứng minh cùng hợp đồng (lỗi, xác thực, upstream sập).
1. **Ranh giới dữ liệu:** mỗi dịch vụ một DB; quan hệ xuyên dịch vụ là tham chiếu logic, kiểm tra qua API (ERD nét đứt).
2. **Không tin client:** giá, chủ quán, người viết đánh giá đều lấy từ server/token, không lấy từ dữ liệu gửi lên.
3. **Chịu lỗi:** Notification sập không làm mất đơn; sự kiện được lưu và gửi lại, không trùng.
4. **Đồng thời:** 2 thao tác cùng lúc trên một đơn hoặc một đánh giá chỉ có 1 thành công.
5. **Kiểm thử:** test tích hợp, E2E với 5 tiến trình thật (kể cả khởi động lại và sự cố Notification), test giao diện bằng trình duyệt.

## Quá trình hợp nhất

Mỗi thành viên giữ ngôn ngữ của mình: Auth giữ FastAPI (TV1), Restaurant giữ Node.js/Express (TV2), Order giữ Spring Boot
(TV3), Notification giữ Go + PostgreSQL (TV4), Review giữ PHP (TV5). Hợp đồng API chung được hoàn thiện từ bản FastAPI;
nghiệp vụ tốt của từng bản được giữ (giỏ hàng + `OrderStatus` của Java, kiểm tra đầu vào của PHP, quy tắc admin chỉ hủy đơn)
và bổ sung các nghiệp vụ trong sơ đồ còn thiếu (khóa tài khoản, duyệt quán, kiểm duyệt đánh giá, outbox).
Chi tiết: `SOURCE_REVIEW.md`, `MERGE_DECISIONS.md`.

## Giới hạn

SQLite/H2 tệp cho demo một máy; cần cài 5 runtime + PostgreSQL; chưa có thanh toán, giao hàng, email/SMS; giờ mở cửa chỉ hiển thị; chưa kiểm thử trên Windows
trong môi trường phát triển (xem `TEST_REPORT.md`). Chưa có đề gốc nên chưa đối chiếu được thang điểm.
