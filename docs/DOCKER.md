# Hướng dẫn dùng Docker cho nhóm

Chạy toàn bộ TDTU Food Booking (5 service + giao diện web + PostgreSQL + nhà cung cấp email giả lập `mock-email`) trên máy cá nhân **chỉ cần cài Docker Desktop**,
không phải cài Python, Node.js, JDK, Go, PHP hay PostgreSQL. Đưa lên máy chủ thật (tên miền, HTTPS, sao lưu): xem
[`DEPLOY.md`](DEPLOY.md).

## Khi nào dùng Docker, khi nào dùng `manage.py`?

| | Docker (tài liệu này) | `python manage.py start` (README) |
| --- | --- | --- |
| Cần cài | Docker Desktop | Python, Node.js, JDK, Go, PHP, PostgreSQL |
| Địa chỉ mở | `https://localhost:8443` | `http://127.0.0.1:8000` |
| Swagger `/docs` của từng service | Không mở được (gateway chặn) | `http://127.0.0.1:8001/docs` … `8005/docs` |
| Hộp thư lấy mã OTP | `http://127.0.0.1:9000` (container `mock-email`) | `http://127.0.0.1:9000` (tiến trình `mock_email`) |
| Dữ liệu | Volume của Docker | Thư mục `data/` |
| Hợp với | Chạy thử, demo, kiểm tra bản giống máy chủ | Sửa code, xem Swagger, chạy test |

Hai cách dùng dữ liệu riêng. Chỉ trùng nhau cổng 9000 của nhà cung cấp email giả lập: muốn chạy song song (tốn RAM) thì
thêm `MOCK_EMAIL_PORT=9100` vào `.env` (chỉ Docker đọc biến này), còn không thì `python manage.py stop` trước.

## 1. Cài Docker Desktop (một lần)

1. Tải tại <https://www.docker.com/products/docker-desktop/>, cài đặt (Windows: để mặc định "Use WSL 2"), khởi động lại máy.
2. Máy nên có từ 8 GB RAM. Ổ đĩa trống khoảng 10 GB cho các image.
3. **Mỗi lần dùng**: mở Docker Desktop, chờ góc dưới báo *Engine running*.
4. Kiểm tra trong PowerShell: `docker compose version`.

## 2. Lấy code và tạo `.env` (một lần)

```powershell
git clone https://github.com/trongcheckmateking/TDTU-Food-Booking.git
cd TDTU-Food-Booking
```

Tạo `.env` (khóa ký token, khóa nội bộ, mật khẩu PostgreSQL, khóa API email `EMAIL_API_KEY` và khóa ký webhook
`EMAIL_WEBHOOK_SECRET` sinh ngẫu nhiên):

```powershell
python manage.py init-env                                                            # máy có Python
docker run --rm -v "${PWD}:/app" -w /app python:3.12-slim python manage.py init-env  # máy không có Python
```

Mở `.env`, sửa 4 dòng ở phần `# ---- Chạy bằng Docker` (cuối tệp):

```ini
SERVER_NAME=localhost
PUBLIC_ORIGIN=https://localhost:8443
HTTP_PORT=8080
HTTPS_PORT=8443
```

Dùng 8080/8443 thay cho 80/443 vì trên Windows hai cổng này hay bị chương trình khác chiếm (IIS, XAMPP, Skype...).

`.env` tạo từ bản cũ (trước khi có OTP) thiếu các biến `OTP_*`, `EMAIL_*`, `MOCK_EMAIL_*`: chạy một lệnh bất kỳ của
`manage.py` (ví dụ `python manage.py doctor`), lệnh tự thêm các biến còn thiếu vào cuối `.env` (khóa bí mật sinh ngẫu
nhiên, không sửa dòng đang có). Không có Python thì chép tay khối OTP / email từ `.env.example` và tự đặt
`EMAIL_API_KEY`, `EMAIL_WEBHOOK_SECRET` (chuỗi ngẫu nhiên ≥ 16 ký tự). `OTP_ENABLED=true` thì tài khoản mới phải nhập
mã gửi qua email trước khi đăng nhập.

> Mỗi bạn tự tạo `.env` của mình. **Không** gửi `.env` qua chat và không commit (đã có trong `.gitignore`).

## 3. Build và chạy

```powershell
docker compose up -d --build     # lần đầu 5–10 phút, cần Internet (tải image, Maven tải thư viện cho Order)
docker compose ps                # chờ các service báo "healthy" và gateway "Up"
```

Mở **<https://localhost:8443>**. Trình duyệt cảnh báo chứng chỉ (gateway tự ký chứng chỉ cho `localhost`): bấm
**Nâng cao → Tiếp tục truy cập localhost**. Mở `http://localhost:8080` cũng tự chuyển sang HTTPS.

```
Trình duyệt ──▶ gateway (Nginx, cổng 8080/8443) ─┬─ /                  → web
                                                 ├─ /svc/auth/         → auth          (Python)  ─ SQLite
                                                 ├─ /svc/restaurant/   → restaurant    (Node.js) ─ SQLite
                                                 ├─ /svc/order/        → order         (Java)    ─ H2
                                                 ├─ /svc/notification/ → notification  (Go)      ─ PostgreSQL
                                                 └─ /svc/review/       → review        (PHP)     ─ SQLite

auth ─▶ notification ─▶ mock-email (giả lập gửi email, chỉ mở 127.0.0.1:9000) ─webhook ký HMAC─▶ notification
```

Chỉ gateway mở cổng ra máy. 5 service và PostgreSQL nằm trong mạng nội bộ của Docker; container `backup` tự sao lưu
mỗi ngày vào thư mục `backups/`. Riêng `mock-email` mở thêm cổng 9000 **chỉ trên 127.0.0.1** để xem thư đã gửi; không
service nào `depends_on` nó, nên `mock-email` dừng thì đăng ký vẫn thành công (`otp_sent=false`, bấm Gửi lại mã sau).

