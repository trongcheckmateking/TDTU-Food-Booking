# Báo cáo kiểm thử

Ngày chạy: 07/10/2026. Mọi kết quả dưới đây là kết quả thực tế của các lệnh được liệt kê; không có số liệu ước lượng.

## Môi trường

| Mục | Giá trị |
| --- | --- |
| Hệ điều hành | Linux 6.18 (x86_64), container |
| Python (Auth, web, test) | 3.13.16 (thư mục phát triển); 3.11.17 (`.venv` mới, cài sạch từ ZIP) |
| Node.js (Restaurant) | 22.22.0, Express 5.1.0 (`npm ci` từ `package-lock.json`) |
| Java (Order) | OpenJDK 21.0.12 chạy jar build với `--release`/`java.version` 17, Spring Boot 3.5.6, H2 2.3.232 |
| Go (Notification) | 1.24.7, Gin 1.10.1, GORM 1.25.12, pgx 5.5.5 |
| PHP (Review) | 8.3.6 CLI (`pdo_sqlite`, `curl`, `mbstring`) |
| PostgreSQL | 16 (cục bộ) |
| Trình duyệt | Chromium qua Playwright 1.56 (headless) |
| Khác | newman 6, PowerShell 7.4.6 cho Linux, Graphviz `dot` |

### Giới hạn mạng của môi trường kiểm thử và cách xử lý (ghi rõ để không hiểu nhầm)

- **Maven Central bị chặn.** Thư viện Spring Boot 3.5.6/H2 được lấy từ thư mục `~/.m2` trên máy của người dùng (sao chép,
  chỉ đọc). Thiếu `maven-surefire-plugin` và `maven-jar-plugin` nên **`mvn package` / `mvn test` không chạy được ở đây**.
  Thay vào đó: `mvn -o compile/test-compile` (thật), đóng gói `order-service.jar` bằng chính `Repackager` của
  `spring-boot-loader-tools` 3.5.6 (cùng cơ chế với `spring-boot-maven-plugin`), và chạy JUnit 5 bằng JUnit Platform
  Launcher 1.12.2 (biên dịch từ mã nguồn chính thức). Jar đó là jar được 5 tiến trình test dùng. Trên máy có Internet,
  `python manage.py build` chạy `mvn -DskipTests package` thông thường (chưa chạy được ở đây).
- `mvnw` (Maven Wrapper 3.3.2, script chính thức của Apache): đã chạy thật với kho Maven được phục vụ cục bộ
  (`MVNW_REPOURL`) — tải, giải nén và gọi Maven thành công; chưa chạy với repo.maven.apache.org thật. `mvnw.cmd` chưa chạy.
- `proxy.golang.org` và các domain `gorm.io`, `golang.org/x` bị chặn: build Go dùng `GOPROXY=direct` và các dòng
  `replace` trỏ về mirror GitHub chính thức (đã ghi trong `go.mod`). Đã kiểm tra `go build` cho linux/amd64,
  windows/amd64, darwin/arm64 với `-mod=readonly` (go.sum đủ).

## Bộ test tự động

Số test theo lần chạy mới nhất (16/10/2026, mục S1–S7 bên dưới).

| Nhóm | Số test | Nội dung | Cách chạy |
| --- | --- | --- | --- |
| Restaurant – `node --test` | 12 | health/CORS/404, duyệt quán, kiểm tra dữ liệu, quyền, món ẩn/hết, khóa, xóa mềm, báo giá, lỗi Auth (Auth giả) | `npm test` |
| Order – JUnit 5 | 20 | `OrderStatusTest` (của TV3), `JsonTest`, `OrderFlowTest` (Spring Boot thật + H2 + server giả: giỏ, checkout chống trùng, đồng thời, outbox gửi lại) | `mvn test` |
| Notification – `go test` | 5 | người nhận, kiểm tra sự kiện, ánh xạ lỗi, tích hợp PostgreSQL thật | `go test .` |
| Review – `php tests/run.php` | 50 kiểm tra | điều kiện đánh giá, dữ liệu sai, trùng, điểm TB half-up, ẩn/hiện, lỗi Order/Auth | `php tests/run.php` |
| `tests/unit` (Python) | 28 | ánh xạ lỗi REST của Auth, dừng khi thiếu JWT_SECRET, OpenAPI Auth | `pytest tests/unit` |
| `tests/integration` | 67 | **5 tiến trình thật, 5 ngôn ngữ**; lời gọi giữa service đi qua fault proxy giả lập sập/timeout/500/JSON hỏng; DB tạm + schema PostgreSQL tạm | `pytest tests/integration` |
| `tests/e2e` | 3 | khởi động bằng đúng `manage.py start`; luồng đầy đủ, restart, Notification sập rồi tự gửi bù | `pytest tests/e2e` |
| `tests/ui` | 4 | Playwright 3 vai trò trên hệ thống đang chạy, lỗi console/5xx, màn hình 390 px | `pytest tests/ui` |

