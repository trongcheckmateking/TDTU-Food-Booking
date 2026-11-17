# Bảng tra lệnh

Mỗi lệnh ghi: **làm gì**, **in ra gì** (ví dụ là kết quả chạy thật), **đọc kết quả thế nào / để làm gì**.
Chạy từ thư mục gốc dự án (thư mục có `manage.py`). Lệnh Docker: xem [`DOCKER.md`](DOCKER.md).

## Cách gõ lệnh

| Hệ điều hành | Gõ | Ví dụ |
| --- | --- | --- |
| Windows (PowerShell) | `.\run.ps1 <lệnh>` | `.\run.ps1 status` |
| Linux / macOS | `./run.sh <lệnh>` | `./run.sh status` |
| Mọi nơi, đã bật `.venv` | `python manage.py <lệnh>` | `python manage.py status` |

`run.ps1` / `run.sh` chỉ là lối tắt: mọi chữ phía sau được chuyển cho `manage.py`. Riêng `setup` và `test` là lệnh của
`run.ps1` / `run.sh` (xem dưới). **Không** gõ lệnh Docker sau `run.ps1`: `.\run.ps1 docker compose ...` báo
`invalid choice: 'docker'`; lệnh Docker gõ thẳng `docker compose ...`.

Mã thoát: lệnh thành công trả `0`, có lỗi trả khác `0` (dùng được trong script / CI). Mọi lệnh tự tạo `.env` nếu chưa có.

## Tóm tắt

| Lệnh | Dùng khi | Ghi / xóa dữ liệu? |
| --- | --- | --- |
| `setup` | Lần đầu cài trên máy (Windows / Linux / macOS) | Tạo `.venv`, `.env`, bản build |
| `init-env` | Tạo `.env` | Tạo `.env` (không ghi đè) |
| `doctor` | Kiểm tra máy đủ phần mềm chưa | Không |
| `build` | Cài thư viện / biên dịch Restaurant, Notification, Order | Tạo bản build |
| `pg-setup` | Tạo user + database PostgreSQL (khi không dùng Docker cho PostgreSQL) | Tạo user/database |
| `init-db` | Tạo bảng cho Auth | Tạo bảng nếu chưa có |
| `start` / `stop` / `status` | Bật / tắt / xem hệ thống | Không |
| `seed` | Nạp dữ liệu demo | Thêm dữ liệu demo |
| `create-admin` | Tạo admin thật | Thêm 1 tài khoản |
| `reset-demo --yes` | Làm sạch trước buổi demo | **XÓA toàn bộ dữ liệu** |
| `backup` / `restore` | Sao lưu / khôi phục | `restore` **thay dữ liệu** |
| `test-services`, `test`, `pytest`, `smoke_test.py` | Kiểm thử | `smoke_test.py` thêm dữ liệu thử |
| `export-openapi` | Cập nhật tài liệu API | Ghi đè `docs/openapi/*.json` |

---

## 1. Cài đặt

### `setup` (chỉ `run.ps1` / `run.sh`)

- **Làm gì:** chạy lần lượt: tạo `.venv` → cài thư viện Python (`requirements.txt`) → `init-env` → `build` → `init-db`
  → `doctor`.
- **In ra:** log cài đặt của pip, npm, go, Maven; cuối cùng là bảng `doctor` và lời nhắc bước tiếp theo
  (tạo PostgreSQL, `start`, `seed`).
- **Đọc kết quả:** nhìn bảng `doctor` ở cuối. Có dòng `THIẾU` thì làm theo gợi ý `->` trên dòng đó rồi chạy lại `doctor`.
  Bước `build` lỗi thì `setup` dừng giữa chừng: đọc dòng `Lệnh thất bại (mã ...)` và lệnh `$ ...` ngay trên nó.

### `init-env`

- **Làm gì:** tạo `.env` từ `.env.example`, sinh ngẫu nhiên `JWT_SECRET` (khóa ký token đăng nhập), `INTERNAL_KEY`
  (khóa để các service gọi nhau), `POSTGRES_PASSWORD`.
