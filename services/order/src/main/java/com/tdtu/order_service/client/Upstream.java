package com.tdtu.order_service.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.tdtu.order_service.config.Env;
import com.tdtu.order_service.web.ApiError;
import com.tdtu.order_service.web.Json;
import java.io.IOException;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Gọi REST sang service khác, có timeout và ánh xạ lỗi thống nhất với 4 service còn lại:
 *   không kết nối được / quá thời gian -> 503 UPSTREAM_UNAVAILABLE
 *   5xx                                -> 502 UPSTREAM_ERROR
 *   body không phải JSON object/list   -> 502 UPSTREAM_BAD_RESPONSE
 *   4xx khác (không nằm trong allow)   -> 502 UPSTREAM_REJECTED
 */
public final class Upstream {
    private static final Logger log = LoggerFactory.getLogger(Upstream.class);
    private static final HttpClient CLIENT = HttpClient.newBuilder()
            .proxy(ProxySelector.of(null))                  // gọi thẳng service nội bộ, bỏ qua proxy hệ thống
            .connectTimeout(Duration.ofMillis((long) (Env.httpTimeoutSeconds() * 1000)))
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    public record Result(int status, JsonNode body) {}

    private Upstream() {}

    public static Result call(String method, String url, String service, String token, boolean internal,
                              Object json, Set<Integer> allow, Double timeoutSeconds) {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofMillis((long) ((timeoutSeconds != null ? timeoutSeconds : Env.httpTimeoutSeconds()) * 1000)))
                .header("Accept", "application/json");
        if (token != null) b.header("Authorization", "Bearer " + token);
        if (internal) b.header("X-Internal-Key", Env.internalKey());
        if (json != null) {
            try {
                b.header("Content-Type", "application/json")
                        .method(method, HttpRequest.BodyPublishers.ofString(Json.MAPPER.writeValueAsString(json),
                                StandardCharsets.UTF_8));
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        } else {
            b.method(method, HttpRequest.BodyPublishers.noBody());
        }
        HttpResponse<String> resp;
        try {
            resp = CLIENT.send(b.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (HttpTimeoutException e) {
            throw new ApiError(503, "UPSTREAM_UNAVAILABLE", service + " phản hồi quá thời gian chờ");
        } catch (IOException e) {
            throw new ApiError(503, "UPSTREAM_UNAVAILABLE", "Không kết nối được " + service);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiError(503, "UPSTREAM_UNAVAILABLE", "Không kết nối được " + service);
        }
        int st = resp.statusCode();
        if ((st >= 200 && st < 300) || allow.contains(st)) {
            if (st == 204) return new Result(st, Json.MAPPER.createObjectNode());
            JsonNode body;
            try {
                body = Json.MAPPER.readTree(resp.body());
            } catch (IOException e) {
                body = null;
            }
            if (body == null || !(body.isObject() || body.isArray())) {
                throw new ApiError(502, "UPSTREAM_BAD_RESPONSE", service + " trả dữ liệu không phải JSON hợp lệ");
            }
            return new Result(st, body);
        }
        if (st >= 500) {
            log.warn("{} trả {} cho {} {}", service, st, method, url);
            throw new ApiError(502, "UPSTREAM_ERROR", service + " đang gặp lỗi, vui lòng thử lại");
        }
        log.warn("{} từ chối {} {}: {}", service, method, url, st);
        throw new ApiError(502, "UPSTREAM_REJECTED", service + " từ chối yêu cầu nội bộ (HTTP " + st + ")");
    }
}