Nội dung chính của test liên service (tên đầy đủ trong `REQUIREMENTS.md`):

- **Hợp đồng chung ở 5 ngôn ngữ** (`test_contract.py`): `/docs`, `/redoc`, `/openapi.json` có Bearer, `/health`, CORS chỉ
  cho origin cấu hình, 404 JSON; lỗi 422 cùng dạng `{detail, code, errors[{field,message}]}` và "JSON gửi lên không hợp lệ";
  401 `UNAUTHORIZED`/`TOKEN_INVALID`; Auth sập/chậm/500/JSON hỏng → cùng 503/502 ở Node, Java, Go, PHP; API nội bộ
  từ chối thiếu/sai khóa và token người dùng; Node/Java/Go dừng khi thiếu `INTERNAL_KEY`, PHP trả 500 `CONFIG_ERROR`.
- **Luồng xuyên suốt:** Python → Node → Java → Go → PHP: đăng ký, tạo quán, duyệt, menu, giỏ, checkout (Idempotency-Key),
  thông báo, xác nhận, hoàn thành, đánh giá, điểm TB, thống kê.
- **Bảo mật và dữ liệu sai:** token sai/hết hạn/thiếu claim/sai issuer/`alg=none`; tài khoản bị khóa bị chặn ở cả 5 service
  (kể cả khóa thẳng trong DB: Node/Java/Go/PHP chuyển tiếp đúng 403 `ACCOUNT_LOCKED`); quyền chủ quán/sinh viên trên đối tượng;
  giá `1.5`, `"1000"`, `true`, `1e309`; trường giả mạo `owner_id`, `restaurant_id`.
- **Đồng thời:** 4 checkout cùng key → 1 đơn (Java, `SELECT … FOR UPDATE`); 3 checkout không key → 1 đơn; 4 đổi trạng thái →
  1 thành công; 5 đánh giá cùng đơn → 1 thành công (PHP + SQLite UNIQUE); 2 admin khóa nhau → luôn còn ≥ 1 admin.
- **Chịu lỗi:** Notification (Go) sập → đơn vẫn tạo, outbox `failed`, gửi lại không nhân đôi; Restaurant sập/JSON hỏng khi
  checkout → 503/502, giỏ giữ nguyên.

## Kết quả

