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

| Nhóm | Số test | Nội dung | Cách chạy |
| --- | --- | --- | --- |
| Restaurant – `node --test` | 7 | health/CORS/404, duyệt quán, kiểm tra dữ liệu, quyền, món ẩn/hết, khóa, xóa mềm, báo giá, lỗi Auth (Auth giả) | `npm test` |
| Order – JUnit 5 | 14 | `OrderStatusTest` (của TV3), `JsonTest`, `OrderFlowTest` (Spring Boot thật + H2 + server giả: giỏ, checkout chống trùng, đồng thời, outbox gửi lại) | `mvn test` |
| Notification – `go test` | 4 | người nhận, kiểm tra sự kiện, ánh xạ lỗi, tích hợp PostgreSQL thật | `go test .` |
| Review – `php tests/run.php` | 44 kiểm tra | điều kiện đánh giá, dữ liệu sai, trùng, điểm TB half-up, ẩn/hiện, lỗi Order/Auth | `php tests/run.php` |
| `tests/unit` (Python) | 9 | ánh xạ lỗi REST của Auth, dừng khi thiếu JWT_SECRET, OpenAPI Auth | `pytest tests/unit` |
| `tests/integration` | 61 | **5 tiến trình thật, 5 ngôn ngữ**; lời gọi giữa service đi qua fault proxy giả lập sập/timeout/500/JSON hỏng; DB tạm + schema PostgreSQL tạm | `pytest tests/integration` |
| `tests/e2e` | 3 | khởi động bằng đúng `manage.py start`; luồng đầy đủ, restart, Notification sập rồi tự gửi bù | `pytest tests/e2e` |
| `tests/ui` | 3 | Playwright 3 vai trò trên hệ thống đang chạy, lỗi console/5xx, màn hình 390 px | `pytest tests/ui` |

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

## Chưa kiểm được

| Mục | Lý do | Cách tự kiểm |
| --- | --- | --- |
| `mvn package` / `mvn test` thật, `mvnw` với Maven Central | Maven Central bị chặn trong môi trường kiểm thử | `python manage.py build` rồi `python manage.py test-services` trên máy có Internet |
| Windows thật (PowerShell 5.1, `mvnw.cmd`, `taskkill`, `notification-service.exe`, `php -S` trên Windows) | Môi trường là Linux; đã cross-compile Go cho Windows nhưng chưa chạy | `.\run.ps1 setup`, `pg-setup`, `start`, `seed`, `status`, `stop` |
| macOS | Không có máy macOS | `./run.sh setup && ./run.sh start` |
| Node.js 24, Java 17 đúng phiên bản (đã chạy trên Java 21), Go 1.22, PHP 8.1 | Chỉ có một phiên bản mỗi runtime | Chạy `python manage.py doctor` + test trên máy có phiên bản đó |
| PostgreSQL bằng Docker Compose | Không chạy Docker daemon trong môi trường | `docker compose -f services/notification/docker-compose.postgres.yml --env-file .env up -d` |
| Trình duyệt khác Chromium | Chỉ có Chromium | Làm theo `DEMO.md` |
| Hiệu năng / tải lớn | Ngoài phạm vi; không công bố số đo hiệu năng | – |
