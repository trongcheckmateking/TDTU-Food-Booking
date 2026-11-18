package com.tdtu.order_service.service;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.client.AuthClient.AuthUser;
import com.tdtu.order_service.client.RestaurantClient;
import com.tdtu.order_service.client.RestaurantClient.Quote;
import com.tdtu.order_service.client.RestaurantClient.QuoteLine;
import com.tdtu.order_service.model.Cart;
import com.tdtu.order_service.model.CartItem;
import com.tdtu.order_service.model.Order;
import com.tdtu.order_service.model.OrderItem;
import com.tdtu.order_service.model.OrderStatus;
import com.tdtu.order_service.model.Payment;
import com.tdtu.order_service.config.Env;
import com.tdtu.order_service.web.ApiError;
import java.time.Instant;
import java.time.LocalDate;
import java.time.Duration;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Đơn hàng: checkout từ giỏ (chống trùng bằng Idempotency-Key, giá do server lấy từ Restaurant),
 * thanh toán trước bằng VietQR vào tài khoản chủ quán (xem Payment), đổi trạng thái theo vai trò
 * (OrderStatus.canChangeTo của bản TV3), danh sách, thống kê.
 */
@Service
public class OrderService {
    private static final Logger log = LoggerFactory.getLogger(OrderService.class);
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final RestaurantClient restaurants;
    private final CartService carts;
    private final OutboxService outbox;
    private final AuthClient auth;
    private ScheduledExecutorService sweeper;

    private static final RowMapper<Order> ORDER = (rs, i) -> new Order(rs.getString("id"), rs.getString("user_id"),
            rs.getString("customer_name"), rs.getString("customer_phone"), rs.getString("restaurant_id"),
            rs.getString("restaurant_name"), rs.getString("restaurant_owner_id"), OrderStatus.from(rs.getString("status")),
            rs.getLong("total_price"), rs.getString("delivery_address"), rs.getString("note"),
            rs.getString("cancel_reason"), rs.getString("cancelled_by"), rs.getString("created_at"),
            rs.getString("updated_at"), rs.getString("pickup_code"), new Payment(rs.getString("payment_method"),
            rs.getString("payment_status"),
            rs.getString("pay_bank_bin"), rs.getString("pay_bank_name"), rs.getString("pay_account"),
            rs.getString("pay_holder"), rs.getString("pay_note"), rs.getString("pay_deadline"),
            rs.getString("pay_claimed_at"), rs.getString("paid_at")), List.of());
    private static final RowMapper<OrderItem> ITEM = (rs, i) -> new OrderItem(rs.getString("id"), rs.getString("order_id"),
            rs.getString("item_id"), rs.getString("item_name"), rs.getInt("quantity"), rs.getLong("price"),
            rs.getLong("line_total"));

    public OrderService(JdbcTemplate jdbc, TransactionTemplate tx, RestaurantClient restaurants, CartService carts,
                        OutboxService outbox, AuthClient auth) {
        this.jdbc = jdbc;
        this.tx = tx;
        this.restaurants = restaurants;
        this.carts = carts;
        this.outbox = outbox;
        this.auth = auth;
    }

    // ---------------------------------------------------------------- đọc đơn
    private List<Order> withItems(List<Order> orders) {
        if (orders.isEmpty()) return orders;
        String marks = String.join(",", orders.stream().map(o -> "?").toList());
        Map<String, List<OrderItem>> byOrder = new HashMap<>();
        for (OrderItem it : jdbc.query("SELECT * FROM order_items WHERE order_id IN (" + marks + ") ORDER BY item_name, id",
                ITEM, orders.stream().map(Order::id).toArray())) {
            byOrder.computeIfAbsent(it.orderId(), k -> new ArrayList<>()).add(it);
        }
        return orders.stream().map(o -> o.withItems(byOrder.getOrDefault(o.id(), List.of()))).toList();
    }

    public Order load(String id) {
        List<Order> l = jdbc.query("SELECT * FROM orders WHERE id=?", ORDER, id);
        if (l.isEmpty()) throw new ApiError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn hàng");
        return withItems(l).get(0);
    }

    private Order findByKey(String userId, String key) {
        List<Order> l = jdbc.query("SELECT * FROM orders WHERE user_id=? AND idempotency_key=?", ORDER, userId, key);
        return l.isEmpty() ? null : withItems(l).get(0);
    }

    public static boolean canView(AuthUser u, Order o) {
        return "admin".equals(u.role()) || o.userId().equals(u.id()) || o.restaurantOwnerId().equals(u.id());
    }

