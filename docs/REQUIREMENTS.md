# Đối chiếu yêu cầu

**Chưa có đề giữa kỳ gốc.** Phạm vi dưới đây lấy từ: kế hoạch phân công TV1–TV5 [KH], tài liệu bàn giao [BG],
sơ đồ Use Case/DFD/ERD [SĐ], ảnh đặc điểm FastAPI [Ả], mã nguồn hai bộ code [M], và prompt hoàn thiện [PR].
Ảnh chỉ mô tả đặc điểm FastAPI, không chứa danh sách chức năng hay thang điểm. Tài liệu này **không** khẳng định
đáp ứng đủ rubric của giảng viên. Khi có đề gốc, cần đối chiếu lại bảng này.

Tên test: `I:` = `tests/integration` (5 tiến trình thật, 5 ngôn ngữ), `U:` = `tests/unit`, `E:` = `tests/e2e`,
`UI:` = `tests/ui`, `S:` = test riêng của service (`node --test`, `go test`, `php tests/run.php`, JUnit).

## Giả định đã chọn

1. **Mỗi service một ngôn ngữ** (nhóm xác nhận): Auth Python, Restaurant Node.js, Order Java Spring Boot,
   Notification Go + PostgreSQL, Review PHP; dùng chung một hợp đồng API.
2. "Duyệt quán" trong DFD = quán mới ở `pending`, admin chuyển `active`; "từ chối" = `locked` kèm lý do.
3. "Xóa tài khoản" = khóa (vô hiệu hóa) để giữ lịch sử; không có xóa cứng.
4. Admin chỉ hủy đơn lỗi, không xác nhận/hoàn thành thay chủ quán (theo bản Java).
5. Giờ mở cửa chỉ để hiển thị; việc nhận đơn do trạng thái quán quyết định (tránh hỏng demo theo giờ máy).
6. Không tích hợp thanh toán, shipper, email/SMS (không có trong nguồn).

## Bảng đối chiếu

