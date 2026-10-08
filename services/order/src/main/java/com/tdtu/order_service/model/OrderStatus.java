package com.tdtu.order_service.model;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

/** Trạng thái đơn hàng, dùng chung toàn nhóm: pending, confirmed, completed, cancelled. */
public enum OrderStatus {
    PENDING("pending"), CONFIRMED("confirmed"),
    COMPLETED("completed"), CANCELLED("cancelled");

    private final String value;

    OrderStatus(String value) { this.value = value; }

    @JsonValue
    public String getValue() { return value; }

    @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
    public static OrderStatus from(String v) {
        if (v != null) {
            for (OrderStatus s : values())
                if (s.value.equalsIgnoreCase(v.trim())) return s;
        }
        throw new IllegalArgumentException("Trạng thái không hợp lệ: " + v);
    }

    /** Luật chuyển trạng thái: completed và cancelled là trạng thái cuối. */
    public boolean canChangeTo(OrderStatus next) {
        return switch (this) {
            case PENDING   -> next == CONFIRMED || next == CANCELLED;
            case CONFIRMED -> next == COMPLETED || next == CANCELLED;
            default        -> false;
        };
    }
}
