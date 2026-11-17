package main

// Test gửi email OTP qua nhà cung cấp (Unit 20): kiểm tra body, ánh xạ lỗi provider, idempotency, gửi lại trên
// cùng bản ghi, webhook có ký HMAC, xóa dữ liệu cá nhân, mã OTP không xuất hiện trong log.

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const testCode = "042917"
const testAPIKey = "provider-key-0123456789abcdef"
const testSecret = "webhook-secret-0123456789abcdef"

func validEmailReq() map[string]any {
	return map[string]any{"to": "sv1@student.tdtu.edu.vn", "template": "otp", "purpose": "verify_email", "code": testCode,
		"user_id": u(2), "expires_in_seconds": 300, "idempotency_key": "otp-" + u(9)}
}

func TestParseEmailRequest(t *testing.T) {
	ok, _ := json.Marshal(validEmailReq())
	req, err := parseEmailRequest(ok)
	if err != nil || req.Code != testCode || req.ExpiresIn != 300 || req.UserID != u(2) {
		t.Fatalf("body hợp lệ bị từ chối: %v %+v", err, req)
	}
	upper := validEmailReq()
	upper["user_id"] = strings.ToUpper(u(2))
	raw, _ := json.Marshal(upper)
	if r, err := parseEmailRequest(raw); err != nil || r.UserID != u(2) {
		t.Fatalf("user_id phải đưa về chữ thường: %v %v", err, r.UserID)
	}
	bad := map[string]func(m map[string]any){
		"trường lạ":          func(m map[string]any) { m["cc"] = "x@y.vn" },
		"thiếu to":           func(m map[string]any) { delete(m, "to") },
		"email sai":          func(m map[string]any) { m["to"] = "khong-phai-email" },
		"email có tên":       func(m map[string]any) { m["to"] = "SV <sv1@student.tdtu.edu.vn>" },
		"email quá dài":      func(m map[string]any) { m["to"] = strings.Repeat("a", 250) + "@x.vn" },
		"to rỗng":            func(m map[string]any) { m["to"] = "  " },
		"template khác":      func(m map[string]any) { m["template"] = "welcome" },
		"purpose khác":       func(m map[string]any) { m["purpose"] = "reset_password" },
		"mã 5 số":            func(m map[string]any) { m["code"] = "12345" },
		"mã có chữ":          func(m map[string]any) { m["code"] = "12a456" },
		"mã là số":           func(m map[string]any) { m["code"] = 123456 },
		"user_id sai":        func(m map[string]any) { m["user_id"] = "abc" },
		"hết hạn 59":         func(m map[string]any) { m["expires_in_seconds"] = 59 },
		"hết hạn 3601":       func(m map[string]any) { m["expires_in_seconds"] = 3601 },
		"hết hạn lẻ":         func(m map[string]any) { m["expires_in_seconds"] = 300.5 },
		"hết hạn chuỗi":      func(m map[string]any) { m["expires_in_seconds"] = "300" },
		"thiếu hết hạn":      func(m map[string]any) { delete(m, "expires_in_seconds") },
		"khóa ngắn":          func(m map[string]any) { m["idempotency_key"] = "otp-12345" },
		"khóa dài":           func(m map[string]any) { m["idempotency_key"] = strings.Repeat("k", 121) },
		"idempotency rỗng":   func(m map[string]any) { m["idempotency_key"] = "" },
		"template là null":   func(m map[string]any) { m["template"] = nil },
		"purpose là boolean": func(m map[string]any) { m["purpose"] = true },
	}
	for name, f := range bad {
		m := validEmailReq()
		f(m)
		raw, _ := json.Marshal(m)
		_, err := parseEmailRequest(raw)
		e, isAPI := err.(*ApiError)
		if !isAPI || e.Status != 422 {
			t.Errorf("%s: mong đợi 422, nhận %v", name, err)
			continue
		}
		if dump, _ := json.Marshal(e); strings.Contains(string(dump), testCode) {
			t.Errorf("%s: thông báo lỗi không được chứa mã OTP: %s", name, dump)
		}
	}
	for _, raw := range []string{`[]`, `{"to":`, `null`, `"x"`} {
		if _, err := parseEmailRequest([]byte(raw)); err == nil || err.(*ApiError).Status != 422 {
			t.Errorf("%s: mong đợi 422", raw)
		}
	}
}

