package main

// X-Request-ID: mã truy vết một yêu cầu xuyên các service.

import (
	"regexp"

	"github.com/gin-gonic/gin"
)

var ridRe = regexp.MustCompile(`^[A-Za-z0-9._-]{8,128}$`)

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
