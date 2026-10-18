'use strict';
/**
 * Restaurant Service (Node.js/Express, cổng 8002): quán ăn, menu, duyệt/khóa quán, báo giá nội bộ cho Order.
 * Hợp đồng API giống hệt tài liệu docs/API.md; OpenAPI ở services/restaurant/openapi.json.
 */
const fs = require('node:fs');
const path = require('node:path');
const express = require('express');
const config = require('./config');
const db = require('./db');
const { ApiError, validationError, notFoundHandler, errorHandler } = require('./errors');
const { requireUser, optionalUser, requireInternal } = require('./auth');
const V = require('./validate');

const { T, req: R, opt: O } = V;
const PUBLIC_STATUSES = ['active', 'closed'];

// ------------------------------------------------------------------ schema dữ liệu vào
const RestaurantCreate = {
  name: R(T.text(2, 150)), address: R(T.text(3, 300)), description: O(T.optText(1000)),
  open_time: O(T.hhmm(), { nullable: true }), close_time: O(T.hhmm(), { nullable: true }), image_url: O(T.optText(500)),
};
const RestaurantUpdate = {
  name: O(T.text(2, 150), { nullable: true }), address: O(T.text(3, 300), { nullable: true }),
  description: O(T.optText(1000)), open_time: O(T.hhmm(), { nullable: true }),
  close_time: O(T.hhmm(), { nullable: true }), image_url: O(T.optText(500)),
  status: O(T.enumOf('active', 'closed'), { nullable: true }),
};
const AdminStatusUpdate = { status: R(T.enumOf('active', 'locked')), reason: O(T.optText(300)) };
const MenuItemCreate = {
  name: R(T.text(1, 150)), price: R(T.int(0, 100000000)), description: O(T.optText(1000)), category: O(T.optText(50)),
  image_url: O(T.optText(500)), status: O(T.enumOf('available', 'sold_out', 'hidden'), { default: 'available' }),
};
const MenuItemUpdate = {     // không có restaurant_id: món không thể bị chuyển sang quán khác
  name: O(T.text(1, 150), { nullable: true }), price: O(T.int(0, 100000000), { nullable: true }),
  description: O(T.optText(1000)), category: O(T.optText(50)), image_url: O(T.optText(500)),
  status: O(T.enumOf('available', 'sold_out', 'hidden'), { nullable: true }),
};
const QuoteIn = {
  restaurant_id: R(T.text(1, 100)),
  items: R(T.array(T.object({ item_id: R(T.text(1, 100)), quantity: R(T.int(1, 50)) }), 1, 50)),
};

// ------------------------------------------------------------------ tiện ích
const RESTAURANT_FIELDS = ['id', 'owner_id', 'name', 'address', 'description', 'open_time', 'close_time', 'image_url',
  'status', 'status_reason'];
const ITEM_FIELDS = ['id', 'restaurant_id', 'name', 'price', 'description', 'category', 'image_url', 'status',
  'created_at', 'updated_at'];

// ------------------------------------------------------------------ ảnh (ảnh bìa quán, ảnh món)
const IMAGE_EXT = { jpg: 'image/jpeg', png: 'image/png', webp: 'image/webp' };
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const UPLOADS_PER_HOUR = 60;                         // mỗi chủ quán, chống lấp đầy ổ đĩa
const UPLOADS_MAX_TOTAL = 500 * 1024 * 1024;         // tổng dung lượng thư mục ảnh
const ORPHAN_AGE_MS = 3600e3;                        // ảnh tải lên quá 1 giờ mà không quán/món nào dùng thì xóa
const UPLOAD_PATH_RE = /^\/uploads\/[0-9a-f-]{36}\.(jpg|png|webp)$/;
const uploadLog = new Map();                         // user id -> thời điểm các lần tải gần đây