- **In ra:**
  ```
  Đã tạo ...\.env (JWT_SECRET, INTERNAL_KEY, mật khẩu PostgreSQL ngẫu nhiên).
  ```
  hoặc, khi đã có `.env`:
  ```
  Đã có .env, giữ nguyên (dùng --force để tạo lại khóa mới).
  ```
- **Để làm gì:** thiếu `.env` thì mọi service dừng ngay khi khởi động với lỗi `Thiếu cấu hình ...`.
- `--force` tạo khóa mới: mọi người phải đăng nhập lại, và nếu PostgreSQL đã tạo với mật khẩu cũ thì phải chạy lại
  `pg-setup` (hoặc tạo lại container PostgreSQL). Chỉ dùng khi lộ `.env`.

### `doctor`

- **Làm gì:** kiểm tra phiên bản Python, Node.js, Java, Go, PHP (+ 3 extension), các bản build, và PostgreSQL có đang
  nghe ở cổng trong `NOTIFICATION_DB_URL` không. Không sửa gì.
- **In ra** (ví dụ thật, PostgreSQL chưa bật):
  ```
    Python (Auth, web)         OK   3.12.6
    Node.js (Restaurant)       OK   v24.16.0
      node_modules             OK   express
    Java (Order)               OK   Java 21
      order-service.jar        OK   services\order\target\order-service.jar
    Go (Notification)          OK   go version go1.27.0 windows/amd64
      notification-service     OK   services\notification\bin\notification-service.exe
    PHP (Review)               OK   8.5.11
      PHP extensions           OK   pdo_sqlite, curl, mbstring
    PostgreSQL (Notification)  THIẾU  127.0.0.1:5432  -> Cài/chạy PostgreSQL 14+ rồi `python manage.py pg-setup` (hoặc docker compose, xem README)
  Có 1 mục cần xử lý.
  ```
- **Đọc kết quả:** dòng thụt vào (`node_modules`, `order-service.jar`, `notification-service`) là **bản build**, thiếu
  thì chạy `build`; dòng không thụt là **phần mềm**, thiếu thì cài. `PostgreSQL THIẾU` thường chỉ là chưa bật
  PostgreSQL / Docker Desktop. Dòng cuối phải là `Mọi thứ sẵn sàng.` thì `start` mới chạy được.
- **Để làm gì:** chạy đầu tiên mỗi khi `start` lỗi hoặc khi cài trên máy mới: biết ngay thiếu gì thay vì đọc log.

### `build` (thêm `--only restaurant,notification,order`, `--force`)

- **Làm gì:** Restaurant: `npm ci` (cài Express); Notification: `go build` ra `bin/notification-service(.exe)`;
  Order: Maven (`mvn`, không có thì dùng `mvnw` đi kèm) đóng gói `target/order-service.jar`.
- **In ra:** từng lệnh đang chạy dạng `  $ npm ci ...  (trong services\restaurant)`, cuối cùng `Build xong.`
  Order đã có jar thì in `Đã có services\order\target\order-service.jar (dùng --force để build lại)` và bỏ qua.
- **Đọc kết quả:** `Lệnh thất bại (mã N).` là lỗi của npm / go / Maven in ngay phía trên. Lần đầu build Order cần Internet
  (Maven tải thư viện).
- **Khi nào chạy lại:** sau khi `git pull` có thay đổi code Java / Go hoặc `package.json`. **Sửa code Java mà không
  `build --only order --force` thì `start` vẫn chạy jar cũ.**

### `pg-setup` (thêm `--admin-user <user>`, mặc định `postgres`)

- **Làm gì:** dùng `psql` tạo user và database PostgreSQL theo `NOTIFICATION_DB_URL` trong `.env` (đặt đúng mật khẩu
  trong `.env`). Không cần nếu chạy PostgreSQL bằng Docker (`docker-compose.postgres.yml`, xem README).
- **In ra:** `Tạo user 'tdtu_food' và database 'tdtu_notification' (psql sẽ hỏi mật khẩu của 'postgres' nếu cần)...`
  rồi `PostgreSQL sẵn sàng cho Notification Service.`
- **Đọc kết quả:** `Không tìm thấy psql` thì lệnh in sẵn câu SQL để tự chạy trong pgAdmin. Sau khi đổi
  `POSTGRES_PASSWORD`, chạy lại để cập nhật mật khẩu user.

