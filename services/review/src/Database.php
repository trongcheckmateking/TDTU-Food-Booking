<?php
declare(strict_types=1);

/**
 * PDO SQLite (DATA_DIR/review.db). Bảng REVIEWS (khớp ERD):
 *  - order_id UNIQUE: mỗi đơn tối đa 1 đánh giá, an toàn khi gửi đồng thời.
 *  - user_id, restaurant_id, order_id là tham chiếu logic sang Auth/Restaurant/Order (khác DB, không FK).
 */
const REVIEW_SCHEMA = <<<SQL
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
SQL;

function connectDatabase(): PDO
{
    static $pdo = null;
    if ($pdo !== null) {
        return $pdo;
    }
    $pdo = new PDO('sqlite:' . dataDir() . '/review.db', null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
        PDO::ATTR_STRINGIFY_FETCHES => false,
    ]);
    $pdo->exec('PRAGMA busy_timeout = 10000');
    $pdo->exec('PRAGMA journal_mode = WAL');
    $pdo->exec(REVIEW_SCHEMA);
    return $pdo;
}
