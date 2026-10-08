'use strict';
/**
 * Test riêng của Restaurant Service (node:test, không cần thư viện ngoài).
 * Auth Service được thay bằng 1 server giả (token -> người dùng) để test độc lập;
 * test liên service với Auth thật nằm ở tests/ của dự án (pytest).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rest-test-'));
process.env.TDTU_ENV_FILE = path.join(tmp, 'no.env');
process.env.DATA_DIR = tmp;
process.env.INTERNAL_KEY = 'test-internal-key-yyyyyyyyyyyyyyyy';
process.env.CORS_ORIGINS = 'http://127.0.0.1:8000';
process.env.LOG_LEVEL = 'WARNING';
process.env.HTTP_TIMEOUT = '1';

const U = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const USERS = {
  owner: { id: U(11), role: 'chu_quan', name: 'Chủ Quán', email: 'o@x.vn', status: 'active' },
  owner2: { id: U(12), role: 'chu_quan', name: 'Chủ Quán 2', email: 'o2@x.vn', status: 'active' },
  sv: { id: U(21), role: 'sinh_vien', name: 'SV', email: 'sv@x.vn', status: 'active' },
  admin: { id: U(1), role: 'admin', name: 'Admin', email: 'a@x.vn', status: 'active' },
};
let authMode = 'ok';
const fakeAuth = http.createServer((req, res) => {
  if (authMode === 'hang') return;                         // không trả lời -> timeout
  if (authMode === '500') { res.writeHead(500); return res.end('{}'); }
  if (authMode === 'badjson') { res.writeHead(200); return res.end('<html>'); }
  const token = (req.headers.authorization || '').replace('Bearer ', '');
  if (token === 'locked') { res.writeHead(403); return res.end('{"detail":"Tài khoản đã bị khóa","code":"ACCOUNT_LOCKED"}'); }
  const u = USERS[token];
  res.writeHead(u ? 200 : 401, { 'Content-Type': 'application/json' });
  return res.end(JSON.stringify(u || { detail: 'x', code: 'TOKEN_INVALID' }));
});

let base;
let server;
const H = (who) => ({ Authorization: `Bearer ${who}` });
const INTERNAL = { 'X-Internal-Key': process.env.INTERNAL_KEY };

async function api(method, url, { headers = {}, json, raw } = {}) {
  const h = { ...headers };
  let body;
  if (json !== undefined) { h['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  if (raw !== undefined) { h['Content-Type'] = 'application/json'; body = raw; }
  const r = await fetch(base + url, { method, headers: h, body });
  const text = await r.text();
  return { status: r.status, body: text ? JSON.parse(text) : null, headers: r.headers };
}

test.before(async () => {
  await new Promise((ok) => fakeAuth.listen(0, '127.0.0.1', ok));
  process.env.AUTH_URL = `http://127.0.0.1:${fakeAuth.address().port}`;
  const db = require('../src/db');
  db.open();
  const { createApp } = require('../src/app');
  server = createApp().listen(0, '127.0.0.1');
  await new Promise((ok) => server.once('listening', ok));
  base = `http://127.0.0.1:${server.address().port}`;
});

test.after(() => {
  server.close();
  fakeAuth.closeAllConnections();
  fakeAuth.close();
});

async function makeRestaurant() {
  const r = await api('POST', '/api/restaurants', { headers: H('owner'), json: { name: 'Cơm Tấm Test', address: '19 Nguyễn Hữu Thọ, Q7' } });
  assert.equal(r.status, 201);
  assert.equal(r.body.status, 'pending');
  assert.equal(r.body.owner_id, USERS.owner.id);
  const a = await api('PATCH', `/api/admin/restaurants/${r.body.id}/status`, { headers: H('admin'), json: { status: 'active' } });
  assert.equal(a.body.status, 'active');
  const m1 = await api('POST', `/api/restaurants/${r.body.id}/menu`, { headers: H('owner'), json: { name: 'Cơm sườn', price: 35000 } });
  const m2 = await api('POST', `/api/restaurants/${r.body.id}/menu`, { headers: H('owner'), json: { name: 'Trà đá', price: 3000 } });
  assert.equal(m1.status, 201);
  return { rid: r.body.id, i1: m1.body.id, i2: m2.body.id };
}

test('health, docs, CORS, 404 JSON', async () => {
  assert.deepEqual((await api('GET', '/health')).body, { service: 'restaurant', status: 'ok', db: 'ok' });
  const spec = (await api('GET', '/openapi.json')).body;
  assert.ok(spec.info.title.endsWith('Service'));
  const pre = await fetch(`${base}/health`, { method: 'OPTIONS', headers: { Origin: 'http://127.0.0.1:8000', 'Access-Control-Request-Method': 'GET' } });
  assert.equal(pre.headers.get('access-control-allow-origin'), 'http://127.0.0.1:8000');
  const bad = await fetch(`${base}/health`, { headers: { Origin: 'http://evil.example' } });
  assert.equal(bad.headers.get('access-control-allow-origin'), null);
  assert.equal((await api('GET', '/khong-co')).body.code, 'NOT_FOUND');
});

test('quán mới chờ duyệt, chủ quán không tự mở', async () => {
  const r = await api('POST', '/api/restaurants', { headers: H('owner2'), json: { name: 'Quán Mới', address: 'Cổng B TDTU' } });
  assert.equal(r.body.accepting_orders, false);
  assert.equal((await api('GET', `/api/restaurants/${r.body.id}`)).status, 404);
  assert.equal((await api('GET', `/api/restaurants/${r.body.id}`, { headers: H('owner2') })).status, 200);
  const p = await api('PATCH', `/api/restaurants/${r.body.id}`, { headers: H('owner2'), json: { status: 'active' } });
  assert.equal(p.status, 409);
  assert.equal(p.body.code, 'RESTAURANT_PENDING');
  assert.equal((await api('PATCH', `/api/admin/restaurants/${r.body.id}/status`, { headers: H('owner2'), json: { status: 'active' } })).status, 403);
});

test('kiểm tra dữ liệu vào', async () => {
  const { rid } = await makeRestaurant();
  const url = `/api/restaurants/${rid}/menu`;
  for (const body of [{ name: 'A', price: 1.5 }, { name: 'A', price: '1000' }, { name: 'A', price: true },
    { name: 'A', price: -1 }, { name: '   ', price: 1 }, { name: 'A', price: 100000001 }, { name: 'A', price: 1, status: 'x' },
    { name: 'A', price: 1, restaurant_id: rid }]) {
    const r = await api('POST', url, { headers: H('owner'), json: body });
    assert.equal(r.status, 422, JSON.stringify(body));
    assert.equal(r.body.code, 'VALIDATION_ERROR');
    assert.ok(Array.isArray(r.body.errors));
  }
  assert.equal((await api('POST', url, { headers: H('owner'), raw: '{"name":"Inf","price":1e309}' })).status, 422);
  const broken = await api('POST', url, { headers: H('owner'), raw: '{"name":' });
  assert.equal(broken.status, 422);
  assert.equal(broken.body.detail, 'JSON gửi lên không hợp lệ');
  assert.equal((await api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner'), json: { open_time: '25:00' } })).status, 422);
  assert.equal((await api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner'), json: { name: null } })).status, 422);
  assert.equal((await api('GET', '/api/restaurants/khong-phai-uuid')).status, 422);
  assert.equal((await api('GET', '/api/restaurants?page_size=101')).status, 422);
  assert.equal((await api('GET', '/api/restaurants?page=abc')).status, 422);
  const ok = await api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner'), json: { name: '  Tên Mới  ', description: '   ' } });
  assert.equal(ok.body.name, 'Tên Mới');
  assert.equal(ok.body.description, null);
});

test('quyền chủ quán và vai trò', async () => {
  const { rid, i1 } = await makeRestaurant();
  assert.equal((await api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner2'), json: { name: 'Chiếm quán' } })).status, 403);
  assert.equal((await api('PATCH', `/api/menu-items/${i1}`, { headers: H('owner2'), json: { price: 1 } })).status, 403);
  assert.equal((await api('DELETE', `/api/restaurants/${rid}`, { headers: H('owner2') })).status, 403);
  assert.equal((await api('POST', '/api/restaurants', { headers: H('sv'), json: { name: 'X Y', address: 'Q7 abc' } })).status, 403);
  assert.equal((await api('POST', '/api/restaurants', { json: { name: 'X Y', address: 'Q7 abc' } })).status, 401);
  assert.equal((await api('GET', '/api/restaurants/mine', { headers: H('locked') })).body.code, 'ACCOUNT_LOCKED');
  assert.equal((await api('GET', '/api/restaurants/mine', { headers: H('khong-hop-le') })).status, 401);
});

test('món ẩn / hết, quán bị khóa, xóa mềm', async () => {
  const { rid, i1, i2 } = await makeRestaurant();
  await api('PATCH', `/api/menu-items/${i2}`, { headers: H('owner'), json: { status: 'hidden' } });
  await api('PATCH', `/api/menu-items/${i1}`, { headers: H('owner'), json: { status: 'sold_out' } });
  const pub = (await api('GET', `/api/restaurants/${rid}/menu`)).body;
  assert.deepEqual(pub.map((m) => m.id), [i1]);
  assert.equal((await api('GET', `/api/restaurants/${rid}/menu?all=true`, { headers: H('sv') })).status, 403);
  assert.equal((await api('GET', `/api/restaurants/${rid}/menu?all=true`, { headers: H('owner') })).body.length, 2);
  assert.equal((await api('GET', `/api/menu-items/${i2}`)).status, 404);

  await api('PATCH', `/api/admin/restaurants/${rid}/status`, { headers: H('admin'), json: { status: 'locked', reason: 'Vi phạm' } });
  assert.equal((await api('GET', `/api/restaurants/${rid}`)).status, 404);
  assert.equal((await api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner'), json: { status: 'active' } })).body.code, 'RESTAURANT_LOCKED');
  assert.equal((await api('GET', `/api/restaurants/${rid}`, { headers: H('owner') })).body.status_reason, 'Vi phạm');
  const un = await api('PATCH', `/api/admin/restaurants/${rid}/status`, { headers: H('admin'), json: { status: 'active' } });
  assert.equal(un.body.status_reason, null);

  assert.equal((await api('DELETE', `/api/restaurants/${rid}`, { headers: H('owner') })).status, 204);
  assert.equal((await api('GET', `/api/restaurants/${rid}`, { headers: H('owner') })).status, 404);
  const all = (await api('GET', '/api/admin/restaurants?include_deleted=true&page_size=100', { headers: H('admin') })).body;
  assert.ok(all.items.some((x) => x.id === rid && x.deleted_at));
});

test('báo giá nội bộ và đếm quán', async () => {
  const { rid, i1 } = await makeRestaurant();
  const body = { restaurant_id: rid, items: [{ item_id: i1, quantity: 2 }, { item_id: U(999), quantity: 1 }] };
  assert.equal((await api('POST', '/internal/quote', { json: body })).status, 403);
  assert.equal((await api('POST', '/internal/quote', { json: body, headers: { 'X-Internal-Key': 'sai' } })).status, 403);
  const q = (await api('POST', '/internal/quote', { json: body, headers: INTERNAL })).body;
  assert.equal(q.items[0].line_total, 70000);
  assert.equal(q.items[1].reason, 'ITEM_NOT_FOUND');
  assert.equal(q.all_available, false);
  assert.equal(q.restaurant.owner_id, USERS.owner.id);
  assert.equal((await api('POST', '/internal/quote', { json: { restaurant_id: U(5), items: [{ item_id: i1, quantity: 1 }] }, headers: INTERNAL })).status, 404);
  const c = (await api('GET', `/internal/owners/${USERS.owner.id}/restaurant-count`, { headers: INTERNAL })).body;
  assert.ok(c.count >= 1);
});

test('ánh xạ lỗi khi Auth sập / chậm / lỗi / trả rác', async () => {
  const cases = [['500', 502, 'UPSTREAM_ERROR'], ['badjson', 502, 'UPSTREAM_BAD_RESPONSE'], ['hang', 503, 'UPSTREAM_UNAVAILABLE']];
  for (const [mode, status, code] of cases) {
    authMode = mode;
    const r = await api('GET', '/api/restaurants/mine', { headers: H('owner') });
    assert.deepEqual([r.status, r.body.code], [status, code], mode);
  }
  authMode = 'ok';
  const saved = process.env.AUTH_URL;
  process.env.AUTH_URL = 'http://127.0.0.1:9';                // cổng không có ai nghe
  const r = await api('GET', '/api/restaurants/mine', { headers: H('owner') });
  assert.deepEqual([r.status, r.body.code], [503, 'UPSTREAM_UNAVAILABLE']);
  process.env.AUTH_URL = saved;
  assert.equal((await api('GET', '/api/restaurants/mine', { headers: H('owner') })).status, 200);
});
