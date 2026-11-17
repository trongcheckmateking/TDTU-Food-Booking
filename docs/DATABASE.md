# Cơ sở dữ liệu

Mỗi service sở hữu một CSDL riêng, đúng công nghệ của ngôn ngữ đó; bảng được tạo bằng `CREATE TABLE IF NOT EXISTS`
khi service khởi động (chạy lại an toàn). Phần SQL bên dưới được trích tự động từ mã nguồn của từng service.

| CSDL | Service (ngôn ngữ) | Thư viện truy cập | Bảng | Nguồn schema |
| --- | --- | --- | --- | --- |
| `DATA_DIR/auth.db` (SQLite) | Auth (Python) | `sqlite3` | `users`, `login_attempts`, `otp_codes` | `services/auth/models.py` |
| `DATA_DIR/restaurant.db` (SQLite) | Restaurant (Node.js) | `node:sqlite` | `restaurants`, `menu_items`, `menu_updates` | `services/restaurant/src/db.js` |
| `DATA_DIR/order.mv.db` (H2 dạng tệp) | Order (Java) | Spring `JdbcTemplate` + HikariCP | `carts`, `cart_items`, `orders`, `order_items`, `notification_outbox`, `pickup_counters` | `services/order/src/main/resources/schema.sql` |
| PostgreSQL `tdtu_notification` | Notification (Go) | GORM + pgx | `notifications`, `email_logs` | `services/notification/store.go` |
| `DATA_DIR/review.db` (SQLite) | Review (PHP) | PDO | `reviews` | `services/review/src/Database.php` |

## Khóa ngoại thật và tham chiếu logic

- **Khóa ngoại thật (cùng DB):** `otp_codes.user_id → users.id` (`ON DELETE CASCADE`), `menu_items.restaurant_id → restaurants.id`, `cart_items.cart_id → carts.id`,
  `order_items.order_id → orders.id`, `notification_outbox.order_id → orders.id`.
- **Tham chiếu logic xuyên service (không có FK, không thể ràng buộc ở DB):** mọi `user_id`, `owner_id`,
  `restaurant_owner_id` (→ Auth), `restaurant_id`, `item_id` trong Order/Review (→ Restaurant), `order_id` trong
  Notification/Review (→ Order), `email_logs.user_id` (→ Auth). Tính đúng đắn được bảo đảm bằng API: Order báo giá qua Restaurant trước khi ghi,
  Review xác minh đơn qua Order, Notification nhận ID từ sự kiện của Order.
- ERD (`docs/diagrams/erd/`) vẽ FK thật bằng nét liền, tham chiếu logic bằng nét đứt.

## Chính sách giữ lịch sử

- Không xóa cứng người dùng (khóa thay cho xóa), quán và món (xóa mềm `deleted_at`), đánh giá (ẩn `status=hidden`).
- Yêu cầu xóa dữ liệu cá nhân (Chính sách quyền riêng tư, mục 8): admin gọi `POST /api/users/{id}/erase`, Auth khóa tài
  khoản rồi gọi `/internal/users/{id}/erase` của Order (tên → "Người dùng đã xóa", xóa số điện thoại, chỗ nhận, ghi chú;
  xóa giỏ), Restaurant (xóa mềm mọi quán của chủ quán, xóa ảnh), Review (ẩn danh tên người viết), Notification (xóa
  thông báo và nhật ký email `email_logs`, vì có địa chỉ email), cuối cùng ẩn danh họ tên, email, số điện thoại trong
  `users`, xóa mọi mã `otp_codes` của tài khoản và ghi `erased_at`. Số tiền, món, số sao giữ
  nguyên nên thống kê không đổi. Order từ chối khi còn đơn `pending`/`confirmed`.
- Sao lưu: `scripts/backup.py` lấy bản sao nhất quán của cả 5 cơ sở dữ liệu khi hệ thống đang chạy (API backup của
  SQLite, `BACKUP TO` của H2 qua `GET /internal/backup` của Order, `pg_dump`), kèm ảnh quán (`uploads/` của Restaurant)
  và ảnh đại diện (`avatars/` của Auth); xem `docs/DEPLOY.md`.
