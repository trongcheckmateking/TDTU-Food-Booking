package main

// Cấu hình đọc từ biến môi trường và tệp .env ở thư mục gốc dự án (dùng chung cho 5 service).
// Không có giá trị bí mật mặc định: thiếu INTERNAL_KEY hoặc NOTIFICATION_DB_URL thì dừng ngay.

import (
	"bufio"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

var envLoaded bool

// projectRoot: thư mục gốc dự án = 2 cấp trên thư mục service (services/notification).
func projectRoot() string {
	if r := os.Getenv("TDTU_ROOT"); r != "" {
		return r
	}
	wd, _ := os.Getwd()
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}

func loadEnv() {
	if envLoaded {
		return
	}
	envLoaded = true
	file := os.Getenv("TDTU_ENV_FILE")
	if file == "" {
		file = filepath.Join(projectRoot(), ".env")
	}
	f, err := os.Open(file)
	if err != nil {
		return
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		i := strings.Index(line, "=")
		key := strings.TrimSpace(line[:i])
		val := strings.Trim(strings.TrimSpace(line[i+1:]), `"'`)
		if _, exists := os.LookupEnv(key); !exists {
			os.Setenv(key, val) // không ghi đè biến môi trường đã có
		}
	}
}

func getenv(name, def string) string {
	loadEnv()
	if v := os.Getenv(name); v != "" {
		return v
	}
	return def
}

func requireEnv(name string, minLen int) (string, error) {
	v := getenv(name, "")
	if len(v) < minLen {
		return "", fmt.Errorf("thiếu cấu hình %s (tối thiểu %d ký tự). Chạy `python manage.py init-env` để tạo tệp .env", name, minLen)
	}
	return v, nil
}

var defaultPorts = map[string]int{"AUTH": 8001, "RESTAURANT": 8002, "ORDER": 8003, "NOTIFICATION": 8004, "REVIEW": 8005}

func serviceURL(name string) string {
	return strings.TrimRight(getenv(name+"_URL", fmt.Sprintf("http://127.0.0.1:%d", defaultPorts[name])), "/")
}

func listenAddr() string {
	host := getenv("BIND_HOST", "127.0.0.1")
	port := strconv.Itoa(defaultPorts["NOTIFICATION"])
	if u, err := url.Parse(serviceURL("NOTIFICATION")); err == nil && u.Port() != "" {
		port = u.Port()
	}
	return host + ":" + port
}

func corsOrigins() map[string]bool {
	out := map[string]bool{}
	for _, o := range strings.Split(getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"), ",") {
		if o = strings.TrimSpace(o); o != "" {
			out[o] = true
		}
	}
	return out
}

func httpTimeout() time.Duration {
	f, err := strconv.ParseFloat(getenv("HTTP_TIMEOUT", "5"), 64)
	if err != nil || f <= 0 {
		f = 5
	}
	return time.Duration(f * float64(time.Second))
}