| # | Lệnh | Môi trường | Kết quả |
| --- | --- | --- | --- |
| 1 | `npm test` (Restaurant) | dev + bản giải nén sạch | **7/7 đạt** |
| 2 | JUnit (Order) qua JUnit Platform Launcher | dev + bản giải nén sạch | **14/14 đạt** |
| 3 | `go test -count=1 .` với PostgreSQL thật | dev + bản giải nén sạch | **4/4 đạt** (gồm test tích hợp DB) |
| 4 | `php tests/run.php` | dev + bản giải nén sạch | **44 đạt, 0 lỗi** |
| 5 | `python manage.py test-services` | bản giải nén sạch | Restaurant, Review, Notification **ĐẠT**; Order **LỖI vì `mvn` không tải được plugin** (Maven Central bị chặn, xem trên) — JUnit đã chạy theo cách #2 |
| 6 | `pytest tests/unit tests/integration` | dev, Python 3.13 | **70 passed** (sau khi sửa 1 test dùng email cố định) |
| 7 | `pytest tests/e2e` | dev | **3 passed** |
| 8 | Giải nén ZIP vào thư mục sạch → `.venv` Python 3.11 → `init-env` → `build` (npm ci, go build) → jar Order (xem trên) → `pg-setup` → `doctor` | sạch | `doctor`: mọi mục OK |
| 9 | `manage.py reset-demo --yes` → `status` | sạch | start 6 tiến trình, seed qua API: 6 user, 4 quán, 10 món, 6 đơn, 2 đánh giá; status 6/6 OK |
| 10 | `python scripts/smoke_test.py` | sạch, hệ thống đang chạy | **ĐẠT** (17 bước) |
| 11 | `pytest tests/ui` (2 lần liên tiếp) | sạch, hệ thống đang chạy | **3 passed** mỗi lần |
| 12 | `newman run … --folder "0. Luồng demo"` | sạch, dữ liệu seed | 16 request, **21/21 assertion đạt** |
| 13 | `pytest tests/unit tests/integration tests/e2e` | sạch, Python 3.11 | **73 passed** (179 s) |
| 14 | `pwsh -File run.ps1 doctor / start / status / stop` | sạch, PowerShell 7.4.6 trên Linux | đều thành công; `run.sh status` sau stop trả mã 1 |
| 15 | `python docs/diagrams/gen_diagrams.py` | Graphviz | Sinh lại sơ đồ (thêm ngôn ngữ/CSDL của từng service) |

ZIP cuối được giải nén lại vào thư mục sạch và chạy lại: setup → build → start → seed → smoke → UI (xem phản hồi bàn giao).

## Lỗi phát hiện và đã sửa trong quá trình làm bản đa ngôn ngữ

| Lỗi | Phát hiện bởi | Sửa |
| --- | --- | --- |
| Order (Spring) trả 500 cho đường dẫn không tồn tại (`NoHandlerFoundException`) | Chạy thử luồng | Bắt thêm ngoại lệ này → 404 `NOT_FOUND` |
| `pg-setup` in mật khẩu PostgreSQL ra màn hình | Đọc output | Che mật khẩu (`***`) khi in lệnh |
| Thứ tự khóa `field/message` trong lỗi 422 của Java không cố định | Đọc output | Dùng `LinkedHashMap` |
| `go mod vendor` cần cả module test của thư viện (45 MB) | Thử đóng gói | Không vendor; giữ `go.sum` đầy đủ, kiểm tra build 3 hệ điều hành |
| Giao diện hiện "Giờ mở cửa: ? – ?" với quán chưa nhập giờ | Ảnh chụp màn hình | Hiển thị "chưa cập nhật" |

Các lỗi của bản trước (SQLite đa luồng, CORS khi 500, TDZ JavaScript, `run.ps1`…) đã sửa ở bản hợp nhất trước và vẫn được
các test trên bao phủ.

## Chạy lại trên Windows 11 thật (14/10/2026)

Sau khi thêm bảng tin món mới, mã QR và giao diện mới. Mọi số liệu là kết quả thực tế của lệnh.

| Mục | Giá trị |
| --- | --- |
| Hệ điều hành | Windows 11 Pro 10.0.26200 |
| Runtime | Python 3.12.6, Node.js 24.16.0, Java 21, Go 1.27.0, PHP 8.5.11 |
| PostgreSQL | 16.15 bằng Docker Desktop (`docker-compose.postgres.yml`) |
| Trình duyệt | Chromium headless qua Playwright 1.56 |

