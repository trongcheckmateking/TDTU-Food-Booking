package main

// Gửi email qua nhà cung cấp bên thứ ba (Unit 20): Auth gọi POST /internal/notifications/email để gửi mã OTP;
// Notification ghi email_logs, gọi provider (MockMail), và nhận webhook kết quả giao thư có ký HMAC.
//
//   - Idempotency: idempotency_key UNIQUE trong email_logs. Gửi lại khi đã sent/delivered -> 200 replay, không gọi
//     provider; đang sending (< 30 giây) -> 409; failed hoặc sending quá 30 giây -> giành lại bằng UPDATE có điều kiện
//     rồi gửi lại trên CHÍNH dòng đó (cùng id). Gọi mạng nằm NGOÀI transaction.
//   - Mã OTP chỉ đi trong body gửi provider: không ghi vào DB, không ghi log (log chỉ có user_id, message_id,
//     email đã che).

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/mail"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// sendingStale: bản ghi "sending" quá thời gian này được coi là bị bỏ dở (tiến trình chết giữa chừng), gửi lại được.
const sendingStale = 30 * time.Second

const otpSubject = "TDTU Food - Mã xác nhận email"

var otpCodeRe = regexp.MustCompile(`^[0-9]{6}$`)

// EmailRequest: body của POST /internal/notifications/email.
type EmailRequest struct {
	To             string
	Template       string
	Purpose        string
	Code           string
	UserID         string
	ExpiresIn      int
	IdempotencyKey string
}

// maskEmail: sv1.abc@student.tdtu.edu.vn -> sv***@student.tdtu.edu.vn (log không lộ địa chỉ đầy đủ).
func maskEmail(addr string) string {
	local, domain, _ := strings.Cut(addr, "@")
	if len(local) > 2 {
		local = local[:2]
	}
	return local + "***@" + domain
}

func validEmail(s string) bool {
	if len(s) > 254 || strings.ContainsAny(s, " <>\"\r\n") {
		return false
	}
	a, err := mail.ParseAddress(s)
	if err != nil || a.Address != s || a.Name != "" {
		return false
	}
	local, domain, ok := strings.Cut(s, "@")
	return ok && local != "" && strings.Contains(domain, ".") && !strings.HasPrefix(domain, ".") && !strings.HasSuffix(domain, ".")
}

