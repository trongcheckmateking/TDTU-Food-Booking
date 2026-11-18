# TDTU Food Booking

Hệ thống đặt đồ ăn cho sinh viên TDTU theo kiến trúc hướng dịch vụ: **5 service độc lập, mỗi service một ngôn ngữ**,
mỗi service một CSDL riêng, gọi nhau qua REST JSON, cùng giao diện web cho sinh viên, chủ quán và admin.

| Service | Thành viên | Ngôn ngữ / framework | CSDL | Cổng |
| --- | --- | --- | --- | --- |
| Auth | TV1 | Python 3.11+ / FastAPI | SQLite | 8001 |
| Restaurant | TV2 | Node.js 22+ / Express 5 | SQLite (`node:sqlite`) | 8002 |
| Order | TV3 | Java 17+ / Spring Boot 3.5.6 | H2 (tệp) | 8003 |
| Notification | TV4 | Go 1.22+ / Gin + GORM | PostgreSQL 14+ | 8004 |
| Review | TV5 | PHP 8.1+ (thuần) | SQLite (PDO) | 8005 |
| Giao diện web | – | Python (phục vụ HTML/CSS/JS tĩnh) | – | 8000 |
| Mock Email Provider | – | Python / FastAPI (nhà cung cấp email **giả lập**, Unit 20) | bộ nhớ | 9000 |

Sơ đồ kiến trúc: [`docs/diagrams/arch/ARCH_0_microservices.png`](docs/diagrams/arch/ARCH_0_microservices.png).

## Cấu trúc thư mục

```
TDTU_FoodBooking_Final/
├── manage.py               # công cụ vận hành: init-env, doctor, build, pg-setup, start, seed, stop, status, ...
├── run.sh / run.ps1        # lối tắt cho Linux/macOS và Windows
├── requirements*.txt       # thư viện Python (Auth, web, công cụ, test)
├── .env.example            # mẫu cấu hình chung cho 5 service (không chứa bí mật)
├── common/                 # thư viện Python của Auth + web (cấu hình, SQLite, lỗi, gọi REST)
├── services/
│   ├── auth/               # Python/FastAPI: tài khoản, JWT, khóa/vai trò
│   ├── restaurant/         # Node.js/Express: quán, menu, duyệt quán   (src/, test/, package.json)
│   ├── order/              # Java/Spring Boot: giỏ, đơn, outbox        (src/main, src/test, pom.xml, mvnw)
│   ├── notification/       # Go/Gin/GORM: thông báo                   (*.go, go.mod, docker-compose.postgres.yml)
│   ├── review/             # PHP: đánh giá                            (public/index.php, src/, tests/)
│   └── mock_email/         # Python/FastAPI: nhà cung cấp email giả lập (MockMail) gửi mã OTP, webhook ký HMAC
├── image/logo/logo.png     # logo dự án (bản gốc, nền trong suốt)
├── web/                    # :8000 giao diện (server.py: trang tĩnh, /config.js, mã QR /qr/*.svg; static/: trang, qr.html, logo, font)
├── scripts/                # seed_data.py (seed qua API), backup.py, smoke_test.py, demo_concurrency.py, build_postman.py, ...
├── docker-compose.yml      # chạy cả hệ thống bằng Docker: 5 service + web + PostgreSQL + gateway HTTPS + mock-email + sao lưu
├── deploy/                 # gateway/ (Nginx: HTTPS, /svc/<service>/, chặn /internal), backup/ (container sao lưu)
├── tests/                  # unit, integration (5 tiến trình thật), e2e (manage.py), ui (Playwright)
└── docs/                   # tài liệu, OpenAPI, Postman, sơ đồ, báo cáo kiểm thử
```

## Yêu cầu cài đặt

