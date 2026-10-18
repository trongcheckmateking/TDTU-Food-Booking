package com.tdtu.order_service;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.tdtu.order_service.web.Json;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import com.tdtu.order_service.controller.SystemController;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.util.Map;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * API nội bộ cho vận hành: sao lưu nóng DB (cần H2 dạng tệp nên dùng thư mục tạm riêng, không dùng DB trong bộ nhớ
 * như OrderFlowTest) và xóa dữ liệu cá nhân theo yêu cầu.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class InternalOpsTest {
    static final String KEY = OrderFlowTest.KEY;
    static final Path DIR;
    static final HttpClient HTTP = HttpClient.newBuilder().proxy(ProxySelector.of(null)).build();

    static {
        try {
            DIR = Files.createTempDirectory("order-internal-test");
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        System.setProperty("tdtu.INTERNAL_KEY", KEY);
        System.setProperty("tdtu.OUTBOX_INTERVAL", "0");
        System.setProperty("tdtu.PAYMENT_SWEEP_SECONDS", "0");
        System.setProperty("tdtu.CORS_ORIGINS", "http://127.0.0.1:8000");
    }

    @DynamicPropertySource
    static void fileDb(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", () -> "jdbc:h2:file:" + DIR.resolve("order").toString().replace('\\', '/')
                + ";LOCK_TIMEOUT=10000");
    }

    @Autowired
    JdbcTemplate jdbc;

    @LocalServerPort
    int port;

    HttpResponse<byte[]> call(String method, String path, String key) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .method(method, HttpRequest.BodyPublishers.noBody());
        if (key != null) b.header("X-Internal-Key", key);
        return HTTP.send(b.build(), HttpResponse.BodyHandlers.ofByteArray());
    }

    static JsonNode json(HttpResponse<byte[]> r) throws IOException {
        return Json.MAPPER.readTree(r.body());
    }

    void insertOrder(String id, String userId, String ownerId, String status) {
        jdbc.update("INSERT INTO orders (id,user_id,customer_name,customer_phone,restaurant_id,restaurant_name,"
                + "restaurant_owner_id,status,total_price,delivery_address,note,created_at,updated_at) "
                + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", id, userId, "Nguyễn Văn Thử", "0901234567",
                "00000000-0000-4000-8000-000000000101", "Quán Test", ownerId, status, 45000, "KTX B305",
                "Gọi trước 5 phút", "2026-10-16T03:00:00Z", "2026-10-16T03:00:00Z");
    }

    @Test
    void saoLuuNongTraVeZipKhoiPhucDuoc() throws Exception {
        assertEquals(403, call("GET", "/internal/backup", null).statusCode());
        assertEquals("INTERNAL_ONLY", json(call("GET", "/internal/backup", "sai-khoa")).get("code").asText());

        String marker = UUID.randomUUID().toString();
        insertOrder(marker, UUID.randomUUID().toString(), UUID.randomUUID().toString(), "completed");
        HttpResponse<byte[]> r = call("GET", "/internal/backup", KEY);
        assertEquals(200, r.statusCode());
        assertEquals("application/zip", r.headers().firstValue("content-type").orElse(""));
        assertEquals("no-store", r.headers().firstValue("cache-control").orElse(""));

        // giải nén vào thư mục mới, mở bằng H2 như khi khôi phục: đơn vừa ghi phải có trong bản sao lưu
        Path restored = Files.createTempDirectory("order-restore-test");
        try (ZipInputStream z = new ZipInputStream(new ByteArrayInputStream(r.body()))) {
            ZipEntry e = z.getNextEntry();
            assertNotNull(e);
            assertEquals("order.mv.db", e.getName());
            Files.copy(z, restored.resolve("order.mv.db"));
        }
        String url = "jdbc:h2:file:" + restored.resolve("order").toString().replace('\\', '/') + ";IFEXISTS=TRUE";
        try (Connection c = DriverManager.getConnection(url, "sa", "");
             ResultSet rs = c.createStatement().executeQuery("SELECT customer_name FROM orders WHERE id='" + marker + "'")) {
            assertTrue(rs.next());
            assertEquals("Nguyễn Văn Thử", rs.getString(1));
        }
        try (var files = Files.list(DIR)) {          // tệp tạm của lần sao lưu không nằm lại trong thư mục DB
            assertTrue(files.allMatch(f -> f.getFileName().toString().startsWith("order.")));
        }
    }

    @Test
    void donBanSaoLuuTamBiBoNgang() throws Exception {
        Path stale = Files.createTempDirectory(SystemController.BACKUP_PREFIX + "-cu");
        Files.writeString(stale.resolve("order.zip"), "bản cũ");
        Files.setLastModifiedTime(stale, FileTime.fromMillis(System.currentTimeMillis() - 3_600_000L));
        Path fresh = Files.createTempDirectory(SystemController.BACKUP_PREFIX + "-moi");
        try {
            assertEquals(200, call("GET", "/internal/backup", KEY).statusCode());
            assertFalse(Files.exists(stale), "bản tạm quá 10 phút bị dọn");
            assertTrue(Files.exists(fresh), "bản tạm đang được gửi không bị đụng");
        } finally {
            Files.deleteIfExists(fresh);
        }
    }

    @Test
    void xoaDuLieuCaNhanAnDanhDonVaChanKhiConDonDangXuLy() throws Exception {
        String sv = UUID.randomUUID().toString(), owner = UUID.randomUUID().toString();
        String o1 = UUID.randomUUID().toString(), o2 = UUID.randomUUID().toString();
        insertOrder(o1, sv, owner, "pending");
        insertOrder(o2, sv, owner, "completed");
        jdbc.update("INSERT INTO carts (id,user_id,restaurant_id,updated_at) VALUES (?,?,NULL,?)",
                UUID.randomUUID().toString(), sv, "2026-10-16T03:00:00Z");

        assertEquals(403, call("POST", "/internal/users/" + sv + "/erase", null).statusCode());
        assertEquals(422, call("POST", "/internal/users/khong-phai-uuid/erase", KEY).statusCode());
        HttpResponse<byte[]> busy = call("POST", "/internal/users/" + sv + "/erase", KEY);
        assertEquals(409, busy.statusCode());
        assertEquals("USER_HAS_ACTIVE_ORDERS", json(busy).get("code").asText());
        assertEquals(409, call("POST", "/internal/users/" + owner + "/erase", KEY).statusCode());   // chủ quán còn đơn
        assertEquals("Nguyễn Văn Thử", jdbc.queryForObject("SELECT customer_name FROM orders WHERE id=?", String.class, o2));

        // đơn đã trả tiền rồi bị hủy, quán chưa hoàn tiền: chưa xóa được (cả sinh viên lẫn chủ quán)
        jdbc.update("UPDATE orders SET status='cancelled', payment_status='refund_due', pay_account='0071000123456', "
                + "pay_holder='NGUYEN VAN CHU' WHERE id=?", o1);
        assertEquals(409, call("POST", "/internal/users/" + sv + "/erase", KEY).statusCode());
        assertEquals(409, call("POST", "/internal/users/" + owner + "/erase", KEY).statusCode());
        jdbc.update("UPDATE orders SET payment_status='refunded' WHERE id=?", o1);
        HttpResponse<byte[]> ok = call("POST", "/internal/users/" + sv + "/erase", KEY);
        assertEquals(200, ok.statusCode());
        assertEquals(2, json(ok).get("orders_anonymized").asInt());
        assertEquals(1, json(ok).get("carts_deleted").asInt());
        for (String oid : new String[] {o1, o2}) {
            Map<String, Object> row = jdbc.queryForMap("SELECT * FROM orders WHERE id=?", oid);
            assertEquals("Người dùng đã xóa", row.get("CUSTOMER_NAME"));
            assertNull(row.get("CUSTOMER_PHONE"));
            assertNull(row.get("NOTE"));
            assertEquals("(đã xóa)", row.get("DELIVERY_ADDRESS"));
            assertEquals(45000L, ((Number) row.get("TOTAL_PRICE")).longValue());     // số liệu thống kê giữ nguyên
        }
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM carts WHERE user_id=?", Integer.class, sv));
        assertEquals(200, call("POST", "/internal/users/" + sv + "/erase", KEY).statusCode());       // gọi lại an toàn
        assertEquals(0, json(call("POST", "/internal/users/" + owner + "/erase", KEY)).get("orders_anonymized").asInt());
        assertNull(jdbc.queryForObject("SELECT pay_account FROM orders WHERE id=?", String.class, o1),
                "xóa chủ quán: bỏ số tài khoản ngân hàng khỏi đơn");
    }
}