| # | Lệnh | Kết quả |
| --- | --- | --- |
| W1 | `python manage.py doctor` | mọi mục OK (sau khi bật Docker Desktop cho PostgreSQL) |
| W2 | `python manage.py start` / `stop` / `status` | 6 tiến trình chạy, dừng đúng |
| W3 | `npm test` (Restaurant) | **9/9 đạt** (thêm 2 test bảng tin món mới) |
| W4 | `mvnw.cmd test` (Order, Maven Central thật) | **14/14 đạt** – lần đầu chạy được `mvnw` với Maven Central |
| W5 | `go test -count=1 .` (Notification, PostgreSQL thật) | **ĐẠT** |
| W6 | `php tests/run.php` (Review) | **44 đạt, 0 lỗi**; PHP 8.5 in cảnh báo `curl_close()` đã lỗi thời (không ảnh hưởng kết quả, xem dưới) |
| W7 | `pytest tests/unit tests/integration tests/e2e` | **77 passed** (197 s); 8 cảnh báo `UnicodeDecodeError` cp1252 ở luồng đọc output của test e2e (xem dưới) |
| W8 | `pytest tests/ui` | **3 passed** (chạy nhiều lần) |
| W9 | `python scripts/smoke_test.py` | **ĐẠT** |
| W10 | Ảnh chụp giao diện 1366 px và 390 px: trang giới thiệu, sinh viên, chi tiết quán, chủ quán, admin, áp phích QR | không lỗi console, không tràn ngang |

Chạy lại sau khi làm giao diện chủ quán (15/10/2026, cùng máy Windows 11):

| Lệnh | Kết quả |
| --- | --- |
| `npm test` (Restaurant) | **11/11 đạt** (thêm: tải ảnh, kiểm tra định dạng / dung lượng / quyền, dọn ảnh mồ côi, danh mục món, nâng cấp DB cũ, ảnh trong thư mục có dấu chấm) |
| `mvnw.cmd test` (Order) | **16/16 đạt** (thêm: báo cáo chủ quán, ranh giới ngày theo giờ Việt Nam) |
| `go test`, `php tests/run.php` | **ĐẠT** |
| `pytest tests/unit tests/integration tests/e2e` | **77 passed** |
| `pytest tests/ui` | **3 passed** (luồng chủ quán mới: nhận đơn trên thẻ, báo hoàn thành, tổng quan, đăng ký quán kèm ảnh bìa, thêm món có ảnh và danh mục, sửa giá tại chỗ, báo hết món) |
| `scripts/smoke_test.py` | **ĐẠT** |

Chạy lại sau khi làm lại giao diện admin (15/10/2026):

| Lệnh | Kết quả |
| --- | --- |
| `npm test` (Restaurant) | **11/11 đạt** (thêm lọc quán theo `owner_id`) |
| `mvnw.cmd test` (Order) | **17/17 đạt** (thêm `baoCaoAdminChiChoAdmin`) |
| `pytest tests/unit tests/integration` | **74 passed** |
| `pytest tests/e2e` | **3 passed** (một lần chạy trước bị quá thời gian vì máy ngủ giữa chừng; chạy lại đạt) |
| `pytest tests/ui` | **3 passed** (bảng điều khiển có 3 biểu đồ vòng, menu trái, duyệt quán, ẩn đánh giá, khóa tài khoản) |
| Kiểm tra tay bằng trình duyệt | gõ tìm nhanh không bị kết quả cũ đè; Tab giữ trong bảng chi tiết; chuyển trang đóng bảng chi tiết; menu điện thoại 320 px không tràn, focus đúng khi mở / đóng |

Ghi chú Windows:
- `manage.py test-services` báo Order "BỎ QUA" khi máy không có `mvn` trong PATH; chạy `services\order\mvnw.cmd test` thay thế.
- PHP 8.5: `curl_close()` không còn tác dụng từ PHP 8.0 và bị đánh dấu lỗi thời ở 8.5 (`services/review/src/Call_Auth_Order.php`,
  `tests/run.php`). Review đặt `display_errors=0` nên phản hồi JSON không bị ảnh hưởng, chỉ log có cảnh báo; có thể xóa dòng
  `curl_close` (TV5) để log sạch.
- Test e2e đọc output tiếng Việt của `manage.py` bằng bảng mã mặc định của Windows (cp1252) nên in cảnh báo; thêm
  `encoding="utf-8"` cho `subprocess.run` trong `tests/e2e/test_system_e2e.py` để hết cảnh báo.

