package main

// Test của Notification Service (go test).
//  - Unit: quy tắc người nhận, kiểm tra body sự kiện, ánh xạ lỗi gọi Auth.
//  - Tích hợp với PostgreSQL thật: chạy khi có biến NOTIFICATION_TEST_DB_URL (bảng được tạo trong schema riêng
//    và xóa sau test); Auth được thay bằng server giả.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

)

const testKey = "test-internal-key-yyyyyyyyyyyyyyyy"

func u(n int) string { return fmt.Sprintf("00000000-0000-4000-8000-%012d", n) }

func TestRecipients(t *testing.T) {
	ev := OrderEvent{EventKey: "k123456789", OrderID: u(1), OrderCode: "ABC", StudentID: u(2), OwnerID: u(3), RestaurantName: "Quán"}
	who := func(event, actor string) []string {
		e := ev
		e.Event, e.ActorRole = event, actor
		var out []string
		for _, r := range recipients(e) {
			out = append(out, r.UserID[len(r.UserID)-1:])
		}
		return out
	}
	cases := map[string][]string{
		"order_created/sinh_vien": {"3"}, "order_confirmed/chu_quan": {"2"}, "order_completed/chu_quan": {"2"},
		"order_cancelled/sinh_vien": {"3"}, "order_cancelled/chu_quan": {"2"}, "order_cancelled/admin": {"2", "3"},
	}
	for k, want := range cases {
		p := strings.Split(k, "/")
		if got := who(p[0], p[1]); strings.Join(got, ",") != strings.Join(want, ",") {
			t.Errorf("%s: got %v want %v", k, got, want)
		}
	}
}

func validEvent() map[string]any {
	return map[string]any{"event_key": u(1) + ":order_created", "event": "order_created", "order_id": u(1),
		"order_code": "00000000", "student_id": u(2), "owner_id": u(3), "restaurant_name": "Quán Test", "actor_role": "sinh_vien"}
}

func TestParseEvent(t *testing.T) {
	ok, _ := json.Marshal(validEvent())
	if _, err := parseEvent(ok); err != nil {
		t.Fatalf("event hợp lệ bị từ chối: %v", err)
	}
	bad := []func(m map[string]any){
		func(m map[string]any) { m["event"] = "order_deleted" },
		func(m map[string]any) { m["actor_role"] = "hacker" },
		func(m map[string]any) { m["student_id"] = "khong-phai-uuid" },
		func(m map[string]any) { m["event_key"] = "ngan" },
		func(m map[string]any) { m["restaurant_name"] = "   " },
		func(m map[string]any) { m["la"] = 1 },
		func(m map[string]any) { delete(m, "owner_id") },
		func(m map[string]any) { m["order_code"] = 123 },
	}
	for i, f := range bad {
		m := validEvent()
		f(m)
		raw, _ := json.Marshal(m)
		_, err := parseEvent(raw)
		if e, isApi := err.(*ApiError); !isApi || e.Status != 422 {
			t.Errorf("case %d: mong đợi 422, nhận %v", i, err)
		}
	}
	if _, err := parseEvent([]byte(`{"event":`)); err == nil || err.(*ApiError).Message != "JSON gửi lên không hợp lệ" {
		t.Errorf("JSON hỏng phải trả 422 JSON gửi lên không hợp lệ")
	}
}

func TestCallServiceErrorMapping(t *testing.T) {
	os.Setenv("HTTP_TIMEOUT", "0.5")
	mk := func(h http.HandlerFunc) string { return httptest.NewServer(h).URL }
	cases := []struct {
		url  string
		code string
	}{
		{mk(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(500) }), "UPSTREAM_ERROR"},
		{mk(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("<html>")) }), "UPSTREAM_BAD_RESPONSE"},
		{mk(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404); w.Write([]byte("{}")) }), "UPSTREAM_REJECTED"},
		{mk(func(w http.ResponseWriter, r *http.Request) { time.Sleep(time.Second) }), "UPSTREAM_UNAVAILABLE"},
		{"http://127.0.0.1:9", "UPSTREAM_UNAVAILABLE"},
	}
	for _, c := range cases {
		_, _, err := callService("GET", c.url, "X", "")
		if e, ok := err.(*ApiError); !ok || e.Code != c.code {
			t.Errorf("%s: mong đợi %s, nhận %v", c.url, c.code, err)
		}
	}
}

