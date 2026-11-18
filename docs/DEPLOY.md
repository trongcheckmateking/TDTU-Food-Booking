# Triển khai chạy thử (pilot) bằng Docker

Tài liệu cho thành viên nhóm phụ trách vận hành giai đoạn chạy thử kín: đưa hệ thống lên một máy chủ có tên miền và
HTTPS, sao lưu, khôi phục, cập nhật, xử lý yêu cầu về dữ liệu cá nhân. Chạy để phát triển trên máy cá nhân vẫn dùng
`python manage.py start` như README.

## 1. Hệ thống khi chạy bằng Docker

```
Trình duyệt ──HTTPS 443──▶ gateway (Nginx) ─┬─ /                   → web           (giao diện, Python)
                (80 → chuyển sang 443)       ├─ /svc/auth/          → auth          (Python)  ── volume auth-data (SQLite)
                                             ├─ /svc/restaurant/    → restaurant    (Node.js) ── volume restaurant-data (SQLite + ảnh)
                                             ├─ /svc/order/         → order         (Java)    ── volume order-data (H2)
                                             ├─ /svc/notification/  → notification  (Go)      ── postgres (volume pg-data)
                                             └─ /svc/review/        → review        (PHP, Apache) ── volume review-data (SQLite)
auth ──▶ notification ──▶ mock-email (giả lập gửi email mã OTP, cổng 9000 chỉ trên 127.0.0.1) ──webhook ký HMAC──▶ notification
backup: mỗi BACKUP_INTERVAL_HOURS giờ đọc 4 volume + pg_dump → ./backups/tdtu-backup-*.tar.gz (giữ BACKUP_KEEP bản)
```

- Chỉ gateway mở cổng ra ngoài. 5 service và PostgreSQL chỉ gọi được trong mạng nội bộ `backend` của Docker; mỗi
  service vẫn giữ cơ sở dữ liệu riêng như khi chạy bằng `manage.py`. `mock-email` mở thêm cổng `MOCK_EMAIL_PORT`
  (mặc định 9000) **chỉ trên 127.0.0.1** của máy chủ, để người vận hành xem thư đã gửi; webhook của nó gọi thẳng
  `notification:8004` trong mạng nội bộ, không đi qua gateway.
- Trình duyệt gọi API qua cùng tên miền với trang (`/svc/<service>/...`), nên không cần CORS và CSP chỉ cho phép `'self'`.
- Gateway trả 404 cho mọi đường `/svc/*/internal/...` (API giữa các service) và trang tài liệu API (`/docs`, `/redoc`,
  `/openapi.json`). Xem tài liệu API khi chạy local ở `http://127.0.0.1:800x/docs`.
- Gateway giới hạn tần suất theo IP (API 100 yêu cầu/giây; đăng nhập, đăng ký, `/api/users/token`, nhập mã và gửi lại
  mã OTP 120/phút; tải ảnh 30/phút; ngưỡng
  rộng vì cả ký túc xá có thể dùng chung một IP), gắn mã truy vết
  `X-Request-ID` vào mọi yêu cầu (trả lại cho trình duyệt ở header cùng tên) và bật HSTS.
- Auth lấy IP thật của người dùng từ `X-Forwarded-For` do gateway ghi đè (người dùng không giả được), dùng cho việc tạm
  khóa đăng nhập sai nhiều lần (IPv6 tính theo dải /64). Trên máy chủ Linux, Docker giữ IP thật của người dùng; trên
  Docker Desktop (Windows/macOS) mọi người dùng hiện cùng một IP nên chỉ dùng để chạy thử. Kiểm tra bằng
  `docker compose logs gateway`: cột đầu mỗi dòng phải là IP thật. Nếu đặt sau một proxy / CDN khác (Cloudflare...),
  cần cấu hình `set_real_ip_from` + `real_ip_header` trong gateway, nếu không cả trường sẽ chung một bộ đếm.
- Ảnh chỉ hiển thị khi là ảnh tải lên Restaurant (`/uploads/...`); ảnh trỏ tới máy chủ khác không được tải (CSP
  `img-src`), để máy chủ lạ không biết IP của sinh viên xem trang.
- Mọi container ghi log ra Docker, mỗi container tối đa khoảng 50 MB (5 tệp × 10 MB).

## 2. Chuẩn bị máy chủ

| Mục | Tối thiểu cho chạy thử |
| --- | --- |
| Máy | 2 vCPU, 4 GB RAM, 20 GB ổ đĩa (Ubuntu 22.04/24.04 hoặc tương đương) |
| Phần mềm | Docker Engine 24+ có Docker Compose v2, Git, Python 3 (chỉ để chạy `manage.py init-env`) |
| Mạng | Tên miền (bản ghi A) trỏ về IP máy chủ; tường lửa mở 22 (SSH), 80, 443 |

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