| Phần mềm | Phiên bản | Dùng cho |
| --- | --- | --- |
| Python | 3.11+ | Auth, giao diện, `manage.py`, test |
| Node.js | 22.13+ (LTS 22 hoặc 24) | Restaurant (cần `node:sqlite` có sẵn trong Node 22+) |
| JDK | 17+ (khuyên dùng Temurin 17/21) | Order; build bằng Maven 3.9 **hoặc** `mvnw` đi kèm (tự tải Maven, cần Internet lần đầu) |
| Go | 1.22+ | Build Notification (chỉ cần khi build) |
| PHP | 8.1+ với `pdo_sqlite`, `curl`, `mbstring` | Review |
| PostgreSQL | 14+ (cài trực tiếp **hoặc** Docker) | CSDL của Notification |

Windows: PHP bản ZIP từ windows.php.net cần bật trong `php.ini`: `extension=pdo_sqlite`, `extension=curl`, `extension=mbstring`.
Kiểm tra nhanh mọi thứ: `python manage.py doctor`.

## Cài đặt và chạy

### Windows (PowerShell)

```powershell
cd TDTU_FoodBooking_Final
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # nếu PowerShell chặn script
.\run.ps1 setup       # .venv + thư viện Python, tạo .env, npm ci, go build, mvnw package, kiểm tra môi trường
.\run.ps1 pg-setup    # tạo user + database PostgreSQL (psql hỏi mật khẩu tài khoản postgres)
.\run.ps1 start       # chạy 5 service + giao diện, chờ đến khi sẵn sàng
.\run.ps1 seed        # (tùy chọn) dữ liệu demo, nạp qua REST API
.\run.ps1 status
.\run.ps1 stop
```

### Linux / macOS

```bash
cd TDTU_FoodBooking_Final
./run.sh setup
./run.sh pg-setup      # hoặc dùng Docker, xem dưới
./run.sh start
./run.sh seed
```

### PostgreSQL bằng Docker (thay cho pg-setup)

```bash
python manage.py init-env       # nếu chưa có .env (sinh POSTGRES_PASSWORD ngẫu nhiên)
docker compose -f services/notification/docker-compose.postgres.yml --env-file .env up -d
```

### Từng bước (mọi hệ điều hành)

```bash
python -m venv .venv            # Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python manage.py init-env       # .env với JWT_SECRET, INTERNAL_KEY, mật khẩu PostgreSQL ngẫu nhiên
python manage.py build          # npm ci (Restaurant), go build (Notification), mvn package (Order)
python manage.py pg-setup       # tạo user/database PostgreSQL theo NOTIFICATION_DB_URL
python manage.py doctor         # mọi dòng phải "OK"
python manage.py start
python manage.py seed           # bỏ qua nếu không cần dữ liệu demo
```

Không dùng dữ liệu demo: bỏ bước `seed`, tạo admin thật bằng `python manage.py create-admin`.
Mỗi lệnh làm gì, in ra gì và đọc kết quả thế nào: [`docs/COMMANDS.md`](docs/COMMANDS.md).
Chạy riêng một service (khi phát triển): xem lệnh trong `docs/ARCHITECTURE.md` mục "Vận hành"; mỗi service tự đọc `.env` ở thư mục gốc.

## Địa chỉ sau khi start

| Thành phần | URL |
| --- | --- |
| Giao diện web | http://127.0.0.1:8000 |
| Auth – Python (Swagger / ReDoc) | http://127.0.0.1:8001/docs · /redoc |
| Restaurant – Node.js | http://127.0.0.1:8002/docs |
| Order – Java | http://127.0.0.1:8003/docs |
| Notification – Go | http://127.0.0.1:8004/docs |
| Review – PHP | http://127.0.0.1:8005/docs |
| Mock Email Provider (hộp thư lấy mã OTP) | http://127.0.0.1:9000/docs |

Health/readiness: `GET /health` ở mỗi service (kiểm tra cả kết nối CSDL). Log: thư mục `logs/`.
Trang `/docs` của Restaurant, Order, Notification, Review tải Swagger UI từ CDN (cần Internet); `/openapi.json` luôn dùng được.

## Xác nhận email bằng OTP (Unit 20)

