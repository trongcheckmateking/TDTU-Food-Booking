# Cơ sở dữ liệu

Mỗi service sở hữu một CSDL riêng, đúng công nghệ của ngôn ngữ đó; bảng được tạo bằng `CREATE TABLE IF NOT EXISTS`
khi service khởi động (chạy lại an toàn). Phần SQL bên dưới được trích tự động từ mã nguồn của từng service.

| CSDL | Service (ngôn ngữ) | Thư viện truy cập | Bảng | Nguồn schema |
| --- | --- | --- | --- | --- |
| `DATA_DIR/auth.db` (SQLite) | Auth (Python) | `sqlite3` | `users` | `services/auth/models.py` |
| `DATA_DIR/restaurant.db` (SQLite) | Restaurant (Node.js) | `node:sqlite` | `restaurants`, `menu_items` | `services/restaurant/src/db.js` |
| `DATA_DIR/order.mv.db` (H2 dạng tệp) | Order (Java) | Spring `JdbcTemplate` + HikariCP | `carts`, `cart_items`, `orders`, `order_items`, `notification_outbox` | `services/order/src/main/resources/schema.sql` |
| PostgreSQL `tdtu_notification` | Notification (Go) | GORM + pgx | `notifications` | `services/notification/store.go` |
| `DATA_DIR/review.db` (SQLite) | Review (PHP) | PDO | `reviews` | `services/review/src/Database.php` |

## Khóa ngoại thật và tham chiếu logic

- **Khóa ngoại thật (cùng DB):** `menu_items.restaurant_id → restaurants.id`, `cart_items.cart_id → carts.id`,
  `order_items.order_id → orders.id`, `notification_outbox.order_id → orders.id`.
- **Tham chiếu logic xuyên service (không có FK, không thể ràng buộc ở DB):** mọi `user_id`, `owner_id`,
  `restaurant_owner_id` (→ Auth), `restaurant_id`, `item_id` trong Order/Review (→ Restaurant), `order_id` trong
  Notification/Review (→ Order). Tính đúng đắn được bảo đảm bằng API: Order báo giá qua Restaurant trước khi ghi,
  Review xác minh đơn qua Order, Notification nhận ID từ sự kiện của Order.
- ERD (`docs/diagrams/erd/`) vẽ FK thật bằng nét liền, tham chiếu logic bằng nét đứt.

## Chính sách giữ lịch sử

- Không xóa cứng người dùng (khóa thay cho xóa), quán và món (xóa mềm `deleted_at`), đánh giá (ẩn `status=hidden`).
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
| `reviews.order_id UNIQUE`, `CHECK rating 1–5`, `CHECK length(comment) ≤ 1000` | 1 đơn 1 đánh giá, kể cả gửi đồng thời |
| `CHECK` trên mọi cột trạng thái | Không ghi trạng thái lạ |

## Máy trạng thái

- Đơn: `pending → confirmed → completed`; `pending → cancelled`; `confirmed → cancelled`. `completed`, `cancelled` là trạng thái cuối.
- Quán: `pending →(admin duyệt) active ↔(chủ quán) closed`; `* →(admin) locked →(admin) active`.
- Outbox: `pending → sending → sent` hoặc `→ failed → sending → …` (tối đa 10 lần).

## Dữ liệu demo

`python manage.py seed` (hệ thống phải đang chạy) nạp dữ liệu **qua REST API** của 5 service, nên dữ liệu demo đi qua
đúng nghiệp vụ (đăng ký, duyệt quán, giỏ, checkout, đổi trạng thái, đánh giá, outbox → thông báo): 1 admin, 2 chủ quán,
3 sinh viên (1 bị khóa), 4 quán (active, active, pending, closed), 10 món (có món hết, món ẩn), 6 đơn ở đủ 4 trạng thái,
2 đánh giá và các thông báo sinh ra từ sự kiện đơn. Chạy lại không tạo trùng. ID là UUID ngẫu nhiên.
`python manage.py reset-demo --yes` **xóa** các tệp CSDL trong `DATA_DIR` và bảng `notifications` rồi start + seed lại.
Test tự động dùng thư mục dữ liệu tạm và schema PostgreSQL tạm riêng, không đụng dữ liệu thật.

## Thay đổi schema sau này

Dự án chưa dùng công cụ migration. Khi đổi schema: thêm lệnh `ALTER TABLE` có kiểm tra (idempotent) vào phần tạo
bảng của service tương ứng, hoặc với dữ liệu demo chạy `reset-demo`.

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
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
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
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','sold_out','hidden')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_menu_restaurant ON menu_items(restaurant_id);
```

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

