package com.tdtu.order_service.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class OrderStatusTest {

    @Test
    void pendingCoTheSangConfirmedHoacCancelled() {
        assertTrue(OrderStatus.PENDING.canChangeTo(OrderStatus.CONFIRMED));
        assertTrue(OrderStatus.PENDING.canChangeTo(OrderStatus.CANCELLED));
        assertFalse(OrderStatus.PENDING.canChangeTo(OrderStatus.COMPLETED));
    }

    @Test
    void confirmedCoTheSangCompletedHoacCancelled() {
        assertTrue(OrderStatus.CONFIRMED.canChangeTo(OrderStatus.COMPLETED));
        assertTrue(OrderStatus.CONFIRMED.canChangeTo(OrderStatus.CANCELLED));
        assertFalse(OrderStatus.CONFIRMED.canChangeTo(OrderStatus.PENDING));
    }

    @Test
    void trangThaiCuoiKhongDoiDuoc() {
        for (OrderStatus next : OrderStatus.values()) {
            assertFalse(OrderStatus.COMPLETED.canChangeTo(next));
            assertFalse(OrderStatus.CANCELLED.canChangeTo(next));
        }
    }

    @Test
    void docTrangThaiTuChuoi() {
        assertEquals(OrderStatus.CONFIRMED, OrderStatus.from("confirmed"));
        assertEquals(OrderStatus.CANCELLED, OrderStatus.from("CANCELLED"));
        assertThrows(IllegalArgumentException.class, () -> OrderStatus.from("khong-co"));
    }

    @Test
    void giaTriJsonLaChuThuong() {
        assertEquals("pending", OrderStatus.PENDING.getValue());
        assertEquals("completed", OrderStatus.COMPLETED.getValue());
    }
}
