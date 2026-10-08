package com.tdtu.order_service.service;

import com.tdtu.order_service.client.AuthClient.AuthUser;
import com.tdtu.order_service.client.RestaurantClient;
import com.tdtu.order_service.client.RestaurantClient.Quote;
import com.tdtu.order_service.client.RestaurantClient.QuoteLine;
import com.tdtu.order_service.model.Cart;
import com.tdtu.order_service.model.CartItem;
import com.tdtu.order_service.web.ApiError;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Giỏ hàng (giữ ý tưởng Cart/CartItem của bản TV3): mỗi sinh viên 1 giỏ, chỉ chứa món của 1 quán;
 * giá và trạng thái món luôn lấy trực tiếp từ Restaurant Service khi xem giỏ.
 */
@Service
public class CartService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final RestaurantClient restaurants;

    public CartService(JdbcTemplate jdbc, TransactionTemplate tx, RestaurantClient restaurants) {
        this.jdbc = jdbc;
        this.tx = tx;
        this.restaurants = restaurants;
    }

    public Cart findCart(String userId) {
        List<Cart> l = jdbc.query("SELECT * FROM carts WHERE user_id=?", (rs, i) -> new Cart(rs.getString("id"),
                rs.getString("user_id"), rs.getString("restaurant_id"), rs.getString("updated_at")), userId);
        return l.isEmpty() ? null : l.get(0);
    }

    /** Khóa dòng giỏ của user đến hết giao dịch (SELECT ... FOR UPDATE): các checkout/sửa giỏ đồng thời xếp hàng. */
    public Cart lockCart(String userId) {
        List<Cart> l = jdbc.query("SELECT * FROM carts WHERE user_id=? FOR UPDATE", (rs, i) -> new Cart(rs.getString("id"),
                rs.getString("user_id"), rs.getString("restaurant_id"), rs.getString("updated_at")), userId);
        return l.isEmpty() ? null : l.get(0);
    }

    public List<CartItem> lines(String cartId) {
        return jdbc.query("SELECT item_id, quantity FROM cart_items WHERE cart_id=? ORDER BY added_at, item_id",
                (rs, i) -> new CartItem(rs.getString("item_id"), rs.getInt("quantity")), cartId);
    }

    private static Map<String, Object> emptyView() {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("restaurant", null);
        v.put("items", List.of());
        v.put("total_price", 0);
        v.put("item_count", 0);
        v.put("can_checkout", false);
        return v;
    }

    public Map<String, Object> view(AuthUser user) {
        Cart cart = findCart(user.id());
        List<CartItem> lines = cart == null ? List.of() : lines(cart.id());
        if (cart == null || lines.isEmpty() || cart.restaurantId() == null) return emptyView();
        int count = lines.stream().mapToInt(CartItem::quantity).sum();
        Map<String, Object> v = new LinkedHashMap<>();
        Quote q;
        try {
            q = restaurants.quote(cart.restaurantId(), lines);
        } catch (ApiError e) {
            if (!"RESTAURANT_NOT_FOUND".equals(e.code())) throw e;
            // Quán đã bị xóa: vẫn trả giỏ để sinh viên xóa và chọn quán khác
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("id", cart.restaurantId());
            r.put("name", null);
            r.put("accepting_orders", false);
            r.put("deleted", true);
            List<Map<String, Object>> items = new ArrayList<>();
            for (CartItem l : lines) {
                items.add(new QuoteLine(l.itemId(), l.quantity(), false, "RESTAURANT_NOT_FOUND", null, null, null).toMap());
            }
            v.put("restaurant", r);
            v.put("items", items);
            v.put("total_price", 0);
            v.put("item_count", count);
            v.put("can_checkout", false);
            return v;
        }
        v.put("restaurant", q.restaurantMap());
        v.put("items", q.items().stream().map(QuoteLine::toMap).toList());
        v.put("total_price", q.total());
        v.put("item_count", count);
        v.put("can_checkout", q.acceptingOrders() && q.allAvailable());
        return v;
    }

    private Cart ensureCart(String userId) {
        Cart c = findCart(userId);
        if (c != null) return c;
        try {
            jdbc.update("INSERT INTO carts (id,user_id,restaurant_id,updated_at) VALUES (?,?,NULL,?)", Times.newId(),
                    userId, Times.now());
        } catch (DuplicateKeyException e) {
            // request song song vừa tạo giỏ: dùng giỏ đó
        }
        return findCart(userId);
    }

    public Map<String, Object> add(AuthUser user, String restaurantId, String itemId, int quantity) {
        Quote q = restaurants.quote(restaurantId, List.of(new CartItem(itemId, quantity)));
        if (!q.acceptingOrders()) throw new ApiError(409, "RESTAURANT_NOT_ACCEPTING", "Quán hiện không nhận đơn");
        QuoteLine line = q.items().get(0);
        if (!line.available()) {
            throw new ApiError(409, line.reason() != null ? line.reason() : "ITEM_UNAVAILABLE",
                    "Món không còn bán hoặc không thuộc quán này");
        }
        ensureCart(user.id());
        tx.executeWithoutResult(s -> {
            Cart cart = lockCart(user.id());
            Integer has = jdbc.queryForObject("SELECT COUNT(*) FROM cart_items WHERE cart_id=?", Integer.class, cart.id());
            if (has > 0 && !restaurantId.equals(cart.restaurantId())) {
                throw new ApiError(409, "CART_OTHER_RESTAURANT",
                        "Giỏ đang có món của quán khác. Hãy xóa giỏ trước khi chọn quán mới.");
            }
            List<Integer> existing = jdbc.queryForList("SELECT quantity FROM cart_items WHERE cart_id=? AND item_id=?",
                    Integer.class, cart.id(), itemId);
            int qty = quantity + (existing.isEmpty() ? 0 : existing.get(0));
            if (qty > 50) throw new ApiError(422, "QUANTITY_LIMIT", "Mỗi món tối đa 50 phần trong giỏ");
            if (existing.isEmpty()) {
                jdbc.update("INSERT INTO cart_items (id,cart_id,item_id,quantity,added_at) VALUES (?,?,?,?,?)",
                        Times.newId(), cart.id(), itemId, qty, Times.now());
            } else {
                jdbc.update("UPDATE cart_items SET quantity=? WHERE cart_id=? AND item_id=?", qty, cart.id(), itemId);
            }
            jdbc.update("UPDATE carts SET restaurant_id=?, updated_at=? WHERE id=?", restaurantId, Times.now(), cart.id());
        });
        return view(user);
    }

    private Cart cartOr404(String userId) {
        Cart c = findCart(userId);
        if (c == null) throw new ApiError(404, "CART_EMPTY", "Giỏ hàng đang trống");
        return c;
    }

    void resetIfEmpty(String cartId) {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM cart_items WHERE cart_id=?", Integer.class, cartId);
        if (n == 0) jdbc.update("UPDATE carts SET restaurant_id=NULL, updated_at=? WHERE id=?", Times.now(), cartId);
    }

    public Map<String, Object> setQuantity(AuthUser user, String itemId, int quantity) {
        Cart cart = cartOr404(user.id());
        tx.executeWithoutResult(s -> {
            int n = jdbc.update("UPDATE cart_items SET quantity=? WHERE cart_id=? AND item_id=?", quantity, cart.id(), itemId);
            if (n == 0) throw new ApiError(404, "CART_ITEM_NOT_FOUND", "Món không có trong giỏ");
        });
        return view(user);
    }

    public Map<String, Object> remove(AuthUser user, String itemId) {
        Cart cart = cartOr404(user.id());
        tx.executeWithoutResult(s -> {
            int n = jdbc.update("DELETE FROM cart_items WHERE cart_id=? AND item_id=?", cart.id(), itemId);
            if (n == 0) throw new ApiError(404, "CART_ITEM_NOT_FOUND", "Món không có trong giỏ");
            resetIfEmpty(cart.id());
        });
        return view(user);
    }

    public void clear(AuthUser user) {
        Cart cart = findCart(user.id());
        if (cart == null) return;
        tx.executeWithoutResult(s -> {
            jdbc.update("DELETE FROM cart_items WHERE cart_id=?", cart.id());
            resetIfEmpty(cart.id());
        });
    }
}