Bật mặc định (`OTP_ENABLED=true` trong `.env`). Đăng ký → Auth tạo mã 6 số (DB chỉ lưu HMAC) → Notification gửi qua nhà
cung cấp email giả lập MockMail → giao diện hiện form nhập mã → đúng mã thì đăng nhập luôn. Chưa xác nhận thì đăng nhập
báo `EMAIL_NOT_VERIFIED` và mở form nhập mã. Đăng ký rồi tải lại trang khi chưa nhập mã thì đăng ký lại cùng email được (cập nhật thông tin, gửi mã mới). Sai 5 lần thì mã bị khóa; gửi lại mã cách nhau tối thiểu 60 giây, tối đa
5 mã / giờ. Notification hoặc MockMail lỗi thì đăng ký vẫn thành công (`otp_sent=false`), bấm *Gửi lại mã* sau.

**Gửi mã tới hộp thư thật:** điền `EMAIL_SMTP_HOST`, `EMAIL_SMTP_USER`, `EMAIL_SMTP_PASSWORD` trong `.env` (Gmail + mật
khẩu ứng dụng, các bước ở [`docs/DEPLOY.md`](docs/DEPLOY.md)) rồi khởi động lại; đăng ký bằng email thật là nhận được mã.

**Lấy mã khi demo** (chế độ giả lập, không gửi thư thật): mở `http://127.0.0.1:9000/docs` → **Authorize** (dán `EMAIL_API_KEY` trong
`.env`) → `GET /api/emails` → Try it out (lọc `to` = email vừa đăng ký) → mã 6 số nằm trong trường `content`.
Giả lập sự cố: `POST /api/_control/mode` với `{"mode": "fail500" | "rate429" | "slow" | "ok"}`; người nhận bắt
đầu bằng `fail` → provider trả 500, bắt đầu bằng `bounce` → webhook báo `failed`. Admin xem trạng thái thư ở
`GET :8004/api/admin/email-logs`. Luồng chi tiết: [`docs/diagrams/arch/ARCH_1_otp_flow.png`](docs/diagrams/arch/ARCH_1_otp_flow.png).
Tắt OTP: `OTP_ENABLED=false` (đăng ký xác nhận luôn, hai API OTP trả 404 `OTP_DISABLED`).

## Giao diện, bảng tin món mới và mã QR

- **Nhận diện:** tông ấm "quán gỗ": nền be giấy dó `#F5EFE5`, thẻ kem `#FFFCF7`, gỗ óc chó `#3B2A1E` cho menu admin và Bảng tin
  món mới; xanh `#15489D` / đỏ `#ED252A` và nét nghiêng của logo TĐT cho nút chính, bảng hiệu quán, điểm nhấn (mọi cặp chữ / nền
  đạt tương phản WCAG AA). Logo dự án là đầu bếp đang chạy mang khay
  có logo TĐT: bản gốc độ phân giải cao ở `image/logo/logo.png` (nền trong suốt), bản dùng trên web
  `web/static/assets/brand/logo.png`, favicon `web/static/assets/favicon.png`. Logo gốc của trường (`brand/tdtu-logo.png`,
  tải từ tdtu.edu.vn) đặt nguyên vẹn ở chân trang kèm ghi chú "đồ án sinh viên, không phải ứng dụng chính thức". Font
  Be Vietnam Pro (SIL OFL) đóng gói trong `assets/fonts/`, chạy được khi không có Internet.
- **Bảng tin món mới:** chủ quán thêm món, đổi giá hoặc bán lại món đã hết thì tin tự hiện ở trang giới thiệu (kèm bảng
  LED chạy chữ) và đầu trang sinh viên. API: `GET :8002/api/menu-updates?limit=` (công khai, xem `docs/API.md`).
- **Mã QR:** `/qr/sinh-vien.svg` và `/qr/chu-quan.svg` mở thẳng form đăng ký với vai trò chọn sẵn
  (`index.html?dang-ky=...`). Admin xem ở tab *Mã QR*; chủ quán có thẻ QR ở *Quán của tôi*; `qr.html` in 2 áp phích A5
  trên một tờ A4 để dán ở quầy quán và bảng tin khoa.

