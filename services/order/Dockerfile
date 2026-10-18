# Order Service (Java 17+/Spring Boot + H2, cổng 8003). Build: docker build -t tdtu-food/order services/order
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src/ src/
RUN mvn -q -B -DskipTests package && cp target/order-service.jar /order-service.jar

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S app && adduser -S -G app -u 10001 app && mkdir /data && chown app:app /data
WORKDIR /app
COPY --from=build /order-service.jar /app/order-service.jar
USER app

ENV TDTU_ROOT=/app DATA_DIR=/data BIND_HOST=0.0.0.0
VOLUME /data
EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1:8003/health || exit 1
CMD ["java", "-Xms64m", "-Xmx384m", "-XX:+ExitOnOutOfMemoryError", "-jar", "/app/order-service.jar"]
