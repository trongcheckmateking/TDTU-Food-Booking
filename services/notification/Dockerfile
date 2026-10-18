# Notification Service (Go/Gin + PostgreSQL, cổng 8004). Build: docker build -t tdtu-food/notification services/notification
FROM golang:1.27-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go openapi.json ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /notification-service .

FROM alpine:3.22
RUN adduser -S -u 10001 app
COPY --from=build /notification-service /usr/local/bin/notification-service
USER app

ENV BIND_HOST=0.0.0.0
EXPOSE 8004
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1:8004/health || exit 1
CMD ["notification-service"]
