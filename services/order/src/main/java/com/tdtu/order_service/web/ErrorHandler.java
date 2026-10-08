package com.tdtu.order_service.web;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** Mọi lỗi trả JSON thống nhất với 4 service còn lại; lỗi bất ngờ trả 500 INTERNAL_ERROR (không lộ chi tiết). */
@RestControllerAdvice
public class ErrorHandler {
    private static final Logger log = LoggerFactory.getLogger(ErrorHandler.class);

    private static Map<String, Object> body(String detail, String code) {
        return new ApiError(0, code, detail).body();
    }

    @ExceptionHandler(ApiError.class)
    public ResponseEntity<Map<String, Object>> api(ApiError e) {
        return ResponseEntity.status(e.status()).body(e.body());
    }

    @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
    public ResponseEntity<Map<String, Object>> notFound(Exception e) {
        return ResponseEntity.status(404).body(body("Không tìm thấy API", "NOT_FOUND"));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<Map<String, Object>> method(HttpRequestMethodNotSupportedException e) {
        return ResponseEntity.status(405)
                .body(body("Phương thức HTTP không được hỗ trợ", "METHOD_NOT_ALLOWED"));
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<Map<String, Object>> media(HttpMediaTypeNotSupportedException e) {
        return ResponseEntity.status(415)
                .body(body("Content-Type không được hỗ trợ", "UNSUPPORTED_MEDIA_TYPE"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> unexpected(Exception e, HttpServletRequest req) {
        log.error("Lỗi không mong đợi tại {} {}", req.getMethod(), req.getRequestURI(), e);
        return ResponseEntity.status(500)
                .body(body("Có lỗi nội bộ, vui lòng thử lại sau", "INTERNAL_ERROR"));
    }
}
