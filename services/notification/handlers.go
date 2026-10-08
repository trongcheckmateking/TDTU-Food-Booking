package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type Server struct {
	db *gorm.DB
}

// ---------------------------------------------------------------- sự kiện đơn hàng
type OrderEvent struct {
	EventKey       string
	Event          string
	OrderID        string
	OrderCode      string
	StudentID      string
	OwnerID        string
	RestaurantName string
	ActorRole      string
}

type recipient struct {
	UserID  string
	Message string
}

// recipients: quy tắc người nhận
//
//	order_created -> chủ quán; order_confirmed / order_completed -> sinh viên;
//	order_cancelled: sinh viên hủy -> chủ quán; chủ quán hủy -> sinh viên; admin hủy -> cả hai.
func recipients(ev OrderEvent) []recipient {
	sv, owner, name, code := ev.StudentID, ev.OwnerID, ev.RestaurantName, ev.OrderCode
	switch ev.Event {
	case "order_created":
		return []recipient{{owner, fmt.Sprintf("Quán %s có đơn mới #%s, vui lòng xác nhận.", name, code)}}
	case "order_confirmed":
		return []recipient{{sv, fmt.Sprintf("Đơn #%s đã được quán %s xác nhận và đang chuẩn bị.", code, name)}}
	case "order_completed":
		return []recipient{{sv, fmt.Sprintf("Đơn #%s đã hoàn thành. Hãy đánh giá quán %s nhé!", code, name)}}
	}
	by := map[string]string{"sinh_vien": "sinh viên", "chu_quan": "quán", "admin": "quản trị viên"}[ev.ActorRole]
	msg := fmt.Sprintf("Đơn #%s tại quán %s đã bị hủy bởi %s.", code, name, by)
	switch ev.ActorRole {
	case "sinh_vien":
		return []recipient{{owner, msg}}
	case "chu_quan":
		return []recipient{{sv, msg}}
	default:
		return []recipient{{sv, msg}, {owner, msg}}
	}
}

// parseEvent: kiểm tra chặt body (trường lạ bị từ chối, chuỗi được cắt khoảng trắng, UUID, enum).
func parseEvent(raw []byte) (OrderEvent, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil || m == nil {
		return OrderEvent{}, &ApiError{Status: 422, Code: "VALIDATION_ERROR", Message: "JSON gửi lên không hợp lệ",
			Errors: []FieldError{{"body", "phải là JSON object"}}}
	}
	var errs []FieldError
	fields := []string{"event_key", "event", "order_id", "order_code", "student_id", "owner_id", "restaurant_name", "actor_role"}
	known := map[string]bool{}
	for _, f := range fields {
		known[f] = true
	}
	for k := range m {
		if !known[k] {
			errs = append(errs, FieldError{k, "trường không được phép"})
		}
	}
	val := map[string]string{}
	for _, f := range fields {
		r, ok := m[f]
		if !ok {
			errs = append(errs, FieldError{f, "bắt buộc"})
			continue
		}
		var s string
		if err := json.Unmarshal(r, &s); err != nil {
			errs = append(errs, FieldError{f, "phải là chuỗi"})
			continue
		}
		val[f] = strings.TrimSpace(s)
	}
	textLen := func(f string, min, max int) {
		if v, ok := val[f]; ok {
			n := len([]rune(v))
			if n < min || n > max {
				errs = append(errs, FieldError{f, fmt.Sprintf("độ dài phải từ %d đến %d ký tự", min, max)})
			}
		}
	}
	textLen("event_key", 10, 120)
	textLen("order_code", 1, 20)
	textLen("restaurant_name", 1, 150)
	for _, f := range []string{"order_id", "student_id", "owner_id"} {
		if v, ok := val[f]; ok {
			if !uuidRe.MatchString(v) {
				errs = append(errs, FieldError{f, "phải là UUID"})
			}
			val[f] = strings.ToLower(v)
		}
	}
	enum := func(f string, allowed ...string) {
		if v, ok := val[f]; ok {
			for _, a := range allowed {
				if v == a {
					return
				}
			}
			errs = append(errs, FieldError{f, "phải là một trong: " + strings.Join(allowed, ", ")})
		}
	}
	enum("event", "order_created", "order_confirmed", "order_completed", "order_cancelled")
	enum("actor_role", "sinh_vien", "chu_quan", "admin")
	if len(errs) > 0 {
		return OrderEvent{}, validationErr(errs)
	}
	return OrderEvent{val["event_key"], val["event"], val["order_id"], val["order_code"], val["student_id"],
		val["owner_id"], val["restaurant_name"], val["actor_role"]}, nil
}

func (s *Server) receiveEvent(c *gin.Context) {
	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, 100<<10))
	if err != nil {
		writeErr(c, err)
		return
	}
	ev, err := parseEvent(bytes.TrimSpace(raw))
	if err != nil {
		writeErr(c, err)
		return
	}
	rs := recipients(ev)
	created := int64(0)
	err = s.db.Transaction(func(tx *gorm.DB) error {
		for _, r := range rs {
			orderID := ev.OrderID
			n := Notification{ID: uuid.NewString(), UserID: r.UserID, OrderID: &orderID, EventKey: ev.EventKey,
				Type: ev.Event, Message: r.Message, Status: "unread", CreatedAt: time.Now().UTC()}
			res := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&n)
			if res.Error != nil {
				return res.Error
			}
			created += res.RowsAffected
		}
		return nil
	})
	if err != nil {
		writeErr(c, err)
		return
	}
	status := 200
	if created > 0 {
		status = 201
	}
	c.JSON(status, gin.H{"created": created, "duplicates": int64(len(rs)) - created})
}