## Bước 2 – chuẩn bị chạy thử kín (16/10/2026, Windows 11, Docker Desktop 29.8)

Thêm: chống dò mật khẩu, mật khẩu 8+ ký tự có chữ và số, CSP + header bảo mật, trang Điều khoản / Quyền riêng tư và ô
đồng ý khi đăng ký, xóa dữ liệu cá nhân theo yêu cầu (Auth điều phối 4 service), sao lưu / khôi phục 5 CSDL, Docker cho
5 service + web, gateway Nginx HTTPS, container sao lưu. Mọi số liệu là kết quả thực tế của lệnh.

| # | Lệnh | Kết quả |
| --- | --- | --- |
| S1 | `npm test` (Restaurant) | **12/12 đạt** (thêm: xóa dữ liệu chủ quán gỡ quán + ảnh, gọi lại an toàn) |
| S2 | `mvnw.cmd test` (Order) | **20/20 đạt** (thêm `InternalOpsTest`: sao lưu nóng H2 rồi mở bản sao kiểm tra dữ liệu, dọn bản tạm bỏ ngang, xóa dữ liệu cá nhân + chặn khi còn đơn) |
| S3 | `go test -count=1 .` (Notification, PostgreSQL thật) | **5/5 đạt** (thêm `TestIntegrationEraseUser`) |
| S4 | `php tests/run.php` (Review) | **50 đạt, 0 lỗi** (thêm 6 kiểm tra xóa dữ liệu; hết cảnh báo `curl_close()` trong test) |
| S5 | `pytest tests/unit` | **28 passed** (thêm: header bảo mật + CSP, trang không có script nhúng, 10 test sao lưu / khôi phục) |
| S6 | `pytest tests/integration tests/e2e` | **70 passed** (198 s); thêm khóa đăng nhập (tuần tự và 30 yêu cầu song song), 4 test xóa dữ liệu trên 5 service thật (kể cả service sập giữa chừng, tự xóa lại sau khi khôi phục bản sao lưu cũ); hết cảnh báo cp1252 |
| S7 | `pytest tests/ui` trên `manage.py start` | **4 passed** (đăng ký phải tick đồng ý, trang pháp lý trên màn hình 390 px, admin xóa dữ liệu phải gõ lại email, không lỗi CSP trong console) |
| S8 | `scripts/smoke_test.py` | **ĐẠT** |
| S9 | Diễn tập khôi phục (`manage.py backup` → ghi thêm tài khoản + đơn → `stop` → `restore --yes` → `start`) | số tài khoản / quán / đơn / thông báo / đánh giá trở về đúng lúc sao lưu; tài khoản tạo sau không đăng nhập được; dữ liệu cũ nằm trong `truoc-khoi-phuc-*`. `pg_dump` / `pg_restore` chạy bằng Docker vì máy không cài PostgreSQL client |
| D1 | `docker compose build` | 8 image: auth 212 MB, web 213 MB, restaurant 252 MB, order 333 MB, notification 32 MB, review (Apache) 721 MB, backup 474 MB, gateway 103 MB |
| D2 | `docker compose up -d --wait` | 9 container healthy; container sao lưu tự tạo bản đầu tiên; gateway tự tạo chứng chỉ tự ký |
| D3 | Thử gateway bằng curl | HTTP → 301 HTTPS; 5 service qua `/svc/*` 200; `/internal` (kể cả `INTERNAL`, `//internal`, `%69nternal`) → 404; `;x=1`, `/;/internal`, `%3B` → 400; `/docs`, `/openapi.json` → 404; HSTS, `X-Request-ID`, CSP `connect-src 'self'`, `img-src 'self' data: blob:` |
| D4 | `smoke_test.py` qua `https://localhost:8443/svc/...` (kiểm tra chứng chỉ) | **ĐẠT** 17 bước (Bearer token qua Apache của Review, các service gọi nhau trong mạng Docker) |
| D5 | `pytest tests/ui` qua gateway (`UI_BASE_URL=https://localhost:8443`) | **4 passed**, 0 yêu cầu bị 429 |
| D6 | Đăng nhập sai 6 lần qua gateway | 401 ×5 rồi 429 `Retry-After: 900`; khóa ghi theo IP người dùng (172.20.0.1), không theo IP gateway (172.20.0.10) |
| D7 | Diễn tập khôi phục trong Docker (`backup create` → `verify` → ghi thêm → `stop` 5 service → `restore` thiếu `--yes` bị từ chối → `restore --yes` → `start`) | số liệu trở về đúng; tệp khôi phục thuộc uid 10001 của service; bản sao lưu mới quyền `-rw-------`; `erasures.log` được chép sang thư mục sao lưu |

