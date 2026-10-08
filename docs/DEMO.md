# Kịch bản demo (khoảng 10–12 phút)

Chuẩn bị (trước giờ trình bày):

```bash
python manage.py stop                  # nếu đang chạy
python manage.py doctor                # 5 runtime + PostgreSQL phải "OK"
python manage.py reset-demo --yes      # XÓA dữ liệu cũ, khởi động 5 service, nạp lại dữ liệu demo qua API
python manage.py status                # 6 dòng OK, kèm ngôn ngữ của từng service
```

Mở đầu (1 phút): chạy `python manage.py status` để cho thấy 5 service chạy bằng 5 runtime (Python, Node.js, Java, Go,
PHP); mở `http://127.0.0.1:8003/docs` (Java) và `http://127.0.0.1:8004/docs` (Go) để thấy cùng một hợp đồng API.

Mở 3 cửa sổ trình duyệt (hoặc 1 cửa sổ thường + 2 cửa sổ ẩn danh để giữ 3 phiên đăng nhập) tại `http://127.0.0.1:8000`.
Trên trang đăng nhập có nút điền nhanh tài khoản demo.

| Vai trò | Email | Mật khẩu |
| --- | --- | --- |
| Sinh viên | `sv1@demo.tdtu.vn` (thêm `sv2@demo.tdtu.vn`) | `Demo@123` |
| Chủ quán | `chuquan1@demo.tdtu.vn` (quán Cơm Tấm Cô Ba, Trà Sữa Mây) | `Demo@123` |
| Admin | `admin@demo.tdtu.vn` | `Admin@123` |

## 1. Sinh viên đặt món (3 phút)

1. Đăng nhập `sv1`. Tab **Quán ăn**: 3 quán công khai, có điểm đánh giá; "Bánh Mì 24h" đang tạm đóng; "Trà Sữa Mây" chưa xuất hiện vì chờ duyệt.
2. Mở **Cơm Tấm Cô Ba**: "Canh chua cá lóc" hết món (nút Thêm bị khóa), món ẩn không hiển thị.
3. Thêm 2 × "Cơm tấm sườn bì chả" và 1 × "Trà đá" → giỏ bên phải tính 73.000 đ.
4. Thử thêm món của quán "Bún Bò Huế O Hà" → hệ thống hỏi xóa giỏ (giỏ chỉ chứa món của 1 quán) → chọn Hủy.
5. **Đặt hàng** → nhập địa chỉ → đơn mới ở tab **Đơn của tôi**, trạng thái "Chờ xác nhận".
   Điểm nhấn: giá do server lấy lại từ Restaurant, đơn lưu ảnh chụp tên và giá món; bấm Đặt hàng nhiều lần không tạo đơn trùng.

## 2. Chủ quán xử lý đơn (2 phút)

1. Đăng nhập `chuquan1` → tab **Đơn hàng** thấy đơn mới; chuông thông báo có "Quán Cơm Tấm Cô Ba có đơn mới".
2. **Xác nhận** → chuyển lọc sang "Đã xác nhận" → **Hoàn thành**.
3. Tab **Thực đơn**: đổi giá "Cơm tấm sườn bì chả" lên 40.000 → quay lại cửa sổ sinh viên, đơn vừa đặt vẫn giữ giá 35.000.
4. Tab **Quán của tôi**: "Trà Sữa Mây" ở trạng thái "Chờ duyệt", chưa thể mở bán.

## 3. Sinh viên nhận thông báo và đánh giá (2 phút)

1. Cửa sổ sinh viên: chuông có thông báo xác nhận và hoàn thành; tab **Thông báo** → "Đánh dấu tất cả đã đọc".
2. Tab **Đơn của tôi** → **Đánh giá** đơn vừa hoàn thành, chọn 4 sao, viết nhận xét → nút chuyển thành "Đã đánh giá".
3. Mở lại quán: điểm trung bình và đánh giá mới hiển thị.

## 4. Admin quản trị (3 phút)

1. Đăng nhập admin → **Tổng quan**: 5 service "Hoạt động", số người dùng, quán chờ duyệt, đơn, doanh thu.
2. **Quán ăn** → **Duyệt** "Trà Sữa Mây" → quán xuất hiện ở trang sinh viên.
3. **Đánh giá** → **Ẩn** một đánh giá kèm lý do → điểm trung bình của quán tính lại.
4. **Người dùng** → **Khóa** `sv2@demo.tdtu.vn` → nếu sv2 đang đăng nhập ở cửa sổ khác, thao tác tiếp theo bị đưa về trang đăng nhập (token bị thu hồi); đăng nhập lại sẽ nhận thông báo tài khoản bị khóa.
5. **Đơn hàng** → lọc trạng thái, xem chi tiết, **Hủy đơn lỗi** một đơn đang chờ (cả sinh viên và chủ quán nhận thông báo).

## 5. Kỹ thuật (tùy thời gian)

- Swagger của từng service: `http://127.0.0.1:8001/docs` … `8005/docs` (bấm Authorize, dán token).
- Khả năng chịu lỗi: lấy PID của `notification` trong `.run/pids.json`, dừng riêng tiến trình đó
  (`kill <pid>`; Windows: `taskkill /PID <pid> /T /F`). Sinh viên vẫn đặt đơn thành công; tab Tổng quan/Thông báo của admin
  hiện "thông báo gửi lỗi". Chạy `python manage.py stop` rồi `python manage.py start`: worker tự gửi lại
  (hoặc bấm "Gửi lại ngay"), chủ quán nhận thông báo đúng 1 lần.
- Chạy `python scripts/smoke_test.py` để kiểm tra nhanh toàn bộ luồng qua API.