## 3. Cài lần đầu

```bash
git clone <repo> tdtu-food && cd tdtu-food
python3 manage.py init-env          # tạo .env: JWT_SECRET, INTERNAL_KEY, POSTGRES_PASSWORD, EMAIL_API_KEY, EMAIL_WEBHOOK_SECRET ngẫu nhiên
nano .env                           # sửa phần "Chạy bằng Docker" và CONTACT_EMAIL (xem bảng dưới)
docker compose up -d --build        # lần đầu build khoảng 5–10 phút
docker compose ps                   # chờ mọi dòng "healthy"
docker compose exec auth python -m services.auth.admin_tools --email <email admin> --name "<Họ tên>"
```

| Biến trong `.env` | Ví dụ | Ý nghĩa |
| --- | --- | --- |
| `SERVER_NAME` | `food.example.edu.vn` | Tên miền (hoặc IP LAN) của máy chủ, dùng cho chứng chỉ |
| `PUBLIC_ORIGIN` | `https://food.example.edu.vn` | Địa chỉ đầy đủ người dùng mở; mã QR trỏ tới đây. Thêm `:cổng` nếu khác 443 |
| `HTTP_PORT`, `HTTPS_PORT` | `80`, `443` | Cổng gateway mở trên máy chủ |
| `CONTACT_EMAIL` | `tdtufood.nhom@gmail.com` | **Bắt buộc**: hiện trên trang Điều khoản / Quyền riêng tư |
| `BACKUP_KEEP`, `BACKUP_INTERVAL_HOURS` | `7`, `24` | Số bản sao lưu giữ lại, chu kỳ sao lưu |
| `BACKUP_HOST_DIR` | `/srv/tdtu-backups` | Thư mục trên máy chủ chứa bản sao lưu (mặc định `./backups`) |
| `LOGIN_MAX_FAILS`, `LOGIN_WINDOW_SECONDS`, `LOGIN_LOCK_SECONDS` | `5`, `900`, `900` | Tạm khóa đăng nhập sai nhiều lần |
| `PAYMENT_TIMEOUT_MINUTES`, `PAYMENT_SWEEP_SECONDS` | `15`, `60` | Đơn chưa chuyển khoản sau bao lâu thì tự hủy; chu kỳ Order quét đơn quá hạn |
| `OTP_ENABLED` | `true` / `false` | Bắt tài khoản mới nhập mã OTP gửi qua email trước khi đăng nhập (xem lưu ý dưới bảng) |
| `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS` | `300`, `5` | Mã còn hiệu lực bao lâu; nhập sai bao nhiêu lần thì khóa mã |
| `OTP_RESEND_SECONDS`, `OTP_RESEND_PER_HOUR` | `60`, `5` | Khoảng cách tối thiểu giữa 2 lần gửi mã; số mã tối đa mỗi giờ |
| `EMAIL_API_KEY`, `EMAIL_WEBHOOK_SECRET` | (sinh ngẫu nhiên) | Khóa API gọi nhà cung cấp email; khóa ký webhook kết quả giao thư |
| `EMAIL_SMTP_HOST`, `EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD` | `smtp.gmail.com`, … | Điền cả 3 để gửi thư OTP thật (xem hướng dẫn Gmail dưới bảng); trống = giả lập |
| `EMAIL_PROVIDER_TIMEOUT`, `MOCK_EMAIL_RATE_PER_MINUTE` | `3`, `30` | Thời gian chờ nhà cung cấp email (giây); giới hạn gửi mỗi phút của `mock-email` |

> **Email OTP trên máy chủ chạy thử:** mặc định `mock-email` là nhà cung cấp **giả lập**, thư không tới hộp thư thật.
> Khi mở cho người dùng thật: hoặc điền `EMAIL_SMTP_*` để gửi thư thật (hướng dẫn ngay dưới bảng), hoặc đặt
> `OTP_ENABLED=false` (tắt bước xác nhận email), hoặc đổi `EMAIL_PROVIDER_URL`, `EMAIL_API_KEY` sang nhà cung cấp email
> khác có cùng kiểu API (khác định dạng thì sửa `buildProviderPayload` / `callProvider` trong
> `services/notification/email.go`) và trỏ webhook của nhà cung cấp về `/internal/webhooks/email-status`.

### Gửi mã OTP thật tới hộp thư người dùng (SMTP)

