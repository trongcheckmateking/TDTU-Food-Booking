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
│   └── review/             # PHP: đánh giá                            (public/index.php, src/, tests/)
├── web/                    # :8000 giao diện (server.py + static/)
├── scripts/                # seed_data.py (seed qua API), smoke_test.py, build_postman.py, gen_api_md.py, package_release.py
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

Health/readiness: `GET /health` ở mỗi service (kiểm tra cả kết nối CSDL). Log: thư mục `logs/`.
Trang `/docs` của Restaurant, Order, Notification, Review tải Swagger UI từ CDN (cần Internet); `/openapi.json` luôn dùng được.

## Tài khoản demo (chỉ có sau `seed`, dữ liệu giả)

| Vai trò | Email | Mật khẩu |
| --- | --- | --- |
| Admin | admin@demo.tdtu.vn | Admin@123 |
| Chủ quán | chuquan1@demo.tdtu.vn, chuquan2@demo.tdtu.vn | Demo@123 |
| Sinh viên | sv1@demo.tdtu.vn, sv2@demo.tdtu.vn | Demo@123 |
| Sinh viên bị khóa | sv3.bikhoa@demo.tdtu.vn | Demo@123 |

Đổi các mật khẩu này hoặc không chạy `seed` nếu dùng ngoài mục đích demo.

## Dữ liệu

- `data/` (đổi bằng `DATA_DIR`): `auth.db`, `restaurant.db`, `review.db` (SQLite), `order.mv.db` (H2); bảng
  `notifications` nằm trong database PostgreSQL `tdtu_notification`. Dữ liệu giữ nguyên sau khi stop/start.
- `python manage.py reset-demo --yes` **XÓA toàn bộ dữ liệu** (các tệp trong `DATA_DIR` và bảng `notifications`),
  rồi start và nạp lại dữ liệu demo (phải stop trước).

## Kiểm thử

```bash
pip install -r requirements-dev.txt
python manage.py test-services                         # test riêng: node --test, go test, php tests/run.php, mvn test
python -m pytest tests/unit tests/integration tests/e2e  # 5 tiến trình thật, dữ liệu tạm + schema PostgreSQL tạm
python scripts/smoke_test.py                           # kiểm tra nhanh hệ thống ĐANG chạy
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
| `docs/DEMO.md` | Kịch bản trình diễn 3 vai trò |
| `docs/REQUIREMENTS.md` | Đối chiếu yêu cầu → chức năng → API/UI → test |
| `docs/SOURCE_REVIEW.md`, `docs/MERGE_DECISIONS.md` | Đánh giá các bộ nguồn và quyết định hợp nhất theo từng thành viên |
| `docs/TEST_REPORT.md` | Môi trường, lệnh, kết quả kiểm thử thực tế |
| `docs/PROJECT_SUMMARY.md` | Tóm tắt phục vụ thuyết trình |
| `docs/diagrams/` | Use Case, DFD mức 0/1/2, ERD (PNG/SVG) + `gen_diagrams.py` |
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
| `Cổng đang bị chiếm` | Tắt chương trình dùng cổng 8000–8005 hoặc đổi `*_URL`, `WEB_PORT`, `CORS_ORIGINS` trong `.env` |
| Một service "KHÔNG PHẢN HỒI" | Xem `logs/<service>.log` |
| Bị đưa về trang đăng nhập "phiên hết hạn" | Token hết hạn, đã đăng xuất, bị đổi vai trò hoặc bị khóa: đăng nhập lại |

## Giới hạn còn lại

- SQLite/H2 dạng tệp phù hợp demo một máy; `php -S` là máy chủ phát triển của PHP.
- Không có thanh toán, giao hàng, email/SMS; giờ mở cửa chỉ để hiển thị.
- Đã chạy và kiểm thử trên Linux; Windows (`run.ps1`, `mvnw.cmd`, `taskkill`, PHP/Go trên Windows) chưa chạy trên máy
  Windows thật (xem `docs/TEST_REPORT.md`).
