# Notification Service – Go / Gin / GORM / PostgreSQL (TV4)

Cổng 8004. Nhận sự kiện đơn hàng (nội bộ, chống trùng), thông báo của tôi, đánh dấu đã đọc, admin xem/xóa.
CSDL: PostgreSQL theo `NOTIFICATION_DB_URL` (tạo user/DB: `python manage.py pg-setup` hoặc `docker-compose.postgres.yml`).

```bash
go build -o bin/notification-service .     # Go 1.22+ (Windows: bin/notification-service.exe)
./bin/notification-service                  # đọc .env ở thư mục gốc dự án
NOTIFICATION_TEST_DB_URL=postgres://... go test .
```
Mã: `main.go` (router), `handlers.go`, `store.go` (schema), `auth.go`, `errors.go`, `config.go`.