// parseEmailRequest: kiểm tra chặt như parseEvent (trường lạ / thiếu / sai kiểu -> 422). Thông báo lỗi không chứa
// giá trị gửi lên (không lộ mã OTP).
func parseEmailRequest(raw []byte) (EmailRequest, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil || m == nil {
		return EmailRequest{}, &ApiError{Status: 422, Code: "VALIDATION_ERROR", Message: "JSON gửi lên không hợp lệ",
			Errors: []FieldError{{"body", "phải là JSON object"}}}
	}
	var errs []FieldError
	strFields := []string{"to", "template", "purpose", "code", "user_id", "idempotency_key"}
	known := map[string]bool{"expires_in_seconds": true}
	for _, f := range strFields {
		known[f] = true
	}
	for k := range m {
		if !known[k] {
			errs = append(errs, FieldError{k, "trường không được phép"})
		}
	}
	val := map[string]string{}
	for _, f := range strFields {
		r, ok := m[f]
		if !ok {
			errs = append(errs, FieldError{f, "bắt buộc"})
			continue
		}
		var s string
		if err := json.Unmarshal(r, &s); err != nil {
			errs = append(errs, FieldError{f, "phải là chuỗi"})
			continue
		}
		s = strings.TrimSpace(s)
		if s == "" {
			errs = append(errs, FieldError{f, "không được để trống"})
			continue
		}
		val[f] = s
	}
	expires := 0
	if r, ok := m["expires_in_seconds"]; !ok {
		errs = append(errs, FieldError{"expires_in_seconds", "bắt buộc"})
	} else {
		// giải mã vào any (không vào json.Number: encoding/json chấp nhận cả chuỗi "300" cho json.Number)
		var v any
		dec := json.NewDecoder(bytes.NewReader(r))
		dec.UseNumber()
		i, convErr := int64(0), error(nil)
		if err := dec.Decode(&v); err != nil {
			convErr = err
		} else if n, isNum := v.(json.Number); !isNum {
			convErr = errors.New("không phải số")
		} else {
			i, convErr = n.Int64()
		}
		if convErr != nil || i < 60 || i > 3600 {
			errs = append(errs, FieldError{"expires_in_seconds", "phải là số nguyên từ 60 đến 3600"})
		} else {
			expires = int(i)
		}
	}
	if v, ok := val["to"]; ok && !validEmail(v) {
		errs = append(errs, FieldError{"to", "phải là email hợp lệ, tối đa 254 ký tự"})
	}
	if v, ok := val["template"]; ok && v != "otp" {
		errs = append(errs, FieldError{"template", "phải là một trong: otp"})
	}
	if v, ok := val["purpose"]; ok && v != "verify_email" {
		errs = append(errs, FieldError{"purpose", "phải là một trong: verify_email"})
	}
	if v, ok := val["code"]; ok && !otpCodeRe.MatchString(v) {
		errs = append(errs, FieldError{"code", "phải gồm đúng 6 chữ số"})
	}
	if v, ok := val["user_id"]; ok {
		if !uuidRe.MatchString(v) {
			errs = append(errs, FieldError{"user_id", "phải là UUID"})
		}
		val["user_id"] = strings.ToLower(v)
	}
	if v, ok := val["idempotency_key"]; ok {
		if n := len([]rune(v)); n < 10 || n > 120 {
			errs = append(errs, FieldError{"idempotency_key", "độ dài phải từ 10 đến 120 ký tự"})
		}
	}
	if len(errs) > 0 {
		return EmailRequest{}, validationErr(errs)
	}
	return EmailRequest{To: val["to"], Template: val["template"], Purpose: val["purpose"], Code: val["code"],
		UserID: val["user_id"], ExpiresIn: expires, IdempotencyKey: val["idempotency_key"]}, nil
}

// buildProviderPayload (build_provider_payload): body gửi provider, trường nội dung tên `content` như
// ProviderEmailRequest của Unit 20.
func buildProviderPayload(req EmailRequest) map[string]any {
	minutes := int(math.Ceil(float64(req.ExpiresIn) / 60))
	content := fmt.Sprintf("Mã xác nhận email TDTU Food của bạn là %s. Mã có hiệu lực %d phút. "+
		"Không chia sẻ mã này cho bất kỳ ai, kể cả người tự xưng là nhân viên TDTU Food.", req.Code, minutes)
	return map[string]any{"to": req.To, "subject": otpSubject, "content": content, "tag": "otp"}
}

