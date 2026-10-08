package main

// Xác thực người dùng: gọi Auth `GET /api/users/me` với Bearer token để lấy danh tính, vai trò, trạng thái
// hiện tại (tài khoản khóa / token bị thu hồi bị từ chối ngay). API nội bộ: header X-Internal-Key.

import (
	"crypto/subtle"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
)

type AuthUser struct {
	ID    string
	Role  string
	Name  string
	Email string
}

var uuidRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
var roles = map[string]bool{"sinh_vien": true, "chu_quan": true, "admin": true}

func bearerToken(c *gin.Context) string {
	h := strings.TrimSpace(c.GetHeader("Authorization"))
	if len(h) > 7 && strings.EqualFold(h[:7], "bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return ""
}

func verifyToken(token string) (*AuthUser, error) {
	status, data, err := callService("GET", serviceURL("AUTH")+"/api/users/me", "Auth Service", token, 401, 403)
	if err != nil {
		return nil, err
	}
	str := func(k string) string { s, _ := data[k].(string); return s }
	if status == 401 {
		code := str("code")
		if code == "" {
			code = "TOKEN_INVALID"
		}
		return nil, apiErr(401, code, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
	}
	if status == 403 {
		code, msg := str("code"), str("detail")
		if code == "" {
			code = "ACCOUNT_LOCKED"
		}
		if msg == "" {
			msg = "Tài khoản đã bị khóa"
		}
		return nil, apiErr(403, code, msg)
	}
	id, role := str("id"), str("role")
	st, hasStatus := data["status"]
	if !uuidRe.MatchString(id) || !roles[role] || (hasStatus && st != "active") {
		return nil, apiErr(502, "UPSTREAM_BAD_RESPONSE", "Auth Service trả thông tin người dùng không đúng định dạng")
	}
	return &AuthUser{ID: strings.ToLower(id), Role: role, Name: str("name"), Email: str("email")}, nil
}

// requireUser: bắt buộc đăng nhập; roles rỗng = mọi vai trò.
func requireUser(allowed ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		token := bearerToken(c)
		if token == "" {
			writeErr(c, apiErr(401, "UNAUTHORIZED", "Cần đăng nhập (thiếu Bearer token)"))
			return
		}
		u, err := verifyToken(token)
		if err != nil {
			writeErr(c, err)
			return
		}
		if len(allowed) > 0 {
			ok := false
			for _, r := range allowed {
				ok = ok || r == u.Role
			}
			if !ok {
				writeErr(c, apiErr(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này"))
				return
			}
		}
		c.Set("user", u)
		c.Next()
	}
}

func currentUser(c *gin.Context) *AuthUser { return c.MustGet("user").(*AuthUser) }

func requireInternal(key string) gin.HandlerFunc {
	return func(c *gin.Context) {
		given := c.GetHeader("X-Internal-Key")
		if given == "" || subtle.ConstantTimeCompare([]byte(given), []byte(key)) != 1 {
			writeErr(c, apiErr(403, "INTERNAL_ONLY", "API nội bộ, chỉ service tin cậy được gọi"))
			return
		}
		c.Next()
	}
}