func TestBuildProviderPayload(t *testing.T) {
	m := buildProviderPayload(EmailRequest{To: "sv1@student.tdtu.edu.vn", Code: testCode, ExpiresIn: 300})
	if len(m) != 4 || m["to"] != "sv1@student.tdtu.edu.vn" || m["subject"] != "TDTU Food - Mã xác nhận email" || m["tag"] != "otp" {
		t.Fatalf("payload sai: %v", m)
	}
	content := m["content"].(string)
	if !strings.Contains(content, testCode) || !strings.Contains(content, "5 phút") {
		t.Fatalf("content phải có mã và số phút hiệu lực: %s", content)
	}
	if _, has := m["body"]; has {
		t.Fatal("trường nội dung phải tên content (ProviderEmailRequest của Unit 20)")
	}
	if c := buildProviderPayload(EmailRequest{Code: testCode, ExpiresIn: 61})["content"].(string); !strings.Contains(c, "2 phút") {
		t.Fatalf("61 giây làm tròn lên 2 phút: %s", c)
	}
}

// providerAt: provider giả trả status / body / header cho trước, ghi lại header và body nhận được.
type fakeProvider struct {
	srv     *httptest.Server
	calls   atomic.Int32
	mu      sync.Mutex
	headers http.Header
	body    map[string]any
	reply   func(w http.ResponseWriter, r *http.Request)
}

func newFakeProvider(t *testing.T) *fakeProvider {
	p := &fakeProvider{}
	p.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p.calls.Add(1)
		raw, _ := io.ReadAll(r.Body)
		p.mu.Lock()
		p.headers = r.Header.Clone()
		json.Unmarshal(raw, &p.body)
		reply := p.reply
		p.mu.Unlock()
		if reply != nil {
			reply(w, r)
			return
		}
		w.WriteHeader(202)
		w.Write([]byte(`{"message_id":"msg_` + strings.ReplaceAll(r.Header.Get("Idempotency-Key"), "-", "") + `","status":"accepted","provider":"MockMail"}`))
	}))
	t.Cleanup(p.srv.Close)
	t.Setenv("EMAIL_PROVIDER_URL", p.srv.URL)
	t.Setenv("EMAIL_API_KEY", testAPIKey)
	return p
}

func (p *fakeProvider) set(reply func(w http.ResponseWriter, r *http.Request)) {
	p.mu.Lock()
	p.reply = reply
	p.mu.Unlock()
}

func status(code int, body string, hdr ...string) func(w http.ResponseWriter, r *http.Request) {
	return func(w http.ResponseWriter, r *http.Request) {
		for i := 0; i+1 < len(hdr); i += 2 {
			w.Header().Set(hdr[i], hdr[i+1])
		}
		w.WriteHeader(code)
		w.Write([]byte(body))
	}
}