// ---------------------------------------------------------------- tham số truy vấn
func intQuery(c *gin.Context, name string, def, min, max int) (int, error) {
	raw, ok := c.GetQuery(name)
	if !ok {
		return def, nil
	}
	n, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		return 0, validationErr([]FieldError{{name, "phải là số nguyên"}})
	}
	if n < min || n > max {
		return 0, validationErr([]FieldError{{name, fmt.Sprintf("phải trong khoảng %d–%d", min, max)}})
	}
	return n, nil
}

func enumQuery(c *gin.Context, name string, allowed ...string) (string, error) {
	raw, ok := c.GetQuery(name)
	if !ok {
		return "", nil
	}
	for _, a := range allowed {
		if raw == a {
			return raw, nil
		}
	}
	return "", validationErr([]FieldError{{name, "phải là một trong: " + strings.Join(allowed, ", ")}})
}

func uuidValue(raw, field string) (string, error) {
	if !uuidRe.MatchString(raw) {
		return "", validationErr([]FieldError{{field, "phải là UUID"}})
	}
	return strings.ToLower(raw), nil
}

func paging(c *gin.Context) (int, int, error) {
	page, err := intQuery(c, "page", 1, 1, 100000)
	if err != nil {
		return 0, 0, err
	}
	size, err := intQuery(c, "page_size", 20, 1, 100)
	return page, size, err
}

func (s *Server) pageOf(q *gorm.DB, page, size int) (gin.H, error) {
	var total int64
	if err := q.Session(&gorm.Session{}).Model(&Notification{}).Count(&total).Error; err != nil {
		return nil, err
	}
	var list []Notification
	if err := q.Session(&gorm.Session{}).Order("created_at DESC, id").Limit(size).Offset((page - 1) * size).
		Find(&list).Error; err != nil {
		return nil, err
	}
	items := make([]NotificationOut, 0, len(list))
	for _, n := range list {
		items = append(items, toOut(n))
	}
	return gin.H{"items": items, "total": total, "page": page, "page_size": size}, nil
}

// ---------------------------------------------------------------- người dùng
func (s *Server) myNotifications(c *gin.Context) {
	u := currentUser(c)
	status, err := enumQuery(c, "status", "unread", "read")
	if err != nil {
		writeErr(c, err)
		return
	}
	page, size, err := paging(c)
	if err != nil {
		writeErr(c, err)
		return
	}
	q := s.db.Model(&Notification{}).Where("user_id = ?", u.ID)
	if status != "" {
		q = q.Where("status = ?", status)
	}
	res, err := s.pageOf(q, page, size)
	if err != nil {
		writeErr(c, err)
		return
	}
	var unread int64
	if err := s.db.Model(&Notification{}).Where("user_id = ? AND status = 'unread'", u.ID).Count(&unread).Error; err != nil {
		writeErr(c, err)
		return
	}
	res["unread"] = unread
	c.JSON(200, res)
}

func (s *Server) readAll(c *gin.Context) {
	res := s.db.Model(&Notification{}).Where("user_id = ? AND status = 'unread'", currentUser(c).ID).
		Updates(map[string]any{"status": "read", "read_at": time.Now().UTC()})
	if res.Error != nil {
		writeErr(c, res.Error)
		return
	}
	c.JSON(200, gin.H{"updated": res.RowsAffected})
}

func (s *Server) markRead(c *gin.Context) {
	id, err := uuidValue(c.Param("nid"), "nid")
	if err != nil {
		writeErr(c, err)
		return
	}
	var n Notification
	if err := s.db.First(&n, "id = ?", id).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErr(c, apiErr(404, "NOTIFICATION_NOT_FOUND", "Không tìm thấy thông báo"))
		} else {
			writeErr(c, err)
		}
		return
	}
	if n.UserID != currentUser(c).ID {
		writeErr(c, apiErr(403, "FORBIDDEN", "Không phải thông báo của bạn"))
		return
	}
	if n.Status == "unread" {
		if err := s.db.Model(&Notification{}).Where("id = ? AND status = 'unread'", n.ID).
			Updates(map[string]any{"status": "read", "read_at": time.Now().UTC()}).Error; err != nil {
			writeErr(c, err)
			return
		}
		if err := s.db.First(&n, "id = ?", id).Error; err != nil {
			writeErr(c, err)
			return
		}
	}
	c.JSON(200, toOut(n))
}

// ---------------------------------------------------------------- admin
func (s *Server) adminList(c *gin.Context) {
	status, err := enumQuery(c, "status", "unread", "read")
	if err != nil {
		writeErr(c, err)
		return
	}
	q := s.db.Model(&Notification{})
	if raw, ok := c.GetQuery("user_id"); ok {
		uid, err := uuidValue(raw, "user_id")
		if err != nil {
			writeErr(c, err)
			return
		}
		q = q.Where("user_id = ?", uid)
	}
	page, size, err := paging(c)
	if err != nil {
		writeErr(c, err)
		return
	}
	if status != "" {
		q = q.Where("status = ?", status)
	}
	res, err := s.pageOf(q, page, size)
	if err != nil {
		writeErr(c, err)
		return
	}
	res["unread"] = nil
	c.JSON(200, res)
}

func (s *Server) adminDelete(c *gin.Context) {
	id, err := uuidValue(c.Param("nid"), "nid")
	if err != nil {
		writeErr(c, err)
		return
	}
	res := s.db.Where("id = ?", id).Delete(&Notification{})
	if res.Error != nil {
		writeErr(c, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		writeErr(c, apiErr(404, "NOTIFICATION_NOT_FOUND", "Không tìm thấy thông báo"))
		return
	}
	c.Status(204)
}
