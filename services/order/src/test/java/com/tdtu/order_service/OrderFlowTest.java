package com.tdtu.order_service;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import com.tdtu.order_service.web.Json;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Test tích hợp Order Service: Spring Boot thật + H2 trong bộ nhớ; Auth, Restaurant, Notification được thay bằng
 * HTTP server giả (JDK HttpServer). Test liên service với 4 service thật nằm ở tests/ của dự án (pytest).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"spring.datasource.url=jdbc:h2:mem:ordertest;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000"})
class OrderFlowTest {
    static final String KEY = "test-internal-key-yyyyyyyyyyyyyyyy";
    static final String SV = "00000000-0000-4000-8000-000000000021";
    static final String SV2 = "00000000-0000-4000-8000-000000000022";
    static final String OWNER = "00000000-0000-4000-8000-000000000011";
    static final String OWNER2 = "00000000-0000-4000-8000-000000000012";
    static final String ADMIN = "00000000-0000-4000-8000-000000000001";
    static final String RID = "00000000-0000-4000-8000-000000000101";
    static final String ITEM1 = "00000000-0000-4000-8000-000000000201";
    static final String ITEM2 = "00000000-0000-4000-8000-000000000202";

    static final HttpServer FAKE;
    static final Map<String, String> ITEM_STATUS = new ConcurrentHashMap<>(Map.of(ITEM1, "available", ITEM2, "available"));
    static volatile String notificationMode = "ok";
    static volatile boolean payoutMissing = false;
    static final String BANK_ACC = "0071000123456";
    static final List<String> EVENTS = Collections.synchronizedList(new ArrayList<>());
    /** Đúng danh sách enum("event", ...) trong parseEvent của services/notification/handlers.go. */
    static final Set<String> NOTIFICATION_EVENTS = Set.of("order_created", "order_confirmed", "order_completed",
            "order_cancelled", "payment_claimed", "payment_confirmed", "payment_refunded");
    static final HttpClient HTTP = HttpClient.newBuilder().proxy(ProxySelector.of(null)).build();

    static {
        try {
            FAKE = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        FAKE.createContext("/api/users/me", ex -> {
            String token = String.valueOf(ex.getRequestHeaders().getFirst("Authorization")).replace("Bearer ", "");
            Map<String, String> users = Map.of("sv", SV + "|sinh_vien|Sinh Viên Một", "sv2", SV2 + "|sinh_vien|SV Hai",
                    "owner", OWNER + "|chu_quan|Chủ Quán", "owner2", OWNER2 + "|chu_quan|Chủ Quán 2", "admin", ADMIN + "|admin|Admin");
            String u = users.get(token);
            if (u == null) {
                send(ex, 401, "{\"detail\":\"x\",\"code\":\"TOKEN_INVALID\"}");
                return;
            }
            String[] p = u.split("\\|");
            send(ex, 200, "{\"id\":\"" + p[0] + "\",\"role\":\"" + p[1] + "\",\"name\":\"" + p[2]
                    + "\",\"phone\":\"0901234567\",\"status\":\"active\"}");
        });
        FAKE.createContext("/internal/quote", ex -> {
            JsonNode req = Json.MAPPER.readTree(ex.getRequestBody());
            if (!KEY.equals(ex.getRequestHeaders().getFirst("X-Internal-Key"))) {
                send(ex, 403, "{}");
                return;
            }
            StringBuilder items = new StringBuilder();
            long total = 0;
            boolean all = true;
            for (JsonNode l : req.get("items")) {
                String id = l.get("item_id").asText();
                int q = l.get("quantity").asInt();
                long price = id.equals(ITEM1) ? 35000 : 3000;
                String st = ITEM_STATUS.getOrDefault(id, "missing");
                boolean ok = st.equals("available");
                all &= ok;
                if (ok) total += price * q;
                if (items.length() > 0) items.append(',');
                items.append(String.format("{\"item_id\":\"%s\",\"quantity\":%d,\"available\":%s,\"reason\":%s,"
                        + "\"name\":\"%s\",\"price\":%d,\"line_total\":%d}", id, q, ok,
                        ok ? "null" : "\"ITEM_SOLD_OUT\"", id.equals(ITEM1) ? "Cơm sườn" : "Trà đá", price, price * q));
            }
            send(ex, 200, "{\"restaurant\":{\"id\":\"" + RID + "\",\"name\":\"Quán Test\",\"owner_id\":\"" + OWNER
                    + "\",\"status\":\"active\",\"accepting_orders\":true},\"items\":[" + items + "],\"total\":" + total
                    + ",\"all_available\":" + all + "}");
        });
        // Auth: tài khoản nhận tiền của chủ quán (OWNER có, chủ quán khác chưa khai báo)
        FAKE.createContext("/internal/users/", ex -> {
            if (!KEY.equals(ex.getRequestHeaders().getFirst("X-Internal-Key"))) {
                send(ex, 403, "{}");
                return;
            }
            if (payoutMissing || !ex.getRequestURI().getPath().equals("/internal/users/" + OWNER + "/payout")) {
                send(ex, 404, "{\"detail\":\"x\",\"code\":\"PAYOUT_MISSING\"}");
                return;
            }
            send(ex, 200, "{\"user_id\":\"" + OWNER + "\",\"bank_bin\":\"970436\",\"bank_name\":\"Vietcombank\","
                    + "\"bank_account\":\"" + BANK_ACC + "\",\"bank_holder\":\"NGUYEN VAN CHU\"}");
        });
        FAKE.createContext("/internal/notifications/events", ex -> {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (!notificationMode.equals("ok")) {
                send(ex, 500, "{}");
                return;
            }
            JsonNode ev = Json.MAPPER.readTree(body);
            // giống parseEvent của Notification thật (handlers.go): tên sự kiện lạ -> 422, không tạo thông báo
            if (!NOTIFICATION_EVENTS.contains(ev.path("event").asText())) {
                send(ex, 422, "{\"detail\":\"Dữ liệu không hợp lệ\",\"code\":\"VALIDATION_ERROR\"}");
                return;
            }
            EVENTS.add(ev.get("event_key").asText());
            send(ex, 201, "{\"created\":1,\"duplicates\":0}");
        });
        FAKE.setExecutor(Executors.newFixedThreadPool(8));
        FAKE.start();
        String base = "http://127.0.0.1:" + FAKE.getAddress().getPort();
        System.setProperty("tdtu.INTERNAL_KEY", KEY);
        System.setProperty("tdtu.AUTH_URL", base);
        System.setProperty("tdtu.RESTAURANT_URL", base);
        System.setProperty("tdtu.NOTIFICATION_URL", base);
        System.setProperty("tdtu.OUTBOX_INTERVAL", "0");
        System.setProperty("tdtu.PAYMENT_SWEEP_SECONDS", "0");   // test gọi expireUnpaid trực tiếp
        System.setProperty("tdtu.CORS_ORIGINS", "http://127.0.0.1:8000");
    }

    static void send(HttpExchange ex, int status, String body) throws IOException {
        byte[] b = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(status, b.length);
        ex.getResponseBody().write(b);
        ex.close();
    }

    @AfterAll
    static void stop() {
        FAKE.stop(0);
    }

    @LocalServerPort
    int port;

    record Res(int status, JsonNode body, HttpResponse<String> raw) {}

    Res call(String method, String path, String token, String json, String... headers) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .method(method, json == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(json));
        if (token != null) b.header("Authorization", "Bearer " + token);
        if (json != null) b.header("Content-Type", "application/json");
        for (int i = 0; i < headers.length; i += 2) b.header(headers[i], headers[i + 1]);
        HttpResponse<String> r = HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
        JsonNode body = r.body().isEmpty() ? null : Json.MAPPER.readTree(r.body());
        return new Res(r.statusCode(), body, r);
    }

