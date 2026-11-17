# Kịch bản demo (khoảng 20 phút: nghiệp vụ 10–12 phút, kỹ thuật cuối kỳ 8–10 phút)

Chuẩn bị (trước giờ trình bày):

```bash
python manage.py stop                  # nếu đang chạy
python manage.py doctor                # 5 runtime + PostgreSQL phải "OK"
python manage.py reset-demo --yes      # XÓA dữ liệu cũ, khởi động các service, nạp lại dữ liệu demo qua API
python manage.py status                # 7 dòng OK: 5 service + mock_email + web, kèm ngôn ngữ của từng service
```

Các lệnh PowerShell ở phần kỹ thuật cần khóa API của MockMail. Lấy vào biến, **không in ra màn hình, không chụp `.env`**:

```powershell
$key = ((Select-String -Path .env -Pattern '^EMAIL_API_KEY=').Line -split '=', 2)[1]
```

Mở đầu (1 phút): chạy `python manage.py status` để cho thấy 5 service chạy bằng 5 runtime (Python, Node.js, Java, Go,
PHP) cùng nhà cung cấp email giả lập; mở `docs/diagrams/arch/ARCH_0_microservices.png` để giới thiệu kiến trúc; mở
`http://127.0.0.1:8003/docs` (Java) và `http://127.0.0.1:8004/docs` (Go) để thấy cùng một hợp đồng API.

Mở 3 cửa sổ trình duyệt (hoặc 1 cửa sổ thường + 2 cửa sổ ẩn danh để giữ 3 phiên đăng nhập) tại `http://127.0.0.1:8000`.
Trên trang đăng nhập có nút điền nhanh tài khoản demo. Tài khoản seed **đã xác nhận email** nên đăng nhập luôn.

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
5. **Đặt hàng** (mặc định "Tự tới quán lấy") → trang **thanh toán**: mã VietQR riêng của đơn (ngân hàng, số tài khoản của
   quán, 73.000 đ, nội dung `TDTU 0xx ...`), đếm ngược 15 phút. Tài khoản demo ghi `TAI KHOAN DEMO`: **không chuyển tiền
   thật**, bấm thẳng **Tôi đã chuyển khoản** → "Chờ quán xác nhận đã nhận tiền".
   Điểm nhấn: giá do server lấy lại từ Restaurant, đơn lưu ảnh chụp tên và giá món; bấm Đặt hàng nhiều lần không tạo đơn trùng.

## 2. Chủ quán xử lý đơn (2 phút)

1. Đăng nhập `chuquan1` → tab **Đơn hàng** → **Chờ tiền**: đơn vừa đặt ghi "Sinh viên báo đã chuyển 73.000 đ" kèm nội dung
   chuyển khoản; chuông có "Quán Cơm Tấm Cô Ba có đơn mới ... sinh viên báo đã chuyển khoản". (Chạy thật: mở app ngân hàng
   tìm khoản tiền đúng nội dung.)
2. **Đã nhận tiền** → đơn sang tab **Mới**; cửa sổ sinh viên tự chuyển thành "Đặt món thành công!" với mã nhận món 3 số.
3. **Nhận đơn** → tab "Đang làm" → **Báo hoàn thành**. (Seed có sẵn 1 đơn ở Chờ tiền để thử nút "Chưa nhận được tiền".)
4. Tab **Thực đơn**: đổi giá "Cơm tấm sườn bì chả" lên 40.000 → quay lại cửa sổ sinh viên, đơn vừa đặt vẫn giữ giá 35.000.
5. Tab **Quán của tôi**: "Trà Sữa Mây" ở trạng thái "Chờ duyệt", chưa thể mở bán.
6. Ảnh đại diện → Profile → **Nhận tiền**: tài khoản nhận tiền (đổi cần mật khẩu) và **Mã QR nhận tiền của quán** để in.

Đơn **tiền mặt**: sinh viên chọn "Tiền mặt" khi đặt → đơn tới quán ngay (tab **Mới**), chủ quán nhận thông báo
"có đơn mới" liền, thu tiền khi giao.

## 3. Sinh viên nhận thông báo và đánh giá (2 phút)

1. Cửa sổ sinh viên: chuông có thông báo xác nhận và hoàn thành; tab **Thông báo** → "Đánh dấu tất cả đã đọc".
2. Tab **Đơn của tôi** → **Đánh giá** đơn vừa hoàn thành, chọn 4 sao, viết nhận xét → nút chuyển thành "Đã đánh giá".
3. Mở lại quán: điểm trung bình và đánh giá mới hiển thị.

## 4. Admin quản trị (3 phút)