### `init-db`

- **Làm gì:** tạo bảng của Auth (`users`, `login_attempts`) nếu chưa có. `setup` và `start` đã tự gọi, thường không cần
  chạy tay.
- **In ra:**
  ```
    schema Auth OK: ...\data\auth.db
    Restaurant, Order, Review, Notification tự tạo bảng khi khởi động (CREATE TABLE IF NOT EXISTS).
  ```
- **Để làm gì:** cho biết tệp CSDL của Auth nằm ở đâu (mở bằng SQLite Viewer khi demo phần CSDL).

---

## 2. Chạy hằng ngày

### `start` (thêm `--timeout <giây>`, mặc định 180)

- **Làm gì:** kiểm tra trước (chưa có tiến trình cũ, cổng 8000–8005 trống, PostgreSQL bật), chạy `init-db`, bật 5 service
  + giao diện ở chế độ nền, ghi PID vào `.run/pids.json`, ghi log vào `logs/<service>.log`, rồi **chờ** đến khi cả 6 trả
  `/health` OK.
- **In ra khi thành công:**
  ```
  Đã khởi động. Giao diện: http://127.0.0.1:8000
    auth          Python/FastAPI         http://127.0.0.1:8001/docs
    restaurant    Node.js/Express        http://127.0.0.1:8002/docs
    ...
  ```
- **Khi bị từ chối** (chưa bật gì, chỉ báo lý do), ví dụ thật:
  ```
  Không kết nối được PostgreSQL cho Notification (127.0.0.1:5432). Xem `python manage.py doctor`.
  ```
  Các lý do khác: `Đang có tiến trình chạy ... Chạy python manage.py stop trước.`;
  `Cổng đang bị chiếm: order:8003 ...`.
- **Khi một service không lên:** in `Không khởi động được: order - xem log trong ...\logs`, kèm **8 dòng cuối log** của
  service đó, rồi tự `stop` các service còn lại. Đọc 8 dòng log đó để biết lỗi (thiếu `.env`, sai mật khẩu PostgreSQL...).

### `status`

- **Làm gì:** gọi `GET /health` của 6 thành phần (health của service có kiểm tra cả kết nối CSDL).
- **In ra** (ví dụ thật khi hệ thống chạy đủ):
  ```
    auth          Python/FastAPI         :8001  OK
    restaurant    Node.js/Express        :8002  OK
    order         Java/Spring Boot       :8003  OK
    notification  Go/Gin + PostgreSQL    :8004  OK
    review        PHP                    :8005  OK
    web           Python (giao diện)     :8000  OK
  ```
- **Đọc kết quả:** `KHÔNG PHẢN HỒI` ở **một** dòng: service đó chết hoặc mất CSDL, xem `logs/<service>.log`.
  **Tất cả** `KHÔNG PHẢN HỒI`: hệ thống chưa chạy, gõ `start`. Mã thoát `0` khi tất cả OK, `1` khi có dòng lỗi.
- **Để làm gì:** kiểm tra nhanh trước khi demo; mở đầu buổi demo để thầy thấy 5 service chạy bằng 5 ngôn ngữ.

### `stop`

- **Làm gì:** tắt đúng các tiến trình mà `start` đã bật (đọc `.run/pids.json`), không đụng chương trình khác. Dữ liệu
  giữ nguyên.
- **In ra:** `Đã dừng: auth, restaurant, order, notification, review, web` hoặc
  `Không có tiến trình nào do manage.py khởi động.`
- **Lưu ý:** service bật tay (`npm start`, `php -S`...) thì `stop` không tắt.

### `seed`

- **Làm gì:** nạp dữ liệu demo **qua REST API** của hệ thống đang chạy (đăng ký, tạo quán, duyệt, đặt đơn, đánh giá...),
  nên cũng là một lần chạy thử cả luồng nghiệp vụ. Riêng admin demo ghi thẳng vào CSDL Auth. Chạy lại không tạo trùng.
- **In ra:** `Đã nạp dữ liệu demo: {...số bản ghi đã tạo...}` và danh sách tài khoản demo.
  Lần chạy lại các con số là `0` (đã có, không tạo trùng).
