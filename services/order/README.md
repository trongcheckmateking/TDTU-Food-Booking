# Order Service – Java / Spring Boot 3.5 (TV3)

Cổng 8003. Giỏ hàng, checkout (Idempotency-Key), đơn hàng, trạng thái, outbox thông báo, thống kê.
CSDL: H2 dạng tệp `DATA_DIR/order.mv.db`, bảng tạo từ `src/main/resources/schema.sql`.

```bash
mvn -DskipTests package     # hoặc ./mvnw / mvnw.cmd (JDK 17+)
java -jar target/order-service.jar   # đọc .env ở thư mục gốc dự án
mvn test                    # OrderStatusTest, JsonTest, OrderFlowTest
```
Gói `com.tdtu.order_service`: `controller/`, `service/` (CartService, OrderService, OutboxService), `client/` (Auth, Restaurant,
Upstream), `model/` (OrderStatus của TV3), `web/` (lỗi, kiểm tra JSON), `config/` (Env, CORS).