func TestCallProviderMapping(t *testing.T) {
	p := newFakeProvider(t)
	req := EmailRequest{To: "sv1@student.tdtu.edu.vn", Code: testCode, ExpiresIn: 300, IdempotencyKey: "otp-" + u(9)}

	id, e, _ := callProvider("demo-rid-0001", req)
	if e != nil || id != "msg_otp"+strings.ReplaceAll(u(9), "-", "") {
		t.Fatalf("2xx: %q %v", id, e)
	}
	h := p.headers
	if h.Get("X-API-Key") != testAPIKey || h.Get("Idempotency-Key") != req.IdempotencyKey ||
		h.Get("X-Request-ID") != "demo-rid-0001" || !strings.HasPrefix(h.Get("Content-Type"), "application/json") {
		t.Fatalf("thiếu header gửi provider: %v", h)
	}
	if p.body["content"] == nil || p.body["tag"] != "otp" || p.body["to"] != req.To {
		t.Fatalf("body gửi provider sai: %v", p.body)
	}

	cases := []struct {
		name   string
		reply  func(w http.ResponseWriter, r *http.Request)
		status int
		code   string
		retry  int
	}{
		{"401", status(401, `{"code":"INVALID_API_KEY"}`), 502, "EMAIL_PROVIDER_AUTH", 0},
		{"403", status(403, `{}`), 502, "EMAIL_PROVIDER_AUTH", 0},
		{"409", status(409, `{"code":"IDEMPOTENCY_IN_PROGRESS"}`), 409, "EMAIL_IN_PROGRESS", 0},
		{"429 có Retry-After", status(429, `{}`, "Retry-After", "17"), 503, "EMAIL_PROVIDER_RATE_LIMITED", 17},
		{"429 không Retry-After", status(429, `{}`), 503, "EMAIL_PROVIDER_RATE_LIMITED", 60},
		{"500", status(500, `{"code":"PROVIDER_ERROR"}`), 502, "EMAIL_PROVIDER_ERROR", 0},
		{"503", status(503, `<html>`), 502, "EMAIL_PROVIDER_ERROR", 0},
		{"400", status(400, `{}`), 400, "EMAIL_REJECTED", 0},
		{"422", status(422, `{}`), 400, "EMAIL_REJECTED", 0},
		{"2xx body hỏng", status(202, `<html>`), 502, "EMAIL_PROVIDER_BAD_RESPONSE", 0},
		{"2xx thiếu message_id", status(202, `{"status":"accepted"}`), 502, "EMAIL_PROVIDER_BAD_RESPONSE", 0},
		{"2xx message_id rỗng", status(200, `{"message_id":"  "}`), 502, "EMAIL_PROVIDER_BAD_RESPONSE", 0},
	}
	for _, c := range cases {
		p.set(c.reply)
		_, e, retry := callProvider("", req)
		if e == nil || e.Status != c.status || e.Code != c.code || retry != c.retry {
			t.Errorf("%s: mong đợi %d %s retry=%d, nhận %v retry=%d", c.name, c.status, c.code, c.retry, e, retry)
		}
	}

	// quá thời gian chờ: EMAIL_PROVIDER_TIMEOUT=0.2 -> 503 sau khoảng 0.2 giây (không chờ provider 1 giây)
	t.Setenv("EMAIL_PROVIDER_TIMEOUT", "0.2")
	p.set(func(w http.ResponseWriter, r *http.Request) { time.Sleep(time.Second); w.WriteHeader(202) })
	t0 := time.Now()
	_, e, _ = callProvider("", req)
	if e == nil || e.Status != 503 || e.Code != "EMAIL_PROVIDER_UNAVAILABLE" || time.Since(t0) > 900*time.Millisecond {
		t.Errorf("timeout: %v sau %v", e, time.Since(t0))
	}

	t.Setenv("EMAIL_PROVIDER_URL", "http://127.0.0.1:9") // cổng đóng
	if _, e, _ = callProvider("", req); e == nil || e.Code != "EMAIL_PROVIDER_UNAVAILABLE" || e.Status != 503 {
		t.Errorf("cổng đóng: %v", e)
	}
	t.Setenv("EMAIL_PROVIDER_URL", "")
	if _, e, _ = callProvider("", req); e == nil || e.Code != "EMAIL_NOT_CONFIGURED" || e.Status != 503 {
		t.Errorf("thiếu URL: %v", e)
	}
	t.Setenv("EMAIL_PROVIDER_URL", p.srv.URL)
	t.Setenv("EMAIL_API_KEY", "")
	if _, e, _ = callProvider("", req); e == nil || e.Code != "EMAIL_NOT_CONFIGURED" {
		t.Errorf("thiếu API key: %v", e)
	}
}

func TestValidSignature(t *testing.T) {
	body := []byte(`{"message_id":"msg_1","status":"delivered","reason":null,"timestamp":"2026-11-17T00:00:00Z"}`)
	good := sign(testSecret, body)
	if !validSignature(testSecret, body, good) {
		t.Fatal("chữ ký đúng bị từ chối")
	}
	for name, h := range map[string]string{"sai khóa": sign("khac", body), "thiếu tiền tố": strings.TrimPrefix(good, "sha256="),
		"không phải hex": "sha256=zz", "rỗng": ""} {
		if validSignature(testSecret, body, h) {
			t.Errorf("%s: phải bị từ chối", name)
		}
	}
	if validSignature("", body, sign("", body)) {
		t.Error("secret rỗng: mọi webhook phải bị từ chối")
	}
	if validSignature(testSecret, append(body, ' '), good) {
		t.Error("body bị sửa 1 byte: chữ ký phải sai")
	}
}

