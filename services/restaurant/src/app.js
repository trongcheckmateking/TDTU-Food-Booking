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
const { ApiError, notFoundHandler, errorHandler } = require('./errors');
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
  name: R(T.text(1, 150)), price: R(T.int(0, 100000000)), description: O(T.optText(1000)),
  image_url: O(T.optText(500)), status: O(T.enumOf('available', 'sold_out', 'hidden'), { default: 'available' }),
};
const MenuItemUpdate = {     // không có restaurant_id: món không thể bị chuyển sang quán khác
  name: O(T.text(1, 150), { nullable: true }), price: O(T.int(0, 100000000), { nullable: true }),
  description: O(T.optText(1000)), image_url: O(T.optText(500)),
  status: O(T.enumOf('available', 'sold_out', 'hidden'), { nullable: true }),
};
const QuoteIn = {
  restaurant_id: R(T.text(1, 100)),
  items: R(T.array(T.object({ item_id: R(T.text(1, 100)), quantity: R(T.int(1, 50)) }), 1, 50)),
};

// ------------------------------------------------------------------ tiện ích
const RESTAURANT_FIELDS = ['id', 'owner_id', 'name', 'address', 'description', 'open_time', 'close_time', 'image_url',
  'status', 'status_reason'];
const ITEM_FIELDS = ['id', 'restaurant_id', 'name', 'price', 'description', 'image_url', 'status', 'created_at',
  'updated_at'];

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

function applyUpdate(table, id, value, present, required) {
  const keys = [...present];
  for (const k of required) {
    if (present.has(k) && value[k] === null) {
      throw new ApiError(422, 'VALIDATION_ERROR', `Trường ${k} không được để trống`);
    }
  }
  if (!keys.length) return;
  const sets = keys.map((k) => `${k}=?`).join(', ');
  db.transaction(() => db.run(`UPDATE ${table} SET ${sets}, updated_at=? WHERE id=?`,
    ...keys.map((k) => value[k]), db.nowIso(), id));
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

  app.get('/api/menu-items/:mid', optionalUser, wrap((req, res) => {
    const it = getItem(V.uuidParam(req.params.mid, 'mid'));
    const r = visibleRestaurant(it.restaurant_id, req.user);
    if (it.status === 'hidden' && !isManager(req.user, r)) throw new ApiError(404, 'ITEM_NOT_FOUND', 'Không tìm thấy món');
    res.json(outItem(it));
  }));

  // ---------------------------------------------------------------- chủ quán
  app.post('/api/restaurants', requireUser('chu_quan'), wrap((req, res) => {
    const { value: d } = V.body(RestaurantCreate, req.body);
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
    const r = getRestaurant(rid);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa, không thể chỉnh sửa');
    if (present.has('status') && !PUBLIC_STATUSES.includes(r.status)) {
      throw new ApiError(409, 'RESTAURANT_PENDING', 'Quán chưa được duyệt nên chưa thể mở/đóng');
    }
    applyUpdate('restaurants', r.id, value, present, ['name', 'address', 'status']);
    res.json(outRestaurant(getRestaurant(r.id)));
  }));

  app.delete('/api/restaurants/:rid', requireUser('chu_quan', 'admin'), wrap((req, res) => {
    const r = getRestaurant(V.uuidParam(req.params.rid, 'rid'));
    if (req.user.role !== 'admin') requireOwner(req.user, r);
    const ts = db.nowIso();
    db.transaction(() => db.run('UPDATE restaurants SET deleted_at=?, updated_at=? WHERE id=?', ts, ts, r.id));
    res.status(204).end();
  }));

  app.post('/api/restaurants/:rid/menu', requireUser('chu_quan'), wrap((req, res) => {
    const rid = V.uuidParam(req.params.rid, 'rid');
    const { value: d } = V.body(MenuItemCreate, req.body);
    const r = getRestaurant(rid);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa');
    const mid = db.newId();
    const ts = db.nowIso();
    db.transaction(() => db.run('INSERT INTO menu_items (id,restaurant_id,name,price,description,image_url,status,' +
      'created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)', mid, r.id, d.name, d.price, d.description ?? null,
    d.image_url ?? null, d.status, ts, ts));
    res.status(201).json(outItem(getItem(mid)));
  }));

  app.patch('/api/menu-items/:mid', requireUser('chu_quan'), wrap((req, res) => {
    const mid = V.uuidParam(req.params.mid, 'mid');
    const { value, present } = V.body(MenuItemUpdate, req.body);
    const it = getItem(mid);
    const r = getRestaurant(it.restaurant_id);
    requireOwner(req.user, r);
    if (r.status === 'locked') throw new ApiError(403, 'RESTAURANT_LOCKED', 'Quán đang bị admin khóa');
    applyUpdate('menu_items', it.id, value, present, ['name', 'price', 'status']);
    res.json(outItem(getItem(it.id)));
  }));

  app.delete('/api/menu-items/:mid', requireUser('chu_quan'), wrap((req, res) => {
    const it = getItem(V.uuidParam(req.params.mid, 'mid'));
    requireOwner(req.user, getRestaurant(it.restaurant_id));
    const ts = db.nowIso();
    db.transaction(() => db.run('UPDATE menu_items SET deleted_at=?, updated_at=? WHERE id=?', ts, ts, it.id));
    res.status(204).end();
  }));

  // ---------------------------------------------------------------- admin
  app.get('/api/admin/restaurants', requireUser('admin'), wrap((req, res) => {
    const status = V.enumQuery(req.query, 'status', ['pending', 'active', 'closed', 'locked']);
    const q = V.textQuery(req.query, 'q', 100);
    const includeDeleted = V.boolQuery(req.query, 'include_deleted');
    const { page, pageSize } = V.pageQuery(req.query);
    let sql = 'SELECT r.*, (SELECT COUNT(*) FROM menu_items m WHERE m.restaurant_id=r.id AND m.deleted_at IS NULL) ' +
      'AS item_count FROM restaurants r WHERE 1=1';
    const args = [];
    if (!includeDeleted) sql += ' AND r.deleted_at IS NULL';
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
    db.transaction(() => db.run('UPDATE restaurants SET status=?, status_reason=?, updated_at=? WHERE id=?',
      d.status, d.status === 'locked' ? (d.reason ?? null) : null, db.nowIso(), r.id));
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

module.exports = { createApp, docsPage };
