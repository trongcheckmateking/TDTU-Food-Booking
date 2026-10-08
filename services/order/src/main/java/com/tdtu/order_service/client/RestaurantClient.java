package com.tdtu.order_service.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.tdtu.order_service.config.Env;
import com.tdtu.order_service.model.CartItem;
import com.tdtu.order_service.web.ApiError;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Báo giá từ Restaurant Service (POST /internal/quote): quán có nhận đơn không, từng món có thuộc quán,
 * còn bán, giá hiện tại. Order không bao giờ tin giá do client gửi.
 */
@Component
public class RestaurantClient {

    public record QuoteLine(String itemId, int quantity, boolean available, String reason, String name, Long price,
                            Long lineTotal) {
        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("item_id", itemId);
            m.put("quantity", quantity);
            m.put("available", available);
            m.put("reason", reason);
            m.put("name", name);
            m.put("price", price);
            m.put("line_total", lineTotal);
            return m;
        }
    }

    public record Quote(String restaurantId, String restaurantName, String ownerId, String status,
                        boolean acceptingOrders, List<QuoteLine> items, long total, boolean allAvailable) {
        public Map<String, Object> restaurantMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", restaurantId);
            m.put("name", restaurantName);
            m.put("owner_id", ownerId);
            m.put("status", status);
            m.put("accepting_orders", acceptingOrders);
            return m;
        }
    }

    public Quote quote(String restaurantId, List<CartItem> lines) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (CartItem l : lines) items.add(Map.of("item_id", l.itemId(), "quantity", l.quantity()));
        Upstream.Result r = Upstream.call("POST", Env.serviceUrl("RESTAURANT") + "/internal/quote", "Restaurant Service",
                null, true, Map.of("restaurant_id", restaurantId, "items", items), Set.of(404), null);
        if (r.status() == 404) {
            throw new ApiError(404, "RESTAURANT_NOT_FOUND", "Quán không tồn tại hoặc đã bị xóa");
        }
        JsonNode b = r.body();
        JsonNode rest = b.path("restaurant");
        JsonNode arr = b.path("items");
        if (!rest.isObject() || !arr.isArray() || !rest.path("id").isTextual() || !rest.path("owner_id").isTextual()
                || !rest.path("name").isTextual() || !rest.path("accepting_orders").isBoolean()) {
            throw new ApiError(502, "UPSTREAM_BAD_RESPONSE", "Restaurant Service trả báo giá không đúng định dạng");
        }
        List<QuoteLine> out = new ArrayList<>();
        for (JsonNode x : arr) {
            out.add(new QuoteLine(x.path("item_id").asText(), x.path("quantity").asInt(), x.path("available").asBoolean(),
                    x.path("reason").isTextual() ? x.get("reason").asText() : null,
                    x.path("name").isTextual() ? x.get("name").asText() : null,
                    x.path("price").isNumber() ? x.get("price").asLong() : null,
                    x.path("line_total").isNumber() ? x.get("line_total").asLong() : null));
        }
        return new Quote(rest.get("id").asText(), rest.get("name").asText(), rest.get("owner_id").asText(),
                rest.path("status").asText(), rest.get("accepting_orders").asBoolean(), out,
                b.path("total").asLong(), b.path("all_available").asBoolean());
    }
}
