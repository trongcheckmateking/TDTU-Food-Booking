package com.tdtu.order_service.controller;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.service.OrderService;
import com.tdtu.order_service.service.OutboxService;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

/** Quản trị đơn hàng và outbox thông báo: /api/admin/... (chỉ admin). */
@RestController
@RequestMapping("/api/admin")
public class AdminController {
    private final AuthClient auth;
    private final OrderService orders;
    private final OutboxService outbox;

    public AdminController(AuthClient auth, OrderService orders, OutboxService outbox) {
        this.auth = auth;
        this.orders = orders;
        this.outbox = outbox;
    }

    @GetMapping("/orders")
    public Map<String, Object> list(HttpServletRequest req, @RequestParam(required = false) String status,
                                    @RequestParam(name = "restaurant_id", required = false) String restaurantId,
                                    @RequestParam(name = "user_id", required = false) String userId,
                                    @RequestParam(name = "date_from", required = false) String dateFrom,
                                    @RequestParam(name = "date_to", required = false) String dateTo,
                                    @RequestParam(required = false) String page,
                                    @RequestParam(name = "page_size", required = false) String pageSize) {
        auth.require(req, "admin");
        return orders.adminOrders(Json.enumQuery(status, "status", OrderController.STATUSES),
                Json.uuidQuery(restaurantId, "restaurant_id"), Json.uuidQuery(userId, "user_id"),
                Json.dateQuery(dateFrom, "date_from"), Json.dateQuery(dateTo, "date_to"),
                Json.intQuery(page, "page", 1, 1, 100000), Json.intQuery(pageSize, "page_size", 20, 1, 100));
    }

    @GetMapping("/orders/stats")
    public Map<String, Object> stats(HttpServletRequest req) {
        auth.require(req, "admin");
        return orders.stats();
    }

    @GetMapping("/outbox")
    public List<Map<String, Object>> outbox(HttpServletRequest req, @RequestParam(required = false) String status) {
        auth.require(req, "admin");
        return outbox.list(Json.enumQuery(status, "status", List.of("pending", "sending", "sent", "failed")));
    }

    @PostMapping("/outbox/retry")
    public Map<String, Integer> retry(HttpServletRequest req) {
        auth.require(req, "admin");
        return outbox.deliver(null, true);
    }
}
