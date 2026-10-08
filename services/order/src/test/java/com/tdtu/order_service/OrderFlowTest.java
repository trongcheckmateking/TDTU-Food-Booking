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
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

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
    static final List<String> EVENTS = Collections.synchronizedList(new ArrayList<>());
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
        FAKE.createContext("/internal/notifications/events", ex -> {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (!notificationMode.equals("ok")) {
                send(ex, 500, "{}");
                return;
            }
            EVENTS.add(Json.MAPPER.readTree(body).get("event_key").asText());
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
        assertEquals(403, call("PATCH", url, "sv", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "admin", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "owner2", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("GET", "/api/orders/" + oid, "sv2", null).status());
        assertEquals("INVALID_TRANSITION", call("PATCH", url, "owner", "{\"status\":\"completed\"}").body().get("code").asText());
        assertEquals(422, call("PATCH", url, "owner", "{\"status\":\"shipped\"}").status());
        assertEquals(200, call("PATCH", url, "owner", "{\"status\":\"confirmed\"}").status());
        assertEquals(403, call("PATCH", url, "sv", "{\"status\":\"cancelled\"}").status());
        assertEquals(200, call("PATCH", url, "owner", "{\"status\":\"completed\"}").status());
        assertEquals(409, call("PATCH", url, "admin", "{\"status\":\"cancelled\"}").status());

        Res internal = call("GET", "/internal/orders/" + oid, null, null, "X-Internal-Key", KEY);
        assertEquals(OWNER, internal.body().get("restaurant_owner_id").asText());
        assertEquals(403, call("GET", "/internal/orders/" + oid, null, null).status());
        assertEquals(404, call("GET", "/internal/orders/" + UUID.randomUUID(), null, null, "X-Internal-Key", KEY).status());
        assertTrue(EVENTS.contains(oid + ":order_completed"));
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
        String oid = checkout("sv", null);                         // Notification lỗi: đơn vẫn tạo được
        notificationMode = "ok";
        Res failed = call("GET", "/api/admin/outbox?status=failed", "admin", null);
        boolean found = false;
        for (JsonNode f : failed.body()) {
            found |= f.get("event_key").asText().equals(oid + ":order_created") && !f.get("last_error").isNull();
        }
        assertTrue(found, failed.body().toString());
        Res retry = call("POST", "/api/admin/outbox/retry", "admin", null);
        assertTrue(retry.body().get("sent").asInt() >= 1);
        assertTrue(EVENTS.contains(oid + ":order_created"));
        assertEquals(0, call("POST", "/api/admin/outbox/retry", "admin", null).body().get("sent").asInt());
        Res stats = call("GET", "/api/admin/orders/stats", "admin", null);
        assertTrue(stats.body().get("by_status").has("pending"));
        assertEquals(403, call("GET", "/api/admin/orders/stats", "owner", null).status());
        assertEquals(422, call("GET", "/api/admin/orders?date_from=07/10/2026", "admin", null).status());
        assertEquals(401, call("GET", "/api/orders/me", null, null).status());
        assertEquals(401, call("GET", "/api/orders/me", "sai-token", null).status());
    }
}
