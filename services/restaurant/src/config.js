'use strict';
/**
 * Cấu hình đọc từ biến môi trường và tệp .env ở thư mục gốc dự án (dùng chung cho 5 service).
 * Không có giá trị bí mật mặc định: thiếu JWT/INTERNAL_KEY thì dừng ngay khi khởi động.
 */
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..', '..');
let loaded = false;

function loadEnv() {
  if (loaded) return;
  loaded = true;
  const file = process.env.TDTU_ENV_FILE || path.join(ROOT, '.env');
  if (!fs.existsSync(file)) return;
  for (const raw of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const i = line.indexOf('=');
    const key = line.slice(0, i).trim();
    const value = line.slice(i + 1).trim().replace(/^["']|["']$/g, '');
    if (process.env[key] === undefined) process.env[key] = value;   // không ghi đè biến đã có
  }
}

function get(name, def = undefined) {
  loadEnv();
  const v = process.env[name];
  return v === undefined || v === '' ? def : v;
}

function require_(name, minLength = 1) {
  const v = get(name);
  if (!v || v.length < minLength) {
    throw new Error(`Thiếu cấu hình ${name} (tối thiểu ${minLength} ký tự). ` +
      'Chạy `python manage.py init-env` để tạo tệp .env cho máy local.');
  }
  return v;
}

const PORTS = { AUTH: 8001, RESTAURANT: 8002, ORDER: 8003, NOTIFICATION: 8004, REVIEW: 8005 };

function serviceUrl(name) {
  return get(`${name}_URL`, `http://127.0.0.1:${PORTS[name]}`).replace(/\/+$/, '');
}

function listenPort() {
  return Number(new URL(serviceUrl('RESTAURANT')).port || PORTS.RESTAURANT);
}

function dataDir() {
  const raw = get('DATA_DIR', 'data');
  const dir = path.isAbsolute(raw) ? raw : path.join(ROOT, raw);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function corsOrigins() {
  return get('CORS_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000')
    .split(',').map((s) => s.trim()).filter(Boolean);
}

function httpTimeoutMs() {
  const v = Number(get('HTTP_TIMEOUT', '5'));
  return (Number.isFinite(v) && v > 0 ? v : 5) * 1000;
}

module.exports = {
  ROOT, get, require: require_, serviceUrl, listenPort, dataDir, corsOrigins, httpTimeoutMs,
  internalKey: () => require_('INTERNAL_KEY', 24),
};