- Đơn lưu ảnh chụp `customer_name`, `restaurant_name`, `restaurant_owner_id`, `item_name`, `price`, `line_total`
  tại thời điểm đặt: đổi giá, đổi tên, xóa món/quán sau đó không làm thay đổi hoặc hỏng đơn cũ, và chủ quán vẫn xử lý
  được đơn mà không cần gọi Restaurant.
- Tiền là số nguyên VND (`INTEGER` / `BIGINT`); `total_price = Σ price × quantity` tính ở server từ giá Restaurant trả về.

## Ràng buộc quan trọng

| Ràng buộc | Mục đích |
| --- | --- |
| `users.email UNIQUE` (lưu chữ thường) | Không trùng email khác hoa/thường |
| `carts.user_id UNIQUE`, `cart_items UNIQUE(cart_id,item_id)` | Mỗi sinh viên 1 giỏ, mỗi món 1 dòng |
| `orders UNIQUE(user_id, idempotency_key)` | Chống tạo đơn trùng khi bấm lặp/thử lại |
| `notification_outbox.event_key UNIQUE` | Mỗi sự kiện của đơn chỉ ghi 1 lần |
| `notifications UNIQUE(event_key, user_id)` | Gửi lại sự kiện không nhân đôi thông báo |
| `otp_codes.code_hash` = HMAC-SHA256(JWT_SECRET, "otp:<id>:<mã>") | Không lưu mã OTP; lộ DB cũng không biết mã |
| `email_logs.idempotency_key UNIQUE` (`otp-<otp_id>`) | Auth gửi lại cùng mã không gửi thư lần 2 |
| `email_logs.provider_message_id UNIQUE` | Webhook của nhà cung cấp cập nhật đúng một bản ghi |
| `reviews.order_id UNIQUE`, `CHECK rating 1–5`, `CHECK length(comment) ≤ 1000` | 1 đơn 1 đánh giá, kể cả gửi đồng thời |
| `CHECK` trên mọi cột trạng thái | Không ghi trạng thái lạ |

## Máy trạng thái

- Đơn: `pending → confirmed → completed`; `pending → cancelled`; `confirmed → cancelled`. `completed`, `cancelled` là trạng thái cuối.
  Chỉ đơn đã thanh toán mới được xác nhận / hoàn thành.
- Thanh toán của đơn (`payment_status`): `unpaid →(sinh viên báo đã chuyển) claimed →(quán: đã nhận tiền) paid`;
  `claimed →(quán: chưa nhận được tiền) failed` (đơn hủy); `unpaid → void` (hủy) / `expired` (quá `PAYMENT_TIMEOUT_MINUTES`,
  `cancelled_by = he_thong`); hủy đơn `paid` (hoặc admin hủy đơn `claimed`) → `refund_due →(quán: đã hoàn tiền) refunded`.
  Báo cáo, thống kê chỉ tính đơn `paid / refund_due / refunded` (đơn đặt thành công).
- Quán: `pending →(admin duyệt) active ↔(chủ quán) closed`; `* →(admin) locked →(admin) active`.
- Outbox: `pending → sending → sent` hoặc `→ failed → sending → …` (tối đa 10 lần). API trả một đơn có thêm
  `notification_status` tính từ mọi dòng outbox của đơn: `none` (chưa có sự kiện) / `failed` / `pending` / `sent`.
- Mã OTP (`otp_codes`): tạo lúc đăng ký / gửi lại (mã cũ bị vô hiệu: điền `used_at`); mỗi lần nhập sai cộng
  `attempts` TRƯỚC khi so mã (UPDATE có điều kiện trong `BEGIN IMMEDIATE`), đủ `OTP_MAX_ATTEMPTS` thì khóa; đúng mã →
  `used_at` + `users.email_verified_at`; quá `expires_at` → hết hạn.
- Nhật ký email (`email_logs`): `sending → sent` (nhà cung cấp nhận) `→ delivered / failed` (webhook có ký HMAC); lỗi gọi
  nhà cung cấp → `failed` (gửi lại trên chính dòng đó); `sending` quá 30 giây coi như bỏ dở, được gửi lại.

