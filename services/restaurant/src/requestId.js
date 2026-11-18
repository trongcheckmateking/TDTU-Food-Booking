'use strict';
/**
 * X-Request-ID: mã truy vết một yêu cầu xuyên các service.
 * Nhận header nếu hợp lệ (^[A-Za-z0-9._-]{8,128}$), không thì sinh UUID bỏ dấu gạch (32 ký tự hex); trả lại trong
 * response; lưu bằng AsyncLocalStorage để http.js chuyển tiếp khi gọi Auth (kể cả sau các lệnh await).
 */
const crypto = require('node:crypto');
const { AsyncLocalStorage } = require('node:async_hooks');

const HEADER = 'X-Request-ID';
const RID_RE = /^[A-Za-z0-9._-]{8,128}$/;
const store = new AsyncLocalStorage();

function accept(raw) {
  return typeof raw === 'string' && RID_RE.test(raw) ? raw : crypto.randomUUID().replace(/-/g, '');
}

/** rid của yêu cầu đang xử lý (null ngoài yêu cầu, ví dụ việc chạy nền). */
function current() {
  return store.getStore() ?? null;
}

function middleware(req, res, next) {
  const rid = accept(req.get(HEADER));
  req.rid = rid;
  res.set(HEADER, rid);
  store.run(rid, next);
}

module.exports = { HEADER, accept, current, middleware };