Lỗi phát hiện và đã sửa trong bước 2:

| Lỗi | Phát hiện bởi | Sửa |
| --- | --- | --- |
| `"accept_terms": "true"` (chuỗi) vẫn được nhận | Test đăng ký | `StrictBool` |
| `manage.py create-admin` hỏng sau khi form đăng ký bắt buộc đồng ý điều khoản | Đọc lại luồng tạo admin | `create_admin` truyền `accept_terms=True`, ghi thời điểm đồng ý; thêm CLI `python -m services.auth.admin_tools` cho Docker |
| Ngưỡng giới hạn tần suất ban đầu của gateway (30 yêu cầu/giây/IP) chặn cả 4 trình duyệt test | UI test qua gateway: 13 yêu cầu 429 | Nâng ngưỡng (cả ký túc xá có thể chung 1 IP), bỏ giới hạn cho trang tĩnh |
| `docker compose run` tự bật lại service đã dừng nên lệnh khôi phục từ chối | Viết hướng dẫn | Dùng `run --no-deps` |
| Rà soát bảo mật (agent security-reviewer): đoán mật khẩu song song vượt ngưỡng khóa | Agent | Giữ chỗ lần thử trong giao dịch ghi trước khi kiểm tra mật khẩu; test 30 yêu cầu song song |
| Rà soát: khôi phục bản sao lưu cũ làm dữ liệu đã xóa "sống lại" | Agent | `erasures.log` ngoài `auth.db` + chép sang thư mục sao lưu; Auth tự xóa lại khi khởi động |
| Rà soát: bản sao lưu ai trên máy cũng đọc được; container sao lưu nhận cả `JWT_SECRET` | Agent | `umask 077`, quyền 600; container sao lưu chỉ nhận `INTERNAL_KEY` + chuỗi kết nối DB |
| Rà soát: lách chặn `/internal` bằng `;x=1`; tên ảnh lạ trong manifest; bản tạm H2 có thể đầy `/tmp` | Agent | Chặn `;` ở gateway, so tiền tố; kiểm tra tên ảnh; khóa tạo bản sao + dọn bản tạm cũ |
| Rà soát: ảnh do chủ quán trỏ tới máy chủ lạ làm lộ IP sinh viên | Agent | CSP `img-src` chỉ cho ảnh nội bộ, giao diện không tải ảnh ngoài |
| IPv6 đổi địa chỉ trong dải để né khóa đăng nhập | Agent | Khóa theo dải /64 |

Còn lại (đã ghi trong `docs/DEPLOY.md`): chưa chạy trên máy chủ Linux thật với tên miền + Let's Encrypt; trên Docker Desktop
mọi người dùng chung một IP với gateway; `Call_Auth_Order.php` (TV5) vẫn gọi `curl_close()` (chỉ PHP 8.5 cảnh báo;
image Docker dùng PHP 8.4).

## Nền quán và trang Profile (16/10/2026)

Thêm: nền tượng trưng cho quán chưa có ảnh bìa, 8 nền có sẵn cho chủ quán (vẽ thành ảnh rồi tải lên); trang Profile
kiểu app be với ảnh đại diện (Auth lưu `DATA_DIR/avatars/`), đổi mật khẩu, số liệu nhanh theo vai trò.

