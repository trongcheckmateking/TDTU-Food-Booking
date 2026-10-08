package com.tdtu.order_service.model;

/** Bảng ORDER_ITEMS: tên món và đơn giá chụp lúc đặt (VND, số nguyên). */
public record OrderItem(String id, String orderId, String itemId, String itemName, int quantity, long price,
                        long lineTotal) {}
