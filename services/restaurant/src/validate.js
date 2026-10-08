'use strict';
/**
 * Kiểm tra dữ liệu vào chặt chẽ (tương đương Pydantic strict ở Auth Service):
 *  - trường lạ bị từ chối (chặn gửi kèm owner_id, restaurant_id, status giả mạo...)
 *  - chuỗi được cắt khoảng trắng hai đầu; chuỗi chỉ có khoảng trắng bị từ chối
 *  - số nguyên phải là số nguyên JSON thật: không nhận 1.5, "1000", true, 1e309
 * Sai -> 422 VALIDATION_ERROR kèm errors: [{field, message}].
 */
const { validationError } = require('./errors');
const { UUID_RE } = require('./auth');

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

const T = {
  text: (min, max) => ({ type: 'text', min, max }),
  optText: (max) => ({ type: 'optText', max, nullable: true }),
  hhmm: () => ({ type: 'hhmm' }),
  int: (min, max) => ({ type: 'int', min, max }),
  enumOf: (...values) => ({ type: 'enum', values }),
  uuid: () => ({ type: 'uuid' }),
  array: (of, min, max) => ({ type: 'array', of, min, max }),
  object: (fields) => ({ type: 'object', fields }),
};

function checkValue(spec, v, field, errors) {
  if (v === null) {
    if (spec.nullable) return null;
    errors.push({ field, message: 'không được để trống (null)' });
    return undefined;
  }
  switch (spec.type) {
    case 'text': case 'optText': case 'hhmm': {
      if (typeof v !== 'string') { errors.push({ field, message: 'phải là chuỗi' }); return undefined; }
      const s = v.trim();
      if (spec.type === 'optText') {
        if (s.length > spec.max) { errors.push({ field, message: `tối đa ${spec.max} ký tự` }); return undefined; }
        return s || null;
      }
      if (spec.type === 'hhmm') {
        if (!HHMM_RE.test(s)) { errors.push({ field, message: 'phải có dạng HH:MM (00:00–23:59)' }); return undefined; }
        return s;
      }
      if (!s) { errors.push({ field, message: 'không được chỉ chứa khoảng trắng' }); return undefined; }
      if (s.length < spec.min || s.length > spec.max) {
        errors.push({ field, message: `độ dài phải từ ${spec.min} đến ${spec.max} ký tự` }); return undefined;
      }
      return s;
    }
    case 'int':
      if (typeof v !== 'number' || !Number.isInteger(v)) {
        errors.push({ field, message: 'phải là số nguyên' }); return undefined;
      }
      if (v < spec.min || v > spec.max) {
        errors.push({ field, message: `phải trong khoảng ${spec.min}–${spec.max}` }); return undefined;
      }
      return v;
    case 'enum':
      if (!spec.values.includes(v)) {
        errors.push({ field, message: `phải là một trong: ${spec.values.join(', ')}` }); return undefined;
      }
      return v;
    case 'uuid':
      if (typeof v !== 'string' || !UUID_RE.test(v)) { errors.push({ field, message: 'phải là UUID' }); return undefined; }
      return v.toLowerCase();
    case 'array': {
      if (!Array.isArray(v)) { errors.push({ field, message: 'phải là danh sách' }); return undefined; }
      if (v.length < spec.min || v.length > spec.max) {
        errors.push({ field, message: `cần từ ${spec.min} đến ${spec.max} phần tử` }); return undefined;
      }
      return v.map((x, i) => checkValue(spec.of, x, `${field}.${i}`, errors));
    }
    case 'object':
      return checkObject(spec.fields, v, field, errors).value;
    default:
      throw new Error(`Kiểu không hỗ trợ: ${spec.type}`);
  }
}

function checkObject(fields, body, prefix, errors) {
  const value = {};
  const present = new Set();
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    errors.push({ field: prefix || 'body', message: 'phải là JSON object' });
    return { value, present };
  }
  for (const key of Object.keys(body)) {
    if (!(key in fields)) errors.push({ field: prefix ? `${prefix}.${key}` : key, message: 'trường không được phép' });
  }
  for (const [key, spec] of Object.entries(fields)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (!(key in body)) {
      if (spec.required) errors.push({ field: name, message: 'bắt buộc' });
      else if (spec.default !== undefined) value[key] = spec.default;
      continue;
    }
    present.add(key);
    value[key] = checkValue(spec, body[key], name, errors);
  }
  return { value, present };
}

/** Kiểm tra body; trả {value, present} với present = các trường client gửi lên. */
function body(fields, raw) {
  const errors = [];
  const out = checkObject(fields, raw === undefined ? null : raw, '', errors);
  if (errors.length) throw validationError(errors);
  return out;
}

const req = (spec, extra = {}) => ({ ...spec, required: true, ...extra });
const opt = (spec, extra = {}) => ({ ...spec, ...extra });

// ------------------------------------------------------------------ query & path
function uuidParam(value, field = 'id') {
  if (typeof value !== 'string' || !UUID_RE.test(value)) throw validationError([{ field, message: 'phải là UUID' }]);
  return value.toLowerCase();
}

function intQuery(query, name, def, min, max) {
  if (query[name] === undefined) return def;
  const raw = String(query[name]);
  if (!/^[+-]?\d+$/.test(raw.trim())) throw validationError([{ field: name, message: 'phải là số nguyên' }]);
  const n = Number(raw);
  if (n < min || n > max) throw validationError([{ field: name, message: `phải trong khoảng ${min}–${max}` }]);
  return n;
}

function boolQuery(query, name) {
  if (query[name] === undefined) return false;
  const raw = String(query[name]).toLowerCase();
  if (['true', '1', 'yes', 'on', 't', 'y'].includes(raw)) return true;
  if (['false', '0', 'no', 'off', 'f', 'n'].includes(raw)) return false;
  throw validationError([{ field: name, message: 'phải là true/false' }]);
}

function enumQuery(query, name, values) {
  if (query[name] === undefined) return null;
  if (!values.includes(query[name])) {
    throw validationError([{ field: name, message: `phải là một trong: ${values.join(', ')}` }]);
  }
  return query[name];
}

function textQuery(query, name, max) {
  if (query[name] === undefined) return null;
  const s = String(query[name]);
  if (s.length > max) throw validationError([{ field: name, message: `tối đa ${max} ký tự` }]);
  return s.trim() || null;
}

function pageQuery(query, defSize = 20) {
  return { page: intQuery(query, 'page', 1, 1, 100000), pageSize: intQuery(query, 'page_size', defSize, 1, 100) };
}

module.exports = { T, req, opt, body, uuidParam, intQuery, boolQuery, enumQuery, textQuery, pageQuery };
