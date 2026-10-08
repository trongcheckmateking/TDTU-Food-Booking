package com.tdtu.order_service.model;

import java.util.List;

/** Bảng ORDERS: đơn hàng, lưu ảnh chụp tên quán, chủ quán, khách hàng lúc đặt; tiền VND số nguyên. */
public record Order(String id, String userId, String customerName, String customerPhone, String restaurantId,
                    String restaurantName, String restaurantOwnerId, OrderStatus status, long totalPrice,
                    String deliveryAddress, String note, String cancelReason, String cancelledBy,
                    String createdAt, String updatedAt, List<OrderItem> items) {

    public Order withItems(List<OrderItem> newItems) {
        return new Order(id, userId, customerName, customerPhone, restaurantId, restaurantName, restaurantOwnerId,
                status, totalPrice, deliveryAddress, note, cancelReason, cancelledBy, createdAt, updatedAt, newItems);
    }
}
