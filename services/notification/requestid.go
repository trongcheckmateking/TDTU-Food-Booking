package main

// X-Request-ID: mã truy vết một yêu cầu xuyên các service.
// requestID() chạy TRƯỚC logger: giữ header hợp lệ hoặc sinh UUID bỏ gạch (32 hex), ghi lại vào c.Request.Header
// (logger và các lời gọi service khác đọc từ đó) và vào response (kể cả lỗi / preflight CORS).

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

const ridHeader = "X-Request-ID"

var ridRe = regexp.MustCompile(`^[A-Za-z0-9._-]{8,128}$`)

func acceptRequestID(raw string) string {
	if ridRe.MatchString(raw) {
		return raw
	}
	return strings.ReplaceAll(uuid.NewString(), "-", "")
}

func requestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := acceptRequestID(c.GetHeader(ridHeader))
		c.Request.Header.Set(ridHeader, rid)
		c.Header(ridHeader, rid)
		c.Next()
	}
}

// accessLog: "<thời điểm> METHOD PATH STATUS <ms>ms rid=<id>" (đọc rid từ p.Request.Header, không dùng p.Keys).
func accessLog(p gin.LogFormatterParams) string {
	return fmt.Sprintf("%s %s %s %d %dms rid=%s\n", p.TimeStamp.Format("2006-01-02T15:04:05Z07:00"), p.Method, p.Path,
		p.StatusCode, p.Latency.Milliseconds(), ridOrDash(p.Request.Header.Get(ridHeader)))
}

// requestIDOf: X-Request-ID hợp lệ của yêu cầu hiện tại, "" nếu không có.
func requestIDOf(c *gin.Context) string {
	if rid := c.Request.Header.Get("X-Request-ID"); ridRe.MatchString(rid) {
		return rid
	}
	return ""
}

// ridOrDash: rid để ghi log ("-" cho luồng chạy nền / không có rid).
func ridOrDash(rid string) string {
	if rid == "" {
		return "-"
	}
	return rid
}
