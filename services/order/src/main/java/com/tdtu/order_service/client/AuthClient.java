package com.tdtu.order_service.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.tdtu.order_service.config.Env;
import com.tdtu.order_service.web.ApiError;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Xác thực (thay MockAuthClient/RealAuthClient của bản TV3): gọi Auth `GET /api/users/me` với Bearer token
 * để lấy danh tính, vai trò, trạng thái hiện tại; tài khoản khóa / token bị thu hồi bị từ chối ngay.
 * API nội bộ: header X-Internal-Key, so sánh hằng thời gian.
 */
@Component
public class AuthClient {
    private static final List<String> ROLES = List.of("sinh_vien", "chu_quan", "admin");

    public record AuthUser(String id, String role, String name, String phone) {}

    public AuthUser verify(String token) {
        Upstream.Result r = Upstream.call("GET", Env.serviceUrl("AUTH") + "/api/users/me", "Auth Service", token,
                false, null, Set.of(401, 403), null);
        JsonNode d = r.body();
        if (r.status() == 401) {
            throw new ApiError(401, d.path("code").isTextual() ? d.get("code").asText() : "TOKEN_INVALID",
                    "Phiên đăng nhập không hợp lệ hoặc đã hết hạn");
        }
        if (r.status() == 403) {
            throw new ApiError(403, d.path("code").isTextual() ? d.get("code").asText() : "ACCOUNT_LOCKED",
                    d.path("detail").isTextual() ? d.get("detail").asText() : "Tài khoản đã bị khóa");
        }
        String id = d.path("id").asText(null);
        String role = d.path("role").asText(null);
        if (!Json.isUuid(id) || !ROLES.contains(role) || (d.has("status") && !"active".equals(d.get("status").asText()))) {
            throw new ApiError(502, "UPSTREAM_BAD_RESPONSE", "Auth Service trả thông tin người dùng không đúng định dạng");
        }
        String phone = d.path("phone").isTextual() ? d.get("phone").asText() : null;
        return new AuthUser(id.toLowerCase(), role, d.path("name").asText(""), phone);
    }

    /** Người dùng hiện tại; roles rỗng = mọi vai trò đã đăng nhập. */
    public AuthUser require(HttpServletRequest req, String... roles) {
        String h = req.getHeader("Authorization");
        String token = null;
        if (h != null && h.strip().regionMatches(true, 0, "Bearer ", 0, 7)) token = h.strip().substring(7).strip();
        if (token == null || token.isEmpty()) {
            throw new ApiError(401, "UNAUTHORIZED", "Cần đăng nhập (thiếu Bearer token)");
        }
        AuthUser u = verify(token);
        if (roles.length > 0 && !List.of(roles).contains(u.role())) {
            throw new ApiError(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này");
        }
        return u;
    }

    public void requireInternal(HttpServletRequest req) {
        String given = req.getHeader("X-Internal-Key");
        if (given == null || !MessageDigest.isEqual(given.getBytes(StandardCharsets.UTF_8),
                Env.internalKey().getBytes(StandardCharsets.UTF_8))) {
            throw new ApiError(403, "INTERNAL_ONLY", "API nội bộ, chỉ service tin cậy được gọi");
        }
    }
}
