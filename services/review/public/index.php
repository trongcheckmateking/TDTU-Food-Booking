<?php
declare(strict_types=1);

/**
 * Review Service (PHP, cổng 8005) - front controller.
 * Chạy: php -S 127.0.0.1:8005 public/index.php   (hoặc python manage.py start)
 * Hợp đồng API: openapi.json (xem /docs).
 */
require dirname(__DIR__) . '/src/bootstrap.php';

function docsPage(string $kind): string
{
    if ($kind === 'redoc') {
        return '<!doctype html><html><head><meta charset="utf-8"><title>Review Service - API docs</title></head><body>'
            . '<redoc spec-url="/openapi.json"></redoc>'
            . '<script src="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"></script></body></html>';
    }
    return '<!doctype html><html><head><meta charset="utf-8"><title>Review Service - API docs</title>'
        . '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head><body>'
        . '<div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js">'
        . '</script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",persistAuthorization:true});</script>'
        . '</body></html>';
}

try {
    requireEnv('INTERNAL_KEY', 24);
    applyCors(corsOrigins());
    $duongDan = rawurldecode((string) parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH));
    $phuongThuc = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $route = "$phuongThuc $duongDan";

    // ---------------------------------------------------------- health & tài liệu
    if ($route === 'GET /') {
        jsonResponse(200, ['service' => 'review', 'status' => 'ok', 'docs' => '/docs']);
    }
    if ($route === 'GET /health') {
        try {
            connectDatabase()->query('SELECT 1')->fetchColumn();
            jsonResponse(200, ['service' => 'review', 'status' => 'ok', 'db' => 'ok']);
        } catch (PDOException) {
            jsonResponse(503, ['service' => 'review', 'status' => 'degraded', 'db' => 'error']);
        }
    }
    if ($route === 'GET /openapi.json') {
        header('Content-Type: application/json; charset=utf-8');
        readfile(dirname(__DIR__) . '/openapi.json');
        exit;
    }
    if ($route === 'GET /docs' || $route === 'GET /redoc') {
        header('Content-Type: text/html; charset=utf-8');
        echo docsPage($duongDan === '/redoc' ? 'redoc' : 'swagger');
        exit;
    }

    $reviews = new Reviews(connectDatabase());

    // ---------------------------------------------------------- sinh viên
    if ($route === 'POST /api/reviews') {
        $user = Call_Auth_Order::currentUser(['sinh_vien']);
        $input = Reviews::validate(jsonBody());
        $order = Call_Auth_Order::order($input['order_id']);
        if (strtolower($order['user_id']) !== $user['id']) {
            throw new ApiError(403, 'ORDER_NOT_OWNED', 'Bạn chỉ được đánh giá đơn hàng của mình');
        }
        if ($order['status'] !== 'completed') {
            throw new ApiError(409, 'ORDER_NOT_COMPLETED', 'Chỉ đánh giá được đơn đã hoàn thành');
        }
        jsonResponse(201, $reviews->create($input, $user, $order));
    }
    if ($route === 'GET /api/reviews/me') {
        $user = Call_Auth_Order::currentUser();
        jsonResponse(200, $reviews->mine($user['id']));
    }

    // ---------------------------------------------------------- công khai
    if ($route === 'GET /api/reviews/summary') {
        $raw = $_GET['restaurant_ids'] ?? null;
        if (!is_string($raw) || strlen($raw) > 2000) {
            throw validationError([['field' => 'restaurant_ids', 'message' => 'bắt buộc, tối đa 2000 ký tự']]);
        }
        $ids = array_values(array_filter(array_map('trim', explode(',', $raw)), fn($x) => $x !== ''));
        if (!$ids || count($ids) > 50) {
            throw new ApiError(422, 'VALIDATION_ERROR', 'Cần 1–50 restaurant_id');
        }
        foreach ($ids as $id) {
            if (!isUuid($id)) {
                throw new ApiError(422, 'VALIDATION_ERROR', 'restaurant_id phải là UUID');
            }
        }
        jsonResponse(200, array_map(fn($id) => $reviews->summary(strtolower($id)), $ids));
    }
    if ($phuongThuc === 'GET' && preg_match('#^/api/reviews/restaurant/([^/]+)/summary$#D', $duongDan, $m)) {
        jsonResponse(200, $reviews->summary(uuidParam($m[1], 'rid')));
    }
    if ($phuongThuc === 'GET' && preg_match('#^/api/reviews/restaurant/([^/]+)$#D', $duongDan, $m)) {
        $rid = uuidParam($m[1], 'rid');
        [$page, $size] = pageQuery(10);
        jsonResponse(200, $reviews->forRestaurant($rid, $page, $size));
    }

    // ---------------------------------------------------------- admin
    if ($route === 'GET /api/admin/reviews') {
        Call_Auth_Order::currentUser(['admin']);
        $status = enumQuery('status', ['visible', 'hidden']);
        $maxRating = array_key_exists('max_rating', $_GET) ? intQuery('max_rating', 5, 1, 5) : null;
        $rid = array_key_exists('restaurant_id', $_GET) ? uuidParam((string) $_GET['restaurant_id'], 'restaurant_id') : null;
        [$page, $size] = pageQuery(20);
        jsonResponse(200, $reviews->adminList($status, $maxRating, $rid, $page, $size));
    }
    if ($phuongThuc === 'PATCH' && preg_match('#^/api/admin/reviews/([^/]+)/status$#D', $duongDan, $m)) {
        Call_Auth_Order::currentUser(['admin']);
        $id = uuidParam($m[1], 'review_id');
        $body = jsonBody();
        $errors = [];
        rejectUnknown($body, ['status', 'reason'], $errors);
        if (!in_array($body['status'] ?? null, ['visible', 'hidden'], true)) {
            $errors[] = ['field' => 'status', 'message' => 'phải là visible hoặc hidden'];
        }
        $reason = optionalText($body, 'reason', 300, $errors);
        if ($errors) {
            throw validationError($errors);
        }
        jsonResponse(200, $reviews->setVisibility($id, $body['status'], $reason));
    }

    throw new ApiError(404, 'NOT_FOUND', 'Không tìm thấy API');
} catch (ApiError $loi) {
    errorResponse($loi);
} catch (Throwable $loi) {
    error_log('[review] Lỗi không mong đợi: ' . get_class($loi) . ': ' . $loi->getMessage());
    if ($loi instanceof RuntimeException && str_starts_with($loi->getMessage(), 'Thiếu cấu hình')) {
        jsonResponse(500, ['detail' => $loi->getMessage(), 'code' => 'CONFIG_ERROR']);
    }
    jsonResponse(500, ['detail' => 'Có lỗi nội bộ, vui lòng thử lại sau', 'code' => 'INTERNAL_ERROR']);
}
