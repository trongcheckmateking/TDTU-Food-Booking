package com.tdtu.order_service;

import com.tdtu.order_service.config.Env;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Order Service (Java Spring Boot, cổng 8003): giỏ hàng, checkout, đơn hàng, trạng thái, outbox thông báo.
 *
 * Chạy: mvn spring-boot:run   hoặc   java -jar target/order-service.jar   (hoặc python manage.py start)
 * Cấu hình đọc từ .env ở thư mục gốc dự án (INTERNAL_KEY, *_URL, DATA_DIR, CORS_ORIGINS, OUTBOX_INTERVAL...).
 */
@SpringBootApplication
public class OrderserviceApplication {

    public static void main(String[] args) {
        try {
            Env.internalKey();                                   // dừng sớm nếu thiếu khóa nội bộ
        } catch (IllegalStateException e) {
            System.err.println(e.getMessage());
            System.exit(1);
        }
        String dbFile = Env.dataDir().resolve("order").toString().replace('\\', '/');
        System.setProperty("server.port", String.valueOf(Env.listenPort()));
        System.setProperty("server.address", Env.get("BIND_HOST", "127.0.0.1"));
        System.setProperty("spring.datasource.url",
                "jdbc:h2:file:" + dbFile + ";DB_CLOSE_ON_EXIT=FALSE;LOCK_TIMEOUT=10000");
        if ("WARNING".equalsIgnoreCase(Env.get("LOG_LEVEL", "INFO"))) {
            System.setProperty("logging.level.root", "WARN");
        }
        SpringApplication.run(OrderserviceApplication.class, args);
    }
}