func sign(secret string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

// ---------------------------------------------------------------- tích hợp với PostgreSQL
func TestIntegrationEmailIdempotencyAndRetry(t *testing.T) {
	srv, call, db := setupIntegrationDB(t)
	p := newFakeProvider(t)

	if st, _ := call("POST", "/internal/notifications/email", "", validEmailReq()); st != 403 {
		t.Fatalf("thiếu khóa nội bộ phải 403, nhận %d", st)
	}
	bad := validEmailReq()
	bad["code"] = "12"
	if st, body := call("POST", "/internal/notifications/email", "internal", bad); st != 422 || body["code"] != "VALIDATION_ERROR" {
		t.Fatalf("body sai phải 422: %d %v", st, body)
	}
	st, first := call("POST", "/internal/notifications/email", "internal", validEmailReq())
	if st != 201 || first["status"] != "sent" || first["provider_message_id"] == nil || first["replay"] != nil {
		t.Fatalf("gửi lần đầu: %d %v", st, first)
	}
	st, again := call("POST", "/internal/notifications/email", "internal", validEmailReq())
	if st != 200 || again["replay"] != true || again["id"] != first["id"] || again["provider_message_id"] != first["provider_message_id"] {
		t.Fatalf("gửi lại cùng khóa phải 200 replay: %d %v", st, again)
	}
	if n := p.calls.Load(); n != 1 {
		t.Fatalf("provider chỉ được gọi 1 lần, đã gọi %d", n)
	}

	// provider lỗi -> failed + last_error; gửi lại -> giành lại CHÍNH dòng đó (cùng id) và thành công
	req2 := validEmailReq()
	req2["idempotency_key"] = "otp-" + u(10)
	p.set(status(500, `{"code":"PROVIDER_ERROR"}`))
	if st, body := call("POST", "/internal/notifications/email", "internal", req2); st != 502 || body["code"] != "EMAIL_PROVIDER_ERROR" {
		t.Fatalf("provider 500 -> 502: %d %v", st, body)
	}
	var row EmailLog
	db.First(&row, "idempotency_key = ?", req2["idempotency_key"])
	if row.Status != "failed" || row.LastError == nil || !strings.Contains(*row.LastError, "EMAIL_PROVIDER_ERROR") {
		t.Fatalf("bản ghi lỗi: %+v", row)
	}
	p.set(status(429, `{}`, "Retry-After", "7"))
	resp := rawPost(t, srv.URL+"/internal/notifications/email", req2)
	if resp.StatusCode != 503 || resp.Header.Get("Retry-After") != "7" {
		t.Fatalf("provider 429 -> 503 + Retry-After: %d %v", resp.StatusCode, resp.Header)
	}
	p.set(nil)
	st, ok := call("POST", "/internal/notifications/email", "internal", req2)
	if st != 201 || ok["id"] != row.ID {
		t.Fatalf("gửi lại sau lỗi phải dùng cùng id %s: %d %v", row.ID, st, ok)
	}
	var count int64
	db.Model(&EmailLog{}).Where("idempotency_key = ?", req2["idempotency_key"]).Count(&count)
	if count != 1 {
		t.Fatalf("chỉ 1 bản ghi cho 1 khóa, có %d", count)
	}

	// đang sending < 30 giây -> 409; quá 30 giây (bỏ dở) -> gửi lại được trên cùng dòng
	req3 := validEmailReq()
	req3["idempotency_key"] = "otp-" + u(11)
	now := time.Now().UTC()
	stuck := EmailLog{ID: u(77), UserID: u(2), ToEmail: "sv1@student.tdtu.edu.vn", Template: "otp", Status: "sending",
		IdempotencyKey: req3["idempotency_key"].(string), CreatedAt: now, UpdatedAt: now}
	db.Create(&stuck)
	if st, body := call("POST", "/internal/notifications/email", "internal", req3); st != 409 || body["code"] != "EMAIL_IN_PROGRESS" {
		t.Fatalf("đang gửi phải 409: %d %v", st, body)
	}
	db.Model(&EmailLog{}).Where("id = ?", u(77)).Update("updated_at", now.Add(-31*time.Second))
	if st, body := call("POST", "/internal/notifications/email", "internal", req3); st != 201 || body["id"] != u(77) {
		t.Fatalf("bản ghi bỏ dở phải gửi lại được trên cùng id: %d %v", st, body)
	}
	// provider trả 409 (cùng khóa đang xử lý bên provider) -> 409
	req4 := validEmailReq()
	req4["idempotency_key"] = "otp-" + u(12)
	p.set(status(409, `{"code":"IDEMPOTENCY_IN_PROGRESS"}`))
	if st, body := call("POST", "/internal/notifications/email", "internal", req4); st != 409 || body["code"] != "EMAIL_IN_PROGRESS" {
		t.Fatalf("provider 409: %d %v", st, body)
	}
	p.set(nil)
	t.Setenv("EMAIL_PROVIDER_URL", "")
	req5 := validEmailReq()
	req5["idempotency_key"] = "otp-" + u(13)
	if st, body := call("POST", "/internal/notifications/email", "internal", req5); st != 503 || body["code"] != "EMAIL_NOT_CONFIGURED" {
		t.Fatalf("chưa cấu hình: %d %v", st, body)
	}
}

// rawPost gửi body JSON (kèm khóa nội bộ) tới url, trả *http.Response (để đọc header).
func rawPost(t *testing.T, url string, body any) *http.Response {
	t.Helper()
	raw, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", url, bytes.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Key", testKey)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	return resp
}

