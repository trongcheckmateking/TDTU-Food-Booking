package com.tdtu.order_service.model;

import java.util.List;

/**
 * Bảng ORDERS: đơn hàng, lưu ảnh chụp tên quán, chủ quán, khách hàng lúc đặt; tiền VND số nguyên.
 * pickupCode: mã nhận món 3 chữ số (001-999) sinh viên đọc khi tới quán, đánh số theo quán trong ngày.
 */
public record Order(String id, String userId, String customerName, String customerPhone, String restaurantId,
                    String restaurantName, String restaurantOwnerId, OrderStatus status, long totalPrice,
                    String deliveryAddress, String note, String cancelReason, String cancelledBy,
                    String createdAt, String updatedAt, String pickupCode, Payment payment, List<OrderItem> items) {

    public Order withItems(List<OrderItem> newItems) {
        return new Order(id, userId, customerName, customerPhone, restaurantId, restaurantName, restaurantOwnerId,
                status, totalPrice, deliveryAddress, note, cancelReason, cancelledBy, createdAt, updatedAt, pickupCode,
                payment, newItems);
    }

    /** Mã hiển thị cho người dùng: mã nhận món 3 số; đơn quá cũ chưa có mã thì 8 ký tự đầu của ID. */
    public String displayCode() {
        return pickupCode != null ? pickupCode : id.substring(0, 8).toUpperCase();
    }
}