    /** JSON trả về cho client (không lộ restaurant_owner_id, idempotency_key). */
    public static Map<String, Object> toJson(Order o, boolean internal) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", o.id());
        m.put("pickup_code", o.pickupCode());
        m.put("user_id", o.userId());
        m.put("customer_name", o.customerName());
        m.put("customer_phone", o.customerPhone());
        m.put("restaurant_id", o.restaurantId());
        m.put("restaurant_name", o.restaurantName());
        if (internal) m.put("restaurant_owner_id", o.restaurantOwnerId());
        m.put("status", o.status().getValue());
        m.put("total_price", o.totalPrice());
        m.put("delivery_address", o.deliveryAddress());
        m.put("note", o.note());
        m.put("cancel_reason", o.cancelReason());
        m.put("cancelled_by", o.cancelledBy());
        m.put("created_at", o.createdAt());
        m.put("updated_at", o.updatedAt());
        Payment p = o.payment();
        Map<String, Object> pay = new LinkedHashMap<>();
        pay.put("method", p.method());
        pay.put("status", p.status());
        pay.put("amount", o.totalPrice());
        pay.put("bank_bin", p.bankBin());
        pay.put("bank_name", p.bankName());
        pay.put("account", p.account());
        pay.put("holder", p.holder());
        pay.put("note", p.note());
        pay.put("deadline", p.deadline());
        pay.put("claimed_at", p.claimedAt());
        pay.put("paid_at", p.paidAt());
        m.put("payment", pay);
        List<Map<String, Object>> items = new ArrayList<>();
        for (OrderItem it : o.items()) {
            Map<String, Object> x = new LinkedHashMap<>();
            x.put("id", it.id());
            x.put("item_id", it.itemId());
            x.put("item_name", it.itemName());
            x.put("quantity", it.quantity());
            x.put("price", it.price());
            x.put("line_total", it.lineTotal());
            items.add(x);
        }
        m.put("items", items);
        return m;
    }

    /**
     * Tình trạng gửi thông báo của đơn, tính từ MỌI dòng outbox của đơn: none (chưa có sự kiện nào, ví dụ đơn chuyển
     * khoản chưa trả tiền), failed (có sự kiện gửi lỗi, worker sẽ gửi lại), pending (đang chờ / đang gửi), sent.
     */
    public String notificationStatus(String orderId) {
        List<String> st = jdbc.queryForList("SELECT status FROM notification_outbox WHERE order_id=?", String.class, orderId);
        if (st.isEmpty()) return "none";
        if (st.contains("failed")) return "failed";
        if (st.contains("pending") || st.contains("sending")) return "pending";
        return "sent";
    }

    /** JSON một đơn cho client = toJson(o, false) + notification_status (danh sách đơn không có trường này). */
    public Map<String, Object> view(Order o) {
        Map<String, Object> m = toJson(o, false);
        m.put("notification_status", notificationStatus(o.id()));
        return m;
    }

    public Map<String, Object> page(String where, List<Object> args, int page, int size) {
        Integer total = jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE " + where, Integer.class, args.toArray());
        List<Object> a = new ArrayList<>(args);
        a.add(size);
        a.add((page - 1) * size);
        List<Order> items = withItems(jdbc.query("SELECT * FROM orders WHERE " + where
                + " ORDER BY created_at DESC, id LIMIT ? OFFSET ?", ORDER, a.toArray()));
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("items", items.stream().map(o -> toJson(o, false)).toList());
        m.put("total", total);
        m.put("page", page);
        m.put("page_size", size);
        return m;
    }

    // ---------------------------------------------------------------- checkout
    public record CheckoutResult(Order order, boolean replay) {}

    public CheckoutResult checkout(AuthUser user, String key, String address, String note) {
        return checkout(user, key, address, note, Payment.TRANSFER);
    }

    /** method: "transfer" (chuyển khoản trước, quán chưa được báo cho tới khi xác nhận tiền) hoặc "cash" (tiền mặt khi
        nhận: đơn tới quán ngay, không cần tài khoản nhận tiền). */
    public CheckoutResult checkout(AuthUser user, String key, String address, String note, String method) {
        boolean cash = Payment.CASH_METHOD.equals(method);
        if (key != null) {
            Order prev = findByKey(user.id(), key);
            if (prev != null) return new CheckoutResult(prev, true);
        }
        Cart cart = carts.findCart(user.id());
        List<CartItem> lines = cart == null ? List.of() : carts.lines(cart.id());
        if (cart == null || lines.isEmpty() || cart.restaurantId() == null) {
            throw new ApiError(400, "CART_EMPTY", "Giỏ hàng đang trống");
        }
        // Server tự kiểm tra lại quán, món, giá qua Restaurant; không tin giá từ client
        Quote q = restaurants.quote(cart.restaurantId(), lines);
        if (!q.acceptingOrders()) throw new ApiError(409, "RESTAURANT_NOT_ACCEPTING", "Quán hiện không nhận đơn");
        List<Map<String, Object>> bad = new ArrayList<>();
        for (QuoteLine x : q.items()) {
            if (!x.available()) {
                Map<String, Object> b = new LinkedHashMap<>();
                b.put("item_id", x.itemId());
                b.put("name", x.name());
                b.put("reason", x.reason());
                bad.add(b);
            }
        }
        if (!bad.isEmpty()) {
            throw new ApiError(409, "ITEMS_UNAVAILABLE", "Một số món trong giỏ đã hết hoặc không còn bán",
                    Map.of("items", bad));
        }
        AuthClient.Payout payout = cash ? null : auth.payout(q.ownerId());   // chủ quán chưa có tài khoản nhận tiền -> 409
        String oid = Times.newId();
        Instant now = Instant.now();
        String ts = Times.iso(now);
        String deadline = Times.iso(now.plus(Duration.ofMinutes(paymentTimeoutMinutes())));
        long total = q.items().stream().mapToLong(x -> x.price() * x.quantity()).sum();
        String eventKey;
        Order[] replayed = {null};
        try {
            eventKey = tx.execute(s -> {
                Cart locked = carts.lockCart(user.id());          // xếp hàng các checkout đồng thời của cùng user
                // cùng Idempotency-Key, yêu cầu trước vừa đặt xong trong lúc yêu cầu này chờ khóa giỏ:
                // trả lại ĐÚNG đơn đó (như gửi lại tuần tự), không tạo đơn mới
                Order prev = key != null ? findByKey(user.id(), key) : null;
                if (prev != null) {
                    replayed[0] = prev;
                    return null;
                }
                if (locked == null || !carts.lines(locked.id()).equals(lines)) {
                    throw new ApiError(409, "CART_CHANGED", "Giỏ hàng vừa thay đổi hoặc đã được đặt, vui lòng kiểm tra lại");
                }
                String code = nextPickupCode(q.restaurantId(), LocalDate.now(VN).toString());
                if (cash) {
                    jdbc.update("INSERT INTO orders (id,user_id,customer_name,customer_phone,restaurant_id,restaurant_name,"
                            + "restaurant_owner_id,status,total_price,delivery_address,note,idempotency_key,created_at,"
                            + "updated_at,pickup_code,payment_method,payment_status) "
                            + "VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?,?,?,?,?, 'cash', 'cash')", oid, user.id(), user.name(),
                            user.phone(), q.restaurantId(), q.restaurantName(), q.ownerId(), total, address, note, key, ts,
                            ts, code);
                } else {
                    // nội dung chuyển khoản: mã nhận món + 4 ký tự đầu của mã đơn (quán dò trong lịch sử ngân hàng)
                    String payNote = "TDTU " + code + " " + oid.substring(0, 4).toUpperCase();
                    jdbc.update("INSERT INTO orders (id,user_id,customer_name,customer_phone,restaurant_id,restaurant_name,"
                            + "restaurant_owner_id,status,total_price,delivery_address,note,idempotency_key,created_at,"
                            + "updated_at,pickup_code,payment_method,payment_status,pay_bank_bin,pay_bank_name,pay_account,"
                            + "pay_holder,pay_note,pay_deadline) VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?,?,?,?,?, 'transfer', "
                            + "'unpaid', ?,?,?,?,?,?)", oid, user.id(), user.name(), user.phone(), q.restaurantId(),
                            q.restaurantName(), q.ownerId(), total, address, note, key, ts, ts, code, payout.bankBin(),
                            payout.bankName(), payout.account(), payout.holder(), payNote, deadline);
                }
                for (QuoteLine x : q.items()) {
                    jdbc.update("INSERT INTO order_items (id,order_id,item_id,item_name,quantity,price,line_total) "
                            + "VALUES (?,?,?,?,?,?,?)", Times.newId(), oid, x.itemId(), x.name(), x.quantity(), x.price(),
                            x.price() * x.quantity());
                }
                jdbc.update("DELETE FROM cart_items WHERE cart_id=?", locked.id());     // chỉ xóa giỏ khi thành công
                jdbc.update("UPDATE carts SET restaurant_id=NULL, updated_at=? WHERE id=?", ts, locked.id());
                // chuyển khoản: chưa báo quán, đơn chỉ "đặt thành công" khi quán xác nhận đã nhận tiền (confirmPayment);
                // tiền mặt: đơn tới quán ngay -> sự kiện order_created (Notification chỉ nhận đúng các tên sự kiện
                // trong parseEvent của handlers.go; tên khác bị trả 422 và chủ quán không bao giờ được báo)
                return cash ? outbox.enqueue(load(oid), "order_created", "sinh_vien") : null;
            });
        } catch (DuplicateKeyException e) {                    // UNIQUE(user_id, idempotency_key): yêu cầu trùng khóa vừa ghi
            Order prev = key != null ? findByKey(user.id(), key) : null;
            if (prev != null) return new CheckoutResult(prev, true);
            throw new ApiError(409, "DUPLICATE_REQUEST", "Yêu cầu đặt hàng này đã được xử lý");
        }
        if (replayed[0] != null) return new CheckoutResult(replayed[0], true);
        if (eventKey != null) outbox.deliverQuietly(eventKey);
        return new CheckoutResult(load(oid), false);
    }

    // ---------------------------------------------------------------- thanh toán trước (VietQR vào tài khoản quán)
    static long paymentTimeoutMinutes() {
        try {
            return Math.max(1, Long.parseLong(Env.get("PAYMENT_TIMEOUT_MINUTES", "15")));
        } catch (NumberFormatException e) {
            return 15;
        }
    }

    /** Đổi payment_status có điều kiện (chỉ 1 yêu cầu đồng thời thắng) + ghi sự kiện thông báo trong cùng giao dịch. */
    private Order movePayment(Order o, List<String> from, String to, String timeColumn, String actorRole, String... events) {
        String ts = Times.now();
        List<String> keys = tx.execute(s -> {
            String extra = timeColumn != null ? ", " + timeColumn + "=?" : "";   // timeColumn: hằng số trong lớp này
            List<Object> args = new ArrayList<>(List.of(to, ts));
            if (timeColumn != null) args.add(ts);
            args.add(o.id());
            args.add(o.status().getValue());
            args.addAll(from);
            int n = jdbc.update("UPDATE orders SET payment_status=?, updated_at=?" + extra + " WHERE id=? AND status=? "
                    + "AND payment_status IN (" + String.join(",", from.stream().map(x -> "?").toList()) + ")",
                    args.toArray());
            if (n == 0) throw new ApiError(409, "STATUS_CHANGED", "Đơn vừa được cập nhật bởi người khác, vui lòng tải lại");
            List<String> k = new ArrayList<>();
            for (String ev : events) k.add(outbox.enqueue(o, ev, actorRole));
            return k;
        });
        for (String k : keys) outbox.deliverQuietly(k);
        return load(o.id());
    }

    private Order ownOrder(AuthUser user, String oid, boolean owner) {
        Order o = load(oid);
        boolean mine = owner ? o.restaurantOwnerId().equals(user.id()) : o.userId().equals(user.id());
        if (!mine) throw new ApiError(403, "FORBIDDEN", owner ? "Bạn không phải chủ quán của đơn này" : "Đây không phải đơn của bạn");
        return o;
    }

    /** Sinh viên báo đã chuyển khoản -> quán được báo có đơn mới, kiểm tra tài khoản ngân hàng rồi xác nhận. */
    public Order claimPayment(AuthUser user, String oid) {
        Order o = ownOrder(user, oid, false);
        if (o.status() != OrderStatus.PENDING || !o.payment().is(Payment.UNPAID)) {
            throw new ApiError(409, "PAYMENT_STATE", "Đơn không còn ở bước chờ thanh toán");
        }
        return movePayment(o, List.of(Payment.UNPAID), Payment.CLAIMED, "pay_claimed_at", "sinh_vien", "payment_claimed");
    }

    /** Chủ quán thấy tiền đã vào tài khoản -> đơn đặt thành công, hiện ở tab Mới để làm món; báo sinh viên. */
    public Order confirmPayment(AuthUser user, String oid) {
        Order o = ownOrder(user, oid, true);
        if (o.status() != OrderStatus.PENDING || !(o.payment().is(Payment.UNPAID) || o.payment().is(Payment.CLAIMED))) {
            throw new ApiError(409, "PAYMENT_STATE", "Đơn không còn ở bước chờ thanh toán");
        }
        return movePayment(o, List.of(Payment.UNPAID, Payment.CLAIMED), Payment.PAID, "paid_at", "chu_quan",
                "payment_confirmed");
    }

    /** Chủ quán không thấy tiền -> hủy đơn, báo sinh viên. */
    public Order rejectPayment(AuthUser user, String oid, String reason) {
        Order o = ownOrder(user, oid, true);
        if (o.status() != OrderStatus.PENDING || !(o.payment().is(Payment.UNPAID) || o.payment().is(Payment.CLAIMED))) {
            throw new ApiError(409, "PAYMENT_STATE", "Đơn không còn ở bước chờ thanh toán");
        }
        String why = reason != null ? reason : "Quán chưa nhận được tiền chuyển khoản";
        String key = tx.execute(s -> {
            int n = jdbc.update("UPDATE orders SET status='cancelled', payment_status='failed', cancel_reason=?, "
                    + "cancelled_by='chu_quan', updated_at=? WHERE id=? AND status='pending' AND payment_status IN "
                    + "('unpaid','claimed')", why, Times.now(), o.id());
            if (n == 0) throw new ApiError(409, "STATUS_CHANGED", "Đơn vừa được cập nhật bởi người khác, vui lòng tải lại");
            return outbox.enqueue(o, "order_cancelled", "chu_quan");
        });
        outbox.deliverQuietly(key);
        return load(o.id());
    }

    /** Đơn đã trả tiền bị hủy -> chủ quán chuyển trả, bấm "Đã hoàn tiền" -> báo sinh viên. */
    public Order markRefunded(AuthUser user, String oid) {
        Order o = ownOrder(user, oid, true);
        if (!o.payment().is(Payment.REFUND_DUE)) throw new ApiError(409, "PAYMENT_STATE", "Đơn không cần hoàn tiền");
        return movePayment(o, List.of(Payment.REFUND_DUE), Payment.REFUNDED, null, "chu_quan", "payment_refunded");
    }

    /** Hủy đơn chưa thanh toán quá hạn (không báo ai: sinh viên thấy ngay trong app, quán chưa từng được báo). */
    public int expireUnpaid(Instant now) {
        return jdbc.update("UPDATE orders SET status='cancelled', payment_status='expired', cancel_reason=?, "
                + "cancelled_by='he_thong', updated_at=? WHERE status='pending' AND payment_status='unpaid' AND pay_deadline < ?",
                "Quá hạn thanh toán", Times.iso(now), Times.iso(now));
    }

    @PostConstruct
    void startSweeper() {
        long every;
        try {
            every = Long.parseLong(Env.get("PAYMENT_SWEEP_SECONDS", "60"));
        } catch (NumberFormatException e) {
            every = 60;
        }
        if (every <= 0) return;
        sweeper = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "payment-expiry");
            t.setDaemon(true);
            return t;
        });
        sweeper.scheduleWithFixedDelay(() -> {
            try {
                int n = expireUnpaid(Instant.now());
                if (n > 0) log.info("Đã hủy {} đơn quá hạn thanh toán", n);
            } catch (RuntimeException e) {
                log.warn("Không quét được đơn quá hạn thanh toán: {}", e.getMessage());
            }
        }, every, every, TimeUnit.SECONDS);
    }

    @PreDestroy
    void stopSweeper() {
        if (sweeper != null) sweeper.shutdownNow();
    }

    // ---------------------------------------------------------------- mã nhận món
    /**
     * Mã nhận món 3 chữ số: số thứ tự đơn trong ngày (giờ Việt Nam) của từng quán, 001 -> 999 rồi quay vòng.
     * Gọi TRONG giao dịch đặt đơn: UPDATE khóa dòng đếm nên các đơn đặt cùng lúc nhận số khác nhau.
     */
    String nextPickupCode(String restaurantId, String day) {
        String bump = "UPDATE pickup_counters SET last_no = last_no + 1 WHERE restaurant_id=? AND order_day=?";
        if (jdbc.update(bump, restaurantId, day) == 0) {
            try {
                jdbc.update("INSERT INTO pickup_counters (restaurant_id, order_day, last_no) VALUES (?,?,1)", restaurantId, day);
            } catch (DuplicateKeyException e) {          // đơn khác của quán vừa tạo dòng đếm của ngày
                jdbc.update(bump, restaurantId, day);
            }
        }
        Integer last = jdbc.queryForObject("SELECT last_no FROM pickup_counters WHERE restaurant_id=? AND order_day=?",
                Integer.class, restaurantId, day);
        return String.format("%03d", (last - 1) % 999 + 1);
    }

    /** Đơn tạo trước khi có mã nhận món: cấp mã theo đúng thứ tự đặt trong ngày của từng quán (chạy 1 lần khi khởi động). */
    @PostConstruct
    public void backfillPickupCodes() {
        List<Map<String, Object>> old = jdbc.queryForList(
                "SELECT id, restaurant_id, created_at FROM orders WHERE pickup_code IS NULL ORDER BY created_at, id");
        for (Map<String, Object> r : old) {
            String day = Instant.parse((String) r.get("created_at")).atZone(VN).toLocalDate().toString();
            tx.executeWithoutResult(s -> jdbc.update("UPDATE orders SET pickup_code=? WHERE id=? AND pickup_code IS NULL",
                    nextPickupCode((String) r.get("restaurant_id"), day), r.get("id")));
        }
    }

    // ---------------------------------------------------------------- trạng thái
    public Order updateStatus(AuthUser user, String oid, OrderStatus next, String reason) {
        Order o = load(oid);
        if (!canView(user, o)) throw new ApiError(403, "FORBIDDEN", "Bạn không có quyền với đơn này");
        switch (user.role()) {
            case "chu_quan" -> {
                if (!o.restaurantOwnerId().equals(user.id())) {
                    throw new ApiError(403, "FORBIDDEN", "Bạn không phải chủ quán của đơn này");
                }
            }
            // đơn đã thanh toán (đặt thành công) / đã báo chuyển khoản thì sinh viên không tự hủy được;
            // đơn chưa thanh toán thì bỏ được (chưa đặt thành công)
            case "sinh_vien" -> {
                if (next != OrderStatus.CANCELLED || o.status() != OrderStatus.PENDING || !o.payment().is(Payment.UNPAID)) {
                    throw new ApiError(403, "FORBIDDEN",
                            "Đơn đã đặt thì không tự hủy được. Cần hủy, hãy liên hệ quán hoặc ban quản trị");
                }
            }
            default -> {
                if (next != OrderStatus.CANCELLED) {
                    throw new ApiError(403, "FORBIDDEN", "Admin chỉ được hủy đơn, không xác nhận / hoàn thành thay chủ quán");
                }
            }
        }
        if (!o.status().canChangeTo(next)) {
            throw new ApiError(409, "INVALID_TRANSITION",
                    "Không thể chuyển đơn từ " + o.status().getValue() + " sang " + next.getValue());
        }
        boolean cancel = next == OrderStatus.CANCELLED;
        String pay = o.payment().status();
        if (!cancel && !Payment.PAID.equals(pay) && !Payment.CASH.equals(pay)) {
            throw new ApiError(409, "NOT_PAID", "Đơn chưa thanh toán xong, chưa làm món được");
        }
        if (cancel && Payment.CLAIMED.equals(pay) && !"admin".equals(user.role())) {
            throw new ApiError(409, "PAYMENT_CHECKING",
                    "Sinh viên đã báo chuyển khoản: quán cần bấm Đã nhận tiền hoặc Chưa nhận được tiền trước");
        }
        // hủy đơn đã chuyển khoản (hoặc admin hủy đơn sinh viên đã báo chuyển mà quán không phản hồi): quán kiểm tra và
        // hoàn tiền; hủy đơn chưa trả / tiền mặt: bỏ thanh toán. Tiền mặt: báo hoàn thành = đã thu tiền.
        boolean transferred = Payment.CLAIMED.equals(pay) || (Payment.PAID.equals(pay) && !o.payment().isCash());
        boolean collect = next == OrderStatus.COMPLETED && Payment.CASH.equals(pay);
        String newPay = cancel ? (transferred ? Payment.REFUND_DUE : Payment.VOID) : collect ? Payment.PAID : pay;
        String ts = Times.now();
        String eventKey = tx.execute(s -> {
            // cập nhật có điều kiện: chỉ 1 trong các request đồng thời thắng, các request còn lại nhận 409
            int n = jdbc.update("UPDATE orders SET status=?, updated_at=?, cancel_reason=?, cancelled_by=?, payment_status=?, "
                    + "paid_at=COALESCE(paid_at, ?) WHERE id=? AND status=? AND payment_status=?", next.getValue(), ts,
                    cancel ? reason : null, cancel ? user.role() : null, newPay, collect ? ts : null, o.id(),
                    o.status().getValue(), pay);
            if (n == 0) throw new ApiError(409, "STATUS_CHANGED", "Đơn vừa được cập nhật bởi người khác, vui lòng tải lại");
            return outbox.enqueue(o, "order_" + next.getValue(), user.role());
        });
        outbox.deliverQuietly(eventKey);
        return load(o.id());
    }

    // ---------------------------------------------------------------- admin
    public Map<String, Object> adminOrders(String status, String restaurantId, String userId, String dateFrom,
                                           String dateTo, List<String> payments, int page, int size) {
        StringBuilder where = new StringBuilder("1=1");
        List<Object> args = new ArrayList<>();
        if (status != null) { where.append(" AND status=?"); args.add(status); }
        if (restaurantId != null) { where.append(" AND restaurant_id=?"); args.add(restaurantId); }
        if (userId != null) { where.append(" AND user_id=?"); args.add(userId); }
        if (dateFrom != null) { where.append(" AND created_at >= ?"); args.add(dateFrom); }
        if (dateTo != null) { where.append(" AND created_at < ?"); args.add(LocalDate.parse(dateTo).plusDays(1).toString()); }
        if (!payments.isEmpty()) { where.append(" AND ").append(Payment.inSql(payments)); args.addAll(payments); }
        return page(where.toString(), args, page, size);
    }

    // ---------------------------------------------------------------- xóa dữ liệu cá nhân (Auth điều phối)
    public static final String ERASED_NAME = "Người dùng đã xóa";

    /**
     * Ẩn danh người đặt trong mọi đơn của tài khoản (tên, số điện thoại, chỗ nhận, ghi chú) và xóa giỏ hàng.
     * Số tiền, món, trạng thái được giữ để thống kê của quán không sai. Từ chối (409) khi tài khoản còn đơn đang xử lý,
     * với vai trò người đặt hoặc chủ quán. Gọi lại nhiều lần cho cùng kết quả.
     */
    public Map<String, Object> eraseUser(String userId) {
        return tx.execute(s -> {
            Integer active = jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE (user_id=? OR restaurant_owner_id=?) "
                    + "AND (status IN ('pending','confirmed') OR payment_status='refund_due')", Integer.class, userId, userId);
            if (active != null && active > 0) {
                throw new ApiError(409, "USER_HAS_ACTIVE_ORDERS", "Tài khoản còn " + active
                        + " đơn đang xử lý hoặc chờ hoàn tiền, hãy xử lý xong các đơn này trước khi xóa dữ liệu");
            }
            int anonymized = jdbc.update("UPDATE orders SET customer_name=?, customer_phone=NULL, delivery_address=?, "
                    + "note=NULL WHERE user_id=?", ERASED_NAME, "(đã xóa)", userId);
            int cartsDeleted = jdbc.update("DELETE FROM carts WHERE user_id=?", userId);
            jdbc.update("UPDATE orders SET pay_account=NULL, pay_holder=NULL WHERE restaurant_owner_id=?", userId);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("user_id", userId);
            m.put("orders_anonymized", anonymized);
            m.put("carts_deleted", cartsDeleted);
            return m;
        });
    }

    // ---------------------------------------------------------------- chủ quán: báo cáo
    /** Ngày làm việc của quán tính theo giờ Việt Nam (đơn lưu created_at dạng UTC). */
    public static final ZoneId VN = ZoneId.of("Asia/Ho_Chi_Minh");

    /**
     * Báo cáo cho chủ quán trong `days` ngày gần nhất (tính cả hôm nay, giờ Việt Nam): số đơn / đơn hoàn thành /
     * doanh thu (chỉ đơn hoàn thành) theo từng ngày, tổng kỳ, hôm nay, món bán chạy và số đơn đang chờ xử lý.
     * Đơn được tính vào ngày đặt (created_at), kể cả khi hoàn thành sau nửa đêm.
     */
    public Map<String, Object> ownerStats(String ownerId, String restaurantId, int days) {
        return report(ownerId, restaurantId, days, LocalDate.now(VN));
    }

    /** Báo cáo toàn hệ thống cho admin (cùng dạng với báo cáo chủ quán). */
    public Map<String, Object> adminReport(String restaurantId, int days) {
        return report(null, restaurantId, days, LocalDate.now(VN));
    }

    /** Báo cáo với "hôm nay" cho trước (test ranh giới ngày); ownerId null = mọi chủ quán (admin). */
    public Map<String, Object> report(String ownerId, String restaurantId, int days, LocalDate today) {
        LocalDate first = today.minusDays(days - 1L);
        String since = Times.iso(first.atStartOfDay(VN).toInstant());
        // phạm vi đơn: của chủ quán (và quán) này; %1$s = tiền tố bảng ("" hoặc "o.")
        String own = (ownerId != null ? "%1$srestaurant_owner_id=?" : "1=1") + (restaurantId != null ? " AND %1$srestaurant_id=?" : "");
        String scope = String.format(own, "") + " AND " + Payment.PLACED_SQL;
        List<Object> args = new ArrayList<>();
        if (ownerId != null) args.add(ownerId);
        if (restaurantId != null) args.add(restaurantId);

        Map<LocalDate, long[]> byDay = new LinkedHashMap<>();          // [đơn, hoàn thành, hủy, doanh thu]
        for (int i = 0; i < days; i++) byDay.put(first.plusDays(i), new long[4]);
        List<Object> rangeArgs = new ArrayList<>(args);
        rangeArgs.add(since);
        jdbc.query("SELECT status, total_price, created_at FROM orders WHERE " + scope + " AND created_at >= ?", (RowCallbackHandler) rs -> {
            long[] d = byDay.get(Instant.parse(rs.getString("created_at")).atZone(VN).toLocalDate());
            if (d == null) return;
            String st = rs.getString("status");
            d[0]++;
            if ("completed".equals(st)) { d[1]++; d[3] += rs.getLong("total_price"); }
            if ("cancelled".equals(st)) d[2]++;
        }, rangeArgs.toArray());

        List<Map<String, Object>> series = new ArrayList<>();
        long[] total = new long[4];
        byDay.forEach((day, d) -> {
            series.add(dayStats(day.toString(), d));
            for (int i = 0; i < 4; i++) total[i] += d[i];
        });

        Map<String, Object> open = new LinkedHashMap<>();
        open.put("pending", 0);
        open.put("confirmed", 0);
        jdbc.query("SELECT status, COUNT(*) AS n FROM orders WHERE " + scope + " AND status IN ('pending','confirmed') "
                + "GROUP BY status", (RowCallbackHandler) rs -> { open.put(rs.getString("status"), rs.getInt("n")); }, args.toArray());

        List<Map<String, Object>> top = jdbc.query("SELECT oi.item_name, SUM(oi.quantity) AS quantity, SUM(oi.line_total) "
                + "AS revenue FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE " + String.format(own, "o.")
                + " AND o.status = 'completed' AND o.created_at >= ? GROUP BY oi.item_name "
                + "ORDER BY quantity DESC, revenue DESC, oi.item_name LIMIT 5", (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("item_name", rs.getString("item_name"));
                    m.put("quantity", rs.getLong("quantity"));
                    m.put("revenue", rs.getLong("revenue"));
                    return m;
                }, rangeArgs.toArray());

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("days", days);
        m.put("timezone", VN.getId());
        m.put("today", dayStats(today.toString(), byDay.get(today)));
        m.put("period", dayStats(null, total));
        m.put("series", series);
        m.put("open", open);
        m.put("top_items", top);
        return m;
    }

    private static Map<String, Object> dayStats(String date, long[] d) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (date != null) m.put("date", date);
        m.put("orders", d[0]);
        m.put("completed", d[1]);
        m.put("cancelled", d[2]);
        m.put("revenue", d[3]);
        return m;
    }

    public Map<String, Object> stats() {
        Map<String, Object> byStatus = new LinkedHashMap<>();
        for (OrderStatus s : OrderStatus.values()) byStatus.put(s.getValue(), 0);
        jdbc.query("SELECT status, COUNT(*) AS n FROM orders WHERE " + Payment.PLACED_SQL + " GROUP BY status",
                rs -> { byStatus.put(rs.getString("status"), rs.getInt("n")); });
        Integer awaiting = jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE status='pending' AND payment_status IN "
                + "('unpaid','claimed')", Integer.class);
        Integer notPlaced = jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE payment_status IN ('void','failed','expired')",
                Integer.class);
        Long revenue = jdbc.queryForObject("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed'",
                Long.class);
        List<Map<String, Object>> top = jdbc.query("SELECT restaurant_id, MAX(restaurant_name) AS restaurant_name, "
                + "COUNT(*) AS orders, COALESCE(SUM(CASE WHEN status='completed' THEN total_price END),0) AS revenue "
                + "FROM orders WHERE " + Payment.PLACED_SQL + " GROUP BY restaurant_id ORDER BY orders DESC, restaurant_id "
                + "LIMIT 5", (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("restaurant_id", rs.getString("restaurant_id"));
                    m.put("restaurant_name", rs.getString("restaurant_name"));
                    m.put("orders", rs.getInt("orders"));
                    m.put("revenue", rs.getLong("revenue"));
                    return m;
                });
        Integer failed = jdbc.queryForObject("SELECT COUNT(*) FROM notification_outbox WHERE status='failed'", Integer.class);
        int total = byStatus.values().stream().mapToInt(v -> (Integer) v).sum();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("by_status", byStatus);
        m.put("total", total);
        m.put("awaiting_payment", awaiting);      // đơn chờ thanh toán (chưa tính vào by_status / total)
        m.put("not_placed", notPlaced);           // bỏ, quá hạn, quán không nhận được tiền
        m.put("revenue", revenue);
        m.put("top_restaurants", top);
        m.put("notification_failed", failed);
        return m;
    }
}
