<?php
declare(strict_types=1);

/**
 * Gọi Auth và Order Service (giữ tên lớp của bản TV5).
 *  - Xác thực: GET Auth /api/users/me với token người dùng.
 *  - Kiểm tra đơn: GET Order /internal/orders/{id} với X-Internal-Key (Review không tin dữ liệu client gửi).
 * Ánh xạ lỗi thống nhất: không kết nối/quá giờ -> 503 UPSTREAM_UNAVAILABLE; 5xx -> 502 UPSTREAM_ERROR;
 * body không phải JSON object/list -> 502 UPSTREAM_BAD_RESPONSE; 4xx khác -> 502 UPSTREAM_REJECTED.
 */
final class Call_Auth_Order
{
    public static function call(string $method, string $url, string $service, ?string $token = null,
                                bool $internal = false, array $allow = []): array
    {
        $headers = ['Accept: application/json'];
        if ($token !== null) {
            $headers[] = 'Authorization: Bearer ' . $token;
        }
        if ($internal) {
            $headers[] = 'X-Internal-Key: ' . requireEnv('INTERNAL_KEY', 24);
        }
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT_MS => httpTimeoutMs(),
            CURLOPT_TIMEOUT_MS => httpTimeoutMs(),
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_PROXY => '',                    // gọi trực tiếp service nội bộ, không qua proxy hệ thống
        ]);
        $raw = curl_exec($curl);
        $errno = curl_errno($curl);
        $status = (int) curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
        curl_close($curl);
        if ($raw === false || $status === 0) {
            $msg = $errno === CURLE_OPERATION_TIMEDOUT ? "$service phản hồi quá thời gian chờ" : "Không kết nối được $service";
            throw new ApiError(503, 'UPSTREAM_UNAVAILABLE', $msg);
        }
        $body = json_decode((string) $raw, true, 64);
        if (($status >= 200 && $status < 300) || in_array($status, $allow, true)) {
            if (!is_array($body)) {
                throw new ApiError(502, 'UPSTREAM_BAD_RESPONSE', "$service trả dữ liệu không phải JSON hợp lệ");
            }
            return [$status, $body];
        }
        if ($status >= 500) {
            error_log("[review] $service trả $status cho $method $url");
            throw new ApiError(502, 'UPSTREAM_ERROR', "$service đang gặp lỗi, vui lòng thử lại");
        }
        throw new ApiError(502, 'UPSTREAM_REJECTED', "$service từ chối yêu cầu nội bộ (HTTP $status)");
    }

    /** Người dùng hiện tại; $roles rỗng = mọi vai trò. */
    public static function currentUser(array $roles = []): array
    {
        $token = bearerToken();
        if ($token === null) {
            throw new ApiError(401, 'UNAUTHORIZED', 'Cần đăng nhập (thiếu Bearer token)');
        }
        [$status, $data] = self::call('GET', serviceUrl('AUTH') . '/api/users/me', 'Auth Service', $token, false, [401, 403]);
        if ($status === 401) {
            throw new ApiError(401, is_string($data['code'] ?? null) ? $data['code'] : 'TOKEN_INVALID',
                'Phiên đăng nhập không hợp lệ hoặc đã hết hạn');
        }
        if ($status === 403) {
            throw new ApiError(403, is_string($data['code'] ?? null) ? $data['code'] : 'ACCOUNT_LOCKED',
                is_string($data['detail'] ?? null) ? $data['detail'] : 'Tài khoản đã bị khóa');
        }
        if (!isUuid($data['id'] ?? null) || !in_array($data['role'] ?? null, ['sinh_vien', 'chu_quan', 'admin'], true)
            || (array_key_exists('status', $data) && $data['status'] !== 'active')) {
            throw new ApiError(502, 'UPSTREAM_BAD_RESPONSE', 'Auth Service trả thông tin người dùng không đúng định dạng');
        }
        $user = ['id' => strtolower($data['id']), 'role' => $data['role'], 'name' => (string) ($data['name'] ?? '')];
        if ($roles && !in_array($user['role'], $roles, true)) {
            throw new ApiError(403, 'FORBIDDEN', 'Bạn không có quyền thực hiện thao tác này');
        }
        return $user;
    }

    /** Đơn hàng đã xác minh qua Order Service (API nội bộ). */
    public static function order(string $orderId): array
    {
        [$status, $order] = self::call('GET', serviceUrl('ORDER') . '/internal/orders/' . $orderId, 'Order Service',
            null, true, [404]);
        if ($status === 404) {
            throw new ApiError(404, 'ORDER_NOT_FOUND', 'Không tìm thấy đơn hàng');
        }
        foreach (['user_id', 'restaurant_id', 'restaurant_name', 'status'] as $field) {
            if (!isset($order[$field]) || !is_string($order[$field])) {
                throw new ApiError(502, 'UPSTREAM_BAD_RESPONSE', 'Order Service trả dữ liệu đơn không đúng định dạng');
            }
        }
        return $order;
    }
}
