<?php
declare(strict_types=1);

/**
 * Test riêng của Review Service: php tests/run.php
 * Chạy Review thật (php -S) với DB SQLite tạm, Auth/Order được thay bằng server giả (tests/upstream.php).
 * Test liên service với Auth/Order thật nằm ở tests/ của dự án (pytest).
 */
$root = dirname(__DIR__);
$tmp = sys_get_temp_dir() . '/review-test-' . bin2hex(random_bytes(4));
mkdir($tmp);
$tag = bin2hex(random_bytes(4));
$key = 'test-internal-key-' . str_repeat('y', 16);

function freePort(): int
{
    $s = stream_socket_server('tcp://127.0.0.1:0');
    $port = (int) substr(strrchr(stream_socket_get_name($s, false), ':'), 1);
    fclose($s);
    return $port;
}

function startServer(int $port, string $router, array $env, string $docroot): array
{
    $cmd = [PHP_BINARY, '-S', "127.0.0.1:$port", '-t', $docroot, $router];
    $proc = proc_open($cmd, [0 => ['pipe', 'r'], 1 => ['file', DIRECTORY_SEPARATOR === '\\' ? 'NUL' : '/dev/null', 'w'],
        2 => ['file', DIRECTORY_SEPARATOR === '\\' ? 'NUL' : '/dev/null', 'w']], $pipes, null, $env + getenv());
    for ($i = 0; $i < 50; $i++) {
        $c = @fsockopen('127.0.0.1', $port, $e, $s, 0.2);
        if ($c) {
            fclose($c);
            return [$proc, $pipes];
        }
        usleep(100000);
    }
    throw new RuntimeException("Không khởi động được server cổng $port");
}

$upPort = freePort();
$revPort = freePort();
$up = startServer($upPort, "$root/tests/upstream.php", ['UPSTREAM_TAG' => $tag, 'INTERNAL_KEY' => $key], "$root/tests");
$rev = startServer($revPort, "$root/public/index.php", [
    'TDTU_ENV_FILE' => "$tmp/no.env", 'DATA_DIR' => $tmp, 'INTERNAL_KEY' => $key, 'HTTP_TIMEOUT' => '1',
    'AUTH_URL' => "http://127.0.0.1:$upPort", 'ORDER_URL' => "http://127.0.0.1:$upPort",
    'CORS_ORIGINS' => 'http://127.0.0.1:8000',
], "$root/public");

function req(string $method, string $url, ?string $token = null, mixed $json = null, ?string $raw = null, array $headers = []): array
{
    $h = $headers;
    if ($token !== null) {
        $h[] = "Authorization: Bearer $token";
    }
    $body = $raw ?? ($json === null ? null : json_encode($json));
    if ($body !== null) {
        $h[] = 'Content-Type: application/json';
    }
    $c = curl_init($url);
    curl_setopt_array($c, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => $h,
        CURLOPT_HEADER => true, CURLOPT_TIMEOUT => 10, CURLOPT_PROXY => '']);
    if ($body !== null) {
        curl_setopt($c, CURLOPT_POSTFIELDS, $body);
    }
    $resp = (string) curl_exec($c);
    $status = curl_getinfo($c, CURLINFO_RESPONSE_CODE);
    $hsize = curl_getinfo($c, CURLINFO_HEADER_SIZE);
    unset($c);                      // curl_close() không còn tác dụng từ PHP 8.0 (và bị đánh dấu lỗi thời từ 8.5)
    return [$status, json_decode(substr($resp, $hsize), true), strtolower(substr($resp, 0, $hsize))];
}

$passed = 0;
$failed = [];
function check(string $name, bool $ok, mixed $info = null): void
{
    global $passed, $failed;
    if ($ok) {
        $passed++;
    } else {
        $failed[] = $name . ($info !== null ? ' -> ' . json_encode($info, JSON_UNESCAPED_UNICODE) : '');
    }
}

