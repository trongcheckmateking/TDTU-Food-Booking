# Review Service – PHP (TV5)

Cổng 8005. Đánh giá đơn đã hoàn thành, điểm trung bình, kiểm duyệt. CSDL: SQLite `DATA_DIR/review.db` qua PDO.

```bash
php -S 127.0.0.1:8005 public/index.php    # PHP 8.1+ với pdo_sqlite, curl, mbstring; đọc .env ở thư mục gốc
php tests/run.php                          # Auth/Order giả (tests/upstream.php)
```
Mã: `public/index.php` (router), `src/Reviews.php`, `src/Call_Auth_Order.php`, `src/Http.php`, `src/Database.php`.