1. Đăng nhập admin → **Tổng quan**: 5 service "Hoạt động", số người dùng, quán chờ duyệt, đơn, doanh thu.
2. **Quán ăn** → **Duyệt** "Trà Sữa Mây" → quán xuất hiện ở trang sinh viên.
3. **Đánh giá** → **Ẩn** một đánh giá kèm lý do → điểm trung bình của quán tính lại.
4. **Người dùng** → **Khóa** `sv2@demo.tdtu.vn` → nếu sv2 đang đăng nhập ở cửa sổ khác, thao tác tiếp theo bị đưa về trang đăng nhập (token bị thu hồi); đăng nhập lại sẽ nhận thông báo tài khoản bị khóa.
5. **Đơn hàng** → lọc trạng thái (có "Chờ thanh toán", "Không thanh toán xong"), xem chi tiết (thanh toán vào tài khoản
   nào, lúc nào), **Hủy đơn** một đơn đang chờ theo lời nhờ của sinh viên (sinh viên không tự hủy được; cả sinh viên và chủ
   quán nhận thông báo). Đơn đã trả tiền bị hủy chuyển sang "Chờ hoàn tiền": chủ quán vào tab **Cần hoàn tiền** → **Đã hoàn tiền**.

## 5. Xác nhận email bằng OTP – dịch vụ bên thứ ba (Unit 20, 2–3 phút)

Ảnh hỗ trợ: `docs/diagrams/arch/ARCH_1_otp_flow.png`.

1. Cửa sổ ẩn danh mới → **Đăng ký** sinh viên `sv9@demo.tdtu.vn` → giao diện chuyển sang ô **Xác nhận email**
   ("Đã gửi mã xác nhận tới …"), nút **Gửi lại mã** đếm ngược 60 giây.
2. Mở hộp thư của nhà cung cấp email giả lập (thay cho mở Gmail):

   ```powershell
   (Invoke-RestMethod "http://127.0.0.1:9000/api/emails?to=sv9@demo.tdtu.vn&limit=1" -Headers @{"X-API-Key"=$key}).items[0].content
   ```

   Hoặc mở `http://127.0.0.1:9000/docs` → Authorize (dán `$key`) → `GET /api/emails`.
3. Nhập **sai** mã 1 lần → "Mã xác nhận không đúng, còn 4 lần thử". Nhập đúng mã → vào thẳng trang sinh viên.
4. Điểm nhấn khi giải thích (mở `services/auth/app.py`, hàm `verify_otp`):
   - DB chỉ có HMAC của mã (mở `data/auth.db` bằng DB Browser for SQLite, hoặc):
     `python -c "import sqlite3; print(sqlite3.connect('data/auth.db').execute('SELECT code_hash, attempts, used_at FROM otp_codes ORDER BY created_at DESC LIMIT 1').fetchone())"`
     → chỉ thấy chuỗi hex 64 ký tự, không thấy mã 6 số.
   - Đếm lần thử **trước** khi so mã, trong `BEGIN IMMEDIATE`; lỗi `raise` sau khi ra khỏi giao dịch.
   - `grep -r "<mã vừa nhập>" logs/` → không có dòng nào (log chỉ có user_id, message_id, email che `sv***@demo.tdtu.vn`).
5. Webhook ký HMAC: mở `http://127.0.0.1:8004/docs` → Authorize bằng token admin → `GET /api/admin/email-logs` → thư vừa
   gửi có `status: delivered` (MockMail gọi `POST /internal/webhooks/email-status` sau ~1 giây, Notification kiểm chữ ký
   `X-Webhook-Signature` trên thân thô). Đăng ký thêm `bounce1@demo.tdtu.vn` → dòng nhật ký chuyển `failed`
   (`WEBHOOK: mailbox_not_found`).
6. Đăng nhập tài khoản chưa nhập mã → 403 `EMAIL_NOT_VERIFIED`, giao diện mở ngay ô nhập mã (chỉ báo khi đúng mật khẩu).

## 6. Swagger theo chuẩn OAuth2 (Unit 18, 1 phút)

1. Mở `http://127.0.0.1:8001/docs` → **Authorize** → khung **OAuth2PasswordBearer**: `username` = `sv1@demo.tdtu.vn`,
   `password` = `Demo@123` → Authorize. Swagger tự gọi `POST /api/users/token` (form `OAuth2PasswordRequestForm`).
2. Thử `GET /api/users/me` → 200. Logout trong khung Authorize rồi thử lại → 401, phần response headers có
   `www-authenticate: Bearer`.
3. 4 service còn lại: gọi `POST /api/users/login` để lấy `access_token`, dán vào khung Bearer của từng Swagger.
4. Mã nguồn Unit 17 / Unit 9: `services/auth/models.py` (`UserBase` dùng chung cho `RegisterIn`, `UserOut`) và
   `list_users` dùng `Annotated[..., Query()]`.

## 7. Giao tiếp giữa service và chịu lỗi (Unit 19 + Unit 22, 2–3 phút)

Lấy PID trong `.run/pids.json`, dừng riêng một tiến trình (`kill <pid>`; Windows: `taskkill /PID <pid> /T /F`):

1. **Dừng Restaurant** → sinh viên bấm thêm món: 503 `UPSTREAM_UNAVAILABLE` "Không kết nối được Restaurant …", giỏ không đổi.
   Bảng ánh xạ lỗi giống nhau ở 5 ngôn ngữ: không kết nối / quá giờ → 503, upstream 5xx → 502 `UPSTREAM_ERROR`, trả
   không phải JSON → 502 `UPSTREAM_BAD_RESPONSE` (`docs/ARCHITECTURE.md`, kiểm bằng `test_contract.py`).
