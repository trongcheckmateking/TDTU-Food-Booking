package com.tdtu.order_service.model;

/** Bảng CART_ITEMS: một món trong giỏ (itemId tham chiếu MENU_ITEMS của Restaurant Service). */
public record CartItem(String itemId, int quantity) {}