Mặc định hệ thống chạy ở chế độ **giả lập** (thư chỉ nằm trong MockMail). Muốn mã tới đúng hộp thư của người đăng ký,
điền cấu hình SMTP trong `.env` rồi khởi động lại (`python manage.py stop`, `python manage.py start`; Docker:
`docker compose up -d`). Không cần sửa code hay đổi service nào: MockMail nhận thư từ Notification như cũ rồi gửi thật
qua SMTP và báo `delivered` / `failed` bằng webhook.

Ví dụ dùng Gmail của nhóm:

1. Tài khoản Google → Bảo mật → bật **Xác minh 2 bước**.
2. Mở <https://myaccount.google.com/apppasswords>, tạo **mật khẩu ứng dụng** (16 ký tự). Không dùng mật khẩu Gmail.
3. Điền vào `.env` (đúng 3 dòng đầu là bắt buộc; thiếu một dòng thì vẫn là chế độ giả lập):

```ini
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_USER=<địa chỉ gmail gửi thư>
EMAIL_SMTP_PASSWORD=<mật khẩu ứng dụng 16 ký tự>
EMAIL_SMTP_PORT=587            # 587 + starttls (mặc định); 465 thì đặt EMAIL_SMTP_SECURITY=ssl
EMAIL_SMTP_FROM=               # trống = dùng EMAIL_SMTP_USER (Gmail bắt buộc trùng tài khoản)
```

4. Đăng ký một tài khoản bằng **email thật** của bạn: thư "TDTU Food - Mã xác nhận email" tới sau vài giây (xem cả thư mục
   Spam). `GET :8004/api/admin/email-logs` hiện `delivered`; sai mật khẩu ứng dụng thì `failed` với lý do `smtp_auth_failed`.

Lưu ý: `EMAIL_SMTP_PASSWORD` là bí mật như `JWT_SECRET`: không commit `.env`, không chụp màn hình, không gửi qua chat.
Khi gửi thật, MockMail **không giữ nội dung thư** trong bộ nhớ (`GET /api/emails` chỉ còn trạng thái) và không còn giả
lập địa chỉ `fail*` / `bounce*`. Gmail giới hạn khoảng 500 thư / ngày với tài khoản thường, đủ cho demo và chạy thử.

Không đưa `.env` lên Git hoặc gửi qua chat: tệp chứa khóa ký token và mật khẩu cơ sở dữ liệu.

Mật khẩu admin (và mọi tài khoản) từ 8 ký tự, có cả chữ và số. Không chạy `manage.py seed` trên máy chủ chạy thử:
tài khoản demo có mật khẩu công khai trong README.

## 4. HTTPS

Khi chưa có chứng chỉ, gateway tự tạo chứng chỉ tự ký cho `SERVER_NAME` (trình duyệt sẽ cảnh báo): chỉ dùng để thử.
Với tên miền thật, lấy chứng chỉ miễn phí của Let's Encrypt (tên miền phải trỏ đúng IP và cổng 80 mở):

```bash
docker compose --profile letsencrypt run --rm certbot certonly --webroot -w /var/www/acme \
  -d food.example.edu.vn --email <email nhóm> --agree-tos --no-eff-email
docker compose restart gateway       # gateway thấy chứng chỉ trong /etc/letsencrypt/live/<SERVER_NAME>/ và dùng ngay
```

Gia hạn (chứng chỉ có hạn 90 ngày): đặt cron hằng tuần trên máy chủ

```cron
0 3 * * 1 cd /srv/tdtu-food && docker compose --profile letsencrypt run --rm certbot renew -q && docker compose exec gateway nginx -s reload
```

### Cài app lên điện thoại

Khi đã có tên miền + chứng chỉ Let's Encrypt, người dùng mở `https://<tên miền>` bằng Chrome (Android) hoặc Safari
(iPhone) rồi bấm "Cài app" / "Thêm vào màn hình chính": TDTU Food mở toàn màn hình như app. Chứng chỉ tự ký (mục trên)
không cho cài app. Mã QR in ở quầy quán trỏ tới `PUBLIC_ORIGIN`, nên quét mã là mở đúng app.

## 5. Chạy thử Docker trên máy cá nhân (Windows / macOS)

Cần Docker Desktop. Dùng cổng khác để không đụng cổng 8000–8005 và 9000 của `manage.py start`:

```powershell
$env:SERVER_NAME="localhost"; $env:HTTP_PORT="8080"; $env:HTTPS_PORT="8443"; $env:PUBLIC_ORIGIN="https://localhost:8443"; $env:MOCK_EMAIL_PORT="9100"
docker compose up -d --build
```

