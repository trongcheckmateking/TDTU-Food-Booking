'use strict';
/** Định dạng lỗi thống nhất: {"detail": "...", "code": "..."}; lỗi 422 có thêm "errors": [{field, message}]. */

class ApiError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

function validationError(errors, message = 'Dữ liệu không hợp lệ') {
  return new ApiError(422, 'VALIDATION_ERROR', message, { errors });
}

function notFoundHandler(req, res) {
  res.status(404).json({ detail: 'Không tìm thấy API', code: 'NOT_FOUND' });
}

// eslint-disable-next-line no-unused-vars
function errorHandler(err, req, res, next) {
  if (err instanceof ApiError) {
    return res.status(err.status).json({ detail: err.message, code: err.code, ...err.extra });
  }
  if (err && (err.type === 'entity.parse.failed' || err instanceof SyntaxError)) {
    return res.status(422).json({ detail: 'JSON gửi lên không hợp lệ', code: 'VALIDATION_ERROR',
      errors: [{ field: 'body', message: 'JSON không hợp lệ' }] });
  }
  if (err && err.type === 'entity.too.large') {
    return res.status(413).json({ detail: 'Dữ liệu gửi lên quá lớn', code: 'PAYLOAD_TOO_LARGE' });
  }
  console.error(`[restaurant] Lỗi không mong đợi tại ${req.method} ${req.path}:`, err);
  return res.status(500).json({ detail: 'Có lỗi nội bộ, vui lòng thử lại sau', code: 'INTERNAL_ERROR' });
}

module.exports = { ApiError, validationError, notFoundHandler, errorHandler };
