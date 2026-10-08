package com.tdtu.order_service.service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

/** Thời gian UTC dạng ISO 8601 đến giây (2026-10-05T03:00:00Z) và UUID mới, dùng chung với 4 service còn lại. */
public final class Times {
    private Times() {}

    public static String iso(Instant t) {
        return t.truncatedTo(ChronoUnit.SECONDS).toString();
    }

    public static String now() {
        return iso(Instant.now());
    }

    public static String newId() {
        return UUID.randomUUID().toString();
    }
}