    String addToCart(String token, String item, int q) throws Exception {
        Res r = call("POST", "/api/cart/items", token,
                "{\"restaurant_id\":\"" + RID + "\",\"item_id\":\"" + item + "\",\"quantity\":" + q + "}");
        assertEquals(200, r.status(), String.valueOf(r.body()));
        return r.body().get("total_price").asText();
    }

    String checkout(String token, String key) throws Exception {
        Res r = key == null ? call("POST", "/api/orders/checkout", token, "{\"delivery_address\":\"KTX B305\"}")
                : call("POST", "/api/orders/checkout", token, "{\"delivery_address\":\"KTX B305\"}", "Idempotency-Key", key);
        assertEquals(201, r.status(), String.valueOf(r.body()));
        return r.body().get("id").asText();
    }

    /** Sinh viên báo đã chuyển khoản, chủ quán xác nhận đã nhận tiền -> đơn đặt thành công. */
    String pay(String token, String oid) throws Exception {
        Res c = call("POST", "/api/orders/" + oid + "/payment/claim", token, null);
        assertEquals(200, c.status(), String.valueOf(c.body()));
        Res p = call("POST", "/api/orders/" + oid + "/payment/confirm", "owner", null);
        assertEquals(200, p.status(), String.valueOf(p.body()));
        assertEquals("paid", p.body().get("payment").get("status").asText());
        return oid;
    }

    String payment(String token, String oid) throws Exception {
        return call("GET", "/api/orders/" + oid, token, null).body().get("payment").get("status").asText();
    }

    @Test
    void healthDocsCors() throws Exception {
        assertEquals("{\"service\":\"order\",\"status\":\"ok\",\"db\":\"ok\"}", call("GET", "/health", null, null).raw().body());
        assertTrue(call("GET", "/openapi.json", null, null).body().get("info").get("title").asText().endsWith("Service"));
        Res pre = call("OPTIONS", "/health", null, null, "Origin", "http://127.0.0.1:8000", "Access-Control-Request-Method", "GET");
        assertEquals("http://127.0.0.1:8000", pre.raw().headers().firstValue("access-control-allow-origin").orElse(null));
        Res bad = call("GET", "/health", null, null, "Origin", "http://evil.example");
        assertTrue(bad.raw().headers().firstValue("access-control-allow-origin").isEmpty());
        assertEquals("NOT_FOUND", call("GET", "/khong-co", null, null).body().get("code").asText());
    }

