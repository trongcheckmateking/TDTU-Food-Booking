package com.tdtu.order_service.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.tdtu.order_service.client.Upstream;
import com.tdtu.order_service.config.Env;
import com.tdtu.order_service.model.Order;
import com.tdtu.order_service.model.OutboxEvent;
import com.tdtu.order_service.web.ApiError;
import com.tdtu.order_service.web.Json;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;

/**
 * Outbox thông báo (thay NotificationClient gọi thẳng của bản TV3):
 *  - enqueue() được gọi BÊN TRONG giao dịch ghi đơn -> sự kiện không bao giờ mất khi Notification sập.
 *  - deliver() gửi sau khi commit: 2xx -> sent; lỗi -> failed + ghi lỗi, gửi lại với backoff min(300, 5·2^n) giây.
 *  - Notification chống trùng bằng UNIQUE(event_key, user_id) nên gửi lại không nhân đôi thông báo.
 *  - Luồng nền quét sự kiện đến hạn mỗi OUTBOX_INTERVAL giây (0 = tắt); admin có thể gửi lại thủ công.
 */
@Service
public class OutboxService {
    private static final Logger log = LoggerFactory.getLogger(OutboxService.class);
    public static final int MAX_ATTEMPTS = 10;
    private final JdbcTemplate jdbc;
    private ScheduledExecutorService worker;

    static final RowMapper<OutboxEvent> MAPPER = (rs, i) -> new OutboxEvent(rs.getString("id"), rs.getString("event_key"),
            rs.getString("order_id"), rs.getString("payload"), rs.getString("status"), rs.getInt("attempts"),
            rs.getString("last_error"), rs.getString("next_attempt_at"), rs.getString("created_at"), rs.getString("sent_at"));

    public OutboxService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Ghi sự kiện vào outbox (trong giao dịch của đơn). Trả event_key. */
    public String enqueue(Order o, String event, String actorRole) {
        String key = o.id() + ":" + event;
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("event_key", key);
        payload.put("event", event);
        payload.put("order_id", o.id());
        payload.put("order_code", o.id().substring(0, 8).toUpperCase());
        payload.put("student_id", o.userId());
        payload.put("owner_id", o.restaurantOwnerId());
        payload.put("restaurant_name", o.restaurantName());
        payload.put("actor_role", actorRole);
        String json;
        try {
            json = Json.MAPPER.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
        String ts = Times.now();
        Integer exists = jdbc.queryForObject("SELECT COUNT(*) FROM notification_outbox WHERE event_key=?", Integer.class, key);
        if (exists == 0) {
            jdbc.update("INSERT INTO notification_outbox (id,event_key,order_id,payload,status,attempts,next_attempt_at,"
                    + "created_at) VALUES (?,?,?,?, 'pending', 0, ?, ?)", Times.newId(), key, o.id(), json, ts, ts);
        }
        return key;
    }

    /** Gửi các sự kiện: theo danh sách key, hoặc mọi sự kiện đến hạn (includeFailedNow: bỏ qua thời điểm hẹn). */
    public Map<String, Integer> deliver(List<String> eventKeys, boolean includeFailedNow) {
        Instant now = Instant.now();
        List<OutboxEvent> candidates;
        if (eventKeys != null && !eventKeys.isEmpty()) {
            String marks = String.join(",", eventKeys.stream().map(k -> "?").toList());
            candidates = jdbc.query("SELECT * FROM notification_outbox WHERE event_key IN (" + marks + ") "
                    + "AND status IN ('pending','failed')", MAPPER, eventKeys.toArray());
        } else {
            String due = Times.iso(includeFailedNow ? now.plusSeconds(3650L * 86400) : now);
            String stale = Times.iso(now.minusSeconds(120));
            candidates = jdbc.query("SELECT * FROM notification_outbox WHERE attempts < ? AND ((status IN "
                    + "('pending','failed') AND next_attempt_at <= ?) OR (status='sending' AND next_attempt_at <= ?)) "
                    + "ORDER BY created_at LIMIT 100", MAPPER, MAX_ATTEMPTS, due, stale);
        }
        int sent = 0;
        int failed = 0;
        for (OutboxEvent ev : candidates) {
            // "giành" bản ghi để 2 luồng không gửi cùng 1 sự kiện cùng lúc
            int claimed = jdbc.update("UPDATE notification_outbox SET status='sending', next_attempt_at=? WHERE id=? "
                    + "AND status=?", Times.iso(now), ev.id(), ev.status());
            if (claimed == 0) continue;
            try {
                JsonNode body = Json.MAPPER.readTree(ev.payload());
                Upstream.call("POST", Env.serviceUrl("NOTIFICATION") + "/internal/notifications/events",
                        "Notification Service", null, true, body, Set.of(), 3.0);
                jdbc.update("UPDATE notification_outbox SET status='sent', attempts=attempts+1, sent_at=?, last_error=NULL "
                        + "WHERE id=?", Times.now(), ev.id());
                sent++;
            } catch (ApiError | JsonProcessingException e) {
                int attempts = ev.attempts() + 1;
                long delay = Math.min(300, 5L * (1L << Math.min(attempts, 6)));
                String err = e instanceof ApiError a ? a.code() + ": " + a.getMessage() : "BAD_PAYLOAD: " + e.getMessage();
                jdbc.update("UPDATE notification_outbox SET status='failed', attempts=?, last_error=?, next_attempt_at=? "
                        + "WHERE id=?", attempts, err.length() > 300 ? err.substring(0, 300) : err,
                        Times.iso(now.plusSeconds(delay)), ev.id());
                log.warn("Gửi thông báo {} thất bại (lần {}): {}", ev.eventKey(), attempts, err);
                failed++;
            }
        }
        Map<String, Integer> result = new LinkedHashMap<>();
        result.put("sent", sent);
        result.put("failed", failed);
        return result;
    }

    /** Gửi ngay sau commit, không để lỗi Notification làm hỏng phản hồi của đơn. */
    public void deliverQuietly(String eventKey) {
        try {
            deliver(List.of(eventKey), false);
        } catch (RuntimeException e) {
            log.warn("Không gửi được sự kiện {} ngay, worker sẽ gửi lại: {}", eventKey, e.getMessage());
        }
    }

    public List<Map<String, Object>> list(String status) {
        List<Object> args = new ArrayList<>();
        String sql = "SELECT id,event_key,order_id,status,attempts,last_error,created_at,sent_at FROM notification_outbox";
        if (status != null) {
            sql += " WHERE status=?";
            args.add(status);
        }
        return jdbc.query(sql + " ORDER BY created_at DESC LIMIT 200", (rs, i) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            for (String c : List.of("id", "event_key", "order_id", "status")) m.put(c, rs.getString(c));
            m.put("attempts", rs.getInt("attempts"));
            for (String c : List.of("last_error", "created_at", "sent_at")) m.put(c, rs.getString(c));
            return m;
        }, args.toArray());
    }

    @PostConstruct
    void startWorker() {
        int interval = Env.getInt("OUTBOX_INTERVAL", 15);
        if (interval <= 0) return;
        worker = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "outbox-worker");
            t.setDaemon(true);
            return t;
        });
        worker.scheduleWithFixedDelay(() -> {
            try {
                deliver(null, false);
            } catch (RuntimeException e) {                   // không để worker chết vì 1 lỗi
                log.error("Lỗi worker outbox", e);
            }
        }, interval, interval, TimeUnit.SECONDS);
    }

    @PreDestroy
    void stopWorker() {
        if (worker != null) worker.shutdownNow();
    }
}