- **Lỗi thường gặp:** `Các service chưa chạy: ...` → `start` trước.
- **Không chạy** trên máy dùng thật: mật khẩu demo công khai trong README.

### `create-admin` (thêm `--email`, `--name`)

- **Làm gì:** tạo tài khoản admin thật (không có API đăng ký admin). Thiếu tham số thì hỏi; mật khẩu lấy từ biến môi trường
  `ADMIN_PASSWORD` nếu có, không thì hỏi (không hiện khi gõ).
- **In ra:** `Đã tạo admin <email>` hoặc `Email đã tồn tại: <email>` (mã thoát 1). Mật khẩu yếu thì báo lỗi kiểm tra
  dữ liệu (từ 8 ký tự, có chữ và số).

### `reset-demo --yes`

- **Làm gì:** **XÓA** `auth.db`, `restaurant.db`, `review.db`, `order.mv.db` trong `data/` và bảng `notifications`
  trong PostgreSQL, rồi `start` + `seed`.
- **In ra:** `Đã xóa dữ liệu trong ...\data và bảng notifications.`, sau đó kết quả của `start` và `seed`.
- **Bị từ chối khi:** thiếu `--yes` (in cảnh báo `Lệnh này XÓA toàn bộ dữ liệu ...`), hoặc hệ thống đang chạy
  (`Hãy dừng hệ thống ... trước khi reset.`).
- **Để làm gì:** trước buổi demo, để dữ liệu đúng như kịch bản `docs/DEMO.md`. Ảnh tải lên không bị xóa.

---

## 3. Sao lưu và khôi phục

### `backup`

| Lệnh | Làm gì | In ra (ví dụ thật) |
| --- | --- | --- |
| `backup` | Tạo 1 bản `backups/tdtu-backup-<thời điểm UTC>.tar.gz` (5 CSDL + ảnh), xóa bớt bản cũ, giữ `BACKUP_KEEP` bản | `[sao lưu ...] Đã tạo tdtu-backup-....tar.gz (0.4 MB, 18 ảnh quán, ...)` |
| `backup --list` | Liệt kê các bản | `tdtu-backup-20261018-175046Z.tar.gz  0.4 MB` … `7 bản trong ...\backups` |
| `backup --verify <tệp>` | Kiểm tra tệp còn nguyên vẹn (SHA-256 từng tệp bên trong) | `[sao lưu ...] tdtu-backup-20261018-175046Z.tar.gz: hợp lệ (tạo lúc 20261018-175046Z, 18 ảnh quán, 0 ảnh đại diện)` |
| `backup --loop` | Chạy mãi, mỗi `BACKUP_INTERVAL_HOURS` giờ một bản | Mỗi lần một dòng `Đã tạo ...` |

- Chạy được khi hệ thống **đang chạy** (lấy bản sao nhất quán). Tệp chứa dữ liệu cá nhân: không đưa lên Git
  (`backups/` đã bị bỏ qua) hay gửi qua chat.
- Lỗi in dạng `[sao lưu ...] LỖI: ...`. Thiếu `pg_dump` trên máy thì công cụ tự chạy `pg_dump` trong Docker.

### `restore <tệp> --yes`

- **Làm gì:** thay dữ liệu hiện tại bằng dữ liệu trong tệp sao lưu. Dữ liệu đang có **không bị xóa** mà được chuyển sang
  thư mục `truoc-khoi-phuc-<thời điểm>/`.
- **Phải** `stop` trước: còn service chạy thì báo `Các service đang chạy: ...` và không làm gì. Tệp hỏng / bị sửa (sai
  SHA-256) cũng bị từ chối.
- **In ra:** `Khôi phục <tệp> (tạo lúc ...)` rồi `Xong. Dữ liệu cũ nằm trong truoc-khoi-phuc-.../ ...`. Sau đó `start`.

---

## 4. Kiểm thử

### `test-services`

- **Làm gì:** chạy test riêng của từng service bằng công cụ của ngôn ngữ đó: `npm test` (Restaurant),
  `php tests/run.php` (Review), `go test` (Notification, cần PostgreSQL), `mvn test` (Order).