// callProvider gọi POST {EMAIL_PROVIDER_URL}/api/send. Trả message_id, hoặc lỗi đã ánh xạ (mục 2.3) và số giây
// Retry-After (chỉ khi provider trả 429).
func callProvider(rid string, req EmailRequest) (string, *ApiError, int) {
	base, key := emailProviderURL(), emailAPIKey()
	if base == "" || key == "" {
		return "", apiErr(503, "EMAIL_NOT_CONFIGURED", "Chưa cấu hình nhà cung cấp email (EMAIL_PROVIDER_URL, EMAIL_API_KEY)"), 0
	}
	body, _ := json.Marshal(buildProviderPayload(req))
	hreq, err := http.NewRequest("POST", base+"/api/send", bytes.NewReader(body))
	if err != nil {
		return "", apiErr(503, "EMAIL_NOT_CONFIGURED", "Địa chỉ nhà cung cấp email không hợp lệ"), 0
	}
	hreq.Header.Set("Content-Type", "application/json")
	hreq.Header.Set("Accept", "application/json")
	hreq.Header.Set("X-API-Key", key)
	hreq.Header.Set("Idempotency-Key", req.IdempotencyKey)
	if rid != "" {
		hreq.Header.Set("X-Request-ID", rid)
	}
	resp, err := (&http.Client{Timeout: providerTimeout()}).Do(hreq)
	if err != nil {
		var te interface{ Timeout() bool }
		if errors.As(err, &te) && te.Timeout() {
			return "", apiErr(503, "EMAIL_PROVIDER_UNAVAILABLE", "Nhà cung cấp email phản hồi quá thời gian chờ"), 0
		}
		return "", apiErr(503, "EMAIL_PROVIDER_UNAVAILABLE", "Không kết nối được nhà cung cấp email"), 0
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if err != nil {
		return "", apiErr(503, "EMAIL_PROVIDER_UNAVAILABLE", "Không đọc được phản hồi của nhà cung cấp email"), 0
	}
	switch st := resp.StatusCode; {
	case st >= 200 && st < 300:
		var out map[string]any
		if json.Unmarshal(raw, &out) != nil || out == nil {
			return "", apiErr(502, "EMAIL_PROVIDER_BAD_RESPONSE", "Nhà cung cấp email trả dữ liệu không hợp lệ"), 0
		}
		id, _ := out["message_id"].(string)
		if id = strings.TrimSpace(id); id == "" || len(id) > 120 {
			return "", apiErr(502, "EMAIL_PROVIDER_BAD_RESPONSE", "Nhà cung cấp email không trả message_id"), 0
		}
		return id, nil, 0
	case st == 401 || st == 403:
		return "", apiErr(502, "EMAIL_PROVIDER_AUTH", "Nhà cung cấp email từ chối khóa API của hệ thống"), 0
	case st == 409:
		return "", apiErr(409, "EMAIL_IN_PROGRESS", "Email này đang được gửi, vui lòng thử lại sau ít giây"), 0
	case st == 429:
		retry := 60
		if n, err := strconv.Atoi(strings.TrimSpace(resp.Header.Get("Retry-After"))); err == nil && n > 0 {
			retry = n
		}
		return "", apiErr(503, "EMAIL_PROVIDER_RATE_LIMITED", "Nhà cung cấp email đang giới hạn tần suất, vui lòng thử lại sau"), retry
	case st >= 500:
		return "", apiErr(502, "EMAIL_PROVIDER_ERROR", "Nhà cung cấp email đang gặp lỗi"), 0
	default:
		return "", apiErr(400, "EMAIL_REJECTED", fmt.Sprintf("Nhà cung cấp email từ chối email (HTTP %d)", st)), 0
	}
}

func clip(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

func emailSent(c *gin.Context, e EmailLog, status int, replay bool) {
	body := gin.H{"id": e.ID, "status": e.Status, "provider_message_id": e.ProviderMessageID}
	if replay {
		body["replay"] = true
	}
	c.JSON(status, body)
}

// sendEmail: POST /internal/notifications/email (X-Internal-Key).
func (s *Server) sendEmail(c *gin.Context) {
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, 16<<10))
	if err != nil {
		writeErr(c, err)
		return
	}
	req, err := parseEmailRequest(bytes.TrimSpace(raw))
	if err != nil {
		writeErr(c, err)
		return
	}
	rid := requestIDOf(c)
	now := time.Now().UTC()
	row := EmailLog{ID: uuid.NewString(), UserID: req.UserID, ToEmail: req.To, Template: req.Template, Status: "sending",
		IdempotencyKey: req.IdempotencyKey, CreatedAt: now, UpdatedAt: now}
	res := s.db.Clauses(clause.OnConflict{DoNothing: true}).Create(&row)
	if res.Error != nil {
		writeErr(c, res.Error)
		return
	}
	if res.RowsAffected == 0 { // khóa đã có: trả lại kết quả cũ, hoặc giành lại bản ghi lỗi / bỏ dở để gửi lại
		var prev EmailLog
		if err := s.db.First(&prev, "idempotency_key = ?", req.IdempotencyKey).Error; err != nil {
			writeErr(c, err)
			return
		}
		switch {
		case prev.Status == "sent" || prev.Status == "delivered":
			emailSent(c, prev, 200, true)
			return
		case prev.Status == "sending" && now.Sub(prev.UpdatedAt) < sendingStale:
			writeErr(c, apiErr(409, "EMAIL_IN_PROGRESS", "Email này đang được gửi, vui lòng thử lại sau ít giây"))
			return
		}
		claim := s.db.Model(&EmailLog{}).
			Where("id = ? AND (status = 'failed' OR (status = 'sending' AND updated_at < ?))", prev.ID, now.Add(-sendingStale)).
			Updates(map[string]any{"status": "sending", "last_error": nil, "updated_at": now})
		if claim.Error != nil {
			writeErr(c, claim.Error)
			return
		}
		if claim.RowsAffected == 0 { // yêu cầu khác vừa giành trước
			writeErr(c, apiErr(409, "EMAIL_IN_PROGRESS", "Email này đang được gửi, vui lòng thử lại sau ít giây"))
			return
		}
		row = prev
	}

	// gọi provider NGOÀI transaction (không giữ khóa DB trong lúc chờ mạng)
	msgID, perr, retryAfter := callProvider(rid, req)
	if perr != nil {
		last := clip(perr.Code+": "+perr.Message, 300)
		if err := s.db.Model(&EmailLog{}).Where("id = ?", row.ID).
			Updates(map[string]any{"status": "failed", "last_error": last, "updated_at": time.Now().UTC()}).Error; err != nil {
			log.Printf("[notification] Không ghi được lỗi gửi email %s: %v rid=%s", row.ID, err, ridOrDash(rid))
		}
		log.Printf("[notification] Gửi email %s tới %s (user %s) thất bại: %s rid=%s", row.ID, maskEmail(req.To),
			req.UserID, perr.Code, ridOrDash(rid))
		if retryAfter > 0 {
			c.Header("Retry-After", strconv.Itoa(retryAfter))
		}
		writeErr(c, perr)
		return
	}
	if err := s.db.Model(&EmailLog{}).Where("id = ?", row.ID).Updates(map[string]any{"status": "sent",
		"provider_message_id": msgID, "last_error": nil, "updated_at": time.Now().UTC()}).Error; err != nil {
		writeErr(c, err)
		return
	}
	log.Printf("[notification] Đã gửi email %s tới %s (user %s) message_id=%s rid=%s", row.ID, maskEmail(req.To),
		req.UserID, msgID, ridOrDash(rid))
	row.Status, row.ProviderMessageID = "sent", &msgID
	emailSent(c, row, 201, false)
}