Mở `https://localhost:8443`, chấp nhận cảnh báo chứng chỉ tự ký. Dừng: `docker compose down` (giữ dữ liệu) hoặc
`docker compose down -v` (xóa luôn dữ liệu).

## 6. Sao lưu và khôi phục

Container `backup` tự sao lưu ngay khi hệ thống sẵn sàng, rồi mỗi `BACKUP_INTERVAL_HOURS` giờ, giữ `BACKUP_KEEP` bản mới
nhất. Mỗi tệp `tdtu-backup-<thời điểm UTC>.tar.gz` gồm:

| Dữ liệu | Cách lấy (không cần dừng hệ thống) |
| --- | --- |
| `auth.db`, `restaurant.db`, `review.db` | API backup của SQLite (bản sao nhất quán) |
| `order.mv.db` | `GET /internal/backup` của Order Service (lệnh `BACKUP TO` của H2) |
| `notification.dump` | `pg_dump -Fc` |
| `uploads/` | Ảnh quán và ảnh món (Restaurant) |
| `avatars/` | Ảnh đại diện người dùng (Auth) |
| `manifest.json` | Thời điểm tạo, cách lấy và mã SHA-256 của từng tệp |

```bash
docker compose run --rm backup create                         # sao lưu ngay
docker compose run --rm backup list
docker compose run --rm backup verify /backups/tdtu-backup-20261016-020000Z.tar.gz

# khôi phục: dừng các service, khôi phục, chạy lại
docker compose stop auth restaurant order notification review
docker compose run --rm --no-deps backup restore /backups/tdtu-backup-20261016-020000Z.tar.gz --yes
docker compose start auth restaurant order notification review
```

Khôi phục không xóa gì: dữ liệu đang có được chuyển sang thư mục `truoc-khoi-phuc-<thời điểm>/` trong từng volume.
Lệnh từ chối chạy khi còn service đang chạy, và từ chối tệp bị sửa hoặc hỏng (sai SHA-256). `--no-deps` để
`docker compose run` không tự bật lại các service đã dừng.

Khi chạy bằng `manage.py` (không Docker), dùng `python manage.py backup` (thêm `--list`, `--verify <tệp>`, `--loop`) và
`python manage.py stop` → `python manage.py restore <tệp> --yes` → `python manage.py start`. Nếu máy không có
`pg_dump`, công cụ tự chạy `pg_dump` trong Docker (image `PG_DOCKER_IMAGE`).

Việc nhóm cần tự làm:

- **Chép bản sao lưu ra nơi khác** ít nhất mỗi tuần (Google Drive của nhóm, máy khác...), vì hỏng ổ đĩa máy chủ là mất cả
  dữ liệu lẫn bản sao lưu. Tệp chứa dữ liệu cá nhân: mã hóa trước khi chép, ví dụ
  `gpg -c tdtu-backup-....tar.gz`, và chỉ người vận hành giữ mật khẩu.
- **Diễn tập khôi phục mỗi tháng** trên máy cá nhân (mục 5): khôi phục bản mới nhất rồi đăng nhập kiểm tra.

## 7. Cập nhật phiên bản mới

```bash
docker compose run --rm backup create          # luôn sao lưu trước
git pull
docker compose up -d --build                   # chỉ build lại và khởi động lại phần thay đổi
docker compose ps
```

## 8. Theo dõi và xử lý sự cố

```bash
docker compose ps                              # trạng thái + healthcheck từng service
docker compose logs -f --tail=100 gateway      # truy cập; mỗi dòng có rid=<X-Request-ID>
docker compose logs --since 1h order | grep <X-Request-ID>
docker compose logs --since 1h | grep <X-Request-ID>     # một yêu cầu qua mọi service (order, auth, restaurant, notification)
docker compose restart order
```

| Hiện tượng | Cách xử lý |
| --- | --- |
| Trình duyệt báo `RATE_LIMITED` | Một IP gửi quá nhiều yêu cầu; nếu cả ký túc xá dùng chung IP, tăng `rate`/`burst` trong `deploy/gateway/default.conf.template` |
| `UPSTREAM_UNAVAILABLE` (503) | Service tương ứng đang dừng / khởi động lại: `docker compose ps`, `docker compose logs <service>` |
| `notification` không healthy | PostgreSQL chưa sẵn sàng hoặc sai `POSTGRES_PASSWORD` (đổi mật khẩu sau khi volume `pg-data` đã tạo thì phải đổi cả trong PostgreSQL) |
| Gateway báo lỗi chứng chỉ | Kiểm tra `SERVER_NAME` khớp tên miền đã xin chứng chỉ; `docker compose logs gateway` |
| Mã QR trỏ sai địa chỉ | Sửa `PUBLIC_ORIGIN` rồi `docker compose up -d web` |
| Đăng ký báo "chưa gửi được email xác nhận" | `docker compose ps mock-email`; `docker compose logs notification` (dòng "Gửi email … thất bại", có mã lỗi `EMAIL_PROVIDER_*`); kiểm `EMAIL_API_KEY` trong `.env`. Người dùng bấm Gửi lại mã sau khi sửa |
| `mock-email` dừng ngay sau khi chạy | `EMAIL_API_KEY` thiếu hoặc dưới 16 ký tự: chạy `python3 manage.py doctor` để bổ sung khóa vào `.env` |