    @Test
    void gioHangCheckoutChongTrungVaTrangThai() throws Exception {
        call("DELETE", "/api/cart", "sv", null);
        assertEquals("70000", addToCart("sv", ITEM1, 2));
        assertEquals("79000", addToCart("sv", ITEM2, 3));
        assertEquals(403, call("GET", "/api/cart", "owner", null).status());
        assertEquals(422, call("POST", "/api/cart/items", "sv", "{\"restaurant_id\":\"" + RID + "\",\"item_id\":\""
                + ITEM1 + "\",\"quantity\":1.5}").status());
        Res tooMany = call("POST", "/api/cart/items", "sv", "{\"restaurant_id\":\"" + RID + "\",\"item_id\":\""
                + ITEM1 + "\",\"quantity\":49}");
        assertEquals("QUANTITY_LIMIT", tooMany.body().get("code").asText());

        String key = UUID.randomUUID().toString();
        String oid = checkout("sv", key);
        Res replay = call("POST", "/api/orders/checkout", "sv", "{\"delivery_address\":\"KTX B305\"}", "Idempotency-Key", key);
        assertEquals(200, replay.status());
        assertEquals("true", replay.raw().headers().firstValue("Idempotent-Replay").orElse(""));
        assertEquals(oid, replay.body().get("id").asText());
        Res order = call("GET", "/api/orders/" + oid, "sv", null);
        assertEquals(79000, order.body().get("total_price").asLong());
        assertEquals("Sinh Viên Một", order.body().get("customer_name").asText());
        assertFalse(order.body().has("restaurant_owner_id"));
        assertEquals(0, call("GET", "/api/cart", "sv", null).body().get("item_count").asInt());
        assertEquals("CART_EMPTY", call("POST", "/api/orders/checkout", "sv", "{\"delivery_address\":\"KTX B305\"}")
                .body().get("code").asText());

        // quyền theo vai trò và máy trạng thái
        String url = "/api/orders/" + oid + "/status";
        assertEquals("NOT_PAID", call("PATCH", url, "owner", "{\"status\":\"confirmed\"}").body().get("code").asText());
        pay("sv", oid);
        assertEquals(403, call("PATCH", url, "sv", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "admin", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "owner2", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("GET", "/api/orders/" + oid, "sv2", null).status());
        assertEquals("INVALID_TRANSITION", call("PATCH", url, "owner", "{\"status\":\"completed\"}").body().get("code").asText());
        assertEquals(422, call("PATCH", url, "owner", "{\"status\":\"shipped\"}").status());
        assertEquals(200, call("PATCH", url, "owner", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "sv", "{\"status\":\"cancelled\"}").status());
        assertEquals(200, call("PATCH", url, "owner", "{\"status\":\"completed\"}").status());
        assertEquals(409, call("PATCH", url, "admin", "{\"status\":\"cancelled\"}").status());   // đơn đã xong: hết hủy

        Res internal = call("GET", "/internal/orders/" + oid, null, null, "X-Internal-Key", KEY);
        assertEquals(OWNER, internal.body().get("restaurant_owner_id").asText());
        assertEquals(403, call("GET", "/internal/orders/" + oid, null, null).status());
        assertEquals(404, call("GET", "/internal/orders/" + UUID.randomUUID(), null, null, "X-Internal-Key", KEY).status());
        assertTrue(EVENTS.contains(oid + ":order_completed"));
    }

    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    com.tdtu.order_service.service.OrderService orderService;

    @Test
    void baoCaoChuQuanTheoNgay() throws Exception {
        // so chênh lệch trên 2 ngày (hôm nay + hôm qua) để test không hỏng nếu chạy qua nửa đêm giờ Việt Nam
        String url = "/api/orders/owner/stats";
        String url2 = url + "?days=2";
        JsonNode before = call("GET", url2, "owner", null).body();
        JsonNode before2 = call("GET", url2, "owner2", null).body();
        call("DELETE", "/api/cart", "sv2", null);
        assertEquals("70000", addToCart("sv2", ITEM1, 2));
        String oid = checkout("sv2", null);
        assertEquals(before.get("period").get("orders").asLong(),
                call("GET", url2, "owner", null).body().get("period").get("orders").asLong(), "đơn chưa thanh toán chưa tính");
        pay("sv2", oid);
        JsonNode pending = call("GET", url2, "owner", null).body();
        assertEquals(before.get("open").get("pending").asInt() + 1, pending.get("open").get("pending").asInt());
        assertEquals(before.get("period").get("revenue").asLong(), pending.get("period").get("revenue").asLong(),
                "đơn chưa hoàn thành chưa tính doanh thu");

        String st = "/api/orders/" + oid + "/status";
        assertEquals(200, call("PATCH", st, "owner", "{\"status\":\"confirmed\"}").status());
        assertEquals(200, call("PATCH", st, "owner", "{\"status\":\"completed\"}").status());
        JsonNode after = call("GET", url2 + "&restaurant_id=" + RID, "owner", null).body();
        assertEquals(before.get("period").get("orders").asLong() + 1, after.get("period").get("orders").asLong());
        assertEquals(before.get("period").get("completed").asLong() + 1, after.get("period").get("completed").asLong());
        assertEquals(before.get("period").get("revenue").asLong() + 70000, after.get("period").get("revenue").asLong());
        assertEquals(before.get("open").get("pending").asInt(), after.get("open").get("pending").asInt());
        JsonNode week = call("GET", url, "owner", null).body();
        assertEquals(7, week.get("series").size());
        assertEquals(week.get("today").get("date").asText(), week.get("series").get(6).get("date").asText(), "ngày cuối là hôm nay");
        assertEquals(week.get("today").get("revenue").asLong(), week.get("series").get(6).get("revenue").asLong());
        boolean found = false;
        for (JsonNode t : after.get("top_items")) found |= t.get("item_name").asText().equals("Cơm sườn");
        assertTrue(found, String.valueOf(after.get("top_items")));
        assertEquals(30, call("GET", url + "?days=30", "owner", null).body().get("series").size());

        assertEquals(before2.get("period").get("orders").asLong(),
                call("GET", url2, "owner2", null).body().get("period").get("orders").asLong(), "chỉ thấy đơn của mình");
        assertEquals(1, call("GET", url + "?days=1", "owner", null).body().get("series").size());
        assertEquals(31, call("GET", url + "?days=31", "owner", null).body().get("series").size());
        assertEquals(422, call("GET", url + "?days=abc", "owner", null).status());
        assertEquals(403, call("GET", url, "sv", null).status());
        assertEquals(422, call("GET", url + "?days=0", "owner", null).status());
        assertEquals(422, call("GET", url + "?days=32", "owner", null).status());
        assertEquals(422, call("GET", url + "?restaurant_id=abc", "owner", null).status());
    }

    /** Ranh giới ngày theo giờ Việt Nam (UTC+7): 16:59:59Z còn là ngày hôm trước, 17:00:00Z đã sang ngày mới. */
    @Test
    void baoCaoChuQuanRanhGioiNgayVietNam() {
        String owner = "00000000-0000-4000-8000-000000000013";
        Object[][] orders = {           // created_at UTC, trạng thái, tổng tiền, món, số lượng
            {"2026-10-07T16:59:59Z", "completed", 1000, "Xôi", 1},     // 23:59:59 ngày 07/10 VN: trước kỳ -> bỏ
            {"2026-10-07T17:00:00Z", "completed", 2000, "Phở", 3},     // 00:00 ngày 08/10 VN: đầu kỳ
            {"2026-10-08T16:59:59Z", "completed", 4000, "Phở", 1},     // 23:59:59 ngày 08/10 VN
            {"2026-10-08T17:00:00Z", "completed", 8000, "Bánh mì", 5}, // 00:00 ngày 09/10 VN
            {"2026-10-09T18:00:00Z", "cancelled", 16000, "Chè", 9},    // 10/10 VN, đã hủy: không tính doanh thu, món
            {"2026-10-10T01:00:00Z", "pending", 32000, "Chè", 9},      // 10/10 VN, đang chờ
        };
        for (Object[] o : orders) {
            String oid = UUID.randomUUID().toString();
            jdbc.update("INSERT INTO orders (id,user_id,customer_name,restaurant_id,restaurant_name,restaurant_owner_id,status,"
                    + "total_price,delivery_address,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    oid, SV, "SV", RID, "Quán Test", owner, o[1], o[2], "KTX", o[0], o[0]);
            jdbc.update("INSERT INTO order_items (id,order_id,item_id,item_name,quantity,price,line_total) VALUES (?,?,?,?,?,?,?)",
                    UUID.randomUUID().toString(), oid, ITEM1, o[3], o[4], o[2], o[2]);
        }
        Map<String, Object> m = orderService.report(owner, null, 3, java.time.LocalDate.of(2026, 10, 10));
        assertEquals("[{date=2026-10-08, orders=2, completed=2, cancelled=0, revenue=6000}, "
                + "{date=2026-10-09, orders=1, completed=1, cancelled=0, revenue=8000}, "
                + "{date=2026-10-10, orders=2, completed=0, cancelled=1, revenue=0}]", m.get("series").toString());
        assertEquals("{orders=5, completed=3, cancelled=1, revenue=14000}", m.get("period").toString());
        assertEquals("{date=2026-10-10, orders=2, completed=0, cancelled=1, revenue=0}", m.get("today").toString());
        assertEquals("{pending=1, confirmed=0}", m.get("open").toString());
        assertEquals("[{item_name=Bánh mì, quantity=5, revenue=8000}, {item_name=Phở, quantity=4, revenue=6000}]",
                m.get("top_items").toString(), "chỉ món của đơn hoàn thành trong kỳ, nhiều phần nhất trước");
        // admin: cùng ngày đó, toàn hệ thống >= phần của chủ quán này
        Map<String, Object> all = orderService.report(null, null, 3, java.time.LocalDate.of(2026, 10, 10));
        assertTrue(((Number) ((Map<?, ?>) all.get("period")).get("revenue")).longValue() >= 14000);
    }

    @Test
    void baoCaoAdminChiChoAdmin() throws Exception {
        assertEquals(200, call("GET", "/api/admin/orders/report?days=30", "admin", null).status());
        assertEquals(30, call("GET", "/api/admin/orders/report?days=30", "admin", null).body().get("series").size());
        assertEquals(403, call("GET", "/api/admin/orders/report", "owner", null).status());
        assertEquals(403, call("GET", "/api/admin/orders/report", "sv", null).status());
        assertEquals(422, call("GET", "/api/admin/orders/report?days=40", "admin", null).status());
        JsonNode own = call("GET", "/api/orders/owner/stats?days=30", "owner", null).body();
        JsonNode all = call("GET", "/api/admin/orders/report?days=30", "admin", null).body();
        assertTrue(all.get("period").get("orders").asLong() >= own.get("period").get("orders").asLong());
    }

    @Test
    void checkoutDongThoiChiTaoMotDon() throws Exception {
        call("DELETE", "/api/cart", "sv2", null);
        addToCart("sv2", ITEM1, 1);
        String key = UUID.randomUUID().toString();
        ExecutorService pool = Executors.newFixedThreadPool(4);
        List<Future<Res>> fs = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            fs.add(pool.submit(() -> call("POST", "/api/orders/checkout", "sv2", "{\"delivery_address\":\"KTX B305\"}",
                    "Idempotency-Key", key)));
        }
        java.util.Set<String> ids = new java.util.HashSet<>();
        for (Future<Res> f : fs) {
            Res r = f.get();
            assertTrue(List.of(200, 201, 409).contains(r.status()), r.status() + " " + r.body());
            if (r.status() != 409) ids.add(r.body().get("id").asText());
        }
        assertEquals(1, ids.size());
        // không có key: giỏ chỉ được đặt 1 lần
        addToCart("sv2", ITEM2, 1);
        fs.clear();
        for (int i = 0; i < 3; i++) {
            fs.add(pool.submit(() -> call("POST", "/api/orders/checkout", "sv2", "{\"delivery_address\":\"KTX B305\"}")));
        }
        int created = 0;
        for (Future<Res> f : fs) created += f.get().status() == 201 ? 1 : 0;
        assertEquals(1, created);
        // đổi trạng thái đồng thời: đúng 1 thành công
        String oid = ids.iterator().next();
        pay("sv2", oid);
        call("PATCH", "/api/orders/" + oid + "/status", "owner", "{\"status\":\"confirmed\"}");
        fs.clear();
        for (String st : List.of("completed", "cancelled", "completed", "cancelled")) {
            fs.add(pool.submit(() -> call("PATCH", "/api/orders/" + oid + "/status", "owner", "{\"status\":\"" + st + "\"}")));
        }
        int ok = 0;
        for (Future<Res> f : fs) {
            int s = f.get().status();
            if (s == 200) ok++;
            else assertEquals(409, s);
        }
        assertEquals(1, ok);
        pool.shutdown();
    }

    @Test
    void monHetGiuNguyenGioVaOutboxGuiLai() throws Exception {
        call("DELETE", "/api/cart", "sv", null);
        addToCart("sv", ITEM2, 1);
        ITEM_STATUS.put(ITEM2, "sold_out");
        Res r = call("POST", "/api/orders/checkout", "sv", "{\"delivery_address\":\"KTX B305\"}");
        ITEM_STATUS.put(ITEM2, "available");
        assertEquals("ITEMS_UNAVAILABLE", r.body().get("code").asText());
        assertEquals("ITEM_SOLD_OUT", r.body().get("items").get(0).get("reason").asText());
        assertEquals(1, call("GET", "/api/cart", "sv", null).body().get("item_count").asInt());

        notificationMode = "down";
        String oid = pay("sv", checkout("sv", null));             // Notification lỗi: đơn vẫn tạo và thanh toán được
        notificationMode = "ok";
        Res failed = call("GET", "/api/admin/outbox?status=failed", "admin", null);
        boolean found = false;
        for (JsonNode f : failed.body()) {
            found |= f.get("event_key").asText().equals(oid + ":payment_claimed") && !f.get("last_error").isNull();
        }
        assertTrue(found, failed.body().toString());
        Res retry = call("POST", "/api/admin/outbox/retry", "admin", null);
        assertTrue(retry.body().get("sent").asInt() >= 1);
        assertTrue(EVENTS.contains(oid + ":payment_claimed") && EVENTS.contains(oid + ":payment_confirmed"));
        assertEquals(0, call("POST", "/api/admin/outbox/retry", "admin", null).body().get("sent").asInt());
        Res stats = call("GET", "/api/admin/orders/stats", "admin", null);
        assertTrue(stats.body().get("by_status").has("pending"));
        assertEquals(403, call("GET", "/api/admin/orders/stats", "owner", null).status());
        assertEquals(422, call("GET", "/api/admin/orders?date_from=07/10/2026", "admin", null).status());
        assertEquals(401, call("GET", "/api/orders/me", null, null).status());
        assertEquals(401, call("GET", "/api/orders/me", "sai-token", null).status());
    }

    String pickupCode(String token, String oid) throws Exception {
        return call("GET", "/api/orders/" + oid, token, null).body().get("pickup_code").asText();
    }

    @Test
    void maNhanMon3ChuSoTangDanKhongTrungVaQuayVong() throws Exception {
        // đặt liên tiếp: 3 chữ số, tăng dần theo quán
        call("DELETE", "/api/cart", "sv2", null);
        addToCart("sv2", ITEM2, 1);
        String a = pickupCode("sv2", checkout("sv2", null));
        addToCart("sv2", ITEM2, 1);
        String b = pickupCode("sv2", checkout("sv2", null));
        assertTrue(a.matches("[0-9]{3}") && b.matches("[0-9]{3}"), a + " " + b);
        assertEquals(Integer.parseInt(a) % 999 + 1, Integer.parseInt(b));

        // 2 sinh viên đặt cùng lúc ở cùng quán: mã khác nhau
        for (String t : new String[] {"sv", "sv2"}) {
            call("DELETE", "/api/cart", t, null);
            addToCart(t, ITEM2, 1);
        }
        ExecutorService pool = Executors.newFixedThreadPool(2);
        List<Future<String>> fs = new ArrayList<>();
        for (String t : new String[] {"sv", "sv2"}) fs.add(pool.submit(() -> pickupCode(t, checkout(t, null))));
        String c1 = fs.get(0).get(), c2 = fs.get(1).get();
        pool.shutdown();
        assertNotEquals(c1, c2);

        // sau 999 quay về 001
        String today = java.time.LocalDate.now(com.tdtu.order_service.service.OrderService.VN).toString();
        jdbc.update("UPDATE pickup_counters SET last_no=999 WHERE restaurant_id=? AND order_day=?", RID, today);
        addToCart("sv2", ITEM2, 1);
        assertEquals("001", pickupCode("sv2", checkout("sv2", null)));

        // đơn cũ chưa có mã được cấp khi khởi động; thông báo dùng mã 3 số
        String old = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO orders (id,user_id,customer_name,restaurant_id,restaurant_name,restaurant_owner_id,status,"
                + "total_price,delivery_address,created_at,updated_at) VALUES (?,?,?,?,?,?,'completed',1000,'Cổng C',"
                + "'2026-01-02T03:00:00Z','2026-01-02T03:00:00Z')", old, SV, "SV", RID, "Quán Test", OWNER);
        orderService.backfillPickupCodes();
        assertTrue(jdbc.queryForObject("SELECT pickup_code FROM orders WHERE id=?", String.class, old).matches("[0-9]{3}"));
        String svOrder = jdbc.queryForObject("SELECT id FROM orders WHERE pickup_code=? AND user_id=? "
                + "ORDER BY created_at DESC LIMIT 1", String.class, c1, SV);
        pay("sv", svOrder);
        String payload = jdbc.queryForObject("SELECT payload FROM notification_outbox WHERE event_key=?", String.class,
                svOrder + ":payment_claimed");
        assertEquals(c1, Json.MAPPER.readTree(payload).get("order_code").asText());
    }

    @Test
    void sinhVienKhongTuHuyDonAdminHuyDuoc() throws Exception {
        call("DELETE", "/api/cart", "sv2", null);
        addToCart("sv2", ITEM2, 1);
        String oid = pay("sv2", checkout("sv2", null));
        String url = "/api/orders/" + oid + "/status";
        Res sv = call("PATCH", url, "sv2", "{\"status\":\"cancelled\"}");          // đơn đã đặt (đã trả tiền): không tự hủy
        assertEquals(403, sv.status());
        assertEquals("FORBIDDEN", sv.body().get("code").asText());
        assertEquals("pending", call("GET", "/api/orders/" + oid, "sv2", null).body().get("status").asText());
        assertEquals(403, call("PATCH", url, "admin", "{\"status\":\"confirmed\"}").status());  // admin không làm thay quán
        Res ad = call("PATCH", url, "admin", "{\"status\":\"cancelled\",\"reason\":\"Sinh viên nhờ hủy\"}");
        assertEquals(200, ad.status());
        assertEquals("admin", ad.body().get("cancelled_by").asText());
        assertEquals("Sinh viên nhờ hủy", ad.body().get("cancel_reason").asText());
        // đơn đã trả tiền bị hủy: quán phải hoàn tiền, bấm Đã hoàn tiền thì sinh viên được báo
        assertEquals("refund_due", ad.body().get("payment").get("status").asText());
        assertEquals(403, call("POST", "/api/orders/" + oid + "/payment/refunded", "owner2", null).status());
        Res rf = call("POST", "/api/orders/" + oid + "/payment/refunded", "owner", null);
        assertEquals(200, rf.status(), String.valueOf(rf.body()));
        assertEquals("refunded", rf.body().get("payment").get("status").asText());
        assertEquals(409, call("POST", "/api/orders/" + oid + "/payment/refunded", "owner", null).status());
        assertTrue(EVENTS.contains(oid + ":payment_refunded"));
    }

    @Test
    void thanhToanTruocQuaVietQrVaoTaiKhoanQuan() throws Exception {
        call("DELETE", "/api/cart", "sv", null);
        addToCart("sv", ITEM1, 1);
        String oid = checkout("sv", null);
        JsonNode o = call("GET", "/api/orders/" + oid, "sv", null).body();
        JsonNode p = o.get("payment");
        assertEquals("unpaid", p.get("status").asText());
        assertEquals(35000, p.get("amount").asLong());
        assertEquals("970436", p.get("bank_bin").asText());
        assertEquals(BANK_ACC, p.get("account").asText());
        assertEquals("NGUYEN VAN CHU", p.get("holder").asText());
        assertEquals("TDTU " + o.get("pickup_code").asText() + " " + oid.substring(0, 4).toUpperCase(), p.get("note").asText());
        assertTrue(java.time.Instant.parse(p.get("deadline").asText()).isAfter(java.time.Instant.now().plusSeconds(60)));
        assertFalse(EVENTS.stream().anyMatch(e -> e.startsWith(oid)), "chưa thanh toán: quán chưa được báo");

        // tab Chờ tiền của quán thấy đơn; tab Mới (đã thanh toán) chưa thấy
        String own = "/api/orders/owner?status=pending&payment_status=";
        assertTrue(call("GET", own + "unpaid,claimed", "owner", null).body().toString().contains(oid));
        assertFalse(call("GET", own + "paid", "owner", null).body().toString().contains(oid));
        assertEquals(422, call("GET", own + "da_tra", "owner", null).status());

        String base = "/api/orders/" + oid + "/payment/";
        assertEquals(403, call("POST", base + "claim", "sv2", null).status());      // không phải đơn của mình
        assertEquals(403, call("POST", base + "claim", "owner", null).status());
        Res claim = call("POST", base + "claim", "sv", null);
        assertEquals("claimed", claim.body().get("payment").get("status").asText());
        assertFalse(claim.body().get("payment").get("claimed_at").isNull());
        assertEquals("PAYMENT_STATE", call("POST", base + "claim", "sv", null).body().get("code").asText());
        assertTrue(EVENTS.contains(oid + ":payment_claimed"));
        // đang chờ quán kiểm tra tiền: sinh viên không hủy được, quán phải chọn Đã nhận / Chưa nhận được tiền
        assertEquals(403, call("PATCH", "/api/orders/" + oid + "/status", "sv", "{\"status\":\"cancelled\"}").status());
        assertEquals("PAYMENT_CHECKING", call("PATCH", "/api/orders/" + oid + "/status", "owner",
                "{\"status\":\"cancelled\"}").body().get("code").asText());
        assertEquals(403, call("POST", base + "confirm", "owner2", null).status());
        assertEquals(403, call("POST", base + "confirm", "sv", null).status());
        Res ok = call("POST", base + "confirm", "owner", null);
        assertEquals("paid", ok.body().get("payment").get("status").asText());
        assertFalse(ok.body().get("payment").get("paid_at").isNull());
        assertTrue(EVENTS.contains(oid + ":payment_confirmed"));
        assertFalse(EVENTS.contains(oid + ":order_created"), "quán tự bấm xác nhận nên không báo đơn mới lần nữa");
        assertEquals(409, call("POST", base + "confirm", "owner", null).status());
        assertEquals(409, call("POST", base + "reject", "owner", null).status());
        assertTrue(call("GET", own + "paid", "owner", null).body().toString().contains(oid));

        // sinh viên tự bỏ đơn chưa thanh toán được
        addToCart("sv", ITEM2, 1);
        String drop = checkout("sv", null);
        Res v = call("PATCH", "/api/orders/" + drop + "/status", "sv", "{\"status\":\"cancelled\",\"reason\":\"Đổi ý\"}");
        assertEquals(200, v.status(), String.valueOf(v.body()));
        assertEquals("void", v.body().get("payment").get("status").asText());
        assertEquals("sinh_vien", v.body().get("cancelled_by").asText());

        // quán không thấy tiền -> từ chối, sinh viên được báo
        addToCart("sv", ITEM2, 1);
        String rej = checkout("sv", null);
        call("POST", "/api/orders/" + rej + "/payment/claim", "sv", null);
        Res r = call("POST", "/api/orders/" + rej + "/payment/reject", "owner", "{\"reason\":\"Chưa thấy tiền vào tài khoản\"}");
        assertEquals(200, r.status(), String.valueOf(r.body()));
        assertEquals("cancelled", r.body().get("status").asText());
        assertEquals("failed", r.body().get("payment").get("status").asText());
        assertEquals("chu_quan", r.body().get("cancelled_by").asText());
        assertEquals("Chưa thấy tiền vào tài khoản", r.body().get("cancel_reason").asText());
        assertTrue(EVENTS.contains(rej + ":order_cancelled"));
        assertEquals(422, call("POST", "/api/orders/" + rej + "/payment/reject", "owner", "{\"lydo\":1}").status());

        // sinh viên đã báo chuyển mà quán không phản hồi: admin hủy giúp, quán kiểm tra rồi hoàn tiền
        addToCart("sv", ITEM2, 1);
        String stuck = checkout("sv", null);
        call("POST", "/api/orders/" + stuck + "/payment/claim", "sv", null);
        Res ad = call("PATCH", "/api/orders/" + stuck + "/status", "admin", "{\"status\":\"cancelled\",\"reason\":\"Quán không phản hồi\"}");
        assertEquals(200, ad.status(), String.valueOf(ad.body()));
        assertEquals("refund_due", ad.body().get("payment").get("status").asText());

        // quá hạn thanh toán -> hệ thống tự hủy; đơn đã thanh toán không bị đụng
        addToCart("sv", ITEM2, 1);
        String late = checkout("sv", null);
        jdbc.update("UPDATE orders SET pay_deadline='2026-01-01T00:00:00Z' WHERE id=?", late);
        assertTrue(orderService.expireUnpaid(java.time.Instant.now()) >= 1);
        JsonNode lo = call("GET", "/api/orders/" + late, "sv", null).body();
        assertEquals("cancelled", lo.get("status").asText());
        assertEquals("expired", lo.get("payment").get("status").asText());
        assertEquals("he_thong", lo.get("cancelled_by").asText());
        assertEquals("paid", payment("sv", oid));
        assertEquals("PAYMENT_STATE", call("POST", "/api/orders/" + late + "/payment/claim", "sv", null).body()
                .get("code").asText());

        // quán chưa khai báo tài khoản nhận tiền: không đặt được, giỏ giữ nguyên
        addToCart("sv", ITEM2, 1);
        payoutMissing = true;
        Res miss = call("POST", "/api/orders/checkout", "sv", "{\"delivery_address\":\"KTX B305\"}");
        payoutMissing = false;
        assertEquals(409, miss.status());
        assertEquals("OWNER_NO_PAYOUT", miss.body().get("code").asText());
        assertEquals(1, call("GET", "/api/cart", "sv", null).body().get("item_count").asInt());
        call("DELETE", "/api/cart", "sv", null);

        JsonNode st = call("GET", "/api/admin/orders/stats", "admin", null).body();
        assertTrue(st.has("awaiting_payment") && st.get("not_placed").asInt() >= 3);   // bỏ đơn, quán từ chối, quá hạn
        String adm = call("GET", "/api/admin/orders?payment_status=expired,void&page_size=100", "admin", null).body().toString();
        assertTrue(adm.contains(late) && adm.contains(drop) && !adm.contains(oid));
        assertEquals(422, call("GET", "/api/admin/orders?payment_status=paid,da_tra", "admin", null).status());
    }

    @Test
    void donTienMatBaoChuQuanNgayVaThuTienKhiHoanThanh() throws Exception {
        call("DELETE", "/api/cart", "sv2", null);
        addToCart("sv2", ITEM1, 1);
        Res r = call("POST", "/api/orders/checkout", "sv2",
                "{\"delivery_address\":\"KTX B305\",\"payment_method\":\"cash\"}");
        assertEquals(201, r.status(), String.valueOf(r.body()));
        String oid = r.body().get("id").asText();
        assertEquals("pending", r.body().get("status").asText());
        assertEquals("cash", r.body().get("payment").get("method").asText());
        assertEquals("cash", r.body().get("payment").get("status").asText());
        assertTrue(r.body().get("payment").get("account").isNull(), "tiền mặt: không cần tài khoản nhận tiền");
        // đơn tiền mặt tới quán ngay: Notification nhận đúng sự kiện order_created và mọi sự kiện đã gửi xong
        assertTrue(EVENTS.contains(oid + ":order_created"), EVENTS.toString());
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM notification_outbox WHERE order_id=? AND status<>'sent'",
                Integer.class, oid));