// ---------------------------------------------------------------- webhook của provider
type webhookBody struct {
	MessageID *string `json:"message_id"`
	Status    *string `json:"status"`
	Reason    *string `json:"reason"`
	Timestamp *string `json:"timestamp"`
}

// validSignature: X-Webhook-Signature = "sha256=" + hex(HMAC-SHA256(EMAIL_WEBHOOK_SECRET, body thô)).
func validSignature(secret string, body []byte, header string) bool {
	if secret == "" || !strings.HasPrefix(header, "sha256=") {
		return false
	}
	given, err := hex.DecodeString(strings.TrimPrefix(header, "sha256="))
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return hmac.Equal(mac.Sum(nil), given)
}

// emailWebhook: POST /internal/webhooks/email-status. KHÔNG dùng requireInternal (provider không giữ INTERNAL_KEY):
// xác thực bằng chữ ký HMAC trên đúng các byte nhận được.
func (s *Server) emailWebhook(c *gin.Context) {
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, 16<<10))
	if err != nil {
		writeErr(c, err)
		return
	}
	if !validSignature(webhookSecret(), raw, c.GetHeader("X-Webhook-Signature")) {
		writeErr(c, apiErr(401, "INVALID_SIGNATURE", "Chữ ký webhook không hợp lệ"))
		return
	}
	var b webhookBody
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&b); err != nil || dec.More() {
		msg := "JSON không hợp lệ"
		if err != nil && strings.Contains(err.Error(), "unknown field") {
			msg = "có trường không được phép"
		}
		writeErr(c, validationErr([]FieldError{{"body", msg}}))
		return
	}
	var errs []FieldError
	if b.MessageID == nil || strings.TrimSpace(*b.MessageID) == "" || len(*b.MessageID) > 120 {
		errs = append(errs, FieldError{"message_id", "bắt buộc, tối đa 120 ký tự"})
	}
	if b.Status == nil || (*b.Status != "delivered" && *b.Status != "failed") {
		errs = append(errs, FieldError{"status", "phải là một trong: delivered, failed"})
	}
	if b.Timestamp == nil || strings.TrimSpace(*b.Timestamp) == "" {
		errs = append(errs, FieldError{"timestamp", "bắt buộc"})
	}
	if len(errs) > 0 {
		writeErr(c, validationErr(errs))
		return
	}
	msgID, status := strings.TrimSpace(*b.MessageID), *b.Status
	var e EmailLog
	found := s.db.Where("provider_message_id = ?", msgID).Limit(1).Find(&e)
	if found.Error != nil {
		writeErr(c, found.Error)
		return
	}
	if found.RowsAffected == 0 { // provider sẽ thử lại sau (có thể webhook tới trước khi kịp lưu message_id)
		writeErr(c, apiErr(404, "EMAIL_NOT_FOUND", "Không tìm thấy email có message_id này"))
		return
	}
	ok := gin.H{"received": true, "message_id": msgID, "status": status}
	if e.Status == status { // provider gửi lại cùng kết quả
		c.JSON(200, ok)
		return
	}
	if e.Status != "sent" { // chỉ cho sent -> delivered / failed; trạng thái cuối khác thì bỏ qua
		c.JSON(200, gin.H{"received": true, "ignored": true})
		return
	}
	upd := map[string]any{"status": status, "updated_at": time.Now().UTC()}
	if status == "failed" {
		reason := "delivery_failed"
		if b.Reason != nil && strings.TrimSpace(*b.Reason) != "" {
			reason = strings.TrimSpace(*b.Reason)
		}
		upd["last_error"] = clip("WEBHOOK: "+reason, 300)
	}
	res := s.db.Model(&EmailLog{}).Where("id = ? AND status = 'sent'", e.ID).Updates(upd)
	if res.Error != nil {
		writeErr(c, res.Error)
		return
	}
	if res.RowsAffected == 0 { // webhook khác vừa đổi trạng thái
		c.JSON(200, gin.H{"received": true, "ignored": true})
		return
	}
	log.Printf("[notification] Webhook email %s (user %s): %s rid=%s", msgID, e.UserID, status, ridOrDash(requestIDOf(c)))
	c.JSON(200, ok)
}