### Giao diện chủ quán (theo mô hình GrabMerchant / beFood Merchant)

| Mục | Chức năng |
| --- | --- |
| Đơn hàng (mở đầu tiên) | Thẻ đơn chia tab Mới / Đang làm / Hoàn thành / Đã hủy; nút Nhận đơn, Từ chối (chọn nhanh lý do), Báo hoàn thành; SĐT khách bấm để gọi; tự làm mới 15 giây, âm báo + số đơn chờ trên tab khi có đơn mới |
| Tổng quan | Bật/tắt nhận đơn, danh sách việc cần làm cho quán mới, doanh thu / đơn hôm nay, đơn chờ, điểm đánh giá, biểu đồ doanh thu 7 hoặc 30 ngày (giờ Việt Nam), món bán chạy |
| Thực đơn | Món chia theo danh mục, ảnh món, công tắc Còn món / Hết món, bấm vào giá để sửa ngay, tìm kiếm, lọc; thêm / sửa / ẩn / xóa món |
| Cửa hàng | Đăng ký quán mới, ảnh bìa (kéo thả, tự thu nhỏ, hoặc chọn 1 trong 8 nền có sẵn: cơm, bún/phở, bánh mì, trà/cà phê, ăn vặt, món chay...), tên, địa chỉ, giới thiệu, giờ mở cửa, xem trước quán như sinh viên thấy, mã QR dán tại quán, xóa quán; nhiều quán thì chọn quán ở đầu trang |
| Đánh giá | Điểm trung bình, phân bố sao, đánh giá mới nhất của từng quán |

Thông báo và hồ sơ mở từ chuông và ảnh đại diện trên thanh trên. Ảnh lưu ở `DATA_DIR/uploads/` (tối đa 2 MB mỗi ảnh,
chỉ JPEG/PNG/WebP, kiểm tra theo nội dung tệp). API mới: `POST :8002/api/uploads`, `GET :8003/api/orders/owner/stats`.
Nền có sẵn được vẽ ngay trên trình duyệt (`web/static/assets/covers.js`) rồi tải lên như ảnh bìa, nên sinh viên thấy đúng
nền chủ quán chọn. Quán chưa có ảnh bìa hiện nền tượng trưng đoán theo tên quán ("Bún Bò..." → tô bún), mọi thẻ quán cao bằng nhau.

### Thanh toán trước bằng VietQR (tiền vào thẳng tài khoản của quán)

- **Chủ quán khai báo tài khoản nhận tiền khi đăng ký** (ngân hàng trong danh sách Napas, số tài khoản, tên chủ tài khoản
  in hoa không dấu); đổi sau ở Profile → *Tài khoản nhận tiền* (phải nhập lại mật khẩu). Chủ quán cũ chưa khai báo thì
  sinh viên chưa đặt được món ở quán đó (409 `OWNER_NO_PAYOUT`), trang Đơn hàng / Tổng quan nhắc khai báo.
- **Sinh viên thanh toán trước khi đơn tới bếp**: bấm Đặt hàng → trang thanh toán có **mã VietQR riêng của đơn** (đúng
  ngân hàng, số tài khoản của quán, số tiền, nội dung `TDTU 047 AB12`), nút chép từng dòng, nút lưu ảnh QR (một điện
  thoại: lưu ảnh rồi chọn ảnh trong app ngân hàng), đếm ngược 15 phút → bấm **"Tôi đã chuyển khoản"**.
- **Chủ quán xác nhận**: tab **Chờ tiền** (có âm báo khi sinh viên báo đã chuyển) → mở app ngân hàng, thấy khoản tiền đúng
  nội dung thì bấm **"Đã nhận tiền"** → đơn sang tab **Mới** để nhận và làm món (sinh viên được báo "đặt thành công", thấy
  mã nhận món); không thấy tiền thì **"Chưa nhận được tiền"** (đơn hủy, sinh viên được báo kèm lý do).
