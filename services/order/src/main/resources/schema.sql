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

-- Mã nhận món 3 chữ số (sinh viên đọc khi tới quán, như Grab / be): số thứ tự đơn trong ngày (giờ Việt Nam) của từng
-- quán, 001 -> 999 rồi quay vòng. Đơn cũ được cấp mã khi Order Service khởi động.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_code VARCHAR(3);
CREATE TABLE IF NOT EXISTS pickup_counters (
    restaurant_id VARCHAR(36) NOT NULL,
    order_day     VARCHAR(10) NOT NULL,          -- YYYY-MM-DD theo giờ Việt Nam
    last_no       INT NOT NULL,
    PRIMARY KEY (restaurant_id, order_day)
);

-- Thanh toán trước bằng VietQR, tiền chuyển thẳng vào tài khoản của chủ quán (xem model/Payment.java).
-- Đơn có trước khi có thanh toán được coi là đã thanh toán (DEFAULT 'paid'); đơn mới ghi rõ 'unpaid'.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(16) DEFAULT 'paid' NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_bank_bin VARCHAR(6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_bank_name VARCHAR(80);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_account VARCHAR(19);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_holder VARCHAR(60);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_note VARCHAR(30);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_deadline VARCHAR(20);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_claimed_at VARCHAR(20);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_orders_payment ON orders(payment_status, pay_deadline);

-- 2 cách trả tiền (thêm 16/10/2026): transfer = chuyển khoản trước (VietQR), cash = tiền mặt khi nhận món.
-- Đơn có từ trước khi có thanh toán trước là trả tại quán -> mặc định 'cash'; đơn chuyển khoản luôn có pay_bank_bin.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(10) DEFAULT 'cash' NOT NULL;
UPDATE orders SET payment_method='transfer' WHERE payment_method='cash' AND pay_bank_bin IS NOT NULL;