## Dữ liệu demo

`python manage.py seed` (hệ thống phải đang chạy) nạp dữ liệu **qua REST API** của 5 service, nên dữ liệu demo đi qua
đúng nghiệp vụ (đăng ký, duyệt quán, giỏ, checkout, đổi trạng thái, đánh giá, outbox → thông báo): 1 admin, 2 chủ quán,
3 sinh viên (1 bị khóa), 4 quán (active, active, pending, closed), 10 món (có món hết, món ẩn), 7 đơn ở đủ 4 trạng thái
(đơn đi qua bước thanh toán; 1 đơn đang chờ quán xác nhận tiền, 1 đơn đã trả bị admin hủy đang chờ hoàn tiền), chủ quán
demo có tài khoản nhận tiền `TAI KHOAN DEMO` (số giả),
2 đánh giá và các thông báo sinh ra từ sự kiện đơn. Chạy lại không tạo trùng. ID là UUID ngẫu nhiên.
`python manage.py reset-demo --yes` **xóa** các tệp CSDL trong `DATA_DIR` và bảng `notifications` rồi start + seed lại.
Test tự động dùng thư mục dữ liệu tạm và schema PostgreSQL tạm riêng, không đụng dữ liệu thật.

## Thay đổi schema sau này

Dự án chưa dùng công cụ migration. Khi đổi schema: thêm lệnh `ALTER TABLE` có kiểm tra (idempotent) vào phần tạo
bảng của service tương ứng, hoặc với dữ liệu demo chạy `reset-demo`. Ví dụ đã làm:

- Auth thêm `users.email_verified_at`: `_migrate()` chạy `ALTER TABLE` và `UPDATE users SET email_verified_at =
  created_at` trong CÙNG giao dịch, chỉ đúng lúc vừa thêm cột (tài khoản có từ trước coi như đã xác nhận); chạy ở mỗi
  lần khởi động thì người chưa nhập mã OTP cũng bị coi là đã xác nhận. Không tạo index trên cột mới trong `SCHEMA`
  (DB cũ chạy `SCHEMA` trước `_migrate()`).
- Order sửa sự kiện đơn tiền mặt: bản cũ ghi `order_created_cash`, Notification không nhận tên này (422) nên chủ quán
  không được báo. Cuối `schema.sql` có `UPDATE` đổi các dòng outbox chưa gửi sang `order_created` và cho gửi lại ngay
  (xem khối SQL của Order bên dưới); chạy lại nhiều lần không sao.

## Schema (trích từ mã)

### Auth – auth.db (SQLite)

```sql
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,            -- luôn lưu chữ thường
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('sinh_vien','chu_quan','admin')),
    phone         TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','locked')),
    token_version INTEGER NOT NULL DEFAULT 0,      -- tăng khi khóa/đổi vai trò/đăng xuất -> token cũ hết hiệu lực
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    terms_accepted_at TEXT,                        -- lúc đồng ý Điều khoản + Chính sách quyền riêng tư (bằng chứng đồng ý)
    erased_at     TEXT,                            -- lúc xóa dữ liệu cá nhân theo yêu cầu (tên/email/SĐT đã ẩn danh)
    avatar_url    TEXT,                            -- /avatars/<tên ngẫu nhiên>.jpg|png|webp (tệp trong DATA_DIR/avatars)
    -- tài khoản nhận tiền của chủ quán: sinh viên chuyển khoản trước bằng mã VietQR tạo từ 3 cột này
    bank_bin      TEXT,                            -- mã ngân hàng 6 số của Napas (banks.py)
    bank_account  TEXT,                            -- số tài khoản 6-19 chữ số
    bank_holder   TEXT,                            -- tên chủ tài khoản, in hoa không dấu
    email_verified_at TEXT                         -- lúc xác nhận email bằng mã OTP (NULL = chưa xác nhận)
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
-- Mã OTP xác nhận email: KHÔNG lưu mã, chỉ lưu HMAC-SHA256(JWT_SECRET, "otp:<id>:<mã>").
-- Mỗi user tối đa 1 mã còn hiệu lực (used_at IS NULL): gửi mã mới thì mã cũ bị vô hiệu (điền used_at).
CREATE TABLE IF NOT EXISTS otp_codes (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose    TEXT NOT NULL CHECK (purpose IN ('verify_email')),
    code_hash  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,              -- số lần nhập sai (đủ OTP_MAX_ATTEMPTS thì khóa mã)
    used_at    TEXT,                                    -- đã xác nhận thành công, hoặc bị thay bằng mã mới
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_user ON otp_codes(user_id, purpose, created_at);
-- Đăng nhập sai liên tiếp theo cặp (email, IP): quá ngưỡng thì khóa tạm, chống dò mật khẩu
CREATE TABLE IF NOT EXISTS login_attempts (
    key          TEXT PRIMARY KEY,                 -- email|ip
    fails        INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    locked_until TEXT
);
```

