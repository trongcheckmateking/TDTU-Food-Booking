package main

// Lưu trữ PostgreSQL qua GORM. Bảng NOTIFICATIONS (khớp ERD):
//   UNIQUE(event_key, user_id): Order gửi lại cùng sự kiện (outbox retry) không tạo thông báo trùng.
//   user_id, order_id là tham chiếu logic sang Auth/Order (không đặt khóa ngoại khác DB).
// Bảng EMAIL_LOGS: nhật ký gửi email OTP qua nhà cung cấp (không lưu mã), xem email.go.

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

const schemaSQL = `
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
`

// EmailLog: một lần gửi email qua provider (không có mã OTP).
type EmailLog struct {
	ID                string    `gorm:"type:uuid;primaryKey"`
	UserID            string    `gorm:"type:uuid;not null"`
	ToEmail           string    `gorm:"not null"`
	Template          string    `gorm:"not null"`
	Status            string    `gorm:"not null"`
	ProviderMessageID *string   `gorm:"column:provider_message_id"`
	IdempotencyKey    string    `gorm:"not null"`
	LastError         *string   `gorm:"column:last_error"`
	CreatedAt         time.Time `gorm:"not null"`
	UpdatedAt         time.Time `gorm:"not null"`
}

func (EmailLog) TableName() string { return "email_logs" }

type EmailLogOut struct {
	ID                string  `json:"id"`
	UserID            string  `json:"user_id"`
	ToEmail           string  `json:"to_email"`
	Template          string  `json:"template"`
	Status            string  `json:"status"`
	ProviderMessageID *string `json:"provider_message_id"`
	LastError         *string `json:"last_error"`
	CreatedAt         string  `json:"created_at"`
	UpdatedAt         string  `json:"updated_at"`
}

func toEmailOut(e EmailLog) EmailLogOut {
	return EmailLogOut{ID: e.ID, UserID: e.UserID, ToEmail: e.ToEmail, Template: e.Template, Status: e.Status,
		ProviderMessageID: e.ProviderMessageID, LastError: e.LastError, CreatedAt: isoTime(e.CreatedAt),
		UpdatedAt: isoTime(e.UpdatedAt)}
}

type Notification struct {
	ID        string    `gorm:"type:uuid;primaryKey"`
	UserID    string    `gorm:"type:uuid;not null"`
	OrderID   *string   `gorm:"type:uuid"`
	EventKey  string    `gorm:"not null"`
	Type      string    `gorm:"not null"`
	Message   string    `gorm:"not null"`
	Status    string    `gorm:"not null;default:unread"`
	CreatedAt time.Time `gorm:"not null"`
	ReadAt    *time.Time
}

func (Notification) TableName() string { return "notifications" }

// NotificationOut: định dạng JSON trả về (thời gian UTC dạng 2026-10-05T03:00:00Z).
type NotificationOut struct {
	ID        string  `json:"id"`
	UserID    string  `json:"user_id"`
	OrderID   *string `json:"order_id"`
	Type      string  `json:"type"`
	Message   string  `json:"message"`
	Status    string  `json:"status"`
	CreatedAt string  `json:"created_at"`
	ReadAt    *string `json:"read_at"`
}

func isoTime(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05Z") }

func toOut(n Notification) NotificationOut {
	o := NotificationOut{ID: n.ID, UserID: n.UserID, OrderID: n.OrderID, Type: n.Type, Message: n.Message,
		Status: n.Status, CreatedAt: isoTime(n.CreatedAt)}
	if n.ReadAt != nil {
		s := isoTime(*n.ReadAt)
		o.ReadAt = &s
	}
	return o
}

var schemaRe = regexp.MustCompile(`^[a-z_][a-z0-9_]{0,62}$`)

// withSchema: nếu đặt NOTIFICATION_DB_SCHEMA (dùng khi chạy test tách biệt), tạo schema đó và dùng làm search_path.
func withSchema(dsn string) (string, error) {
	schema := getenv("NOTIFICATION_DB_SCHEMA", "")
	if schema == "" {
		return dsn, nil
	}
	if !schemaRe.MatchString(schema) {
		return "", fmt.Errorf("NOTIFICATION_DB_SCHEMA không hợp lệ: %q", schema)
	}
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if err != nil {
		return "", fmt.Errorf("không kết nối được PostgreSQL: %w", err)
	}
	defer func() {
		if sqlDB, e := db.DB(); e == nil {
			sqlDB.Close()
		}
	}()
	if os.Getenv("NOTIFICATION_DROP_SCHEMA") == "1" {
		return "", db.Exec("DROP SCHEMA IF EXISTS " + schema + " CASCADE").Error
	}
	if err := db.Exec("CREATE SCHEMA IF NOT EXISTS " + schema).Error; err != nil {
		return "", err
	}
	sep := "?"
	if strings.Contains(dsn, "?") {
		sep = "&"
	}
	return dsn + sep + "search_path=" + schema, nil
}

func openDB(dsn string) (*gorm.DB, error) {
	dsn, err := withSchema(dsn)
	if err != nil {
		return nil, err
	}
	if os.Getenv("NOTIFICATION_DROP_SCHEMA") == "1" {
		return nil, nil
	}
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Warn),
		NowFunc: func() time.Time { return time.Now().UTC() }})
	if err != nil {
		return nil, fmt.Errorf("không kết nối được PostgreSQL (kiểm tra NOTIFICATION_DB_URL và PostgreSQL đã chạy): %w", err)
	}
	sqlDB, err := db.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(10)
	sqlDB.SetConnMaxIdleTime(5 * time.Minute)
	if err := db.Exec(schemaSQL).Error; err != nil {
		return nil, fmt.Errorf("lỗi tạo bảng notifications: %w", err)
	}
	return db, nil
}
