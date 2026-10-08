'use strict';
/**
 * Xác thực: service gọi Auth `GET /api/users/me` với Bearer token của người dùng để lấy danh tính,
 * vai trò và trạng thái hiện tại (tài khoản bị khóa/token bị thu hồi bị từ chối ngay).
 * API nội bộ: header X-Internal-Key, so sánh hằng thời gian.
 */
const crypto = require('node:crypto');
const config = require('./config');
const { ApiError } = require('./errors');
const { call } = require('./http');

const ROLES = ['sinh_vien', 'chu_quan', 'admin'];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function bearerToken(req) {
  const h = req.get('authorization') || '';
  const m = /^Bearer\s+(.+)$/i.exec(h.trim());
  return m ? m[1].trim() : null;
}

async function verifyToken(token) {
  const { status, data } = await call('GET', `${config.serviceUrl('AUTH')}/api/users/me`, 'Auth Service',
    { token, allow: [401, 403] });
  if (status === 401) {
    throw new ApiError(401, (data && data.code) || 'TOKEN_INVALID', 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn');
  }
  if (status === 403) {
    throw new ApiError(403, (data && data.code) || 'ACCOUNT_LOCKED', (data && data.detail) || 'Tài khoản đã bị khóa');
  }
  if (!data || typeof data.id !== 'string' || !UUID_RE.test(data.id) || !ROLES.includes(data.role) ||
      (data.status !== undefined && data.status !== 'active')) {
    throw new ApiError(502, 'UPSTREAM_BAD_RESPONSE', 'Auth Service trả thông tin người dùng không đúng định dạng');
  }
  return { id: data.id.toLowerCase(), role: data.role, name: String(data.name || ''), email: String(data.email || ''),
    phone: data.phone ?? null };
}

/** Bắt buộc đăng nhập; roles rỗng = mọi vai trò. */
function requireUser(...roles) {
  return async (req, res, next) => {
    try {
      const token = bearerToken(req);
      if (!token) throw new ApiError(401, 'UNAUTHORIZED', 'Cần đăng nhập (thiếu Bearer token)');
      req.user = await verifyToken(token);
      if (roles.length && !roles.includes(req.user.role)) {
        throw new ApiError(403, 'FORBIDDEN', 'Bạn không có quyền thực hiện thao tác này');
      }
      next();
    } catch (e) { next(e); }
  };
}

/** Token tùy chọn: không gửi token -> khách; gửi token sai -> 401. */
async function optionalUser(req, res, next) {
  try {
    const token = bearerToken(req);
    req.user = token ? await verifyToken(token) : null;
    next();
  } catch (e) { next(e); }
}

function requireInternal(req, res, next) {
  const key = req.get('x-internal-key') || '';
  const expected = Buffer.from(config.internalKey());
  const given = Buffer.from(key);
  if (!key || given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) {
    return next(new ApiError(403, 'INTERNAL_ONLY', 'API nội bộ, chỉ service tin cậy được gọi'));
  }
  return next();
}

module.exports = { requireUser, optionalUser, requireInternal, UUID_RE };