$B = "http://127.0.0.1:$revPort";
$U = fn(int $n) => sprintf('00000000-0000-4000-8000-%012d', $n);
$R1 = $U(101);
try {
    // health, docs, CORS, 404
    [$s, $b] = req('GET', "$B/health");
    check('health', $s === 200 && $b === ['service' => 'review', 'status' => 'ok', 'db' => 'ok'], $b);
    [$s, $b] = req('GET', "$B/openapi.json");
    check('openapi', $s === 200 && str_ends_with($b['info']['title'], 'Service'));
    [$s, , $h] = req('OPTIONS', "$B/health", null, null, null, ['Origin: http://127.0.0.1:8000', 'Access-Control-Request-Method: GET']);
    check('cors cho phép', str_contains($h, 'access-control-allow-origin: http://127.0.0.1:8000'));
    [$s, , $h] = req('GET', "$B/health", null, null, null, ['Origin: http://evil.example']);
    check('cors chặn', !str_contains($h, 'access-control-allow-origin'));
    [$s, $b] = req('GET', "$B/khong-co");
    check('404 json', $s === 404 && $b['code'] === 'NOT_FOUND');

    // chưa có đánh giá -> average null
    [$s, $b] = req('GET', "$B/api/reviews/restaurant/$R1/summary");
    check('summary rỗng', $s === 200 && $b['average'] === null && $b['count'] === 0 && $b['distribution']['5'] === 0, $b);

    // quyền và dữ liệu vào
    [$s] = req('POST', "$B/api/reviews", null, ['order_id' => $U(301), 'rating' => 5]);
    check('không token 401', $s === 401);
    [$s, $b] = req('POST', "$B/api/reviews", 'owner', ['order_id' => $U(301), 'rating' => 5]);
    check('chủ quán 403', $s === 403);
    [$s, $b] = req('POST', "$B/api/reviews", 'locked', ['order_id' => $U(301), 'rating' => 5]);
    check('tài khoản khóa 403', $s === 403 && $b['code'] === 'ACCOUNT_LOCKED', $b);
    foreach ([['order_id' => $U(301), 'rating' => 0], ['order_id' => $U(301), 'rating' => 6], ['order_id' => $U(301), 'rating' => 4.5],
                 ['order_id' => $U(301), 'rating' => '5'], ['order_id' => $U(301), 'rating' => true], ['order_id' => 'abc', 'rating' => 5],
                 ['order_id' => $U(301), 'rating' => 5, 'restaurant_id' => $R1], ['order_id' => $U(301), 'rating' => 5, 'comment' => str_repeat('a', 1001)],
                 ['rating' => 5]] as $i => $body) {
        [$s, $b] = req('POST', "$B/api/reviews", 'sv1', $body);
        check("422 case $i", $s === 422 && $b['code'] === 'VALIDATION_ERROR' && is_array($b['errors']), [$s, $b]);
    }
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', null, '{"order_id":');
    check('JSON hỏng', $s === 422 && $b['detail'] === 'JSON gửi lên không hợp lệ', $b);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(302), 'rating' => 5]);
    check('đơn chưa xong 409', $s === 409 && $b['code'] === 'ORDER_NOT_COMPLETED', $b);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(303), 'rating' => 5]);
    check('đơn người khác 403', $s === 403 && $b['code'] === 'ORDER_NOT_OWNED', $b);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(999), 'rating' => 5]);
    check('đơn không tồn tại 404', $s === 404 && $b['code'] === 'ORDER_NOT_FOUND', $b);

    // tạo đánh giá
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(301), 'rating' => 5, 'comment' => '  Ngon, giao nhanh.  ']);
    check('tạo 201', $s === 201 && $b['reviewer_name'] === 'Nguyễn Văn An' && $b['restaurant_id'] === $R1
        && $b['comment'] === 'Ngon, giao nhanh.' && $b['status'] === 'visible', $b);
    $rev1 = $b['id'] ?? '';
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(301), 'rating' => 1]);
    check('trùng 409', $s === 409 && $b['code'] === 'REVIEW_EXISTS', $b);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv2', ['order_id' => $U(303), 'rating' => 4]);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(304), 'rating' => 4]);
    [$s, $b] = req('GET', "$B/api/reviews/restaurant/$R1/summary");
    check('TB half-up 4.3', $b['average'] === 4.3 && $b['count'] === 3 && $b['distribution']['4'] === 2, $b);
    [$s, $b] = req('GET', "$B/api/reviews/restaurant/$R1?page_size=2");
    check('danh sách công khai', $s === 200 && $b['total'] === 3 && count($b['items']) === 2
        && !isset($b['items'][0]['user_id']) && !isset($b['items'][0]['order_id']) && $b['summary']['count'] === 3, $b);
    [$s, $b] = req('GET', "$B/api/reviews/summary?restaurant_ids=$R1,{$U(102)}");
    check('summary nhiều quán', $s === 200 && count($b) === 2 && $b[1]['average'] === null, $b);
    [$s] = req('GET', "$B/api/reviews/summary?restaurant_ids=abc");
    check('summary id sai 422', $s === 422);
    [$s] = req('GET', "$B/api/reviews/summary");
    check('summary thiếu tham số 422', $s === 422);
    [$s, $b] = req('GET', "$B/api/reviews/me", 'sv1');
    check('của tôi', $s === 200 && count($b) === 2, $b);

    // admin ẩn / hiện
    [$s] = req('GET', "$B/api/admin/reviews", 'sv1');
    check('sv xem admin 403', $s === 403);
    [$s, $b] = req('GET', "$B/api/admin/reviews?max_rating=4", 'admin');
    check('admin lọc sao', $s === 200 && $b['total'] === 2 && isset($b['items'][0]['user_id']), $b);
    [$s, $b] = req('PATCH', "$B/api/admin/reviews/$rev1/status", 'admin', ['status' => 'hidden', 'reason' => 'Spam']);
    check('ẩn', $s === 200 && $b['status'] === 'hidden' && $b['hidden_reason'] === 'Spam', $b);
    [$s, $b] = req('GET', "$B/api/reviews/restaurant/$R1/summary");
    check('TB sau khi ẩn = 4.0', $b['average'] === 4.0 && $b['count'] === 2, $b);
    [$s, $b] = req('POST', "$B/api/reviews", 'sv1', ['order_id' => $U(301), 'rating' => 5]);
    check('đơn đã đánh giá (bị ẩn) không đánh giá lại', $s === 409, $b);
    [$s] = req('PATCH', "$B/api/admin/reviews/{$U(77)}/status", 'admin', ['status' => 'hidden']);
    check('ẩn id không có 404', $s === 404);
    [$s] = req('PATCH', "$B/api/admin/reviews/$rev1/status", 'admin', ['status' => 'deleted']);
    check('trạng thái sai 422', $s === 422);
    [$s, $b] = req('PATCH', "$B/api/admin/reviews/$rev1/status", 'admin', ['status' => 'visible', 'reason' => 'x']);
    check('hiện lại', $s === 200 && $b['hidden_reason'] === null, $b);
    [$s] = req('GET', "$B/api/reviews/restaurant/khong-phai-uuid");
    check('rid sai 422', $s === 422);
    [$s] = req('GET', "$B/api/reviews/restaurant/$R1?page=0");
    check('page sai 422', $s === 422);

    // nội bộ: xóa dữ liệu cá nhân -> tên người viết bị ẩn danh, điểm của quán giữ nguyên
    $erase = "$B/internal/users/{$U(21)}/erase";
    [$s, $b] = req('POST', $erase);
    check('xóa dữ liệu thiếu khóa 403', $s === 403 && $b['code'] === 'INTERNAL_ONLY', $b);
    [$s] = req('POST', $erase, null, null, null, ['X-Internal-Key: sai']);
    check('xóa dữ liệu sai khóa 403', $s === 403);
    [$s] = req('POST', "$B/internal/users/abc/erase", null, null, null, ["X-Internal-Key: $key"]);
    check('xóa dữ liệu id sai 422', $s === 422);
    [$s, $b] = req('POST', $erase, null, null, null, ["X-Internal-Key: $key"]);
    check('xóa dữ liệu', $s === 200 && $b['reviews_anonymized'] === 2, $b);
    [$s, $b] = req('GET', "$B/api/reviews/restaurant/$R1?page_size=10");
    $names = array_count_values(array_column($b['items'] ?? [], 'reviewer_name'));
    check('tên người viết đã ẩn danh', ($names['Người dùng đã xóa'] ?? 0) === 2 && !isset($names['Nguyễn Văn An'])
        && ($names['Phạm Thị Bình'] ?? 0) === 1 && $b['summary']['count'] === 3, $b);
    [$s, $b] = req('POST', $erase, null, null, null, ["X-Internal-Key: $key"]);
    check('xóa dữ liệu gọi lại an toàn', $s === 200 && $b['reviews_anonymized'] === 2, $b);

    // lỗi upstream
    foreach ([['500', 502, 'UPSTREAM_ERROR'], ['badjson', 502, 'UPSTREAM_BAD_RESPONSE'], ['slow', 503, 'UPSTREAM_UNAVAILABLE']] as [$mode, $st, $code]) {
        req('GET', "http://127.0.0.1:$upPort/mode/$mode");
        [$s, $b] = req('GET', "$B/api/reviews/me", 'sv1');
        check("upstream $mode", $s === $st && ($b['code'] ?? '') === $code, [$s, $b]);
        if ($mode === 'slow') {
            sleep(3);
        }
        req('GET', "http://127.0.0.1:$upPort/mode/ok");
    }
    [$s] = req('GET', "$B/api/reviews/me", 'sv1');
    check('upstream hồi phục', $s === 200);

    // X-Request-ID: trả lại rid hợp lệ, sinh 32 hex khi thiếu / sai, chuyển tiếp sang Auth, có trên response lỗi
    $ridOf = fn(string $h) => preg_match('/^x-request-id: (\S+)/m', $h, $mm) ? $mm[1] : null;
    [$s, , $h] = req('GET', "$B/api/reviews/me", 'sv1', null, null, ['X-Request-ID: demo-rid-0001']);
    $forwarded = (string) @file_get_contents(sys_get_temp_dir() . '/review-upstream-rid-' . $tag);
    check('X-Request-ID trả lại và chuyển tiếp sang Auth', $s === 200 && $ridOf($h) === 'demo-rid-0001'
        && $forwarded === 'demo-rid-0001', [$ridOf($h), $forwarded]);
    foreach ([null, 'ngan', 'co dau cach!!', str_repeat('x', 129)] as $bad) {
        [$s, , $h] = req('GET', "$B/khong-co", null, null, null, $bad === null ? [] : ["X-Request-ID: $bad"]);
        check('X-Request-ID sinh mới khi ' . var_export($bad, true), $s === 404
            && preg_match('/^[0-9a-f]{32}$/D', (string) $ridOf($h)) === 1, $ridOf($h));
    }
    [$s, , $h] = req('OPTIONS', "$B/health", null, null, null, ['Origin: http://127.0.0.1:8000',
        'Access-Control-Request-Method: GET']);
    check('preflight có X-Request-ID và Expose-Headers', $s === 200 && preg_match('/^[0-9a-f]{32}$/D', (string) $ridOf($h)) === 1
        && str_contains($h, 'access-control-allow-headers: authorization, content-type, idempotency-key, x-request-id'), $h);
    [, , $h] = req('GET', "$B/health", null, null, null, ['Origin: http://127.0.0.1:8000']);
    check('CORS cho trình duyệt đọc X-Request-ID', str_contains($h, 'access-control-expose-headers: x-request-id'), $h);
} finally {
    foreach ([$rev, $up] as [$proc]) {
        proc_terminate($proc);
        proc_close($proc);
    }
    @unlink(sys_get_temp_dir() . '/review-upstream-mode-' . $tag);
    @unlink(sys_get_temp_dir() . '/review-upstream-rid-' . $tag);
    array_map('unlink', glob("$tmp/*") ?: []);
    @rmdir($tmp);
}

echo "Review Service: $passed đạt, " . count($failed) . " lỗi\n";
foreach ($failed as $f) {
    echo "  LỖI: $f\n";
}
exit($failed ? 1 : 0);
