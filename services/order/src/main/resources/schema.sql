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
