package com.tdtu.order_service.controller;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.client.AuthClient.AuthUser;
import com.tdtu.order_service.model.Order;
import com.tdtu.order_service.model.OrderStatus;
import com.tdtu.order_service.model.Payment;
import com.tdtu.order_service.service.OrderService;
import com.tdtu.order_service.web.ApiError;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Checkout và đơn hàng: /api/orders. */
@RestController
@RequestMapping("/api/orders")
public class OrderController {
    static final List<String> STATUSES = List.of("pending", "confirmed", "completed", "cancelled");
    private final AuthClient auth;
    private final OrderService orders;

    public OrderController(AuthClient auth, OrderService orders) {
        this.auth = auth;
        this.orders = orders;
    }

    /** Đặt hàng từ giỏ. Header Idempotency-Key: bấm lại / gửi lại không tạo đơn trùng (trả 200 + Idempotent-Replay). */
    @PostMapping("/checkout")
    public ResponseEntity<Map<String, Object>> checkout(HttpServletRequest req, @RequestBody(required = false) String raw,
                                                        @RequestHeader(value = "Idempotency-Key", required = false) String key) {
        AuthUser u = auth.require(req, "sinh_vien");
        if (key != null && key.length() > 100) throw ApiError.field("Idempotency-Key", "tối đa 100 ký tự");
        Json.Body b = Json.body(raw, Set.of("delivery_address", "note", "payment_method"));
        String address = b.text("delivery_address", 3, 300, true);
        String note = b.optText("note", 500);
        String method = b.oneOf("payment_method", Payment.METHODS, false);
        b.done();
        String k = key == null || key.isBlank() ? null : key.strip();
        OrderService.CheckoutResult r = orders.checkout(u, k, address, note, method == null ? Payment.TRANSFER : method);
        if (r.replay()) {
            return ResponseEntity.ok().header("Idempotent-Replay", "true").body(OrderService.toJson(r.order(), false));
        }
        return ResponseEntity.status(201).body(OrderService.toJson(r.order(), false));
    }

    @GetMapping("/me")
    public Map<String, Object> mine(HttpServletRequest req, @RequestParam(required = false) String status,
                                    @RequestParam(required = false) String page,
                                    @RequestParam(name = "page_size", required = false) String pageSize) {
        AuthUser u = auth.require(req);
        String st = Json.enumQuery(status, "status", STATUSES);
        int p = Json.intQuery(page, "page", 1, 1, 100000);
        int s = Json.intQuery(pageSize, "page_size", 20, 1, 100);
        List<Object> args = new ArrayList<>(List.of(u.id()));
        String where = "user_id=?";
        if (st != null) { where += " AND status=?"; args.add(st); }
        return orders.page(where, args, p, s);
    }

    @GetMapping("/owner")
    public Map<String, Object> owner(HttpServletRequest req, @RequestParam(required = false) String status,
                                     @RequestParam(name = "restaurant_id", required = false) String restaurantId,
                                     @RequestParam(name = "payment_status", required = false) String paymentStatus,
                                     @RequestParam(required = false) String page,
                                     @RequestParam(name = "page_size", required = false) String pageSize) {
        AuthUser u = auth.require(req, "chu_quan");
        String st = Json.enumQuery(status, "status", STATUSES);
        String rid = Json.uuidQuery(restaurantId, "restaurant_id");
        List<String> pays = Payment.parseFilter(paymentStatus);
        int p = Json.intQuery(page, "page", 1, 1, 100000);
        int s = Json.intQuery(pageSize, "page_size", 20, 1, 100);
        List<Object> args = new ArrayList<>(List.of(u.id()));
        String where = "restaurant_owner_id=?";
        if (st != null) { where += " AND status=?"; args.add(st); }
        if (rid != null) { where += " AND restaurant_id=?"; args.add(rid); }
        if (!pays.isEmpty()) {
            where += " AND " + Payment.inSql(pays);
            args.addAll(pays);
        }
        return orders.page(where, args, p, s);
    }

    @GetMapping("/owner/stats")
    public Map<String, Object> ownerStats(HttpServletRequest req,
                                          @RequestParam(name = "restaurant_id", required = false) String restaurantId,
                                          @RequestParam(required = false) String days) {
        AuthUser u = auth.require(req, "chu_quan");
        return orders.ownerStats(u.id(), Json.uuidQuery(restaurantId, "restaurant_id"), Json.intQuery(days, "days", 7, 1, 31));
    }

    @GetMapping("/{oid}")
    public Map<String, Object> detail(HttpServletRequest req, @PathVariable String oid) {
        AuthUser u = auth.require(req);
        Order o = orders.load(Json.uuidParam(oid, "oid"));
        if (!OrderService.canView(u, o)) throw new ApiError(403, "FORBIDDEN", "Bạn không có quyền xem đơn này");
        return OrderService.toJson(o, false);
    }

    // ---------------------------------------------------------------- thanh toán trước
    /** Sinh viên: đã quét mã VietQR và chuyển khoản xong. */
    @PostMapping("/{oid}/payment/claim")
    public Map<String, Object> claimPayment(HttpServletRequest req, @PathVariable String oid) {
        return OrderService.toJson(orders.claimPayment(auth.require(req, "sinh_vien"), Json.uuidParam(oid, "oid")), false);
    }

    /** Chủ quán: tiền đã vào tài khoản -> đơn đặt thành công, bắt đầu làm món. */
    @PostMapping("/{oid}/payment/confirm")
    public Map<String, Object> confirmPayment(HttpServletRequest req, @PathVariable String oid) {
        return OrderService.toJson(orders.confirmPayment(auth.require(req, "chu_quan"), Json.uuidParam(oid, "oid")), false);
    }

    /** Chủ quán: không thấy tiền -> hủy đơn. */
    @PostMapping("/{oid}/payment/reject")
    public Map<String, Object> rejectPayment(HttpServletRequest req, @PathVariable String oid,
                                             @RequestBody(required = false) String raw) {
        AuthUser u = auth.require(req, "chu_quan");
        Json.Body b = Json.body(raw == null || raw.isBlank() ? "{}" : raw, Set.of("reason"));
        String reason = b.optText("reason", 300);
        b.done();
        return OrderService.toJson(orders.rejectPayment(u, Json.uuidParam(oid, "oid"), reason), false);
    }

    /** Chủ quán: đã chuyển trả tiền cho sinh viên (đơn đã thanh toán bị hủy). */
    @PostMapping("/{oid}/payment/refunded")
    public Map<String, Object> refunded(HttpServletRequest req, @PathVariable String oid) {
        return OrderService.toJson(orders.markRefunded(auth.require(req, "chu_quan"), Json.uuidParam(oid, "oid")), false);
    }

    /** Chủ quán: xác nhận / hoàn thành / hủy (đơn đã thanh toán); sinh viên: bỏ đơn chưa thanh toán; admin: chỉ hủy. */
    @PatchMapping("/{oid}/status")
    public Map<String, Object> status(HttpServletRequest req, @PathVariable String oid,
                                      @RequestBody(required = false) String raw) {
        AuthUser u = auth.require(req);
        String id = Json.uuidParam(oid, "oid");
        Json.Body b = Json.body(raw, Set.of("status", "reason"));
        String st = b.oneOf("status", STATUSES, true);
        String reason = b.optText("reason", 300);
        b.done();
        return OrderService.toJson(orders.updateStatus(u, id, OrderStatus.from(st), reason), false);
    }
}