## 9. Yêu cầu của người dùng về dữ liệu cá nhân

Chính sách quyền riêng tư cam kết phản hồi trong 72 giờ. Chỉ xử lý khi yêu cầu gửi từ chính email đã đăng ký.

- **Xóa dữ liệu / rút lại đồng ý**: admin → Sinh viên (hoặc Chủ quán) → Chi tiết → *Xóa dữ liệu cá nhân*, gõ lại email để
  xác nhận. Auth khóa tài khoản, thu hồi token, rồi yêu cầu Order (ẩn danh người đặt, xóa giỏ), Restaurant (gỡ quán, xóa
  ảnh), Review (ẩn danh tên người viết), Notification (xóa thông báo và nhật ký email `email_logs`); cuối cùng ẩn danh họ
  tên, email, số điện thoại trong Auth (với chủ quán: cả tài khoản nhận tiền) và xóa mã OTP `otp_codes`. Còn đơn đang chờ / đã xác nhận, hoặc đơn đã trả tiền bị hủy mà quán
  chưa hoàn tiền, thì hệ thống từ chối: xử lý xong các đơn đó rồi làm lại.
  API: `POST /api/users/{id}/erase` (admin). Người đó muốn ẩn cả nhận xét đã viết: admin → Đánh giá → *Ẩn*.
- **Sau khi khôi phục bản sao lưu cũ**: mỗi lần xóa được ghi ID vào `erasures.log` cạnh `auth.db` (và chép sang thư mục
  sao lưu). Tệp này không bị khôi phục đè; khi khởi động, Auth tự xóa lại những tài khoản có trong nhật ký mà dữ liệu
  khôi phục còn chứa (thử lại mỗi 30 giây trong 20 phút, xem `docker compose logs auth`).
- **Nhận bản sao dữ liệu**: admin mở Chi tiết của người đó (hồ sơ, đơn gần đây), hoặc gọi API admin
  (`GET /api/users/{id}`, `GET /api/admin/orders?user_id=...`), gửi lại cho người yêu cầu.
- **Kết thúc chạy thử**: báo trong ứng dụng trước ít nhất 7 ngày, rồi `docker compose down -v` (xóa mọi volume) và xóa
  toàn bộ bản sao lưu, kể cả bản đã chép ra nơi khác.

## 10. Danh sách kiểm tra trước khi mở cho người dùng thật

- [ ] Tên miền + chứng chỉ Let's Encrypt; `PUBLIC_ORIGIN` đúng; mở thử trên điện thoại bằng mã QR.
- [ ] `CONTACT_EMAIL` đã đặt và có người đọc hộp thư.
- [ ] Email OTP: `OTP_ENABLED=false`, hoặc đã nối nhà cung cấp email thật và thử đăng ký nhận được mã (mục 3).
- [ ] Đã tạo admin thật, không có tài khoản demo (`seed`) trên máy chủ.
- [ ] `docker compose ps` toàn bộ healthy; `docker compose run --rm backup create` chạy được và đã chép thử ra nơi khác.
- [ ] Đã diễn tập khôi phục một lần.
- [ ] Nhóm đã xin phép nhà trường dùng tên và logo TDTU, và nhờ giảng viên / bộ phận pháp chế đọc lại hai trang Điều khoản,
      Quyền riêng tư (bản hiện tại là bản nháp do nhóm soạn).
- [ ] Chủ quán tham gia chạy thử có giấy chứng nhận đủ điều kiện an toàn thực phẩm (theo Điều khoản, mục 4).
- [ ] Mỗi chủ quán đã khai báo tài khoản ngân hàng **thật** của mình và thử một giao dịch nhỏ: quét mã VietQR trên trang
      thanh toán bằng app ngân hàng, kiểm tra app điền đúng tên chủ tài khoản, số tiền, nội dung; chủ quán biết bấm
      "Đã nhận tiền" / "Chưa nhận được tiền" và cách hoàn tiền (Điều khoản, mục 5).
