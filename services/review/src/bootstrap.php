<?php
declare(strict_types=1);

/**
 * Nạp cấu hình từ biến môi trường và tệp .env ở thư mục gốc dự án (dùng chung cho 5 service).
 * Không có giá trị bí mật mặc định: thiếu INTERNAL_KEY thì service từ chối chạy.
 */

date_default_timezone_set('UTC');
ini_set('display_errors', '0');
error_reporting(E_ALL);

require_once __DIR__ . '/Http.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/Call_Auth_Order.php';
require_once __DIR__ . '/Reviews.php';

const PROJECT_ROOT = __DIR__ . '/../../..';

function loadEnv(): void
{
    static $daNap = false;
    if ($daNap) {
        return;
    }
    $daNap = true;
    $tep = getenv('TDTU_ENV_FILE') ?: PROJECT_ROOT . '/.env';
    if (!is_file($tep)) {
        return;
    }
    foreach (preg_split('/\r?\n/', (string) file_get_contents($tep)) as $dong) {
        $dong = trim($dong);
        if ($dong === '' || str_starts_with($dong, '#') || !str_contains($dong, '=')) {
            continue;
        }
        [$khoa, $giaTri] = explode('=', $dong, 2);
        $khoa = trim($khoa);
        $giaTri = trim(trim($giaTri), "\"'");
        if (getenv($khoa) === false) {         // không ghi đè biến môi trường đã có
            putenv("$khoa=$giaTri");
        }
    }
}

function env(string $ten, ?string $macDinh = null): ?string
{
    loadEnv();
    $v = getenv($ten);
    return ($v === false || $v === '') ? $macDinh : $v;
}

function requireEnv(string $ten, int $doDaiToiThieu): string
{
    $v = env($ten);
    if ($v === null || strlen($v) < $doDaiToiThieu) {
        throw new RuntimeException("Thiếu cấu hình $ten (tối thiểu $doDaiToiThieu ký tự). "
            . 'Chạy `python manage.py init-env` để tạo tệp .env cho máy local.');
    }
    return $v;
}

function serviceUrl(string $ten): string
{
    $mac = ['AUTH' => 8001, 'RESTAURANT' => 8002, 'ORDER' => 8003, 'NOTIFICATION' => 8004, 'REVIEW' => 8005];
    return rtrim(env($ten . '_URL', 'http://127.0.0.1:' . $mac[$ten]), '/');
}

function dataDir(): string
{
    $raw = env('DATA_DIR', 'data');
    $isAbs = str_starts_with($raw, '/') || preg_match('/^[A-Za-z]:[\\\\\/]/', $raw) === 1 || str_starts_with($raw, '\\\\');
    $dir = $isAbs ? $raw : PROJECT_ROOT . '/' . $raw;
    if (!is_dir($dir)) {
        mkdir($dir, 0777, true);
    }
    return $dir;
}

function corsOrigins(): array
{
    $raw = env('CORS_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000');
    return array_values(array_filter(array_map('trim', explode(',', $raw)), fn($x) => $x !== ''));
}

function httpTimeoutMs(): int
{
    $v = (float) env('HTTP_TIMEOUT', '5');
    return (int) (($v > 0 ? $v : 5) * 1000);
}