| Lệnh | Kết quả |
| --- | --- |
| `pytest tests/unit` | **28 passed** (CSP cho ảnh đại diện ở Auth, sao lưu gồm `avatars/`) |
| `pytest tests/integration tests/e2e` | **72 passed** (213 s); thêm ảnh đại diện: chặn tệp không phải ảnh, quá 1 MB, xóa ảnh cũ khi đổi, chặn `..%2F`; đổi mật khẩu thu hồi phiên khác; xóa dữ liệu gỡ cả ảnh đại diện |
| `pytest tests/ui` (local và qua gateway Docker) | **4 passed** mỗi nơi: chủ quán chọn nền "Bún, phở, mì" → admin duyệt → sinh viên thấy ảnh `/uploads/...`, mọi thẻ quán có ảnh bìa; Profile: đổi ảnh đại diện hiện ở thanh trên, gỡ ảnh, không lỗi console |
| `docker compose run --rm backup create` | bản sao lưu ghi số ảnh quán và ảnh đại diện |

## Mã nhận món 3 số, hướng dẫn, admin không hủy đơn, app điện thoại (16/10/2026)

| Lệnh | Kết quả |
| --- | --- |
| `mvnw.cmd test` (Order) | **22/22 đạt** (thêm: mã 3 số tăng dần theo quán, 2 đơn đặt cùng lúc không trùng mã, quay về 001 sau 999, cấp mã cho đơn cũ, thông báo dùng mã 3 số; sinh viên không tự hủy, admin hủy được) |
| `go test`, `npm test`, `php tests/run.php` | **ĐẠT** (5/5, 12/12, 50/50) |
| `pytest tests/unit` | **29 passed** (thêm: manifest PWA đúng MIME, biểu tượng có thật, `sw.js` không bị lưu đệm cũ) |
| `pytest tests/integration tests/e2e` | **73 passed** (thêm: sinh viên không tự hủy đơn đã đặt, admin hủy được đơn chờ / đang làm và cả hai bên được báo, mã 3 số tăng dần và có trong thông báo; e2e đọc mã 3 số trong thông báo) |
| `pytest tests/ui` (local và qua gateway Docker) | **5 passed** mỗi nơi: sinh viên không có nút Hủy, admin hủy đơn kèm lý do, mặc định "Tự tới quán lấy", thẻ đơn có mã thật to, chủ quán gõ mã ra đúng đơn, tài khoản mới đi hết 4 bước hướng dẫn và không hiện lại, thanh "Xem giỏ hàng" trên điện thoại, PWA (manifest, biểu tượng, service worker) |
| `scripts/smoke_test.py` | **ĐẠT** |

Lỗi phát hiện và đã sửa: nút "Xóa giỏ" làm Chrome báo yêu cầu bị hủy (`net::ERR_ABORTED`) vì phản hồi 204 không được đọc
→ `api()` luôn đọc hết phản hồi; thông báo nổi che thanh giỏ hàng / nút đặt hàng trên điện thoại → chuyển lên trên;
test e2e / tích hợp dựa vào thứ tự các đơn tạo cùng một giây → so theo mã.