| Nguồn | Chức năng | API / Giao diện | Test | Trạng thái |
| --- | --- | --- | --- | --- |
| KH TV1, BG | Đăng ký (kiểm tra dữ liệu), đăng nhập trả token | `POST /api/users/register`, `/login`; trang đăng nhập/đăng ký | I: `test_register_login_me_and_profile`, `test_register_validation`, `test_login_errors`; UI: `test_full_flow_three_roles` | Hoàn thành |
| KH TV1 | Kiểm tra token, phân quyền 3 vai trò | `GET /api/users/me`; client xác thực trong từng ngôn ngữ (`auth.js`, `AuthClient.java`, `auth.go`, `Call_Auth_Order.php`) | I: `test_jwt_rejections`, `test_owner_id_from_token_and_role_checks`; E: `test_negative_security_on_real_services` | Hoàn thành |
| SĐ UC Auth | Đăng xuất | `POST /api/users/logout` (thu hồi token) + xóa phiên ở client | I: `test_logout_revokes_tokens` | Hoàn thành |
| SĐ DFD Auth, PR | Admin khóa / mở khóa, đổi vai trò; bảo vệ admin cuối | `PATCH /api/users/{id}/status`, `/role`; tab Người dùng | I: `test_lock_unlock_blocks_everywhere`, `test_last_admin_never_lost_under_concurrency`, `test_self_action_blocked`, `test_demote_owner_with_restaurants_blocked`; UI: khóa tài khoản trong `test_full_flow_three_roles` | Hoàn thành |
| PR | Không tự đăng ký admin, email không phân biệt hoa thường, mật khẩu ≤ 72 byte | `RegisterIn` | I: `test_register_validation`, `test_duplicate_email_case_insensitive` | Hoàn thành |
| KH TV2, SĐ | Thêm/xem/sửa/xóa quán; owner lấy từ token | `/api/restaurants*`; tab Quán của tôi | I: `test_owner_id_from_token_and_role_checks`, `test_cross_owner_forbidden`, `test_soft_delete` | Hoàn thành |
| KH TV2 | Thêm/xem/sửa/xóa món, giá, trạng thái món | `/api/restaurants/{id}/menu`, `/api/menu-items/{id}`; tab Thực đơn | I: `test_menu_validation`, `test_hidden_and_sold_out_visibility` | Hoàn thành |
| SĐ DFD Restaurant | Admin duyệt / khóa / mở khóa quán | `PATCH /api/admin/restaurants/{id}/status`; tab Quán ăn (admin) | I: `test_new_restaurant_pending_until_approved`, `test_locked_restaurant`; UI: duyệt quán | Hoàn thành |
| SĐ, PR | Xem, tìm quán, menu, tạm đóng | `GET /api/restaurants?q=`, tab Quán ăn | I: `test_owner_open_close`; UI: `test_full_flow_three_roles` | Hoàn thành |
| KH TV3, Java | Giỏ hàng: thêm, đổi số lượng, xóa món, xóa giỏ, 1 quán/giỏ | `/api/cart*`; tab Giỏ hàng | I: `test_cart_operations`, `test_cart_single_restaurant_and_switch_when_empty`, `test_cart_validation_and_availability` | Hoàn thành |
| KH TV3, PR | Đặt món (checkout) kiểm tra lại giá, giao dịch, ảnh chụp giá, chống trùng | `POST /api/orders/checkout` + `Idempotency-Key` | I: `test_checkout_snapshot_and_history_survives_menu_changes`, `test_checkout_rejects_unavailable_and_keeps_cart`, `test_checkout_idempotency_and_double_click`; E: luồng đầy đủ | Hoàn thành |
| KH TV3 | Xem đơn theo người dùng, theo quán, lọc | `/api/orders/me`, `/owner`, `/api/admin/orders` | I: `test_lists_filters_and_pagination` | Hoàn thành |
| KH TV3, BG | Cập nhật trạng thái pending/confirmed/completed/cancelled đúng quyền | `PATCH /api/orders/{id}/status` | I: `test_status_rules_by_role`, `test_cancel_by_student_and_admin`, `test_concurrent_status_updates`; S: `OrderStatusTest` (JUnit) | Hoàn thành |
| KH TV4 | Thông báo đơn mới, xác nhận, hoàn thành (và hủy) | `POST /internal/notifications/events` | I: `test_recipients_by_event_and_actor`; S: `TestRecipients` (go test) | Hoàn thành |
| KH TV4, SĐ UC | Xem lịch sử, lọc chưa đọc, đánh dấu đã đọc 1/tất cả | `/api/notifications/me*`; tab Thông báo + chuông | I: `test_read_one_all_and_ownership`; UI: đánh dấu tất cả | Hoàn thành |
| PR | Endpoint sự kiện chỉ cho service tin cậy; lỗi thông báo không mất đơn; gửi lại không trùng | Outbox + `X-Internal-Key` + `UNIQUE(event_key,user_id)` | I: `test_internal_event_requires_key_and_is_idempotent`, `test_notifications_flow_and_outbox_retry_without_duplicates`; E: `test_full_business_flow_restart_and_notification_outage` | Hoàn thành |
| KH TV5 | Đánh giá, chấm sao sau khi đơn hoàn thành; 1 đơn 1 đánh giá | `POST /api/reviews` | I: `test_review_conditions`, `test_review_input_validation`, `test_concurrent_reviews_same_order` | Hoàn thành |
| KH TV5 | Xem đánh giá theo quán, điểm trung bình, phân bố sao | `/api/reviews/restaurant/{id}`, `/summary` | I: `test_summary_rounding_privacy_and_moderation` | Hoàn thành |
| SĐ DFD Review | Admin xử lý đánh giá vi phạm | `PATCH /api/admin/reviews/{id}/status`; tab Đánh giá | I: `test_summary_rounding_privacy_and_moderation`; UI: ẩn đánh giá | Hoàn thành |
| KH chung | Trang Admin quản lý user, quán, đơn (+ thông báo, đánh giá) | `admin.html` | UI: `test_full_flow_three_roles` | Hoàn thành |
| PR | Giao diện sinh viên, chủ quán; trạng thái tải/rỗng/lỗi/hết phiên; điện thoại | `student.html`, `owner.html` | UI: `test_full_flow_three_roles`, `test_session_expired_redirects`, `test_mobile_layout_no_horizontal_scroll` | Hoàn thành |
| KH chung | Ghép nối các service gọi nhau | REST nội bộ, xem `API.md` | E: cả 3 test; `scripts/smoke_test.py` | Hoàn thành |
| Ả, PR | Swagger UI, ReDoc, OpenAPI có Bearer | `/docs`, `/redoc`, `/openapi.json` | I: `test_docs_openapi_health_cors_404` (5 service); E: `test_status_and_docs` | Hoàn thành |
| PR | Lỗi upstream ánh xạ 502/503, timeout (giống nhau ở 5 ngôn ngữ) | `http.py`, `http.js`, `Upstream.java`, `errors.go`, `Call_Auth_Order.php` | U: `test_http_call_error_mapping`; I: `test_auth_errors_and_upstream_mapping_same_in_every_language`, `test_auth_upstream_errors_mapped`, `test_review_upstream_failures`, `test_checkout_rejects_unavailable_and_keeps_cart`; S: `TestCallServiceErrorMapping`, Review `upstream *` | Hoàn thành |
| PR | Không có secret mặc định; dừng khi thiếu cấu hình | `.env.example`, bộ đọc cấu hình của từng ngôn ngữ | U: `test_auth_missing_or_short_jwt_secret_stops_startup`; I: `test_missing_internal_key_stops_startup`, `test_review_refuses_requests_without_internal_key` | Hoàn thành |
| PR | Định dạng lỗi 422 thống nhất, JSON hỏng, API nội bộ cần khóa ở mọi ngôn ngữ | – | I: `test_validation_error_format`, `test_internal_apis_require_key_in_every_language` | Hoàn thành |
| PR | Dữ liệu còn sau restart | SQLite, H2 tệp, PostgreSQL | E: `test_full_business_flow_restart_and_notification_outage` | Hoàn thành |
| KH | Use Case, DFD mức 1/2, ERD từng service + tổng | `docs/diagrams/` | Sinh lại bằng `gen_diagrams.py` | Hoàn thành |
| KH | Báo cáo từng phần / báo cáo chung theo khung TDTU | – | – | Ngoài phạm vi mã: `PROJECT_SUMMARY.md` cung cấp nội dung, nhóm tự trình bày theo khung báo cáo |
| BG, nhóm | Mỗi service một ngôn ngữ khác nhau | Python, Node.js, Java, Go, PHP (xem `ARCHITECTURE.md`) | I: toàn bộ chạy trên 5 runtime thật; E: `test_status_and_docs` kiểm tra 5 runtime | Hoàn thành |