### Restaurant – restaurant.db (SQLite)

```sql
CREATE TABLE IF NOT EXISTS restaurants (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL,                 -- users.id (Auth Service) - tham chiếu logic, không FK
    name          TEXT NOT NULL,
    address       TEXT NOT NULL,
    description   TEXT,
    open_time     TEXT,
    close_time    TEXT,
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','active','closed','locked')),
    status_reason TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_restaurants_owner ON restaurants(owner_id);
CREATE INDEX IF NOT EXISTS idx_restaurants_status ON restaurants(status);
CREATE TABLE IF NOT EXISTS menu_items (
    id            TEXT PRIMARY KEY,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),   -- FK thật (cùng DB)
    name          TEXT NOT NULL,
    price         INTEGER NOT NULL CHECK (price >= 0),        -- VND, số nguyên
    description   TEXT,
    category      TEXT,                                       -- danh mục: Món chính, Đồ uống...
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','sold_out','hidden')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_menu_restaurant ON menu_items(restaurant_id);
-- Bảng tin món mới: mỗi món một tin mới nhất. new = món mới, price = đổi giá, back = bán lại món đã hết/ẩn
CREATE TABLE IF NOT EXISTS menu_updates (
    item_id       TEXT PRIMARY KEY REFERENCES menu_items(id),
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    kind          TEXT NOT NULL CHECK (kind IN ('new','price','back')),
    old_price     INTEGER,
    new_price     INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_menu_updates_created ON menu_updates(created_at);
```

`menu_items.category` (tùy chọn, tối đa 50 ký tự) nhóm món theo danh mục ở thực đơn; DB cũ được tự thêm cột khi khởi
động (`ALTER TABLE ... ADD COLUMN`). Ảnh quán / món (`image_url`) là đường dẫn `/uploads/<uuid>.jpg|png|webp` tới tệp
trong `DATA_DIR/uploads/` (Restaurant tự phục vụ) hoặc link http(s); tệp ảnh cũ được xóa khi không còn quán/món nào dùng.

`menu_updates` giữ **một dòng mỗi món** (khóa chính `item_id`), ghi trong cùng giao dịch với lệnh thêm/sửa món, chỉ khi
món ở trạng thái `available`: lần đầu bán → `new`; đang bán đổi giá → `price` (kèm giá cũ); bán lại sau ít nhất 24 giờ
hết/ẩn → `back`. Tin chưa quá 30 phút chỉ được cập nhật giá, không bị đẩy lên lại (chống spam). Admin duyệt quán →
các món của quán lên bảng tin từ lúc duyệt. `GET /api/menu-updates` lấy tin trong 14 ngày, món đang bán của quán `active`,
mỗi quán tối đa 3 tin. DB có từ trước được nạp các món đang bán làm tin `new` (`INSERT OR IGNORE`, chạy lại không trùng).

### Order – order.mv.db (H2)