- **In ra:** log test của từng service, cuối cùng:
  ```
  Kết quả test từng service:
    restaurant (node --test)       ĐẠT
    review (php tests/run.php)     ĐẠT
    notification (go test)         ĐẠT
    order (mvn test)               BỎ QUA (thiếu công cụ)
  ```
- **Đọc kết quả:** `LỖI` = có test trượt, kéo lên đọc log của service đó. `BỎ QUA` = máy thiếu công cụ.
  **Lưu ý:** lệnh này chỉ tìm `mvn`, không dùng `mvnw`; máy không cài Maven thì Order luôn `BỎ QUA` (tự chạy
  `.\mvnw.cmd test` trong `services/order`). Notification `LỖI` khi PostgreSQL chưa bật.

### `test` (`run.ps1` / `run.sh`) và `pytest`

```powershell
.\run.ps1 test                                            # = cài requirements-dev + test-services + pytest dòng dưới
python -m pytest tests/unit tests/integration tests/e2e   # cần đã build và có PostgreSQL
python -m pytest tests/ui                                 # Playwright; cần hệ thống đang chạy + dữ liệu demo
```

- **Làm gì:** test tích hợp / E2E tự bật 5 tiến trình thật với dữ liệu tạm và schema PostgreSQL tạm, **không đụng**
  `data/`.
- **In ra:** dấu `.` cho mỗi test đạt, `F` trượt, `s` bỏ qua; dòng cuối dạng `N passed, M skipped in ...s`.
  Có `failed` thì pytest in chi tiết test trượt (tên test, dòng assert, giá trị thực tế).

### `scripts/smoke_test.py`

```powershell
python scripts/smoke_test.py
```

- **Làm gì:** kiểm tra nhanh hệ thống **đang chạy** bằng một luồng đầy đủ qua API: health 5 service → đăng ký chủ quán và
  sinh viên → tạo quán → admin duyệt → thêm giỏ → checkout → chuyển khoản / xác nhận tiền → thông báo → đánh giá → token
  sai bị từ chối. Cần admin demo (`seed`) hoặc đặt `SMOKE_ADMIN_EMAIL`, `SMOKE_ADMIN_PASSWORD`.
- **In ra:** mỗi bước một dòng `  ĐẠT  checkout` hoặc `  LỖI  checkout  (chi tiết lỗi từ API)`, cuối cùng
  `KẾT QUẢ: ĐẠT` hoặc `KẾT QUẢ: 2 bước lỗi`.
- **Để làm gì:** chạy sau `start` / sau khi sửa code để chắc cả luồng còn chạy, trước khi demo. **Tạo thêm** tài khoản
  và quán thử (có hậu tố ngẫu nhiên) vào dữ liệu đang dùng: chạy trước `reset-demo` nếu cần dữ liệu demo sạch.

---

## 5. Tài liệu API

### `export-openapi`

- **Làm gì:** chép OpenAPI của 5 service vào `docs/openapi/<service>.json` (ghi đè).
- **In ra:** đường dẫn 5 tệp đã ghi.
- **Khi nào chạy:** sau khi thêm / sửa endpoint, để tài liệu và bộ Postman khớp code; commit 5 tệp này cùng thay đổi.

---

## 6. Chạy riêng một service (khi phát triển)

| Service | Lệnh (trong thư mục service) | Ghi chú |
| --- | --- | --- |
| Restaurant | `npm ci`, `npm start`, `npm test` | [`services/restaurant/README.md`](../services/restaurant/README.md) |
| Order | `.\mvnw.cmd -DskipTests package`, `.\mvnw.cmd test` | [`services/order/README.md`](../services/order/README.md) |
| Notification | `go build -o bin/notification-service.exe .`, `.\bin\notification-service.exe` | [`services/notification/README.md`](../services/notification/README.md) |
| Review | `php -S 127.0.0.1:8005 public/index.php`, `php tests/run.php` | [`services/review/README.md`](../services/review/README.md) |

Mỗi service tự đọc `.env` ở thư mục gốc. `status` vẫn thấy service bật kiểu này (nó chỉ gọi `/health` theo cổng), nhưng
`stop` không tắt được: dừng bằng `Ctrl + C` trong cửa sổ đang chạy service.