// ---------------------------------------------------------------- tích hợp với PostgreSQL
func setupIntegration(t *testing.T) (*httptest.Server, func(method, path, token string, body any) (int, map[string]any)) {
	dsn := os.Getenv("NOTIFICATION_TEST_DB_URL")
	if dsn == "" {
		t.Skip("bỏ qua: chưa đặt NOTIFICATION_TEST_DB_URL (PostgreSQL dùng cho test)")
	}
	schema := fmt.Sprintf("test_%d", time.Now().UnixNano())
	sep := "?"
	if strings.Contains(dsn, "?") {
		sep = "&"
	}
	admin, err := openDB(dsn)
	if err != nil {
		t.Fatal(err)
	}
	admin.Exec("CREATE SCHEMA " + schema)
	db, err := openDB(dsn + sep + "search_path=" + schema)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Exec("DROP SCHEMA " + schema + " CASCADE") })

	users := map[string]map[string]any{
		"sv":    {"id": u(2), "role": "sinh_vien", "name": "SV", "status": "active"},
		"owner": {"id": u(3), "role": "chu_quan", "name": "CQ", "status": "active"},
		"admin": {"id": u(1), "role": "admin", "name": "AD", "status": "active"},
	}
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		usr, ok := users[strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")]
		if !ok {
			w.WriteHeader(401)
			w.Write([]byte(`{"detail":"x","code":"TOKEN_INVALID"}`))
			return
		}
		json.NewEncoder(w).Encode(usr)
	}))
	t.Cleanup(auth.Close)
	os.Setenv("AUTH_URL", auth.URL)
	srv := httptest.NewServer(newRouter(db, testKey, map[string]bool{"http://127.0.0.1:8000": true}, true))
	t.Cleanup(srv.Close)
	call := func(method, path, token string, body any) (int, map[string]any) {
		var rd *strings.Reader
		if body != nil {
			raw, _ := json.Marshal(body)
			rd = strings.NewReader(string(raw))
		} else {
			rd = strings.NewReader("")
		}
		req, _ := http.NewRequest(method, srv.URL+path, rd)
		req.Header.Set("Content-Type", "application/json")
		if token == "internal" {
			req.Header.Set("X-Internal-Key", testKey)
		} else if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
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
	return srv, call
}

func TestIntegrationEventsAndReading(t *testing.T) {
	_, call := setupIntegration(t)
	if st, _ := call("POST", "/internal/notifications/events", "", validEvent()); st != 403 {
		t.Fatalf("thiếu khóa nội bộ phải 403, nhận %d", st)
	}
	st, body := call("POST", "/internal/notifications/events", "internal", validEvent())
	if st != 201 || body["created"].(float64) != 1 {
		t.Fatalf("tạo sự kiện: %d %v", st, body)
	}
	st, body = call("POST", "/internal/notifications/events", "internal", validEvent())
	if st != 200 || body["duplicates"].(float64) != 1 {
		t.Fatalf("gửi lại phải không tạo trùng: %d %v", st, body)
	}
	cancel := validEvent()
	cancel["event"], cancel["actor_role"], cancel["event_key"] = "order_cancelled", "admin", u(1)+":order_cancelled"
	if st, body = call("POST", "/internal/notifications/events", "internal", cancel); body["created"].(float64) != 2 {
		t.Fatalf("admin hủy phải báo cả 2 bên: %v", body)
	}

	st, page := call("GET", "/api/notifications/me", "owner", nil)
	if st != 200 || page["total"].(float64) != 2 || page["unread"].(float64) != 2 {
		t.Fatalf("chủ quán phải có 2 thông báo chưa đọc: %v", page)
	}
	first := page["items"].([]any)[0].(map[string]any)
	if st, _ := call("PATCH", "/api/notifications/"+first["id"].(string)+"/read", "sv", nil); st != 403 {
		t.Fatalf("đánh dấu thông báo người khác phải 403, nhận %d", st)
	}
	if st, n := call("PATCH", "/api/notifications/"+first["id"].(string)+"/read", "owner", nil); st != 200 || n["status"] != "read" || n["read_at"] == nil {
		t.Fatalf("đánh dấu đã đọc: %d %v", st, n)
	}
	if _, r := call("PATCH", "/api/notifications/me/read-all", "owner", nil); r["updated"].(float64) != 1 {
		t.Fatalf("read-all: %v", r)
	}
	if st, _ := call("GET", "/api/notifications/me?status=xyz", "owner", nil); st != 422 {
		t.Fatalf("status sai phải 422")
	}
	if st, _ := call("GET", "/api/notifications/me?page_size=0", "owner", nil); st != 422 {
		t.Fatalf("page_size sai phải 422")
	}
	if st, _ := call("PATCH", "/api/notifications/khong-phai-uuid/read", "owner", nil); st != 422 {
		t.Fatalf("id sai phải 422")
	}
	if st, _ := call("GET", "/api/admin/notifications", "sv", nil); st != 403 {
		t.Fatalf("sinh viên xem admin phải 403")
	}
	st, all := call("GET", "/api/admin/notifications?user_id="+u(2), "admin", nil)
	if st != 200 || all["total"].(float64) != 1 {
		t.Fatalf("admin lọc theo user: %v", all)
	}
	id := all["items"].([]any)[0].(map[string]any)["id"].(string)
	if st, _ := call("DELETE", "/api/admin/notifications/"+id, "admin", nil); st != 204 {
		t.Fatalf("admin xóa phải 204")
	}
	if st, _ := call("DELETE", "/api/admin/notifications/"+id, "admin", nil); st != 404 {
		t.Fatalf("xóa lần 2 phải 404")
	}
	if st, _ := call("GET", "/api/notifications/me", "", nil); st != 401 {
		t.Fatalf("không token phải 401")
	}
	if st, h := call("GET", "/health", "", nil); st != 200 || h["db"] != "ok" {
		t.Fatalf("health: %v", h)
	}
}
