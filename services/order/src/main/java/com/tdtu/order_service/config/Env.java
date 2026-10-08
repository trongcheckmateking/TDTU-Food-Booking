package com.tdtu.order_service.config;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Cấu hình đọc từ biến môi trường và tệp .env ở thư mục gốc dự án (dùng chung cho 5 service).
 * Biến môi trường thật được ưu tiên hơn .env. Không có giá trị bí mật mặc định.
 */
public final class Env {
    private static final Map<String, String> FILE = new HashMap<>();
    private static boolean loaded;
    private static final Map<String, Integer> PORTS = Map.of("AUTH", 8001, "RESTAURANT", 8002, "ORDER", 8003,
            "NOTIFICATION", 8004, "REVIEW", 8005);

    private Env() {}

    /** Thư mục gốc dự án: TDTU_ROOT, hoặc 2 cấp trên thư mục service (services/order). */
    public static Path root() {
        String r = System.getenv("TDTU_ROOT");
        if (r != null && !r.isBlank()) return Path.of(r).toAbsolutePath().normalize();
        return Path.of("").toAbsolutePath().resolve("../..").normalize();
    }

    public static synchronized void load() {
        if (loaded) return;
        loaded = true;
        String custom = System.getenv("TDTU_ENV_FILE");
        Path file = custom != null && !custom.isBlank() ? Path.of(custom) : root().resolve(".env");
        if (!Files.isRegularFile(file)) return;
        try {
            for (String raw : Files.readAllLines(file, StandardCharsets.UTF_8)) {
                String line = raw.strip();
                if (line.startsWith("﻿")) line = line.substring(1);
                if (line.isEmpty() || line.startsWith("#") || !line.contains("=")) continue;
                int i = line.indexOf('=');
                String key = line.substring(0, i).strip();
                String val = line.substring(i + 1).strip().replaceAll("^[\"']|[\"']$", "");
                FILE.put(key, val);
            }
        } catch (IOException e) {
            throw new IllegalStateException("Không đọc được " + file + ": " + e.getMessage(), e);
        }
    }

    public static String get(String name, String def) {
        load();
        String v = System.getenv(name);
        if (v == null || v.isEmpty()) v = System.getProperty("tdtu." + name);   // dùng trong test
        if (v == null || v.isEmpty()) v = FILE.get(name);
        return v == null || v.isEmpty() ? def : v;
    }

    public static String require(String name, int minLength) {
        String v = get(name, null);
        if (v == null || v.length() < minLength) {
            throw new IllegalStateException("Thiếu cấu hình " + name + " (tối thiểu " + minLength + " ký tự). "
                    + "Chạy `python manage.py init-env` để tạo tệp .env cho máy local.");
        }
        return v;
    }

    public static String serviceUrl(String name) {
        return get(name + "_URL", "http://127.0.0.1:" + PORTS.get(name)).replaceAll("/+$", "");
    }

    public static int listenPort() {
        int p = URI.create(serviceUrl("ORDER")).getPort();
        return p > 0 ? p : PORTS.get("ORDER");
    }

    public static Path dataDir() {
        Path p = Path.of(get("DATA_DIR", "data"));
        if (!p.isAbsolute()) p = root().resolve(p);
        try {
            Files.createDirectories(p);
        } catch (IOException e) {
            throw new IllegalStateException("Không tạo được thư mục dữ liệu " + p, e);
        }
        return p.toAbsolutePath().normalize();
    }

    public static List<String> corsOrigins() {
        List<String> out = new ArrayList<>();
        for (String o : get("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")) {
            if (!o.isBlank()) out.add(o.strip());
        }
        return out;
    }

    public static double httpTimeoutSeconds() {
        try {
            double v = Double.parseDouble(get("HTTP_TIMEOUT", "5"));
            return v > 0 ? v : 5;
        } catch (NumberFormatException e) {
            return 5;
        }
    }

    public static int getInt(String name, int def) {
        try {
            return Integer.parseInt(get(name, String.valueOf(def)).strip());
        } catch (NumberFormatException e) {
            throw new IllegalStateException("Cấu hình " + name + " phải là số nguyên");
        }
    }

    public static String internalKey() {
        return require("INTERNAL_KEY", 24);
    }
}