2. **Dừng Notification** → sinh viên đặt đơn **tiền mặt**: vẫn 201; xem đơn ở `http://127.0.0.1:8003/docs`
   (`GET /api/orders/{id}`) → `notification_status: "failed"`; tab Tổng quan/Thông báo của admin hiện "thông báo gửi lỗi".
   Chạy `python manage.py stop` rồi `python manage.py start`: worker outbox tự gửi lại (hoặc bấm "Gửi lại ngay") →
   `notification_status: "sent"`, chủ quán nhận thông báo đúng 1 lần.
3. **Nhà cung cấp email lỗi** (Notification vẫn chạy):

   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:9000/api/_control/mode -Headers @{"X-API-Key"=$key} -ContentType application/json -Body '{"mode":"fail500"}'
   ```

   Đăng ký `sv10@demo.tdtu.vn` → tài khoản vẫn tạo, giao diện báo "chưa gửi được email xác nhận" (`otp_sent=false`).
   Đổi lại `{"mode":"ok"}`, chờ hết 60 giây → **Gửi lại mã** → nhận mã, xác nhận bình thường. Các chế độ khác:
   `rate429` (Notification trả 503 kèm `Retry-After`), `slow` (MockMail chờ 10 giây, Notification hết giờ sau
   `EMAIL_PROVIDER_TIMEOUT` giây). **Nhớ đổi về `ok`** sau khi demo.
4. Kiểm thử E2E chạy trên tiến trình thật (Unit 22): `python -m pytest tests/e2e -q` (tự dựng hệ thống riêng, không
   đụng dữ liệu đang demo; mất vài phút, nên chạy sẵn trước và mở `docs/TEST_REPORT.md`).

## 8. Xử lý đồng thời (1–2 phút)

```bash
python scripts/demo_concurrency.py
```

In bảng kết quả, dòng cuối **ĐẠT** (mã thoát 1 nếu LỖI):

- 10 luồng checkout **cùng** `Idempotency-Key` → đúng 1 phản hồi 201, 9 phản hồi 200 trả lại **đúng đơn đó**
  (`SELECT … FOR UPDATE` trên giỏ + `UNIQUE(user_id, idempotency_key)`).
- 10 luồng checkout **không** khóa → chỉ 1 đơn được tạo, các luồng khác 409 (giỏ đã đặt).
- 2 lệnh đổi trạng thái cùng lúc (Báo hoàn thành và Hủy trên một đơn đã nhận) → đúng 1 thành công, lệnh kia 409
  (`UPDATE … WHERE status=<cũ>`).

Script tạo thêm vài đơn trong dữ liệu đang chạy (đơn chuyển khoản tạo ra được tự bỏ ngay); chạy sau `reset-demo` nếu
muốn dữ liệu sạch.

## 9. Truy vết một yêu cầu bằng X-Request-ID (1 phút)

1. Sinh viên đặt một đơn tiền mặt trên giao diện, mở DevTools (F12) → **Network** → request `checkout` → Response
   Headers → sao chép `x-request-id`.
2. Tìm mã đó trong log của mọi service:

   ```powershell
   Select-String -Path logs\*.log -Pattern "<mã vừa chép>"
   ```

   Thấy cùng một `rid=` ở `order.log` (nhận request), `auth.log` (xác thực token), `restaurant.log` (báo giá),
   `notification.log` (sự kiện đơn mới).
3. Tự đặt mã: gửi request có header `X-Request-ID` (8–128 ký tự `A-Za-z0-9._-`) thì mã được giữ nguyên:

   ```powershell
   $t = (Invoke-RestMethod -Method Post http://127.0.0.1:8001/api/users/login -ContentType application/json -Body '{"email":"sv1@demo.tdtu.vn","password":"Demo@123"}').access_token
   Invoke-RestMethod http://127.0.0.1:8003/api/orders/me -Headers @{Authorization="Bearer $t"; "X-Request-ID"="demo-rid-0001"} | Out-Null
   Select-String -Path logs\*.log -Pattern "rid=demo-rid-0001"
   ```

## 10. Docker Compose (Unit 21, tùy thời gian)

```bash
docker compose up -d --build
docker compose ps        # mọi container "healthy", gồm mock-email
```

Truy cập qua gateway Nginx (HTTPS, rate limit đăng nhập / OTP, chặn `/internal` và `/docs`): xem `docs/DOCKER.md`.
Chạy `python manage.py stop` trước: container `mock-email` dùng cổng 9000 giống MockMail của `manage.py start`.

## 11. Kỹ thuật khác (tùy thời gian)

- Swagger của từng service: `http://127.0.0.1:8001/docs` … `8005/docs`, MockMail `9000/docs`.
- Chạy `python scripts/smoke_test.py` để kiểm tra nhanh toàn bộ luồng qua API (có cả bước OTP và đơn tiền mặt).