```sql
-- Order Service (H2): CARTS, CART_ITEMS, ORDERS, ORDER_ITEMS, NOTIFICATION_OUTBOX (khớp ERD).
-- user_id, restaurant_id, item_id, restaurant_owner_id là tham chiếu logic sang Auth/Restaurant (khác DB, không FK).
-- Đơn lưu ảnh chụp tên quán, tên món, đơn giá lúc đặt -> lịch sử đọc được khi menu/quán đổi hoặc bị xóa.
-- Tiền VND là số nguyên (BIGINT). Thời gian lưu dạng chuỗi ISO UTC: 2026-10-05T03:00:00Z.

CREATE TABLE IF NOT EXISTS carts (
    id            VARCHAR(36) PRIMARY KEY,
    user_id       VARCHAR(36) NOT NULL UNIQUE,
    restaurant_id VARCHAR(36),
    updated_at    VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    id        VARCHAR(36) PRIMARY KEY,
    cart_id   VARCHAR(36) NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    item_id   VARCHAR(36) NOT NULL,
    quantity  INT NOT NULL CHECK (quantity BETWEEN 1 AND 50),
    added_at  VARCHAR(20) NOT NULL,
    CONSTRAINT uq_cart_item UNIQUE (cart_id, item_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id                  VARCHAR(36) PRIMARY KEY,
    user_id             VARCHAR(36) NOT NULL,
    customer_name       VARCHAR(200) NOT NULL,
    customer_phone      VARCHAR(30),
    restaurant_id       VARCHAR(36) NOT NULL,
    restaurant_name     VARCHAR(200) NOT NULL,
    restaurant_owner_id VARCHAR(36) NOT NULL,
    status              VARCHAR(12) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','confirmed','completed','cancelled')),
    total_price         BIGINT NOT NULL CHECK (total_price >= 0),
    delivery_address    VARCHAR(300) NOT NULL,
    note                VARCHAR(500),
    cancel_reason       VARCHAR(300),
    cancelled_by        VARCHAR(12),
    idempotency_key     VARCHAR(100),
    created_at          VARCHAR(20) NOT NULL,
    updated_at          VARCHAR(20) NOT NULL,
    CONSTRAINT uq_order_idempotency UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_restaurant ON orders(restaurant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_owner ON orders(restaurant_owner_id, created_at);

CREATE TABLE IF NOT EXISTS order_items (
    id         VARCHAR(36) PRIMARY KEY,
    order_id   VARCHAR(36) NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id    VARCHAR(36) NOT NULL,
    item_name  VARCHAR(200) NOT NULL,
    quantity   INT NOT NULL CHECK (quantity > 0),
    price      BIGINT NOT NULL CHECK (price >= 0),
    line_total BIGINT NOT NULL CHECK (line_total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id              VARCHAR(36) PRIMARY KEY,
    event_key       VARCHAR(120) NOT NULL UNIQUE,
    order_id        VARCHAR(36) NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    payload         VARCHAR(2000) NOT NULL,
    status          VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sending','sent','failed')),
    attempts        INT NOT NULL DEFAULT 0,
    last_error      VARCHAR(300),
    next_attempt_at VARCHAR(20) NOT NULL,
    created_at      VARCHAR(20) NOT NULL,
    sent_at         VARCHAR(20)
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON notification_outbox(status, next_attempt_at);
```

Mã nhận món 3 chữ số (thêm 16/10/2026, `schema.sql` của Order):

```sql
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_code VARCHAR(3);   -- 001-999, sinh viên đọc khi tới quán
CREATE TABLE IF NOT EXISTS pickup_counters (                         -- số thứ tự đơn trong ngày của từng quán
    restaurant_id VARCHAR(36) NOT NULL,
    order_day     VARCHAR(10) NOT NULL,                              -- YYYY-MM-DD theo giờ Việt Nam
    last_no       INT NOT NULL,
    PRIMARY KEY (restaurant_id, order_day)
);
```

Hai cách trả tiền (`payment_method`) và sửa sự kiện đơn tiền mặt (cuối `schema.sql`, chạy mỗi lần Order khởi động):

