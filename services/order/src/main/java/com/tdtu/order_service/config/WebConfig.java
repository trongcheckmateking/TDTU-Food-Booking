package com.tdtu.order_service.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Filter đầu tiên của mọi request:
 *  - X-Request-ID: nhận header hợp lệ (^[A-Za-z0-9._-]{8,128}$) hoặc sinh UUID bỏ gạch (32 hex), trả lại trong
 *    response (kể cả lỗi / preflight), đặt vào MDC "rid" để mọi dòng log có rid=... và Upstream chuyển tiếp khi gọi
 *    service khác. Toàn bộ filter nằm trong try/finally MDC.remove (luồng Tomcat được dùng lại cho request khác).
 *  - CORS chỉ cho các origin trong CORS_ORIGINS (giống 4 service còn lại).
 *  - Log ngắn mỗi request (method, đường dẫn, mã trả về, thời gian; không ghi token hay body, không ghi /health).
 */
@Configuration
public class WebConfig {
    private static final Logger log = LoggerFactory.getLogger("access");
    public static final String RID_HEADER = "X-Request-ID";
    public static final String RID_MDC = "rid";
    private static final Pattern RID = Pattern.compile("^[A-Za-z0-9._-]{8,128}$");

    public static String acceptRequestId(String raw) {
        return raw != null && RID.matcher(raw).matches() ? raw : UUID.randomUUID().toString().replace("-", "");
    }

    @Bean
    public FilterRegistrationBean<OncePerRequestFilter> corsAndLogFilter() {
        Set<String> allowed = new HashSet<>(Env.corsOrigins());
        OncePerRequestFilter filter = new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
                    throws ServletException, IOException {
                String rid = acceptRequestId(req.getHeader(RID_HEADER));
                MDC.put(RID_MDC, rid);
                try {
                    res.setHeader(RID_HEADER, rid);
                    handle(req, res, chain, allowed);
                } finally {
                    MDC.remove(RID_MDC);
                }
            }
        };
        FilterRegistrationBean<OncePerRequestFilter> reg = new FilterRegistrationBean<>(filter);
        reg.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return reg;
    }

    private static void handle(HttpServletRequest req, HttpServletResponse res, FilterChain chain, Set<String> allowed)
            throws ServletException, IOException {
        long t0 = System.currentTimeMillis();
        String origin = req.getHeader("Origin");
        boolean preflight = "OPTIONS".equals(req.getMethod()) && req.getHeader("Access-Control-Request-Method") != null;
        if (origin != null && allowed.contains(origin)) {
            res.setHeader("Access-Control-Allow-Origin", origin);
            res.setHeader("Vary", "Origin");
            res.setHeader("Access-Control-Expose-Headers", "Idempotent-Replay, " + RID_HEADER);
            if (preflight) {
                res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
                res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key, " + RID_HEADER);
                res.setHeader("Access-Control-Max-Age", "600");
                res.setStatus(200);
                return;
            }
        } else if (preflight) {
            res.setStatus(400);
            res.setContentType("application/json;charset=UTF-8");
            res.getOutputStream().write("{\"detail\":\"Origin không được phép\",\"code\":\"CORS_REJECTED\"}"
                    .getBytes(StandardCharsets.UTF_8));
            return;
        }
        try {
            chain.doFilter(req, res);
        } finally {
            if (!"/health".equals(req.getRequestURI())) {
                log.info("{} {} {} {}ms", req.getMethod(), req.getRequestURI(), res.getStatus(),
                        System.currentTimeMillis() - t0);
            }
        }
    }
}
