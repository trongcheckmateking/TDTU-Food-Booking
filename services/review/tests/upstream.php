<?php
declare(strict_types=1);

/**
 * Auth + Order giả cho test riêng của Review (php -S ... tests/upstream.php).
 * Token: sv1, sv2, owner, admin, locked. Đơn: ...0301 completed của sv1, ...0302 pending của sv1,
 * ...0303 completed của sv2. Đường dẫn /mode/{x} đổi chế độ lỗi: ok | 500 | badjson | slow.
 */
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$modeFile = sys_get_temp_dir() . '/review-upstream-mode-' . getenv('UPSTREAM_TAG');
if (preg_match('#^/mode/(\w+)$#', $path, $m)) {
    file_put_contents($modeFile, $m[1]);
    exit('{}');
}
$mode = is_file($modeFile) ? trim((string) file_get_contents($modeFile)) : 'ok';
header('Content-Type: application/json');
if ($mode === '500') {
    http_response_code(500);
    exit('{"detail":"boom"}');
}
if ($mode === 'badjson') {
    exit('<html>');
}
if ($mode === 'slow') {
    sleep(3);
}
$U = fn(int $n) => sprintf('00000000-0000-4000-8000-%012d', $n);
$users = [
    'sv1' => ['id' => $U(21), 'role' => 'sinh_vien', 'name' => 'Nguyễn Văn An', 'status' => 'active'],
    'sv2' => ['id' => $U(22), 'role' => 'sinh_vien', 'name' => 'Phạm Thị Bình', 'status' => 'active'],
    'owner' => ['id' => $U(11), 'role' => 'chu_quan', 'name' => 'Chủ Quán', 'status' => 'active'],
    'admin' => ['id' => $U(1), 'role' => 'admin', 'name' => 'Admin', 'status' => 'active'],
];
if ($path === '/api/users/me') {
    $token = preg_replace('/^Bearer /', '', $_SERVER['HTTP_AUTHORIZATION'] ?? '');
    if ($token === 'locked') {
        http_response_code(403);
        exit('{"detail":"Tài khoản đã bị khóa","code":"ACCOUNT_LOCKED"}');
    }
    if (!isset($users[$token])) {
        http_response_code(401);
        exit('{"detail":"x","code":"TOKEN_INVALID"}');
    }
    exit(json_encode($users[$token]));
}
if (preg_match('#^/internal/orders/(.+)$#', $path, $m)) {
    if (($_SERVER['HTTP_X_INTERNAL_KEY'] ?? '') !== getenv('INTERNAL_KEY')) {
        http_response_code(403);
        exit('{"code":"INTERNAL_ONLY"}');
    }
    $orders = [
        $U(301) => ['user_id' => $U(21), 'status' => 'completed'],
        $U(302) => ['user_id' => $U(21), 'status' => 'pending'],
        $U(303) => ['user_id' => $U(22), 'status' => 'completed'],
        $U(304) => ['user_id' => $U(21), 'status' => 'completed'],
    ];
    if (!isset($orders[$m[1]])) {
        http_response_code(404);
        exit('{"code":"ORDER_NOT_FOUND"}');
    }
    exit(json_encode(['id' => $m[1], 'restaurant_id' => $U(101), 'restaurant_name' => 'Cơm Tấm Cô Ba'] + $orders[$m[1]]));
}
http_response_code(404);
echo '{"code":"NOT_FOUND"}';
