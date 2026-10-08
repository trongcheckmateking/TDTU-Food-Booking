package main

// Định dạng lỗi thống nhất: {"detail": "...", "code": "..."}; lỗi 422 thêm "errors": [{field, message}].

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ApiError struct {
	Status  int
	Code    string
	Message string
	Errors  []FieldError
}

type FieldError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func (e *ApiError) Error() string { return e.Code + ": " + e.Message }

func apiErr(status int, code, msg string) *ApiError {
	return &ApiError{Status: status, Code: code, Message: msg}
}

func validationErr(errs []FieldError) *ApiError {
	return &ApiError{Status: 422, Code: "VALIDATION_ERROR", Message: "Dữ liệu không hợp lệ", Errors: errs}
}

func writeErr(c *gin.Context, err error) {
	e, ok := err.(*ApiError)
	if !ok {
		log.Printf("[notification] Lỗi không mong đợi tại %s %s: %v", c.Request.Method, c.Request.URL.Path, err)
		e = apiErr(500, "INTERNAL_ERROR", "Có lỗi nội bộ, vui lòng thử lại sau")
	}
	body := gin.H{"detail": e.Message, "code": e.Code}
	if e.Errors != nil {
		body["errors"] = e.Errors
	}
	c.AbortWithStatusJSON(e.Status, body)
}

// ---------------------------------------------------------------- gọi service khác
// Ánh xạ: không kết nối/quá giờ -> 503 UPSTREAM_UNAVAILABLE; 5xx -> 502 UPSTREAM_ERROR;
// body không phải JSON object/list -> 502 UPSTREAM_BAD_RESPONSE; 4xx khác -> 502 UPSTREAM_REJECTED.
func callService(method, url, service, token string, allow ...int) (int, map[string]any, error) {
	req, err := http.NewRequest(method, url, nil)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Accept", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	client := &http.Client{Timeout: httpTimeout()}
	resp, err := client.Do(req)
	if err != nil {
		var te interface{ Timeout() bool }
		if errors.As(err, &te) && te.Timeout() {
			return 0, nil, apiErr(503, "UPSTREAM_UNAVAILABLE", service+" phản hồi quá thời gian chờ")
		}
		return 0, nil, apiErr(503, "UPSTREAM_UNAVAILABLE", "Không kết nối được "+service)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return 0, nil, apiErr(503, "UPSTREAM_UNAVAILABLE", "Không đọc được phản hồi của "+service)
	}
	allowed := resp.StatusCode >= 200 && resp.StatusCode < 300
	for _, a := range allow {
		allowed = allowed || resp.StatusCode == a
	}
	if allowed {
		var body map[string]any
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.UseNumber()
		if err := dec.Decode(&body); err != nil || body == nil {
			return 0, nil, apiErr(502, "UPSTREAM_BAD_RESPONSE", service+" trả dữ liệu không phải JSON hợp lệ")
		}
		return resp.StatusCode, body, nil
	}
	if resp.StatusCode >= 500 {
		log.Printf("[notification] %s trả %d cho %s %s", service, resp.StatusCode, method, url)
		return 0, nil, apiErr(502, "UPSTREAM_ERROR", service+" đang gặp lỗi, vui lòng thử lại")
	}
	return 0, nil, apiErr(502, "UPSTREAM_REJECTED", fmt.Sprintf("%s từ chối yêu cầu nội bộ (HTTP %d)", service, resp.StatusCode))
}
