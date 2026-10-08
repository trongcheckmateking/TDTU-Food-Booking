package com.tdtu.order_service.web;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Đọc và kiểm tra chặt dữ liệu vào (tương đương Pydantic strict ở Auth Service):
 * trường lạ bị chặn, chuỗi được cắt khoảng trắng, số nguyên phải là số nguyên JSON thật (không nhận 1.5, "2", true).
 * Sai -> 422 VALIDATION_ERROR kèm errors: [{field, message}].
 */
public final class Json {
    public static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Pattern UUID_RE =
            Pattern.compile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$");
    private static final Pattern INT_RE = Pattern.compile("^\\s*[+-]?\\d{1,9}\\s*$");
    private static final Pattern DATE_RE = Pattern.compile("^\\d{4}-\\d{2}-\\d{2}$");

    private Json() {}

    /** {"field": ..., "message": ...} giữ đúng thứ tự khóa. */
    public static Map<String, String> fieldError(String field, String message) {
        Map<String, String> m = new java.util.LinkedHashMap<>();
        m.put("field", field);
        m.put("message", message);
        return m;
    }

    /** Một body đang được kiểm tra; gom mọi lỗi rồi ném 1 lần bằng done(). */
    public static final class Body {
        private final JsonNode node;
        private final List<Map<String, String>> errors = new ArrayList<>();

        private Body(JsonNode node, Set<String> allowed) {
            this.node = node;
            Iterator<String> it = node.fieldNames();
            while (it.hasNext()) {
                String k = it.next();
                if (!allowed.contains(k)) error(k, "trường không được phép");
            }
        }

        private void error(String field, String message) {
            errors.add(fieldError(field, message));
        }

        public boolean has(String f) { return node.has(f); }

        public String text(String f, int min, int max, boolean required) {
            JsonNode v = node.get(f);
            if (v == null || v.isNull()) {
                if (required) error(f, v == null ? "bắt buộc" : "không được để trống");
                return null;
            }
            if (!v.isTextual()) { error(f, "phải là chuỗi"); return null; }
            String s = v.asText().strip();
            if (s.isEmpty()) { error(f, "không được chỉ chứa khoảng trắng"); return null; }
            if (s.length() < min || s.length() > max) {
                error(f, "độ dài phải từ " + min + " đến " + max + " ký tự");
                return null;
            }
            return s;
        }

        /** Chuỗi tùy chọn: null hoặc chuỗi rỗng sau khi cắt -> null. */
        public String optText(String f, int max) {
            JsonNode v = node.get(f);
            if (v == null || v.isNull()) return null;
            if (!v.isTextual()) { error(f, "phải là chuỗi"); return null; }
            String s = v.asText().strip();
            if (s.length() > max) { error(f, "tối đa " + max + " ký tự"); return null; }
            return s.isEmpty() ? null : s;
        }

        public Integer integer(String f, int min, int max, Integer def) {
            JsonNode v = node.get(f);
            if (v == null) {
                if (def == null) error(f, "bắt buộc");
                return def;
            }
            if (!v.isIntegralNumber() || !v.canConvertToInt()) { error(f, "phải là số nguyên"); return null; }
            int n = v.intValue();
            if (n < min || n > max) { error(f, "phải trong khoảng " + min + "–" + max); return null; }
            return n;
        }

        public String uuid(String f) {
            JsonNode v = node.get(f);
            if (v == null) { error(f, "bắt buộc"); return null; }
            if (!v.isTextual() || !UUID_RE.matcher(v.asText().strip()).matches()) { error(f, "phải là UUID"); return null; }
            return v.asText().strip().toLowerCase();
        }

        public String oneOf(String f, List<String> values, boolean required) {
            JsonNode v = node.get(f);
            if (v == null || v.isNull()) {
                if (required) error(f, "bắt buộc");
                return null;
            }
            if (!v.isTextual() || !values.contains(v.asText())) {
                error(f, "phải là một trong: " + String.join(", ", values));
                return null;
            }
            return v.asText();
        }

        public void done() {
            if (!errors.isEmpty()) throw ApiError.validation(errors);
        }
    }

    /** Phân tích body: JSON hỏng -> 422 "JSON gửi lên không hợp lệ"; không phải object -> 422. */
    public static Body body(String raw, Set<String> allowed) {
        JsonNode node;
        try {
            node = raw == null || raw.isBlank() ? null : MAPPER.readTree(raw);
        } catch (JsonProcessingException e) {
            throw ApiError.validation("JSON gửi lên không hợp lệ",
                    List.of(fieldError("body", "JSON không hợp lệ")));
        }
        if (node == null || !node.isObject()) {
            throw ApiError.field("body", "phải là JSON object");
        }
        return new Body(node, allowed);
    }

    // ---------------------------------------------------------------- path & query
    public static boolean isUuid(String s) {
        return s != null && UUID_RE.matcher(s).matches();
    }

    public static String uuidParam(String s, String field) {
        if (!isUuid(s)) throw ApiError.field(field, "phải là UUID");
        return s.toLowerCase();
    }

    public static String uuidQuery(String s, String field) {
        return s == null ? null : uuidParam(s, field);
    }

    public static int intQuery(String raw, String field, int def, int min, int max) {
        if (raw == null) return def;
        if (!INT_RE.matcher(raw).matches()) throw ApiError.field(field, "phải là số nguyên");
        int n = Integer.parseInt(raw.strip());
        if (n < min || n > max) throw ApiError.field(field, "phải trong khoảng " + min + "–" + max);
        return n;
    }

    public static String enumQuery(String raw, String field, List<String> values) {
        if (raw == null) return null;
        if (!values.contains(raw)) throw ApiError.field(field, "phải là một trong: " + String.join(", ", values));
        return raw;
    }

    public static String dateQuery(String raw, String field) {
        if (raw == null) return null;
        if (!DATE_RE.matcher(raw).matches()) throw ApiError.field(field, "phải có dạng YYYY-MM-DD");
        try {
            java.time.LocalDate.parse(raw);
        } catch (java.time.format.DateTimeParseException e) {
            throw ApiError.field(field, "ngày không hợp lệ");
        }
        return raw;
    }
}
