package main

// X-Request-ID: trả lại rid hợp lệ, sinh mới (32 hex) khi thiếu / sai, có trên response lỗi và preflight CORS,
// chuyển tiếp sang Auth khi xác thực token, log truy cập ghi rid=...

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

var hex32 = regexp.MustCompile(`^[0-9a-f]{32}$`)

func TestRequestIDEchoGenerateAndForward(t *testing.T) {
	var authRid string
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authRid = r.Header.Get("X-Request-ID")
		w.WriteHeader(401)
		w.Write([]byte(`{"detail":"x","code":"TOKEN_INVALID"}`))
	}))
	defer auth.Close()
	t.Setenv("AUTH_URL", auth.URL)
	srv := httptest.NewServer(newRouter(nil, testKey, map[string]bool{"http://127.0.0.1:8000": true}, true))
	defer srv.Close()

	get := func(path string, hdr map[string]string) *http.Response {
		req, _ := http.NewRequest("GET", srv.URL+path, nil)
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp
	}
	if r := get("/khong-co", map[string]string{"X-Request-ID": "demo-rid-0001"}); r.Header.Get("X-Request-ID") != "demo-rid-0001" || r.StatusCode != 404 {
		t.Fatalf("rid hợp lệ phải được trả lại (cả response lỗi): %d %q", r.StatusCode, r.Header.Get("X-Request-ID"))
	}
	for _, bad := range []string{"", "ngan", "co dau cach!!", strings.Repeat("x", 129)} {
		hdr := map[string]string{}
		if bad != "" {
			hdr["X-Request-ID"] = bad
		}
		if r := get("/khong-co", hdr); !hex32.MatchString(r.Header.Get("X-Request-ID")) {
			t.Errorf("rid %q: phải sinh 32 hex, nhận %q", bad, r.Header.Get("X-Request-ID"))
		}
	}
	// xác thực token: Notification gọi Auth kèm đúng rid
	r := get("/api/notifications/me", map[string]string{"Authorization": "Bearer abc", "X-Request-ID": "demo-rid-0002"})
	if r.StatusCode != 401 || authRid != "demo-rid-0002" || r.Header.Get("X-Request-ID") != "demo-rid-0002" {
		t.Fatalf("chuyển tiếp rid sang Auth: %d auth=%q", r.StatusCode, authRid)
	}
	// preflight CORS cũng có rid, và trình duyệt được đọc header này
	req, _ := http.NewRequest("OPTIONS", srv.URL+"/health", nil)
	req.Header.Set("Origin", "http://127.0.0.1:8000")
	req.Header.Set("Access-Control-Request-Method", "GET")
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	if !hex32.MatchString(resp.Header.Get("X-Request-ID")) || resp.Header.Get("Access-Control-Expose-Headers") != "X-Request-ID" {
		t.Fatalf("preflight: %v", resp.Header)
	}
}

func TestAccessLogHasRid(t *testing.T) {
	var buf bytes.Buffer
	gin.DefaultWriter = &buf
	defer func() { gin.DefaultWriter = os.Stdout }()
	srv := httptest.NewServer(newRouter(nil, testKey, map[string]bool{}, false))
	defer srv.Close()
	req, _ := http.NewRequest("GET", srv.URL+"/khong-co", nil)
	req.Header.Set("X-Request-ID", "demo-rid-0003")
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	if line := buf.String(); !strings.Contains(line, "GET /khong-co 404") || !strings.Contains(line, "rid=demo-rid-0003") {
		t.Fatalf("log truy cập phải có METHOD PATH STATUS và rid: %q", line)
	}
}
