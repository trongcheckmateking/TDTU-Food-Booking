<?php
declare(strict_types=1);

/**
 * Tiện ích HTTP dùng chung của Review Service (giữ cách tổ chức của bản TV5: ApiError + jsonResponse + jsonBody).
 * Định dạng lỗi thống nhất với 4 service còn lại: {"detail": "...", "code": "..."}; 422 có thêm "errors".
 */

// 1. Lỗi có mã HTTP + mã lỗi riêng
final class ApiError extends RuntimeException
{
    public function __construct(
        public int $status,
        public string $errorCode,
        string $thongBao,
        public ?array $errors = null,
    ) {
        parent::__construct($thongBao);
    }
}

function validationError(array $errors, string $thongBao = 'Dữ liệu không hợp lệ'): ApiError
{
    return new ApiError(422, 'VALIDATION_ERROR', $thongBao, $errors);
}

// 2. Trả JSON (giữ tiếng Việt, số thực luôn có phần thập phân như 5.0)
function jsonResponse(int $maTrangThai, mixed $noiDung): never
{
    http_response_code($maTrangThai);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($noiDung, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION
        | JSON_THROW_ON_ERROR);
    exit;
}

function emptyResponse(int $maTrangThai = 204): never
{
    http_response_code($maTrangThai);
    exit;
}

function errorResponse(ApiError $loi): never
{
    $body = ['detail' => $loi->getMessage(), 'code' => $loi->errorCode];
    if ($loi->errors !== null) {
        $body['errors'] = $loi->errors;
    }
    jsonResponse($loi->status, $body);
}

// 3. Đọc body JSON: phải là object; JSON hỏng -> 422 "JSON gửi lên không hợp lệ"
function jsonBody(): array
{
    $chuoiTho = file_get_contents('php://input', false, null, 0, 102401);
    if ($chuoiTho === false || strlen($chuoiTho) > 102400) {
        throw new ApiError(413, 'PAYLOAD_TOO_LARGE', 'Dữ liệu gửi lên quá lớn');
    }
    try {
        $giaTri = json_decode($chuoiTho, false, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        throw validationError([['field' => 'body', 'message' => 'JSON không hợp lệ']], 'JSON gửi lên không hợp lệ');
    }
    if (!$giaTri instanceof stdClass) {
        throw validationError([['field' => 'body', 'message' => 'phải là JSON object']]);
    }
    return (array) $giaTri;
}

// 4. Kiểm tra dữ liệu (tương đương Pydantic strict: trường lạ bị chặn, cắt khoảng trắng, số nguyên thật)
function rejectUnknown(array $body, array $allowed, array &$errors): void
{
    foreach (array_keys($body) as $key) {
        if (!in_array($key, $allowed, true)) {
            $errors[] = ['field' => (string) $key, 'message' => 'trường không được phép'];
        }
    }
}

function optionalText(array $body, string $field, int $max, array &$errors): ?string
{
    if (!array_key_exists($field, $body) || $body[$field] === null) {
        return null;
    }
    if (!is_string($body[$field])) {
        $errors[] = ['field' => $field, 'message' => 'phải là chuỗi'];
        return null;
    }
    $s = trim($body[$field]);
    if (mb_strlen($s) > $max) {
        $errors[] = ['field' => $field, 'message' => "tối đa $max ký tự"];
        return null;
    }
    return $s === '' ? null : $s;
}

function isUuid(mixed $giaTri): bool
{
    return is_string($giaTri)
        && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iD', $giaTri) === 1;
}

function uuidParam(string $giaTri, string $field): string
{
    if (!isUuid($giaTri)) {
        throw validationError([['field' => $field, 'message' => 'phải là UUID']]);
    }
    return strtolower($giaTri);
}

function intQuery(string $ten, int $macDinh, int $min, int $max): int
{
    if (!array_key_exists($ten, $_GET)) {
        return $macDinh;
    }
    $giaTri = $_GET[$ten];
    if (!is_string($giaTri) || preg_match('/^\s*[+-]?\d+\s*$/D', $giaTri) !== 1) {
        throw validationError([['field' => $ten, 'message' => 'phải là số nguyên']]);
    }
    $so = (int) trim($giaTri);
    if ($so < $min || $so > $max) {
        throw validationError([['field' => $ten, 'message' => "phải trong khoảng $min–$max"]]);
    }
    return $so;
}

function enumQuery(string $ten, array $choPhep): ?string
{
    if (!array_key_exists($ten, $_GET)) {
        return null;
    }
    if (!in_array($_GET[$ten], $choPhep, true)) {
        throw validationError([['field' => $ten, 'message' => 'phải là một trong: ' . implode(', ', $choPhep)]]);
    }
    return $_GET[$ten];
}

function pageQuery(int $macDinhKichThuoc = 20): array
{
    return [intQuery('page', 1, 1, 100000), intQuery('page_size', $macDinhKichThuoc, 1, 100)];
}

// 5. Bearer token
function bearerToken(): ?string
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (preg_match('/^\s*Bearer\s+(\S+)\s*$/i', $header, $m) === 1) {
        return $m[1];
    }
    return null;
}

// 6. CORS: chỉ các origin trong CORS_ORIGINS; preflight hợp lệ được trả lời ngay (200)
function applyCors(array $choPhep): void
{
    $nguon = $_SERVER['HTTP_ORIGIN'] ?? '';
    $preflight = ($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS' && isset($_SERVER['HTTP_ACCESS_CONTROL_REQUEST_METHOD']);
    if ($nguon !== '' && in_array($nguon, $choPhep, true)) {
        header('Access-Control-Allow-Origin: ' . $nguon);
        header('Vary: Origin');
        if ($preflight) {
            header('Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS');
            header('Access-Control-Allow-Headers: Authorization, Content-Type, Idempotency-Key');
            header('Access-Control-Max-Age: 600');
            http_response_code(200);
            exit;
        }
    } elseif ($preflight) {
        throw new ApiError(400, 'CORS_REJECTED', 'Origin không được phép');
    }
}

function nowIso(): string
{
    return gmdate('Y-m-d\TH:i:s\Z');
}

function newUuid(): string
{
    $b = random_bytes(16);
    $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
    $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
}
