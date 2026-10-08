package com.tdtu.order_service.controller;

import com.tdtu.order_service.client.AuthClient;
import com.tdtu.order_service.client.AuthClient.AuthUser;
import com.tdtu.order_service.service.CartService;
import com.tdtu.order_service.web.Json;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Giỏ hàng của sinh viên: /api/cart. */
@RestController
@RequestMapping("/api/cart")
public class CartController {
    private final AuthClient auth;
    private final CartService carts;

    public CartController(AuthClient auth, CartService carts) {
        this.auth = auth;
        this.carts = carts;
    }

    @GetMapping
    public Map<String, Object> view(HttpServletRequest req) {
        return carts.view(auth.require(req, "sinh_vien"));
    }

    @PostMapping("/items")
    public Map<String, Object> add(HttpServletRequest req, @RequestBody(required = false) String raw) {
        AuthUser u = auth.require(req, "sinh_vien");
        Json.Body b = Json.body(raw, Set.of("restaurant_id", "item_id", "quantity"));
        String rid = b.uuid("restaurant_id");
        String iid = b.uuid("item_id");
        Integer q = b.integer("quantity", 1, 50, 1);
        b.done();
        return carts.add(u, rid, iid, q);
    }

    @PatchMapping("/items/{itemId}")
    public Map<String, Object> setQuantity(HttpServletRequest req, @PathVariable String itemId,
                                           @RequestBody(required = false) String raw) {
        AuthUser u = auth.require(req, "sinh_vien");
        String iid = Json.uuidParam(itemId, "item_id");
        Json.Body b = Json.body(raw, Set.of("quantity"));
        Integer q = b.integer("quantity", 1, 50, null);
        b.done();
        return carts.setQuantity(u, iid, q);
    }

    @DeleteMapping("/items/{itemId}")
    public Map<String, Object> remove(HttpServletRequest req, @PathVariable String itemId) {
        AuthUser u = auth.require(req, "sinh_vien");
        return carts.remove(u, Json.uuidParam(itemId, "item_id"));
    }

    @DeleteMapping
    public ResponseEntity<Void> clear(HttpServletRequest req) {
        carts.clear(auth.require(req, "sinh_vien"));
        return ResponseEntity.noContent().build();
    }
}
