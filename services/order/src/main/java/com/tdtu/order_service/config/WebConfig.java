package com.tdtu.order_service.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * CORS chỉ cho các origin trong CORS_ORIGINS (giống 4 service còn lại) và log ngắn mỗi request
 * (method, đường dẫn, mã trả về, thời gian; không ghi token hay body).
 */
@Configuration
public class WebConfig {
    private static final Logger log = LoggerFactory.getLogger("access");

    @Bean
    public FilterRegistrationBean<OncePerRequestFilter> corsAndLogFilter() {
        Set<String> allowed = new HashSet<>(Env.corsOrigins());
        OncePerRequestFilter filter = new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
                    throws ServletException, IOException {
                long t0 = System.currentTimeMillis();
                String origin = req.getHeader("Origin");
                boolean preflight = "OPTIONS".equals(req.getMethod())
                        && req.getHeader("Access-Control-Request-Method") != null;
                if (origin != null && allowed.contains(origin)) {
                    res.setHeader("Access-Control-Allow-Origin", origin);
                    res.setHeader("Vary", "Origin");
                    if (preflight) {
                        res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
                        res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key");
                        res.setHeader("Access-Control-Expose-Headers", "Idempotent-Replay");
                        res.setHeader("Access-Control-Max-Age", "600");
                        res.setStatus(200);
                        return;
                    }
                    res.setHeader("Access-Control-Expose-Headers", "Idempotent-Replay");
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
        };
        FilterRegistrationBean<OncePerRequestFilter> reg = new FilterRegistrationBean<>(filter);
        reg.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return reg;
    }
}