// ---------------------------------------------------------------- admin
func (s *Server) adminEmailLogs(c *gin.Context) {
	status, err := enumQuery(c, "status", "sending", "sent", "delivered", "failed")
	if err != nil {
		writeErr(c, err)
		return
	}
	page, size, err := paging(c)
	if err != nil {
		writeErr(c, err)
		return
	}
	q := s.db.Model(&EmailLog{})
	if raw, ok := c.GetQuery("user_id"); ok {
		uid, err := uuidValue(raw, "user_id")
		if err != nil {
			writeErr(c, err)
			return
		}
		q = q.Where("user_id = ?", uid)
	}
	if status != "" {
		q = q.Where("status = ?", status)
	}
	var total int64
	if err := q.Session(&gorm.Session{}).Count(&total).Error; err != nil {
		writeErr(c, err)
		return
	}
	var list []EmailLog
	if err := q.Session(&gorm.Session{}).Order("created_at DESC, id").Limit(size).Offset((page - 1) * size).
		Find(&list).Error; err != nil {
		writeErr(c, err)
		return
	}
	items := make([]EmailLogOut, 0, len(list))
	for _, e := range list {
		items = append(items, toEmailOut(e))
	}
	c.JSON(200, gin.H{"items": items, "total": total, "page": page, "page_size": size})
}
