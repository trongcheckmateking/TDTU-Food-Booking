'use strict';
/**
 * Gọi REST sang service khác, có timeout và ánh xạ lỗi thống nhất (giống 4 service còn lại):
 *   không kết nối được / quá thời gian -> 503 UPSTREAM_UNAVAILABLE
 *   5xx                                -> 502 UPSTREAM_ERROR
 *   body không phải JSON object/list   -> 502 UPSTREAM_BAD_RESPONSE
 *   4xx khác (không nằm trong allow)   -> 502 UPSTREAM_REJECTED
 */
const config = require('./config');
const { ApiError } = require('./errors');

async function call(method, url, service, { token, internal, json, allow = [], timeoutMs } = {}) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (internal) headers['X-Internal-Key'] = config.internalKey();
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  let resp;
  let text;
  try {
    resp = await fetch(url, {
      method, headers, body: json === undefined ? undefined : JSON.stringify(json),
      signal: AbortSignal.timeout(timeoutMs || config.httpTimeoutMs()),
    });
    text = await resp.text();
  } catch (e) {
    const timeout = e && (e.name === 'TimeoutError' || e.name === 'AbortError');
    throw new ApiError(503, 'UPSTREAM_UNAVAILABLE',
      timeout ? `${service} phản hồi quá thời gian chờ` : `Không kết nối được ${service}`);
  }
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  const ok = (resp.status >= 200 && resp.status < 300) || allow.includes(resp.status);
  if (ok) {
    if (resp.status === 204) return { status: 204, data: {} };
    if (body === null || typeof body !== 'object') {
      throw new ApiError(502, 'UPSTREAM_BAD_RESPONSE', `${service} trả dữ liệu không phải JSON hợp lệ`);
    }
    return { status: resp.status, data: body };
  }
  if (resp.status >= 500) {
    console.warn(`[restaurant] ${service} trả ${resp.status} cho ${method} ${url}`);
    throw new ApiError(502, 'UPSTREAM_ERROR', `${service} đang gặp lỗi, vui lòng thử lại`);
  }
  throw new ApiError(502, 'UPSTREAM_REJECTED', `${service} từ chối yêu cầu nội bộ (HTTP ${resp.status})`);
}

module.exports = { call };