- **Hủy và hoàn tiền**: đơn chưa trả tiền sinh viên tự bỏ được, quá hạn thì tự hủy. Đơn đã trả tiền bị hủy (quán hoặc
  admin) chuyển sang **Cần hoàn tiền**; quán chuyển trả rồi bấm "Đã hoàn tiền". Sinh viên báo đã chuyển mà quán không phản
  hồi: admin hủy giúp, đơn cũng vào Cần hoàn tiền.
- App **không giữ tiền, không thu phí** và không đối soát tự động với ngân hàng: chủ quán tự kiểm tra tài khoản. Tài khoản
  của chủ quán demo ghi `TAI KHOAN DEMO` (số giả); trang thanh toán cảnh báo không chuyển tiền thật.
- Mã QR do máy chủ giao diện tạo: `/qr/vietqr.svg|png?bin=&acc=&amount=&note=` (chuẩn EMVCo của Napas, CRC16).

### Nhận món bằng mã 3 số và dùng như app trên điện thoại

- **Mã đơn luôn là 3 chữ số** (`#047`): số thứ tự đơn trong ngày của từng quán. Sinh viên đặt món (mặc định "Tự tới quán
  lấy", hoặc "Nhờ quán mang tới"), tới quầy đọc 3 số như khi lấy món Grab, be. Thẻ đơn của sinh viên có mã thật to; chủ quán
  gõ mã vào ô "Tìm mã nhận món" là ra đúng đơn, đối chiếu tên rồi giao và bấm Báo hoàn thành.
- **Hướng dẫn cho tài khoản mới**: vừa đăng ký xong sẽ hiện màn hướng dẫn 4 bước (sinh viên: đặt món → chuyển khoản
  trước → nhớ mã → tới quán đọc mã; chủ quán: sinh viên chuyển khoản → bấm Đã nhận tiền → nhận đơn, làm món → hỏi mã,
  giao món). Mở lại ở Profile.
- **Sinh viên không tự hủy đơn đã đặt**: cần hủy thì gọi quán hoặc nhờ ban quản trị; **admin là người hủy đơn** (đơn chờ
  xác nhận hoặc đang làm, kèm lý do; không xác nhận / hoàn thành thay quán). Chủ quán vẫn từ chối / hủy đơn của quán mình.
- **Cài lên điện thoại như app (PWA)**: mở trang bằng Chrome (Android) hoặc Safari (iPhone) → nút "Cài app" (hoặc menu →
  "Thêm vào màn hình chính"). App mở toàn màn hình, có biểu tượng riêng, hiện trang báo khi mất mạng. Trình duyệt chỉ cho cài
  khi trang chạy qua HTTPS (bản Docker có gateway HTTPS) hoặc mở bằng `localhost` / `127.0.0.1`; điện thoại vào bằng
  `http://192.168.x.x:8000` vẫn dùng được nhưng không cài được.
- Giao diện điện thoại: thanh tab ở đáy, hộp thoại trượt từ dưới lên, thanh "Xem giỏ hàng" nổi, nút Đặt hàng dính đáy,
  chừa vùng tai thỏ / thanh home của iPhone.

### Trang Profile (kiểu trang Tài khoản của app be, dùng chung 3 vai trò)

Thẻ đầu trang có ảnh đại diện (bấm biểu tượng máy ảnh để đổi; ảnh được cắt vuông, thu nhỏ 512 px rồi lưu ở Auth Service,
`DATA_DIR/avatars/`), họ tên, email, số điện thoại; hàng số liệu nhanh theo vai trò (sinh viên: đơn đã đặt / hoàn thành /
đánh giá; chủ quán: số quán / đơn đã nhận / hoàn thành; admin: tài khoản / quán chờ duyệt / đơn); nhóm **Tài khoản**
(thông tin cá nhân, ảnh đại diện, đổi mật khẩu - các thiết bị khác bị đăng xuất), **Hoạt động** (lối tắt theo vai trò,
chỗ nhận hay dùng của sinh viên), **Hỗ trợ và pháp lý** (email hỗ trợ, điều khoản, quyền riêng tư, yêu cầu xóa tài khoản),
Đăng xuất. Ảnh đại diện cũng hiện ở thanh trên và trong danh sách người dùng của admin.

### Giao diện admin (menu bên trái, kiểu AdminLTE / CoreUI)

| Mục | Chức năng |
| --- | --- |
| Bảng điều khiển | 6 chỉ số (doanh thu hôm nay, đơn, tỉ lệ hoàn thành, người dùng, quán đang bán, điểm đánh giá); biểu đồ doanh thu / số đơn 7 hoặc 30 ngày; biểu đồ vòng tỉ lệ trạng thái đơn, cơ cấu người dùng, tình trạng quán; top quán theo % doanh thu; phân bố sao; danh sách "Cần xử lý"; tình trạng 5 service |
| Sinh viên | Lọc theo trạng thái, bảng chi tiết: số đơn, hoàn thành, bị hủy, tổng chi, đơn gần đây; khóa / mở khóa, chuyển thành chủ quán |
| Chủ quán | Số quán và trạng thái từng quán; bảng chi tiết: đơn và doanh thu 30 ngày của từng quán, duyệt / từ chối / khóa quán, xem thực đơn; khóa / mở khóa, chuyển thành sinh viên |
| Tất cả tài khoản | Đổi vai trò (kể cả admin), khóa / mở khóa |
| Quán ăn, Đơn hàng, Đánh giá | Bộ lọc dạng nút có số đếm; bấm tên chủ quán / sinh viên để mở bảng chi tiết của người đó |
| Thông báo, Mã QR, Hồ sơ | Gửi lại thông báo lỗi, in mã QR, hồ sơ admin |

Màu biểu đồ đã kiểm tra cho người mù màu (vàng = đang chờ, xanh dương = đang xử lý, xanh lá = tốt, hồng tím = hủy / khóa).
Trên điện thoại menu thu vào nút ☰. API mới: `GET :8003/api/admin/orders/report`, lọc `owner_id` ở `GET :8002/api/admin/restaurants`.

### Dùng mã QR trên điện thoại (cùng mạng Wi-Fi)

Mặc định mọi địa chỉ là `127.0.0.1`, điện thoại không mở được. Trên máy chạy app (ví dụ IP LAN `192.168.1.10`, xem bằng
`ipconfig` / `ip addr`), sửa `.env`:

```
PUBLIC_WEB_URL=http://192.168.1.10:8000
PUBLIC_AUTH_URL=http://192.168.1.10:8001
PUBLIC_RESTAURANT_URL=http://192.168.1.10:8002
PUBLIC_ORDER_URL=http://192.168.1.10:8003
PUBLIC_NOTIFICATION_URL=http://192.168.1.10:8004
PUBLIC_REVIEW_URL=http://192.168.1.10:8005
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,http://192.168.1.10:8000
```

rồi `python manage.py stop` và `python manage.py start --host 0.0.0.0` (Windows có thể hỏi mở tường lửa cho cổng
8000–8005: chọn mạng riêng). In lại áp phích sau khi đổi địa chỉ. Khi triển khai thật trên tên miền, đặt các biến trên
bằng địa chỉ công khai.

## Tài khoản demo (chỉ có sau `seed`, dữ liệu giả)

| Vai trò | Email | Mật khẩu |
| --- | --- | --- |
| Admin | admin@demo.tdtu.vn | Admin@123 |
| Chủ quán | chuquan1@demo.tdtu.vn, chuquan2@demo.tdtu.vn | Demo@123 |
| Sinh viên | sv1@demo.tdtu.vn, sv2@demo.tdtu.vn | Demo@123 |
| Sinh viên bị khóa | sv3.bikhoa@demo.tdtu.vn | Demo@123 |

Các tài khoản seed được đánh dấu **đã xác nhận email sẵn** (không cần mã OTP). Đổi các mật khẩu này hoặc không chạy `seed`
nếu dùng ngoài mục đích demo.

## Dữ liệu

- `data/` (đổi bằng `DATA_DIR`): `auth.db`, `restaurant.db`, `review.db` (SQLite), `order.mv.db` (H2); bảng
  `notifications` nằm trong database PostgreSQL `tdtu_notification`. Dữ liệu giữ nguyên sau khi stop/start.
- `python manage.py reset-demo --yes` **XÓA toàn bộ dữ liệu** (các tệp trong `DATA_DIR` và bảng `notifications`),
  rồi start và nạp lại dữ liệu demo (phải stop trước).

## Chạy thử với người dùng thật (Docker, HTTPS, sao lưu)

Hướng dẫn đầy đủ: [`docs/DEPLOY.md`](docs/DEPLOY.md). Tóm tắt:

```bash
python manage.py init-env                    # sửa SERVER_NAME, PUBLIC_ORIGIN, CONTACT_EMAIL trong .env
docker compose up -d --build                 # 5 service + web + PostgreSQL + gateway Nginx (HTTPS) + sao lưu tự động
docker compose exec auth python -m services.auth.admin_tools --email <email> --name "<Họ tên>"
```

- Một tên miền: giao diện ở `/`, API ở `/svc/<service>/`; chỉ gateway mở cổng, `/internal` và trang tài liệu API bị chặn.
- Bảo mật: mật khẩu từ 8 ký tự có cả chữ và số; đăng nhập sai 5 lần (cùng email + IP) thì tạm khóa 15 phút; giới hạn
  tần suất ở gateway; HTTPS + HSTS; giao diện có CSP chặt (không script nhúng), chống nhúng trang (clickjacking).
- Pháp lý: trang [Điều khoản sử dụng](web/static/dieu-khoan.html) và [Chính sách quyền riêng tư](web/static/quyen-rieng-tu.html);
  đăng ký phải tick đồng ý (lưu thời điểm đồng ý); admin xử lý yêu cầu xóa dữ liệu cá nhân bằng nút
  *Xóa dữ liệu cá nhân* (Auth điều phối 4 service còn lại ẩn danh / xóa dữ liệu của người đó).
- Sao lưu: container `backup` sao lưu mỗi ngày cả 5 cơ sở dữ liệu + ảnh, giữ 7 bản. Không dùng Docker:
  `python manage.py backup` / `python manage.py restore <tệp> --yes` (xem `docs/DEPLOY.md`, mục 6).

## Kiểm thử

```bash
pip install -r requirements-dev.txt
python manage.py test-services                         # test riêng: node --test, go test, php tests/run.php, mvn test
python -m pytest tests/unit tests/integration tests/e2e  # 5 tiến trình thật, dữ liệu tạm + schema PostgreSQL tạm
python scripts/smoke_test.py                           # kiểm tra nhanh hệ thống ĐANG chạy (có luồng OTP qua MockMail)
python scripts/demo_concurrency.py                     # demo đồng thời: Idempotency-Key, khóa giỏ, đổi trạng thái
python -m playwright install chromium && python -m pytest tests/ui   # cần hệ thống đang chạy với dữ liệu demo
```

Test tích hợp/E2E cần đã `build` và có PostgreSQL (dùng `NOTIFICATION_TEST_DB_URL` nếu đặt, nếu không dùng
`NOTIFICATION_DB_URL` trong `.env`, mỗi lần chạy tạo một schema riêng rồi xóa). Không đụng dữ liệu trong `data/`.
Postman: import `docs/postman/*.json`, chạy thư mục "0. Luồng demo". Kết quả đã chạy: `docs/TEST_REPORT.md`.

## Tài liệu

| Tệp | Nội dung |
| --- | --- |
| `docs/ARCHITECTURE.md` | 5 ngôn ngữ, hợp đồng chung, xác thực, luồng đặt món, outbox, đồng thời, vận hành |
| `docs/API.md` | Quy ước, mã lỗi, ví dụ, bảng mọi endpoint và quyền |
| `docs/DATABASE.md` | 5 CSDL (SQLite, H2, PostgreSQL), khóa ngoại vs tham chiếu logic, schema |
| `docs/DEMO.md` | Kịch bản trình diễn 3 vai trò, Unit 18–22, đồng thời, truy vết X-Request-ID |
| `docs/REQUIREMENTS.md` | Đối chiếu yêu cầu → chức năng → API/UI → test |
| `docs/SOURCE_REVIEW.md`, `docs/MERGE_DECISIONS.md` | Đánh giá các bộ nguồn và quyết định hợp nhất theo từng thành viên |
| `docs/TEST_REPORT.md` | Môi trường, lệnh, kết quả kiểm thử thực tế |
| `docs/COMMANDS.md` | Bảng tra mọi lệnh: làm gì, in ra gì, đọc kết quả thế nào, khi nào dùng |
| `docs/DOCKER.md` | Hướng dẫn nhóm chạy cả hệ thống bằng Docker Desktop trên máy cá nhân |
| `docs/DEPLOY.md` | Chạy thử bằng Docker: gateway HTTPS, sao lưu / khôi phục, cập nhật, yêu cầu xóa dữ liệu |
| `docs/PROJECT_SUMMARY.md` | Tóm tắt phục vụ thuyết trình |
| `docs/diagrams/` | Kiến trúc microservices + luồng OTP (`arch/`), Use Case, DFD mức 0/1/2, ERD (PNG/SVG) + `gen_diagrams.py` |
| `docs/CHANGELOG_FINAL.md` | Thay đổi bản cuối kỳ, mức trần đã gỡ, việc còn lại |
| `docs/openapi/` | OpenAPI của 5 service (`python manage.py export-openapi`) |

## Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `Thiếu cấu hình ...` | `python manage.py init-env` |
| `Không kết nối được PostgreSQL` khi start | Bật PostgreSQL (hoặc Docker), chạy `python manage.py pg-setup`; kiểm tra `NOTIFICATION_DB_URL` |
| `password authentication failed` (Notification) | Mật khẩu trong `.env` khác DB: chạy lại `pg-setup` (cập nhật mật khẩu user) |
| `Chưa có order-service.jar` / `Chưa build Notification` | `python manage.py build` (cần JDK + Internet cho Maven lần đầu; cần Go) |
| `Restaurant chưa cài thư viện` | `python manage.py build --only restaurant` |
| Node báo không có `node:sqlite` | Cài Node.js 22.13 trở lên |
| PHP: `could not find driver` / `Call to undefined function curl_init` | Bật `pdo_sqlite`, `curl` trong `php.ini` |
| `Cổng đang bị chiếm` | Tắt chương trình dùng cổng 8000–8005, 9000 hoặc đổi `*_URL`, `MOCK_EMAIL_URL`, `WEB_PORT`, `CORS_ORIGINS` trong `.env` |
| Đăng ký xong báo chưa gửi được email (`otp_sent=false`) | Xem `logs/notification.log`, `logs/mock_email.log`; kiểm tra `EMAIL_PROVIDER_URL`, `EMAIL_API_KEY` trong `.env`; bấm Gửi lại mã |
| Một service "KHÔNG PHẢN HỒI" | Xem `logs/<service>.log` |
| Bị đưa về trang đăng nhập "phiên hết hạn" | Token hết hạn, đã đăng xuất, bị đổi vai trò hoặc bị khóa: đăng nhập lại |

## Giới hạn còn lại

- SQLite/H2 dạng tệp phù hợp chạy thử một máy chủ (vài trăm người dùng), chưa mở rộng ngang được.
  `php -S` chỉ dùng khi phát triển; bản Docker chạy Review trên Apache.
- Thanh toán trước do chủ quán tự xác nhận (chưa nối webhook ngân hàng / cổng thanh toán); không có giao hàng; email chỉ
  gửi qua nhà cung cấp giả lập MockMail (chưa nối dịch vụ email thật, không có SMS); giờ mở cửa chỉ để hiển thị.
- Đã chạy và kiểm thử trên Linux và Windows 11 (`manage.py`, `mvnw.cmd`, PHP/Go/Java/Node trên Windows, PostgreSQL bằng
  Docker); `run.ps1 setup` / `pg-setup` trên PowerShell 5.1 chưa chạy lại (xem `docs/TEST_REPORT.md`).
