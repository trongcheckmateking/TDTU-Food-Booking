// Notification Service (Go + Gin + GORM + PostgreSQL, cổng 8004).
//
// Nhận sự kiện đơn hàng từ Order Service (API nội bộ, idempotent theo event_key), lưu thông báo cho đúng
// người nhận; người dùng xem / đánh dấu đã đọc; admin xem / xóa. Hợp đồng API: openapi.json.
//
// Chạy: go build -o bin/notification-service . && ./bin/notification-service  (hoặc python manage.py start)
package main

import (
	"context"
	_ "embed"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

//go:embed openapi.json
var openapiSpec []byte

func corsMiddleware(allowed map[string]bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		preflight := c.Request.Method == http.MethodOptions && c.GetHeader("Access-Control-Request-Method") != ""
		if origin != "" && allowed[origin] {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Vary", "Origin")
			if preflight {
				c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
				c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key")
				c.Header("Access-Control-Max-Age", "600")
				c.AbortWithStatus(200)
				return
			}
		} else if preflight {
			writeErr(c, apiErr(400, "CORS_REJECTED", "Origin không được phép"))
			return
		}
		c.Next()
	}
}

func recovery() gin.HandlerFunc {
	return gin.CustomRecovery(func(c *gin.Context, err any) {
		writeErr(c, fmt.Errorf("panic: %v", err))
	})
}

func docsPage(kind string) string {
	if kind == "redoc" {
		return `<!doctype html><html><head><meta charset="utf-8"><title>Notification Service - API docs</title></head><body>` +
			`<redoc spec-url="/openapi.json"></redoc><script src="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"></script></body></html>`
	}
	return `<!doctype html><html><head><meta charset="utf-8"><title>Notification Service - API docs</title>` +
		`<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head><body>` +
		`<div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>` +
		`<script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",persistAuthorization:true});</script></body></html>`
}

func newRouter(db *gorm.DB, internalKey string, origins map[string]bool, quiet bool) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	if !quiet {
		r.Use(gin.LoggerWithConfig(gin.LoggerConfig{SkipPaths: []string{"/health"}}))
	}
	r.Use(recovery(), corsMiddleware(origins))
	s := &Server{db: db}

	r.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{"service": "notification", "status": "ok", "docs": "/docs"})
	})
	r.GET("/health", func(c *gin.Context) {
		ok := false
		if sqlDB, err := db.DB(); err == nil {
			ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
			defer cancel()
			ok = sqlDB.PingContext(ctx) == nil
		}
		if ok {
			c.JSON(200, gin.H{"service": "notification", "status": "ok", "db": "ok"})
		} else {
			c.JSON(503, gin.H{"service": "notification", "status": "degraded", "db": "error"})
		}
	})
	r.GET("/openapi.json", func(c *gin.Context) { c.Data(200, "application/json", openapiSpec) })
	r.GET("/docs", func(c *gin.Context) { c.Data(200, "text/html; charset=utf-8", []byte(docsPage("swagger"))) })
	r.GET("/redoc", func(c *gin.Context) { c.Data(200, "text/html; charset=utf-8", []byte(docsPage("redoc"))) })

	r.POST("/internal/notifications/events", requireInternal(internalKey), s.receiveEvent)
	r.GET("/api/notifications/me", requireUser(), s.myNotifications)
	r.PATCH("/api/notifications/me/read-all", requireUser(), s.readAll)
	r.PATCH("/api/notifications/:nid/read", requireUser(), s.markRead)
	r.GET("/api/admin/notifications", requireUser("admin"), s.adminList)
	r.DELETE("/api/admin/notifications/:nid", requireUser("admin"), s.adminDelete)

	r.NoRoute(func(c *gin.Context) { writeErr(c, apiErr(404, "NOT_FOUND", "Không tìm thấy API")) })
	return r
}

func main() {
	internalKey, err := requireEnv("INTERNAL_KEY", 24)
	if err != nil {
		log.Fatal(err)
	}
	dsn, err := requireEnv("NOTIFICATION_DB_URL", 10)
	if err != nil {
		log.Fatal(err)
	}
	db, err := openDB(dsn)
	if err != nil {
		log.Fatal(err)
	}
	if db == nil { // NOTIFICATION_DROP_SCHEMA=1: chỉ xóa schema test rồi thoát
		log.Print("Đã xóa schema " + getenv("NOTIFICATION_DB_SCHEMA", ""))
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "--reset-db" { // dùng bởi `python manage.py reset-demo --yes`
		if err := db.Exec("DROP TABLE IF EXISTS notifications").Error; err != nil {
			log.Fatal(err)
		}
		if err := db.Exec(schemaSQL).Error; err != nil {
			log.Fatal(err)
		}
		log.Print("Đã xóa và tạo lại bảng notifications")
		return
	}
	addr := listenAddr()
	srv := &http.Server{Addr: addr, Handler: newRouter(db, internalKey, corsOrigins(), getenv("LOG_LEVEL", "INFO") == "WARNING"),
		ReadHeaderTimeout: 10 * time.Second}
	go func() {
		log.Printf("Notification Service (Go) chạy tại http://%s", addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Không mở được %s: %v", addr, err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}
