package com.tdtu.order_service.web;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Lỗi nghiệp vụ trả về JSON {"detail": "...", "code": "...", ...extra}. */
public class ApiError extends RuntimeException {
    private final int status;
    private final String code;
    private final Map<String, Object> extra;

    public ApiError(int status, String code, String message) {
        this(status, code, message, Map.of());
    }

    public ApiError(int status, String code, String message, Map<String, Object> extra) {
        super(message);
        this.status = status;
        this.code = code;
        this.extra = extra;
    }

    public static ApiError validation(List<Map<String, String>> errors) {
        return validation("Dữ liệu không hợp lệ", errors);
    }

    public static ApiError validation(String message, List<Map<String, String>> errors) {
        return new ApiError(422, "VALIDATION_ERROR", message, Map.of("errors", errors));
    }

    public static ApiError field(String field, String message) {
        return validation(List.of(Json.fieldError(field, message)));
    }

    public int status() { return status; }
    public String code() { return code; }

    public Map<String, Object> body() {
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("detail", getMessage());
        b.put("code", code);
        b.putAll(extra);
        return b;
    }
}
