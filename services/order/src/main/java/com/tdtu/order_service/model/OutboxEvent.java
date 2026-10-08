package com.tdtu.order_service.model;

/** Bảng NOTIFICATION_OUTBOX: sự kiện thông báo ghi cùng giao dịch với đơn, gửi sau và gửi lại khi lỗi. */
public record OutboxEvent(String id, String eventKey, String orderId, String payload, String status, int attempts,
                          String lastError, String nextAttemptAt, String createdAt, String sentAt) {}
