package com.tdtu.order_service.model;

/** Bảng CARTS: mỗi sinh viên 1 giỏ, chỉ chứa món của 1 quán (restaurantId = null khi giỏ trống). */
public record Cart(String id, String userId, String restaurantId, String updatedAt) {}