## 4. Nạp dữ liệu demo hoặc tạo admin

Dữ liệu demo (tài khoản `sv1@demo.tdtu.vn`, `chuquan1@demo.tdtu.vn`, `admin@demo.tdtu.vn`... như README):

```powershell
docker compose cp scripts auth:/app/
docker compose exec auth python -c "from scripts.seed_data import seed; print(seed())"
```

Seed phải chạy trong container `auth` vì nó gọi API các service qua mạng nội bộ của Docker và ghi tài khoản admin demo
thẳng vào CSDL của Auth. Chạy lại không tạo trùng.

Tạo admin thật (hỏi mật khẩu khi chạy):

```powershell
docker compose exec auth python -m services.auth.admin_tools --email <email> --name "<Họ tên>"
```

## 5. Lệnh dùng hằng ngày

| Việc | Lệnh |
| --- | --- |
| Xem trạng thái | `docker compose ps` |
| Xem log một service | `docker compose logs -f --tail=100 order` |
| Khởi động lại một service | `docker compose restart order` |
| Xem mã OTP vừa gửi (đăng ký tài khoản mới) | xem mục 7 |
| Tạm dừng / chạy lại | `docker compose stop` / `docker compose start` |
| Tắt hẳn, **giữ** dữ liệu | `docker compose down` |
| Tắt và **xóa sạch** dữ liệu (làm lại từ đầu) | `docker compose down -v` |

Các container đặt `restart: unless-stopped`: lần sau mở Docker Desktop chúng tự chạy lại (trừ khi đã `stop`/`down`).

## 6. Khi có code mới trên GitHub

```powershell
git pull
docker compose up -d --build           # chỉ build lại phần thay đổi
docker compose up -d --build order     # hoặc chỉ một service
```

Sửa code (kể cả HTML/CSS/JS trong `web/`) phải build lại thì container mới thấy thay đổi.

## 7. Xem dữ liệu khi chạy Docker

PostgreSQL (thông báo):

```powershell
docker compose exec postgres psql -U tdtu_food -d tdtu_notification -c "SELECT message, status, created_at FROM notifications ORDER BY created_at DESC LIMIT 5;"
```

SQLite của Auth / Restaurant / Review: chép ra thư mục `backups/` (đã bị Git bỏ qua) rồi mở bằng extension
**SQLite Viewer** của VS Code. Đây là bản sao, sửa không ảnh hưởng hệ thống:

```powershell
docker compose cp auth:/data backups/xem-auth          # mở backups/xem-auth/auth.db
docker compose cp restaurant:/data backups/xem-restaurant
```

Nhật ký gửi email (không chứa mã OTP):

```powershell
docker compose exec postgres psql -U tdtu_food -d tdtu_notification -c "SELECT to_email, status, last_error, created_at FROM email_logs ORDER BY created_at DESC LIMIT 5;"
```

Mã OTP vừa gửi (hộp thư của `mock-email`, mất khi container khởi động lại). Lấy khóa từ `.env` vào biến, không in ra:

```powershell
$key = ((Select-String -Path .env -Pattern '^EMAIL_API_KEY=').Line -split '=', 2)[1]
(Invoke-RestMethod "http://127.0.0.1:9000/api/emails?to=<email>&limit=1" -Headers @{"X-API-Key"=$key}).items[0].content
```

Swagger `/docs` và API nội bộ `/internal/...` bị gateway chặn (đúng thiết kế bảo mật). Cần Swagger để demo thì chạy
bằng `manage.py` theo README.

## 8. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `failed to connect to the docker API at npipe:...` | Docker Desktop chưa mở hoặc chưa khởi động xong |
| `ports are not available` / `port is already allocated` | Cổng đang bị chiếm: đổi `HTTP_PORT`, `HTTPS_PORT` (và cổng trong `PUBLIC_ORIGIN`) trong `.env`, chạy lại `docker compose up -d` |
| `Thiếu POSTGRES_PASSWORD trong .env` | Chưa tạo `.env`: làm lại bước 2 |
| `mock-email` dừng ngay, log báo `EMAIL_API_KEY` | `.env` cũ thiếu khóa email: xem cuối bước 2 |
| Đăng ký xong báo "chưa gửi được email xác nhận" | `docker compose ps mock-email` phải "healthy"; `EMAIL_API_KEY`, `EMAIL_WEBHOOK_SECRET` có trong `.env`; chờ hết đếm ngược rồi bấm Gửi lại mã |
| `notification` không healthy, log báo `password authentication failed` | `POSTGRES_PASSWORD` đã đổi sau khi tạo volume PostgreSQL. Đặt lại mật khẩu cũ, hoặc xóa CSDL thông báo: `docker compose down`, `docker volume rm tdtu-food_pg-data`, `docker compose up -d` |
| Gateway mãi không lên | Một service chưa healthy: `docker compose ps` tìm service đó, xem `docker compose logs <service>` |
| Build `order` lỗi tải thư viện / timeout | Kiểm tra Internet rồi chạy lại `docker compose build order` |
| Gateway/backup báo `/bin/sh^M` hoặc `no such file or directory` | Script bị đổi sang xuống dòng CRLF (bản clone cũ, trước khi có `.gitattributes`): clone lại repo |
| Máy chậm, hết RAM | Dừng `manage.py` nếu đang chạy song song, tắt bớt ứng dụng, hoặc `docker compose stop backup` |

Xem thêm: [`DEPLOY.md`](DEPLOY.md) (máy chủ, HTTPS, sao lưu / khôi phục), [`../docker-compose.yml`](../docker-compose.yml).