```sql
-- 2 cách trả tiền (thêm 16/10/2026): transfer = chuyển khoản trước (VietQR), cash = tiền mặt khi nhận món.
-- Đơn có từ trước khi có thanh toán trước là trả tại quán -> mặc định 'cash'; đơn chuyển khoản luôn có pay_bank_bin.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(10) DEFAULT 'cash' NOT NULL;
UPDATE orders SET payment_method='transfer' WHERE payment_method='cash' AND pay_bank_bin IS NOT NULL;

-- Sửa lỗi đơn tiền mặt (17/11/2026): bản cũ ghi sự kiện "order_created_cash", Notification không có tên này nên trả
-- 422 và chủ quán không được báo. Đổi các sự kiện chưa gửi được sang "order_created" và cho gửi lại ngay. Chạy lại
-- nhiều lần không sao: sau lần đầu không còn dòng nào khớp điều kiện.
UPDATE notification_outbox
   SET payload = REPLACE(payload, 'order_created_cash', 'order_created'),
       event_key = REPLACE(event_key, ':order_created_cash', ':order_created'),
       status = 'pending', attempts = 0, last_error = NULL, next_attempt_at = created_at
 WHERE event_key LIKE '%:order_created_cash' AND status <> 'sent';
```

Thanh toán trước bằng VietQR (thêm 16/10/2026, `schema.sql` của Order). Tài khoản nhận tiền của chủ quán được chụp vào
đơn lúc đặt (lấy từ Auth `GET /internal/users/{id}/payout`), nên chủ quán đổi tài khoản không ảnh hưởng đơn cũ:

```sql
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(16) DEFAULT 'paid' NOT NULL;   -- đơn cũ coi như đã trả
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_bank_bin VARCHAR(6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_bank_name VARCHAR(80);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_account VARCHAR(19);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_holder VARCHAR(60);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_note VARCHAR(30);        -- nội dung chuyển khoản: TDTU <mã 3 số> <4 ký tự mã đơn>
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_deadline VARCHAR(20);    -- quá hạn mà chưa báo chuyển -> hệ thống hủy
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_claimed_at VARCHAR(20);  -- lúc sinh viên báo đã chuyển
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at VARCHAR(20);         -- lúc chủ quán xác nhận đã nhận tiền
CREATE INDEX IF NOT EXISTS idx_orders_payment ON orders(payment_status, pay_deadline);
```

### Notification – PostgreSQL

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY,
    user_id    UUID NOT NULL,
    order_id   UUID,
    event_key  VARCHAR(120) NOT NULL,
    type       VARCHAR(40)  NOT NULL,
    message    VARCHAR(500) NOT NULL,
    status     VARCHAR(10)  NOT NULL DEFAULT 'unread' CHECK (status IN ('unread','read')),
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    read_at    TIMESTAMPTZ,
    CONSTRAINT uq_notifications_event_user UNIQUE (event_key, user_id)
);
CREATE INDEX IF NOT EXISTS idx_noti_user ON notifications(user_id, status, created_at);

-- Nhật ký gửi email qua nhà cung cấp (mã OTP xác nhận email). KHÔNG lưu mã OTP hay nội dung thư.
--   idempotency_key UNIQUE: Auth gửi lại cùng mã (otp-<otp_id>) không gửi thư lần 2.
--   provider_message_id UNIQUE: webhook của provider tìm đúng một bản ghi.
--   sending -> sent (provider nhận) -> delivered / failed (webhook); lỗi gọi provider -> failed (được gửi lại).
CREATE TABLE IF NOT EXISTS email_logs (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    to_email            VARCHAR(254) NOT NULL,
    template            VARCHAR(30)  NOT NULL,
    status              VARCHAR(10)  NOT NULL CHECK (status IN ('sending','sent','delivered','failed')),
    provider_message_id VARCHAR(120) UNIQUE,
    idempotency_key     VARCHAR(120) NOT NULL UNIQUE,
    last_error          VARCHAR(300),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_email_logs_user ON email_logs(user_id);
```

### Review – review.db (SQLite)

```sql
CREATE TABLE IF NOT EXISTS reviews (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    reviewer_name   TEXT NOT NULL,
    restaurant_id   TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    order_id        TEXT NOT NULL UNIQUE,
    rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT CHECK (comment IS NULL OR length(comment) <= 1000),
    status          TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden')),
    hidden_reason   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant ON reviews(restaurant_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);
```