func webhook(t *testing.T, base, secret string, body []byte, sig ...string) (int, map[string]any) {
	t.Helper()
	req, _ := http.NewRequest("POST", base+"/internal/webhooks/email-status", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if len(sig) > 0 {
		req.Header.Set("X-Webhook-Signature", sig[0])
	} else {
		req.Header.Set("X-Webhook-Signature", sign(secret, body))
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

func TestIntegrationWebhook(t *testing.T) {
	srv, call, db := setupIntegrationDB(t)
	newFakeProvider(t)
	t.Setenv("EMAIL_WEBHOOK_SECRET", testSecret)
	_, sent := call("POST", "/internal/notifications/email", "internal", validEmailReq())
	msg := sent["provider_message_id"].(string)
	body := func(m map[string]any) []byte { b, _ := json.Marshal(m); return b }
	delivered := body(map[string]any{"message_id": msg, "status": "delivered", "reason": nil, "timestamp": "2026-11-17T00:00:00Z"})

	if st, r := webhook(t, srv.URL, testSecret, delivered, "sha256=00"); st != 401 || r["code"] != "INVALID_SIGNATURE" {
		t.Fatalf("chữ ký sai phải 401: %d %v", st, r)
	}
	if st, _ := webhook(t, srv.URL, testSecret, delivered, ""); st != 401 {
		t.Fatalf("thiếu chữ ký phải 401")
	}
	if st, _ := webhook(t, srv.URL, "khoa-khac-0123456789", delivered); st != 401 {
		t.Fatalf("ký bằng khóa khác phải 401")
	}
	for name, b := range map[string][]byte{
		"trường lạ":       body(map[string]any{"message_id": msg, "status": "delivered", "reason": nil, "timestamp": "x", "extra": 1}),
		"status sai":      body(map[string]any{"message_id": msg, "status": "opened", "reason": nil, "timestamp": "x"}),
		"thiếu id":        body(map[string]any{"status": "delivered", "reason": nil, "timestamp": "x"}),
		"thiếu thời gian": body(map[string]any{"message_id": msg, "status": "delivered", "reason": nil}),
		"không phải JSON": []byte("xin chao"),
		"status là số":    body(map[string]any{"message_id": msg, "status": 1, "reason": nil, "timestamp": "x"}),
	} {
		if st, r := webhook(t, srv.URL, testSecret, b); st != 422 {
			t.Errorf("%s: mong đợi 422, nhận %d %v", name, st, r)
		}
	}
	unknown := body(map[string]any{"message_id": "msg_khongco", "status": "delivered", "reason": nil, "timestamp": "x"})
	if st, r := webhook(t, srv.URL, testSecret, unknown); st != 404 || r["code"] != "EMAIL_NOT_FOUND" {
		t.Fatalf("message_id lạ phải 404: %d %v", st, r)
	}
	st, r := webhook(t, srv.URL, testSecret, delivered)
	if st != 200 || r["received"] != true || r["message_id"] != msg || r["status"] != "delivered" {
		t.Fatalf("webhook delivered: %d %v", st, r)
	}
	var row EmailLog
	db.First(&row, "provider_message_id = ?", msg)
	if row.Status != "delivered" {
		t.Fatalf("trạng thái phải delivered: %+v", row)
	}
	if st, r := webhook(t, srv.URL, testSecret, delivered); st != 200 || r["status"] != "delivered" || r["ignored"] != nil {
		t.Fatalf("gửi lại cùng trạng thái phải 200: %d %v", st, r)
	}
	failedAfter := body(map[string]any{"message_id": msg, "status": "failed", "reason": "late", "timestamp": "x"})
	if st, r := webhook(t, srv.URL, testSecret, failedAfter); st != 200 || r["ignored"] != true {
		t.Fatalf("đã delivered rồi báo failed phải ignored: %d %v", st, r)
	}
	db.First(&row, "provider_message_id = ?", msg)
	if row.Status != "delivered" {
		t.Fatalf("trạng thái cuối không được đổi: %+v", row)
	}

	// sent -> failed, lưu lý do
	req2 := validEmailReq()
	req2["idempotency_key"] = "otp-" + u(20)
	_, s2 := call("POST", "/internal/notifications/email", "internal", req2)
	msg2 := s2["provider_message_id"].(string)
	if st, r := webhook(t, srv.URL, testSecret, body(map[string]any{"message_id": msg2, "status": "failed",
		"reason": "mailbox_not_found", "timestamp": "x"})); st != 200 || r["status"] != "failed" {
		t.Fatalf("webhook failed: %d %v", st, r)
	}
	var row2 EmailLog
	db.First(&row2, "provider_message_id = ?", msg2)
	if row2.Status != "failed" || row2.LastError == nil || !strings.Contains(*row2.LastError, "mailbox_not_found") {
		t.Fatalf("lý do failed phải được lưu: %+v", row2)
	}

	// secret rỗng -> mọi webhook bị từ chối
	t.Setenv("EMAIL_WEBHOOK_SECRET", "")
	if st, _ := webhook(t, srv.URL, "", delivered); st != 401 {
		t.Fatalf("secret rỗng phải 401, nhận %d", st)
	}

	// admin xem nhật ký email
	if st, _ := call("GET", "/api/admin/email-logs", "sv", nil); st != 403 {
		t.Fatalf("sinh viên xem email-logs phải 403")
	}
	if st, _ := call("GET", "/api/admin/email-logs?status=xyz", "admin", nil); st != 422 {
		t.Fatalf("status sai phải 422")
	}
	st, page := call("GET", "/api/admin/email-logs?status=delivered", "admin", nil)
	items, _ := page["items"].([]any)
	if st != 200 || page["total"].(float64) != 1 || len(items) != 1 {
		t.Fatalf("lọc delivered: %d %v", st, page)
	}
	it := items[0].(map[string]any)
	for _, k := range []string{"id", "user_id", "to_email", "template", "status", "provider_message_id", "last_error", "created_at", "updated_at"} {
		if _, ok := it[k]; !ok {
			t.Errorf("thiếu trường %s trong email-logs", k)
		}
	}
	if _, ok := it["code"]; ok {
		t.Error("email-logs không được có mã OTP")
	}
	if st, all := call("GET", "/api/admin/email-logs?page_size=1&user_id="+u(2), "admin", nil); st != 200 || all["total"].(float64) != 2 {
		t.Fatalf("lọc theo user: %d %v", st, all)
	}
}

func TestIntegrationEmailEraseAndNoCodeInLog(t *testing.T) {
	_, call, db := setupIntegrationDB(t)
	newFakeProvider(t)
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)
	call("POST", "/internal/notifications/email", "internal", validEmailReq())
	failing := validEmailReq()
	failing["idempotency_key"] = "otp-" + u(30)
	t.Setenv("EMAIL_PROVIDER_URL", "http://127.0.0.1:9")
	call("POST", "/internal/notifications/email", "internal", failing)
	if strings.Contains(buf.String(), testCode) {
		t.Fatalf("mã OTP xuất hiện trong log:\n%s", buf.String())
	}
	if !strings.Contains(buf.String(), "sv***@student.tdtu.edu.vn") || strings.Contains(buf.String(), "sv1@student.tdtu.edu.vn") {
		t.Fatalf("log phải che email:\n%s", buf.String())
	}
	var stored []EmailLog
	db.Find(&stored)
	if dump, _ := json.Marshal(stored); strings.Contains(string(dump), testCode) {
		t.Fatalf("mã OTP không được lưu trong email_logs: %s", dump)
	}

	call("POST", "/internal/notifications/events", "internal", validEvent()) // thông báo của chủ quán u(3)
	st, body := call("POST", "/internal/users/"+u(2)+"/erase", "internal", nil)
	if st != 200 || body["emails_deleted"].(float64) != 2 || body["notifications_deleted"].(float64) != 0 {
		t.Fatalf("erase phải xóa email_logs của user: %d %v", st, body)
	}
	if st, body := call("POST", "/internal/users/"+u(2)+"/erase", "internal", nil); st != 200 || body["emails_deleted"].(float64) != 0 {
		t.Fatalf("gọi lại phải an toàn: %d %v", st, body)
	}
}
