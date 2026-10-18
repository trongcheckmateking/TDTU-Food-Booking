package com.tdtu.order_service.controller;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.service.OrderService;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import com.tdtu.order_service.web.ApiError;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

/**
 * Health, tài liệu API (Swagger/ReDoc từ openapi.json) và API nội bộ: chi tiết đơn cho Review Service, sao lưu nóng
 * DB cho scripts/backup.py, xóa dữ liệu cá nhân khi Auth xử lý yêu cầu xóa. Gateway chặn mọi đường /internal.
 */
@RestController
public class SystemController {
    private static final Logger log = LoggerFactory.getLogger(SystemController.class);
    private static final Object BACKUP_LOCK = new Object();
    public static final String BACKUP_PREFIX = "order-backup";
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

    /**
     * Bản sao lưu DB H2 khi service đang chạy (lệnh BACKUP TO: nhất quán theo giao dịch, không khóa bảng).
     * Trả tệp zip chứa order.mv.db; khôi phục = giải nén vào DATA_DIR khi service đã dừng. Cần X-Internal-Key.
     */
    @GetMapping("/internal/backup")
    public ResponseEntity<StreamingResponseBody> backup(HttpServletRequest req) throws IOException {
        auth.requireInternal(req);
        sweepAbandonedBackups(10 * 60_000L);
        Path dir = Files.createTempDirectory(BACKUP_PREFIX);
        Path zip = dir.resolve("order.zip");
        try {
            synchronized (BACKUP_LOCK) {               // mỗi lúc chỉ tạo 1 bản: gọi dồn dập không làm đầy /tmp
                jdbc.execute("BACKUP TO '" + zip.toString().replace("'", "''") + "'");
            }
        } catch (DataAccessException e) {
            Files.deleteIfExists(zip);
            Files.deleteIfExists(dir);
            log.error("BACKUP TO lỗi: {}", e.getMostSpecificCause().getMessage());
            throw new ApiError(500, "BACKUP_FAILED", "Không sao lưu được cơ sở dữ liệu");
        }
        long size = Files.size(zip);
        StreamingResponseBody body = out -> {
            try {
                Files.copy(zip, out);
            } finally {
                Files.deleteIfExists(zip);
                Files.deleteIfExists(dir);
            }
        };
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("application/zip")).contentLength(size)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"order-h2.zip\"")
                .header(HttpHeaders.CACHE_CONTROL, "no-store").body(body);
    }

    /**
     * Xóa bản sao lưu tạm cũ hơn maxAgeMs mà bên gọi bỏ ngang (ngắt kết nối trước khi nhận dữ liệu thì phần gửi không
     * chạy nên không tự xóa).
     */
    static void sweepAbandonedBackups(long maxAgeMs) {
        Path tmp = Path.of(System.getProperty("java.io.tmpdir"));
        long cutoff = System.currentTimeMillis() - maxAgeMs;
        try (var dirs = Files.newDirectoryStream(tmp, BACKUP_PREFIX + "*")) {
            for (Path d : dirs) {
                if (!Files.isDirectory(d) || Files.getLastModifiedTime(d).toMillis() >= cutoff) continue;
                try (var files = Files.list(d)) {
                    for (Path f : (Iterable<Path>) files::iterator) Files.deleteIfExists(f);
                }
                Files.deleteIfExists(d);
            }
        } catch (IOException e) {
            log.warn("Không dọn được bản sao lưu tạm cũ: {}", e.getMessage());
        }
    }

    /** Xóa dữ liệu cá nhân của một tài khoản (Auth gọi khi admin xử lý yêu cầu xóa dữ liệu). Cần X-Internal-Key. */
    @PostMapping("/internal/users/{uid}/erase")
    public Map<String, Object> eraseUser(HttpServletRequest req, @PathVariable String uid) {
        auth.requireInternal(req);
        return orders.eraseUser(Json.uuidParam(uid, "uid"));
    }
}
