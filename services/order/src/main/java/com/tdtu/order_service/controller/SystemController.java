package com.tdtu.order_service.controller;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.service.OrderService;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** Health, tài liệu API (Swagger/ReDoc từ openapi.json) và API nội bộ cho Review Service. */
@RestController
public class SystemController {
    private final JdbcTemplate jdbc;
    private final AuthClient auth;
    private final OrderService orders;
    private final String spec;

    public SystemController(JdbcTemplate jdbc, AuthClient auth, OrderService orders) throws IOException {
        this.jdbc = jdbc;
        this.auth = auth;
        this.orders = orders;
        try (InputStream in = getClass().getResourceAsStream("/openapi.json")) {
            this.spec = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @GetMapping("/")
    public Map<String, Object> root() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("service", "order");
        m.put("status", "ok");
        m.put("docs", "/docs");
        return m;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        boolean ok;
        try {
            ok = Integer.valueOf(1).equals(jdbc.queryForObject("SELECT 1", Integer.class));
        } catch (RuntimeException e) {
            ok = false;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("service", "order");
        m.put("status", ok ? "ok" : "degraded");
        m.put("db", ok ? "ok" : "error");
        return ResponseEntity.status(ok ? 200 : 503).body(m);
    }

    @GetMapping(value = "/openapi.json", produces = MediaType.APPLICATION_JSON_VALUE)
    public String openapi() {
        return spec;
    }

    @GetMapping(value = "/docs", produces = MediaType.TEXT_HTML_VALUE)
    public String docs() {
        return "<!doctype html><html><head><meta charset=\"utf-8\"><title>Order Service - API docs</title>"
                + "<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css\">"
                + "</head><body><div id=\"swagger-ui\"></div>"
                + "<script src=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js\"></script>"
                + "<script>SwaggerUIBundle({url:\"/openapi.json\",dom_id:\"#swagger-ui\",persistAuthorization:true});"
                + "</script></body></html>";
    }

    @GetMapping(value = "/redoc", produces = MediaType.TEXT_HTML_VALUE)
    public String redoc() {
        return "<!doctype html><html><head><meta charset=\"utf-8\"><title>Order Service - API docs</title></head><body>"
                + "<redoc spec-url=\"/openapi.json\"></redoc>"
                + "<script src=\"https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js\"></script>"
                + "</body></html>";
    }

    /** Chi tiết đơn cho service nội bộ (Review kiểm tra điều kiện đánh giá). Cần X-Internal-Key. */
    @GetMapping("/internal/orders/{oid}")
    public Map<String, Object> internalOrder(HttpServletRequest req, @PathVariable String oid) {
        auth.requireInternal(req);
        return OrderService.toJson(orders.load(Json.uuidParam(oid, "oid")), true);
    }
}
