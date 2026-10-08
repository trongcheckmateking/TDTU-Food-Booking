package com.tdtu.order_service.service;

import com.tdtu.order_service.client.AuthClient.AuthUser;
import com.tdtu.order_service.client.RestaurantClient;
import com.tdtu.order_service.client.RestaurantClient.Quote;
import com.tdtu.order_service.client.RestaurantClient.QuoteLine;
import com.tdtu.order_service.model.Cart;
import com.tdtu.order_service.model.CartItem;
import com.tdtu.order_service.model.Order;
import com.tdtu.order_service.model.OrderItem;
import com.tdtu.order_service.model.OrderStatus;
import com.tdtu.order_service.web.ApiError;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Đơn hàng: checkout từ giỏ (chống trùng bằng Idempotency-Key, giá do server lấy từ Restaurant),
 * đổi trạng thái theo vai trò (OrderStatus.canChangeTo của bản TV3), danh sách, thống kê.
 */
@Service
public class OrderService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final RestaurantClient restaurants;
    private final CartService carts;
    private final OutboxService outbox;

    private static final RowMapper<Order> ORDER = (rs, i) -> new Order(rs.getString("id"), rs.getString("user_id"),
            rs.getString("customer_name"), rs.getString("customer_phone"), rs.getString("restaurant_id"),
            rs.getString("restaurant_name"), rs.getString("restaurant_owner_id"), OrderStatus.from(rs.getString("status")),
            rs.getLong("total_price"), rs.getString("delivery_address"), rs.getString("note"),
            rs.getString("cancel_reason"), rs.getString("cancelled_by"), rs.getString("created_at"),
            rs.getString("updated_at"), List.of());
    private static final RowMapper<OrderItem> ITEM = (rs, i) -> new OrderItem(rs.getString("id"), rs.getString("order_id"),
            rs.getString("item_id"), rs.getString("item_name"), rs.getInt("quantity"), rs.getLong("price"),
            rs.getLong("line_total"));

    public OrderService(JdbcTemplate jdbc, TransactionTemplate tx, RestaurantClient restaurants, CartService carts,
                        OutboxService outbox) {
        this.jdbc = jdbc;
        this.tx = tx;
        this.restaurants = restaurants;
        this.carts = carts;
        this.outbox = outbox;
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
        String oid = Times.newId();
        String ts = Times.now();
        long total = q.items().stream().mapToLong(x -> x.price() * x.quantity()).sum();
        Order order = new Order(oid, user.id(), user.name(), user.phone(), q.restaurantId(), q.restaurantName(),
                q.ownerId(), OrderStatus.PENDING, total, address, note, null, null, ts, ts, List.of());
        String eventKey;
        try {
            eventKey = tx.execute(s -> {
                Cart locked = carts.lockCart(user.id());          // xếp hàng các checkout đồng thời của cùng user
                if (key != null && findByKey(user.id(), key) != null) {
                    throw new ApiError(409, "DUPLICATE_REQUEST", "Yêu cầu đặt hàng này đã được xử lý");
                }
                if (locked == null || !carts.lines(locked.id()).equals(lines)) {
                    throw new ApiError(409, "CART_CHANGED", "Giỏ hàng vừa thay đổi hoặc đã được đặt, vui lòng kiểm tra lại");
                }
                jdbc.update("INSERT INTO orders (id,user_id,customer_name,customer_phone,restaurant_id,restaurant_name,"
                        + "restaurant_owner_id,status,total_price,delivery_address,note,idempotency_key,created_at,updated_at) "
                        + "VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?,?,?,?)", oid, user.id(), user.name(), user.phone(),
                        q.restaurantId(), q.restaurantName(), q.ownerId(), total, address, note, key, ts, ts);
                for (QuoteLine x : q.items()) {
                    jdbc.update("INSERT INTO order_items (id,order_id,item_id,item_name,quantity,price,line_total) "
                            + "VALUES (?,?,?,?,?,?,?)", Times.newId(), oid, x.itemId(), x.name(), x.quantity(), x.price(),
                            x.price() * x.quantity());
                }
                String k = outbox.enqueue(order, "order_created", "sinh_vien");
                jdbc.update("DELETE FROM cart_items WHERE cart_id=?", locked.id());     // chỉ xóa giỏ khi thành công
                jdbc.update("UPDATE carts SET restaurant_id=NULL, updated_at=? WHERE id=?", ts, locked.id());
                return k;
            });
        } catch (DuplicateKeyException e) {
            throw new ApiError(409, "DUPLICATE_REQUEST", "Yêu cầu đặt hàng này đã được xử lý");
        }
        outbox.deliverQuietly(eventKey);
        return new CheckoutResult(load(oid), false);
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
            case "sinh_vien" -> {
                if (next != OrderStatus.CANCELLED || o.status() != OrderStatus.PENDING) {
                    throw new ApiError(403, "FORBIDDEN", "Sinh viên chỉ được hủy đơn đang chờ xác nhận");
                }
            }
            default -> {
                if (next != OrderStatus.CANCELLED) {
                    throw new ApiError(403, "FORBIDDEN", "Admin chỉ được hủy đơn lỗi, không xử lý thay chủ quán");
                }
            }
        }
        if (!o.status().canChangeTo(next)) {
            throw new ApiError(409, "INVALID_TRANSITION",
                    "Không thể chuyển đơn từ " + o.status().getValue() + " sang " + next.getValue());
        }
        boolean cancel = next == OrderStatus.CANCELLED;
        String eventKey = tx.execute(s -> {
            // cập nhật có điều kiện: chỉ 1 trong các request đồng thời thắng, các request còn lại nhận 409
            int n = jdbc.update("UPDATE orders SET status=?, updated_at=?, cancel_reason=?, cancelled_by=? "
                    + "WHERE id=? AND status=?", next.getValue(), Times.now(), cancel ? reason : null,
                    cancel ? user.role() : null, o.id(), o.status().getValue());
            if (n == 0) throw new ApiError(409, "STATUS_CHANGED", "Đơn vừa được cập nhật bởi người khác, vui lòng tải lại");
            return outbox.enqueue(o, "order_" + next.getValue(), user.role());
        });
        outbox.deliverQuietly(eventKey);
        return load(o.id());
    }

    // ---------------------------------------------------------------- admin
    public Map<String, Object> adminOrders(String status, String restaurantId, String userId, String dateFrom,
                                           String dateTo, int page, int size) {
        StringBuilder where = new StringBuilder("1=1");
        List<Object> args = new ArrayList<>();
        if (status != null) { where.append(" AND status=?"); args.add(status); }
        if (restaurantId != null) { where.append(" AND restaurant_id=?"); args.add(restaurantId); }
        if (userId != null) { where.append(" AND user_id=?"); args.add(userId); }
        if (dateFrom != null) { where.append(" AND created_at >= ?"); args.add(dateFrom); }
        if (dateTo != null) { where.append(" AND created_at < ?"); args.add(LocalDate.parse(dateTo).plusDays(1).toString()); }
        return page(where.toString(), args, page, size);
    }

    public Map<String, Object> stats() {
        Map<String, Object> byStatus = new LinkedHashMap<>();
        for (OrderStatus s : OrderStatus.values()) byStatus.put(s.getValue(), 0);
        jdbc.query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status",
                rs -> { byStatus.put(rs.getString("status"), rs.getInt("n")); });
        Long revenue = jdbc.queryForObject("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed'",
                Long.class);
        List<Map<String, Object>> top = jdbc.query("SELECT restaurant_id, MAX(restaurant_name) AS restaurant_name, "
                + "COUNT(*) AS orders, COALESCE(SUM(CASE WHEN status='completed' THEN total_price END),0) AS revenue "
                + "FROM orders GROUP BY restaurant_id ORDER BY orders DESC, restaurant_id LIMIT 5", (rs, i) -> {
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
        m.put("revenue", revenue);
        m.put("top_restaurants", top);
        m.put("notification_failed", failed);
        return m;
    }
}