Ghi chú: chứng chỉ tự ký (gateway chạy thử) không cho trình duyệt đăng ký service worker, nên chỉ cài app được khi có chứng
chỉ thật (Let's Encrypt) hoặc mở bằng `localhost` / `127.0.0.1`.

## Thanh toán trước bằng VietQR vào tài khoản của chủ quán (16/10/2026)

| Lệnh | Kết quả |
| --- | --- |
| `mvnw.cmd test` (Order) | **23/23 đạt** (thêm `thanhToanTruocQuaVietQrVaoTaiKhoanQuan`: chụp tài khoản + nội dung chuyển khoản, chưa báo quán khi chưa trả, tab Chờ tiền / Mới, claim → confirm, sai vai trò 403, đơn đã báo chuyển thì quán không hủy ngang, sinh viên bỏ đơn chưa trả, quán từ chối khi không thấy tiền, admin hủy đơn đã báo chuyển → chờ hoàn tiền, quá hạn → hệ thống hủy, chủ quán chưa khai báo tài khoản → 409 và giỏ giữ nguyên, lọc `payment_status` cho admin; hoàn tiền; xóa dữ liệu chặn khi còn đơn chờ hoàn tiền) |
| `go test` (Notification, có PostgreSQL) | **6/6 đạt** (thêm nội dung thông báo `payment_claimed`, `payment_confirmed`, `payment_refunded`) |
| `npm test`, `php tests/run.php` | **ĐẠT** (12/12, 50/50) |
| `pytest tests/unit` | **32 passed** (thêm: CRC16 khớp giá trị kiểm tra chuẩn `0x29B1`, chuỗi VietQR đúng tag 38/53/54/58/62/63, ảnh SVG/PNG, chặn tham số sai) |
| `pytest tests/integration tests/e2e` | **80 passed** (77 + 3; thêm: đăng ký chủ quán bắt buộc tài khoản nhận tiền, chuẩn hóa tên chủ tài khoản, đổi tài khoản cần mật khẩu, API nội bộ cần khóa; luồng thanh toán trên 5 service thật; hoàn tiền; chủ quán chưa khai báo không nhận được đơn; seed đi qua bước thanh toán; e2e: luồng chính có ảnh VietQR, claim, confirm, Notification sập lúc thanh toán vẫn gửi bù đúng 1 lần) |
| `pytest tests/ui` | **5 passed**: trang thanh toán có mã QR + cảnh báo tài khoản DEMO, Tôi đã chuyển khoản, danh sách đơn tự cập nhật khi quán nhận tiền, tab Chờ tiền của chủ quán, Đã nhận tiền, admin hủy đơn đã trả → quán Đã hoàn tiền → sinh viên thấy đã hoàn, hướng dẫn có bước Chuyển khoản trước |
| `scripts/smoke_test.py` | **ĐẠT** (thêm 3 bước thanh toán) |

Lỗi phát hiện và đã sửa trong lúc làm: sinh viên đã báo chuyển mà quán không phản hồi thì không ai hủy được đơn → admin
hủy được, đơn chuyển sang chờ hoàn tiền; danh sách "Đơn của tôi" không tự cập nhật khi quán xác nhận tiền → tự làm mới
khi còn đơn ở bước thanh toán; số tài khoản bị xuống dòng trên điện thoại → nút Chép chỉ còn biểu tượng.

## Chưa kiểm được

| Mục | Lý do | Cách tự kiểm |
| --- | --- | --- |
| `mvn package` / `mvn test` thật, `mvnw` với Maven Central | Maven Central bị chặn trong môi trường kiểm thử | `python manage.py build` rồi `python manage.py test-services` trên máy có Internet |
| `run.ps1 setup` / `pg-setup` trên PowerShell 5.1 | Trên Windows 11 mới chạy `manage.py` trực tiếp (mục W1–W10 ở trên); `mvnw.cmd`, `taskkill`, `notification-service.exe`, `php -S` đã chạy | `.\run.ps1 setup`, `pg-setup`, `start`, `seed`, `status`, `stop` |
| macOS | Không có máy macOS | `./run.sh setup && ./run.sh start` |
| Node.js 24, Java 17 đúng phiên bản (đã chạy trên Java 21), Go 1.22, PHP 8.1 | Chỉ có một phiên bản mỗi runtime | Chạy `python manage.py doctor` + test trên máy có phiên bản đó |
| Docker trên máy chủ Linux thật, tên miền + Let's Encrypt | Mới chạy trên Docker Desktop (Windows) với chứng chỉ tự ký | Làm theo `docs/DEPLOY.md` mục 3–4, chạy `smoke_test.py` qua tên miền |
| Trình duyệt khác Chromium | Chỉ có Chromium | Làm theo `DEMO.md` |
| Hiệu năng / tải lớn | Ngoài phạm vi; không công bố số đo hiệu năng | – |
| Quét mã VietQR bằng app ngân hàng thật | Môi trường kiểm thử không có app ngân hàng; đã kiểm chuỗi theo chuẩn EMVCo và CRC | Chủ quán khai báo tài khoản thật, quét mã trên trang thanh toán bằng app ngân hàng, kiểm tra app điền đúng tên chủ tài khoản, số tiền, nội dung |