        // luật Payment: cash --quán xác nhận--> vẫn cash (chưa thu tiền) --quán báo hoàn thành--> paid
        String url = "/api/orders/" + oid + "/status";
        Res c = call("PATCH", url, "owner", "{\"status\":\"confirmed\"}");
        assertEquals(200, c.status(), String.valueOf(c.body()));
        assertEquals("cash", c.body().get("payment").get("status").asText());
        assertTrue(c.body().get("payment").get("paid_at").isNull());
        Res done = call("PATCH", url, "owner", "{\"status\":\"completed\"}");
        assertEquals(200, done.status(), String.valueOf(done.body()));
        assertEquals("completed", done.body().get("status").asText());
        assertEquals("paid", done.body().get("payment").get("status").asText());
        assertFalse(done.body().get("payment").get("paid_at").isNull());
        assertTrue(EVENTS.contains(oid + ":order_confirmed") && EVENTS.contains(oid + ":order_completed"));
    }

    @Autowired
    javax.sql.DataSource dataSource;

    @Test
    void schemaSqlSuaSuKienTienMatCuChuaGuiDuoc() throws Exception {
        // dữ liệu do bản cũ ghi: sự kiện "order_created_cash" bị Notification trả 422, nằm ở trạng thái failed
        String old = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO orders (id,user_id,customer_name,restaurant_id,restaurant_name,restaurant_owner_id,status,"
                + "total_price,delivery_address,created_at,updated_at,payment_method,payment_status) VALUES (?,?,?,?,?,?,"
                + "'pending',3000,'Cổng C','2026-11-01T03:00:00Z','2026-11-01T03:00:00Z','cash','cash')",
                old, SV, "SV", RID, "Quán Test", OWNER);
        String payload = "{\"event_key\":\"" + old + ":order_created_cash\",\"event\":\"order_created_cash\",\"order_id\":\""
                + old + "\",\"order_code\":\"001\",\"student_id\":\"" + SV + "\",\"owner_id\":\"" + OWNER
                + "\",\"restaurant_name\":\"Quán Test\",\"actor_role\":\"sinh_vien\"}";
        jdbc.update("INSERT INTO notification_outbox (id,event_key,order_id,payload,status,attempts,last_error,next_attempt_at,"
                + "created_at) VALUES (?,?,?,?,'failed',4,'HTTP_422: x','2099-01-01T00:00:00Z','2026-11-01T03:00:00Z')",
                UUID.randomUUID().toString(), old + ":order_created_cash", old, payload);

        // chạy lại schema.sql như lúc Order khởi động (chạy nhiều lần không hỏng dữ liệu)
        for (int i = 0; i < 2; i++) {
            try (java.sql.Connection conn = dataSource.getConnection()) {
                org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(conn,
                        new org.springframework.core.io.support.EncodedResource(
                                new org.springframework.core.io.ClassPathResource("schema.sql"), StandardCharsets.UTF_8));
            }
        }
        Map<String, Object> row = jdbc.queryForMap("SELECT * FROM notification_outbox WHERE order_id=?", old);
        assertEquals(old + ":order_created", row.get("EVENT_KEY"));
        assertEquals("pending", row.get("STATUS"));
        assertEquals(0, ((Number) row.get("ATTEMPTS")).intValue());
        assertNull(row.get("LAST_ERROR"));
        assertEquals("2026-11-01T03:00:00Z", row.get("NEXT_ATTEMPT_AT"));
        JsonNode fixed = Json.MAPPER.readTree((String) row.get("PAYLOAD"));
        assertEquals("order_created", fixed.get("event").asText());
        assertEquals(old + ":order_created", fixed.get("event_key").asText());

        // worker / admin gửi lại -> lần này Notification nhận và chủ quán được báo
        assertTrue(call("POST", "/api/admin/outbox/retry", "admin", null).body().get("sent").asInt() >= 1);
        assertTrue(EVENTS.contains(old + ":order_created"), EVENTS.toString());
    }
}