function uploadDir() {
  const dir = path.join(config.dataDir(), 'uploads');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

/** Nhận dạng ảnh theo byte đầu tệp, không tin Content-Type do trình duyệt gửi. */
function sniffImage(buf) {
  if (buf.length > 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpg';
  if (buf.length > 8 && buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'png';
  if (buf.length > 12 && buf.toString('latin1', 0, 4) === 'RIFF' && buf.toString('latin1', 8, 12) === 'WEBP') return 'webp';
  return null;
}

/** image_url chỉ nhận ảnh đã tải lên service này (/uploads/...) hoặc đường dẫn http(s). */
function checkImageUrl(body) {
  const v = body.image_url;
  if (v === undefined || v === null || UPLOAD_PATH_RE.test(v) || /^https?:\/\/[^\s"'<>]+$/i.test(v)) return;
  throw validationError([{ field: 'image_url', message: 'phải là ảnh đã tải lên (/uploads/...) hoặc đường dẫn http(s)' }]);
}

const imageInUse = (url) => !!db.one(
  'SELECT 1 AS x FROM restaurants WHERE image_url=? UNION ALL SELECT 1 FROM menu_items WHERE image_url=? LIMIT 1', url, url);

function removeFile(name) {
  fs.rm(path.join(uploadDir(), name), { force: true }, (e) => {
    if (e) console.warn(`[restaurant] Không xóa được ảnh ${name}: ${e.code || e.message}`);
  });
}

/** Xóa tệp ảnh cũ khi không còn quán / món nào dùng (sau khi đổi ảnh hoặc xóa quán / món). */
function removeUnusedUpload(url) {
  if (!url || !UPLOAD_PATH_RE.test(url) || imageInUse(url)) return;
  removeFile(path.basename(url));
}

/** Dọn ảnh đã tải lên nhưng không được gán (hủy hộp thoại, lưu lỗi...) sau ORPHAN_AGE_MS. */
function sweepUploads() {
  let names;
  try { names = fs.readdirSync(uploadDir()); } catch { return; }
  for (const name of names) {
    if (!/^[0-9a-f-]{36}\.(jpg|png|webp)$/.test(name)) continue;
    try {
      if (Date.now() - fs.statSync(path.join(uploadDir(), name)).mtimeMs > ORPHAN_AGE_MS && !imageInUse(`/uploads/${name}`)) removeFile(name);
    } catch { /* tệp vừa bị xóa */ }
  }
}

function uploadsTotalBytes() {
  let total = 0;
  for (const name of fs.readdirSync(uploadDir())) {
    try { total += fs.statSync(path.join(uploadDir(), name)).size; } catch { /* bỏ qua */ }
  }
  return total;
}

function takeUploadSlot(userId) {
  const now = Date.now();
  if (uploadLog.size > 1000) {                       // bỏ người dùng không tải gì trong 1 giờ qua
    for (const [k, v] of uploadLog) if (!v.some((t) => now - t < 3600e3)) uploadLog.delete(k);
  }
  const recent = (uploadLog.get(userId) || []).filter((t) => now - t < 3600e3);
  if (recent.length >= UPLOADS_PER_HOUR) {
    throw new ApiError(429, 'TOO_MANY_UPLOADS', `Chỉ được tải tối đa ${UPLOADS_PER_HOUR} ảnh mỗi giờ, vui lòng thử lại sau`);
  }
  recent.push(now);
  uploadLog.set(userId, recent);
}

function outRestaurant(r) {
  const o = {};
  for (const k of RESTAURANT_FIELDS) o[k] = r[k] ?? null;
  o.accepting_orders = r.status === 'active' && !r.deleted_at;
  o.created_at = r.created_at;
  o.updated_at = r.updated_at;
  o.deleted_at = r.deleted_at ?? null;
  o.item_count = r.item_count ?? null;
  return o;
}

function outItem(it) {
  const o = {};
  for (const k of ITEM_FIELDS) o[k] = it[k] ?? null;
  return o;
}

function getRestaurant(rid, includeDeleted = false) {
  const r = db.one('SELECT * FROM restaurants WHERE id=?', rid);
  if (!r || (r.deleted_at && !includeDeleted)) throw new ApiError(404, 'RESTAURANT_NOT_FOUND', 'Không tìm thấy quán');
  return r;
}

const isManager = (user, r) => !!user && (user.role === 'admin' || (user.role === 'chu_quan' && r.owner_id === user.id));

function requireOwner(user, r) {
  if (user.role !== 'chu_quan' || r.owner_id !== user.id) throw new ApiError(403, 'NOT_OWNER', 'Bạn không phải chủ quán này');
}

function visibleRestaurant(rid, user) {
  const r = getRestaurant(rid);
  if (!PUBLIC_STATUSES.includes(r.status) && !isManager(user, r)) {
    throw new ApiError(404, 'RESTAURANT_NOT_FOUND', 'Không tìm thấy quán');
  }
  return r;
}

function getItem(mid) {
  const it = db.one('SELECT * FROM menu_items WHERE id=? AND deleted_at IS NULL', mid);
  if (!it) throw new ApiError(404, 'ITEM_NOT_FOUND', 'Không tìm thấy món');
  return it;
}

// Bảng tin món mới: giới hạn để bảng tin gọn và không bị một quán chiếm hết / đẩy món lên liên tục
const FEED_DAYS = 14;                 // chỉ hiện tin trong 14 ngày gần nhất
const FEED_PER_RESTAURANT = 3;        // mỗi quán tối đa 3 tin
const BUMP_COOLDOWN_MS = 30 * 60e3;   // tin của một món chỉ được đẩy lên lại sau 30 phút
const BACK_AFTER_MS = 24 * 3600e3;    // món hết / ẩn ít nhất 24 giờ mới có tin "bán lại" (hết món qua đêm thì không)
const ageMs = (iso) => Date.now() - Date.parse(iso);

/**
 * Cập nhật tin của món khi món đang bán (gọi trong giao dịch thêm/sửa món). Mỗi món giữ một tin mới nhất:
 * lần đầu bán -> new; bán lại sau >= 24 giờ hết/ẩn -> back; đổi giá khi đang bán -> price (giữ giá cũ).
 * Tin vừa đăng chưa quá 30 phút thì chỉ cập nhật giá, không đẩy lên đầu bảng tin.
 */
function recordMenuUpdate(before, after) {
  if (after.status !== 'available') return;
  const prev = db.one('SELECT * FROM menu_updates WHERE item_id=?', after.id);
  const wasOn = before && before.status === 'available';
  let kind = null;
  if (!prev) kind = 'new';
  else if (!wasOn && ageMs(before.updated_at) >= BACK_AFTER_MS) kind = 'back';
  else if (wasOn && before.price !== after.price) kind = 'price';
  if (!kind) {
    if (prev && prev.new_price !== after.price) db.run('UPDATE menu_updates SET new_price=? WHERE item_id=?', after.price, after.id);
    return;
  }
  if (prev && ageMs(prev.created_at) < BUMP_COOLDOWN_MS) {
    db.run('UPDATE menu_updates SET new_price=? WHERE item_id=?', after.price, after.id);
    return;
  }
  const oldPrice = before && before.price !== after.price ? before.price : null;
  db.run('INSERT INTO menu_updates (item_id,restaurant_id,kind,old_price,new_price,created_at) VALUES (?,?,?,?,?,?) ' +
    'ON CONFLICT(item_id) DO UPDATE SET kind=excluded.kind, old_price=excluded.old_price, new_price=excluded.new_price, ' +
    'created_at=excluded.created_at', after.id, after.restaurant_id, kind, oldPrice, after.price, db.nowIso());
}

function outMenuUpdate(u) {
  return {
    kind: u.kind, restaurant_id: u.restaurant_id, restaurant_name: u.restaurant_name,
    item_id: u.item_id, item_name: u.item_name, item_description: u.item_description ?? null,
    price: u.price, old_price: u.old_price ?? null, created_at: u.created_at,
  };
}

/** Cập nhật các trường có gửi lên; `then(before)` (nếu có) chạy trong cùng giao dịch, sau lệnh UPDATE. */
function applyUpdate(table, id, value, present, required, then) {
  const keys = [...present];
  for (const k of required) {
    if (present.has(k) && value[k] === null) {
      throw new ApiError(422, 'VALIDATION_ERROR', `Trường ${k} không được để trống`);
    }
  }
  if (!keys.length) return;
  const sets = keys.map((k) => `${k}=?`).join(', ');
  db.transaction(() => {
    const before = then ? db.one(`SELECT * FROM ${table} WHERE id=?`, id) : null;
    db.run(`UPDATE ${table} SET ${sets}, updated_at=? WHERE id=?`, ...keys.map((k) => value[k]), db.nowIso(), id);
    if (then) then(before);
  });
}

const wrap = (fn) => async (req, res, next) => { try { await fn(req, res, next); } catch (e) { next(e); } };

// ------------------------------------------------------------------ ứng dụng
function createApp() {
  const app = express();
  app.disable('x-powered-by');
  app.set('etag', false);
  const allowed = new Set(config.corsOrigins());

  app.use((req, res, next) => {                      // log ngắn, không ghi token/body
    const t0 = Date.now();
    res.on('finish', () => {
      if (config.get('LOG_LEVEL', 'INFO') !== 'WARNING') {
        console.log(`${new Date().toISOString()} ${req.method} ${req.path} ${res.statusCode} ${Date.now() - t0}ms`);
      }
    });
    next();
  });
  app.use((req, res, next) => {                      // CORS: chỉ origin trong CORS_ORIGINS
    const origin = req.get('origin');
    if (origin && allowed.has(origin)) {
      res.set('Access-Control-Allow-Origin', origin);
      res.set('Vary', 'Origin');
      if (req.method === 'OPTIONS' && req.get('access-control-request-method')) {
        res.set('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
        res.set('Access-Control-Allow-Headers', 'Authorization, Content-Type, Idempotency-Key');
        res.set('Access-Control-Max-Age', '600');
        return res.status(200).end();
      }
    } else if (req.method === 'OPTIONS' && req.get('access-control-request-method')) {
      return res.status(400).json({ detail: 'Origin không được phép', code: 'CORS_REJECTED' });
    }
    return next();
  });
  app.use(express.json({ limit: '100kb' }));

  // ---------------------------------------------------------------- health & tài liệu
  app.get('/', (req, res) => res.json({ service: 'restaurant', status: 'ok', docs: '/docs' }));
  app.get('/health', (req, res) => {
    const ok = db.check();
    res.status(ok ? 200 : 503).json({ service: 'restaurant', status: ok ? 'ok' : 'degraded', db: ok ? 'ok' : 'error' });
  });
  const spec = fs.readFileSync(path.join(__dirname, '..', 'openapi.json'), 'utf8');
  app.get('/openapi.json', (req, res) => res.type('application/json').send(spec));
  app.get('/docs', (req, res) => res.type('html').send(docsPage('swagger')));
  app.get('/redoc', (req, res) => res.type('html').send(docsPage('redoc')));

  // ---------------------------------------------------------------- công khai
  app.get('/api/restaurants', wrap((req, res) => {
    const q = V.textQuery(req.query, 'q', 100);
    const { page, pageSize } = V.pageQuery(req.query);
    let sql = "SELECT * FROM restaurants WHERE deleted_at IS NULL AND status IN ('active','closed')";
    const args = [];
    if (q) { sql += ' AND (name LIKE ? OR address LIKE ?)'; args.push(`%${q}%`, `%${q}%`); }
    const result = db.paginate(sql, args, page, pageSize, "status='active' DESC, name");
    result.items = result.items.map(outRestaurant);
    res.json(result);
  }));

  app.get('/api/restaurants/mine', requireUser('chu_quan'), wrap((req, res) => {
    const rows = db.all('SELECT r.*, (SELECT COUNT(*) FROM menu_items m WHERE m.restaurant_id=r.id AND ' +
      'm.deleted_at IS NULL) AS item_count FROM restaurants r WHERE owner_id=? AND deleted_at IS NULL ' +
      'ORDER BY created_at DESC', req.user.id);
    res.json(rows.map(outRestaurant));
  }));

  app.get('/api/restaurants/:rid', optionalUser, wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    res.json(outRestaurant(visibleRestaurant(rid, req.user)));
  }));

  app.get('/api/restaurants/:rid/menu', optionalUser, wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    const showAll = V.boolQuery(req.query, 'all');
    const r = visibleRestaurant(rid, req.user);
    if (showAll && !isManager(req.user, r)) throw new ApiError(403, 'FORBIDDEN', 'Chỉ chủ quán hoặc admin được xem cả món ẩn');
    let sql = 'SELECT * FROM menu_items WHERE restaurant_id=? AND deleted_at IS NULL';
    if (!showAll) sql += " AND status != 'hidden'";
    res.json(db.all(`${sql} ORDER BY status='available' DESC, name`, rid).map(outItem));
  }));

  // Bảng tin món mới: tin trong FEED_DAYS ngày, món đang bán của quán đang hoạt động, mỗi quán tối đa FEED_PER_RESTAURANT tin
  app.get('/api/menu-updates', wrap((req, res) => {
    const limit = V.intQuery(req.query, 'limit', 20, 1, 50);
    const since = new Date(Date.now() - FEED_DAYS * 86400e3).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const rows = db.all(`SELECT * FROM (
        SELECT u.*, r.name AS restaurant_name, i.name AS item_name, i.description AS item_description, i.price AS price,
               ROW_NUMBER() OVER (PARTITION BY u.restaurant_id ORDER BY u.created_at DESC, u.item_id) AS rn
        FROM menu_updates u
        JOIN menu_items i ON i.id = u.item_id
        JOIN restaurants r ON r.id = u.restaurant_id
        WHERE u.created_at >= ? AND i.deleted_at IS NULL AND i.status = 'available'
          AND r.deleted_at IS NULL AND r.status = 'active')
      WHERE rn <= ? ORDER BY created_at DESC, item_id LIMIT ?`, since, FEED_PER_RESTAURANT, limit);
    res.json({ items: rows.map(outMenuUpdate) });
  }));

  app.get('/api/menu-items/:mid', optionalUser, wrap((req, res) => {
    const it = getItem(V.uuidParam(req.params.mid, 'mid'));
    const r = visibleRestaurant(it.restaurant_id, req.user);
    if (it.status === 'hidden' && !isManager(req.user, r)) throw new ApiError(404, 'ITEM_NOT_FOUND', 'Không tìm thấy món');
    res.json(outItem(it));
  }));

  // ---------------------------------------------------------------- ảnh
  // Chủ quán tải ảnh lên (thân request là dữ liệu ảnh), nhận lại đường dẫn /uploads/... để gán vào image_url
  app.post('/api/uploads', requireUser('chu_quan'),
    express.raw({ type: Object.values(IMAGE_EXT), limit: MAX_IMAGE_BYTES }), wrap((req, res) => {
      if (!Buffer.isBuffer(req.body) || !req.body.length) {
        throw new ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Chỉ nhận ảnh JPEG, PNG hoặc WebP (tối đa 2 MB)');
      }
      const ext = sniffImage(req.body);
      if (!ext) throw new ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Tệp không phải ảnh JPEG, PNG hoặc WebP');
      if (uploadsTotalBytes() + req.body.length > UPLOADS_MAX_TOTAL) {
        throw new ApiError(507, 'STORAGE_FULL', 'Bộ nhớ ảnh của hệ thống đã đầy, vui lòng báo ban quản trị');
      }
      takeUploadSlot(req.user.id);
      const name = `${db.newId()}.${ext}`;
      fs.writeFileSync(path.join(uploadDir(), name), req.body, { flag: 'wx' });
      res.status(201).json({ url: `/uploads/${name}`, content_type: IMAGE_EXT[ext], bytes: req.body.length });
    }));

  app.get('/uploads/:file', (req, res, next) => {
    const m = /^[0-9a-f-]{36}\.(jpg|png|webp)$/.exec(req.params.file);
    if (!m) return next();
    res.set({ 'Content-Type': IMAGE_EXT[m[1]], 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'",
      'Cross-Origin-Resource-Policy': 'cross-origin', 'Cache-Control': 'public, max-age=31536000, immutable' });
    // root + dotfiles 'allow': thư mục dự án / DATA_DIR có thể nằm trong thư mục bắt đầu bằng dấu chấm (tên tệp đã kiểm tra)
    return res.sendFile(req.params.file, { root: uploadDir(), dotfiles: 'allow' }, (err) => {
      if (!err) return;
      if (res.headersSent) return;
      res.removeHeader('Cache-Control');
      next(err.status === 404 || err.code === 'ENOENT' ? undefined : err);
    });
  });

  // ---------------------------------------------------------------- chủ quán
  app.post('/api/restaurants', requireUser('chu_quan'), wrap((req, res) => {
    const { value: d } = V.body(RestaurantCreate, req.body);
    checkImageUrl(d);
    const rid = db.newId();
    const ts = db.nowIso();
    db.transaction(() => db.run('INSERT INTO restaurants (id,owner_id,name,address,description,open_time,close_time,' +
      "image_url,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'pending', ?, ?)",
    rid, req.user.id, d.name, d.address, d.description ?? null, d.open_time ?? null, d.close_time ?? null,
    d.image_url ?? null, ts, ts));
    res.status(201).json(outRestaurant(getRestaurant(rid)));
  }));

  app.patch('/api/restaurants/:rid', requireUser('chu_quan'), wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    const { value, present } = V.body(RestaurantUpdate, req.body);
    checkImageUrl(value);
    const r = getRestaurant(rid);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa, không thể chỉnh sửa');
    if (present.has('status') && !PUBLIC_STATUSES.includes(r.status)) {
      throw new ApiError(409, 'RESTAURANT_PENDING', 'Quán chưa được duyệt nên chưa thể mở/đóng');
    }
    applyUpdate('restaurants', r.id, value, present, ['name', 'address', 'status']);
    if (present.has('image_url') && value.image_url !== r.image_url) removeUnusedUpload(r.image_url);
    res.json(outRestaurant(getRestaurant(r.id)));
  }));

  app.delete('/api/restaurants/:rid', requireUser('chu_quan', 'admin'), wrap((req, res) => {
    const r = getRestaurant(V.uuidParam(req.params.rid, 'rid'));
    if (req.user.role !== 'admin') requireOwner(req.user, r);
    const ts = db.nowIso();
    db.transaction(() => db.run('UPDATE restaurants SET deleted_at=?, updated_at=?, image_url=NULL WHERE id=?', ts, ts, r.id));
    removeUnusedUpload(r.image_url);
    res.status(204).end();
  }));

  app.post('/api/restaurants/:rid/menu', requireUser('chu_quan'), wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    const { value: d } = V.body(MenuItemCreate, req.body);
    checkImageUrl(d);
    const r = getRestaurant(rid);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa');
    const mid = db.newId();
    const ts = db.nowIso();
    db.transaction(() => {
      db.run('INSERT INTO menu_items (id,restaurant_id,name,price,description,category,image_url,status,' +
        'created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)', mid, r.id, d.name, d.price, d.description ?? null,
      d.category ?? null, d.image_url ?? null, d.status, ts, ts);
      recordMenuUpdate(null, getItem(mid));
    });
    res.status(201).json(outItem(getItem(mid)));
  }));

  app.patch('/api/menu-items/:mid', requireUser('chu_quan'), wrap((req, res) => {
    const mid = V.uuidParam(req.params.mid, 'mid');
    const { value, present } = V.body(MenuItemUpdate, req.body);
    checkImageUrl(value);
    const it = getItem(mid);
    const r = getRestaurant(it.restaurant_id);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa');
    applyUpdate('menu_items', it.id, value, present, ['name', 'price', 'status'],
      (before) => recordMenuUpdate(before, getItem(it.id)));
    if (present.has('image_url') && value.image_url !== it.image_url) removeUnusedUpload(it.image_url);
    res.json(outItem(getItem(it.id)));
  }));

  app.delete('/api/menu-items/:mid', requireUser('chu_quan'), wrap((req, res) => {
    const it = getItem(V.uuidParam(req.params.mid, 'mid'));
    requireOwner(req.user, getRestaurant(it.restaurant_id));
    const ts = db.nowIso();
    db.transaction(() => db.run('UPDATE menu_items SET deleted_at=?, updated_at=?, image_url=NULL WHERE id=?', ts, ts, it.id));
    removeUnusedUpload(it.image_url);
    res.status(204).end();
  }));

  // ---------------------------------------------------------------- admin
  app.get('/api/admin/restaurants', requireUser('admin'), wrap((req, res) => {
    const status = V.enumQuery(req.query, 'status', ['pending', 'active', 'closed', 'locked']);
    const q = V.textQuery(req.query, 'q', 100);
    const includeDeleted = V.boolQuery(req.query, 'include_deleted');
    const ownerId = req.query.owner_id === undefined ? null : V.uuidParam(req.query.owner_id, 'owner_id');
    const { page, pageSize } = V.pageQuery(req.query);
    let sql = 'SELECT r.*, (SELECT COUNT(*) FROM menu_items m WHERE m.restaurant_id=r.id AND m.deleted_at IS NULL) ' +
      'AS item_count FROM restaurants r WHERE 1=1';
    const args = [];
    if (!includeDeleted) sql += ' AND r.deleted_at IS NULL';
    if (ownerId) { sql += ' AND r.owner_id=?'; args.push(ownerId); }
    if (status) { sql += ' AND r.status=?'; args.push(status); }
    if (q) { sql += ' AND (r.name LIKE ? OR r.address LIKE ?)'; args.push(`%${q}%`, `%${q}%`); }
    const result = db.paginate(sql, args, page, pageSize, "status='pending' DESC, created_at DESC");
    result.items = result.items.map(outRestaurant);
    res.json(result);
  }));

  app.patch('/api/admin/restaurants/:rid/status', requireUser('admin'), wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    const { value: d } = V.body(AdminStatusUpdate, req.body);
    const r = getRestaurant(rid);
    const ts = db.nowIso();
    db.transaction(() => {
      db.run('UPDATE restaurants SET status=?, status_reason=?, updated_at=? WHERE id=?',
        d.status, d.status === 'locked' ? (d.reason ?? null) : null, ts, r.id);
      // quán vừa được duyệt: các món đang bán lên bảng tin tính từ lúc duyệt
      if (r.status === 'pending' && d.status === 'active') {
        db.run("UPDATE menu_updates SET kind='new', old_price=NULL, created_at=? WHERE restaurant_id=?", ts, r.id);
      }
    });
    res.json(outRestaurant(getRestaurant(r.id)));
  }));

  // ---------------------------------------------------------------- nội bộ
  app.post('/internal/quote', requireInternal, wrap((req, res) => {
    const { value: d } = V.body(QuoteIn, req.body);
    const r = db.one('SELECT * FROM restaurants WHERE id=?', d.restaurant_id);
    if (!r || r.deleted_at) throw new ApiError(404, 'RESTAURANT_NOT_FOUND', 'Không tìm thấy quán');
    let total = 0;
    const lines = d.items.map((line) => {
      const it = db.one('SELECT * FROM menu_items WHERE id=? AND restaurant_id=? AND deleted_at IS NULL',
        line.item_id, r.id);
      if (!it) {
        return { item_id: line.item_id, quantity: line.quantity, available: false, reason: 'ITEM_NOT_FOUND',
          name: null, price: null, line_total: null };
      }
      const ok = it.status === 'available';
      const lt = it.price * line.quantity;
      if (ok) total += lt;
      return { item_id: it.id, quantity: line.quantity, available: ok,
        reason: ok ? null : (it.status === 'sold_out' ? 'ITEM_SOLD_OUT' : 'ITEM_HIDDEN'),
        name: it.name, price: it.price, line_total: lt };
    });
    res.json({ restaurant: { id: r.id, name: r.name, owner_id: r.owner_id, status: r.status,
      accepting_orders: r.status === 'active' }, items: lines, total, all_available: lines.every((x) => x.available) });
  }));

  app.get('/internal/owners/:ownerId/restaurant-count', requireInternal, wrap((req, res) => {
    const ownerId = V.uuidParam(req.params.ownerId, 'owner_id');
    const n = db.one('SELECT COUNT(*) AS n FROM restaurants WHERE owner_id=? AND deleted_at IS NULL', ownerId).n;
    res.json({ owner_id: ownerId, count: n });
  }));

  // Xóa dữ liệu cá nhân (Auth điều phối khi admin xử lý yêu cầu xóa): gỡ mọi quán của chủ quán khỏi ứng dụng
  // (xóa mềm như khi chủ quán tự xóa quán) và xóa ảnh quán / món đã tải lên. Gọi lại nhiều lần cho cùng kết quả.
  app.post('/internal/users/:userId/erase', requireInternal, wrap((req, res) => {
    const userId = V.uuidParam(req.params.userId, 'user_id');
    const ts = db.nowIso();
    const images = [];
    let removed = 0;
    db.transaction(() => {
      for (const r of db.all('SELECT id, image_url, deleted_at FROM restaurants WHERE owner_id=?', userId)) {
        if (!r.deleted_at) removed += 1;
        images.push(r.image_url, ...db.all('SELECT image_url FROM menu_items WHERE restaurant_id=? AND image_url IS NOT NULL',
          r.id).map((x) => x.image_url));
        db.run('UPDATE menu_items SET image_url=NULL, updated_at=? WHERE restaurant_id=? AND image_url IS NOT NULL', ts, r.id);
        db.run('UPDATE restaurants SET deleted_at=COALESCE(deleted_at, ?), image_url=NULL, updated_at=? WHERE id=?', ts, ts, r.id);
      }
    });
    images.forEach(removeUnusedUpload);
    res.json({ user_id: userId, restaurants_removed: removed });
  }));

  app.use(notFoundHandler);
  app.use(errorHandler);
  return app;
}

function docsPage(kind) {
  const title = 'Restaurant Service - API docs';
  if (kind === 'redoc') {
    return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title></head><body>` +
      '<redoc spec-url="/openapi.json"></redoc>' +
      '<script src="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"></script></body></html>';
  }
  return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>` +
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head><body>' +
    '<div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js">' +
    '</script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",persistAuthorization:true});</script>' +
    '</body></html>';
}

module.exports = { createApp, docsPage, sweepUploads };
