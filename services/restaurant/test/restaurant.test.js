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
  owner3: { id: U(13), role: 'chu_quan', name: 'Chủ Quán 3', email: 'o3@x.vn', status: 'active' },
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
  const mine = (await api('GET', `/api/admin/restaurants?owner_id=${USERS.owner2.id}&page_size=100`, { headers: H('admin') })).body;
  assert.ok(mine.items.length > 0 && mine.items.every((x) => x.owner_id === USERS.owner2.id), 'lọc theo chủ quán');
  assert.equal((await api('GET', '/api/admin/restaurants?owner_id=abc', { headers: H('admin') })).status, 422);
});

test('bảng tin món mới: món mới, đổi giá, bán lại, chống spam, quán duyệt/khóa', async () => {
  const db = require('../src/db');
  const ago = (ms) => new Date(Date.now() - ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const age = (mid, ms) => db.run('UPDATE menu_updates SET created_at=? WHERE item_id=?', ago(ms), mid);
  const { rid, i1, i2 } = await makeRestaurant();
  const feed = async () => (await api('GET', '/api/menu-updates?limit=50')).body.items.filter((u) => u.restaurant_id === rid);
  const one = async (mid) => (await feed()).find((u) => u.item_id === mid);
  const patch = (mid, json) => api('PATCH', `/api/menu-items/${mid}`, { headers: H('owner'), json });

  assert.deepEqual((await feed()).map((u) => [u.item_id, u.kind]).sort(), [[i1, 'new'], [i2, 'new']].sort());
  assert.equal((await one(i1)).restaurant_name, 'Cơm Tấm Test');

  // vừa đăng < 30 phút: sửa giá chỉ cập nhật giá, không thành tin "đổi giá"
  await patch(i1, { price: 32000 });
  assert.deepEqual([(await one(i1)).kind, (await one(i1)).price], ['new', 32000]);
  // sau 30 phút: đổi giá -> tin price kèm giá cũ, mỗi món vẫn chỉ một tin
  age(i1, 31 * 60e3);
  await patch(i1, { price: 30000 });
  const p = await one(i1);
  assert.deepEqual([p.kind, p.old_price, p.price], ['price', 32000, 30000]);
  assert.equal((await feed()).filter((u) => u.item_id === i1).length, 1);
  await patch(i1, { name: 'Cơm sườn bì' });                                    // đổi tên: không có tin mới
  assert.equal((await one(i1)).kind, 'price');

  // hết món qua đêm rồi bán lại: không đẩy lên; hết >= 24 giờ: tin "bán lại", có giá cũ nếu đổi giá
  age(i2, 2 * 3600e3);
  await patch(i2, { status: 'sold_out' });
  assert.equal(await one(i2), undefined, 'món hết không hiện');
  await patch(i2, { status: 'available' });
  assert.equal((await one(i2)).kind, 'new');
  await patch(i2, { status: 'sold_out' });
  db.run('UPDATE menu_items SET updated_at=? WHERE id=?', ago(25 * 3600e3), i2);
  await patch(i2, { status: 'available', price: 2500 });
  const back = await one(i2);
  assert.deepEqual([back.kind, back.old_price, back.price], ['back', 3000, 2500]);

  // món ẩn không hiện; ẩn -> bán lần đầu là "món mới"
  const hidden = await api('POST', `/api/restaurants/${rid}/menu`, { headers: H('owner'), json: { name: 'Thử', price: 1000, status: 'hidden' } });
  assert.equal(await one(hidden.body.id), undefined);
  await patch(hidden.body.id, { status: 'available' });
  assert.equal((await one(hidden.body.id)).kind, 'new');

  // mỗi quán tối đa 3 tin; tin cũ hơn 14 ngày không hiện
  await api('POST', `/api/restaurants/${rid}/menu`, { headers: H('owner'), json: { name: 'Món thứ tư', price: 1000 } });
  assert.equal((await feed()).length, 3);
  db.run('UPDATE menu_updates SET created_at=? WHERE restaurant_id=?', ago(15 * 86400e3), rid);
  assert.equal((await feed()).length, 0);

  // quán bị khóa không hiện; quán mới được duyệt thì món lên bảng tin từ lúc duyệt
  const r2 = (await api('POST', '/api/restaurants', { headers: H('owner'), json: { name: 'Quán Chờ Duyệt', address: 'Cổng A TDTU' } })).body;
  const m = (await api('POST', `/api/restaurants/${r2.id}/menu`, { headers: H('owner'), json: { name: 'Bánh flan', price: 8000 } })).body;
  db.run('UPDATE menu_updates SET created_at=? WHERE item_id=?', ago(20 * 86400e3), m.id);
  const pub = async () => (await api('GET', '/api/menu-updates?limit=50')).body.items.some((u) => u.item_id === m.id);
  assert.equal(await pub(), false, 'quán chờ duyệt không hiện');
  await api('PATCH', `/api/admin/restaurants/${r2.id}/status`, { headers: H('admin'), json: { status: 'active' } });
  assert.equal(await pub(), true, 'duyệt quán -> món lên bảng tin');
  await api('PATCH', `/api/admin/restaurants/${r2.id}/status`, { headers: H('admin'), json: { status: 'locked', reason: 'x' } });
  assert.equal(await pub(), false, 'quán bị khóa không hiện');

  assert.equal((await api('GET', '/api/menu-updates?limit=0')).status, 422);
  assert.equal((await api('GET', '/api/menu-updates?limit=51')).status, 422);
  assert.ok((await api('GET', '/api/menu-updates?limit=1')).body.items.length <= 1);
});

test('nâng cấp DB cũ: thêm cột danh mục, nạp bảng tin một lần', () => {
  const { DatabaseSync } = require('node:sqlite');
  const db = require('../src/db');
  const file = path.join(tmp, 'legacy.db');
  const old = new DatabaseSync(file);
  // DB cũ: menu_items chưa có cột category, chưa có bảng menu_updates
  old.exec(db.SCHEMA.split('-- Bảng tin món mới')[0].replace(/^\s*category .*\n/m, ''));
  assert.ok(!old.prepare('PRAGMA table_info(menu_items)').all().some((c) => c.name === 'category'));
  old.exec("INSERT INTO restaurants (id,owner_id,name,address,status,created_at,updated_at) VALUES ('r1','o','Q','A','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')");
  for (const [id, st] of [['a', 'available'], ['b', 'sold_out'], ['c', 'hidden']]) {
    old.exec(`INSERT INTO menu_items (id,restaurant_id,name,price,status,created_at,updated_at) VALUES ('${id}','r1','M',1000,'${st}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')`);
  }
  old.close();
  const conn = new DatabaseSync(file);
  for (let i = 0; i < 2; i++) db.migrate(conn);                  // mở 2 lần: không lỗi, không nhân đôi
  assert.ok(conn.prepare('PRAGMA table_info(menu_items)').all().some((c) => c.name === 'category'));
  assert.deepEqual(conn.prepare('SELECT item_id, kind FROM menu_updates').all().map((r) => [r.item_id, r.kind]), [['a', 'new']]);
  conn.close();
});

test('ảnh quán / món: tải lên, kiểm tra định dạng, gán, xóa ảnh cũ; danh mục món', async () => {
  const { rid, i1 } = await makeRestaurant();
  const png = Buffer.from('89504e470d0a1a0a0000000d49484452000000040000000308020000003b963991000000104944415478' +
    '9c6310f5980b470c383900de4b0bb9545d06570000000049454e44ae426082', 'hex');   // PNG 4x3 hợp lệ
  const up = async (who, body, type = 'image/png') => {
    const r = await fetch(`${base}/api/uploads`, { method: 'POST', headers: { ...(who ? H(who) : {}), 'Content-Type': type }, body });
    return { status: r.status, body: await r.json() };
  };
  const a = await up('owner', png);
  assert.equal(a.status, 201);
  assert.match(a.body.url, /^\/uploads\/[0-9a-f-]{36}\.png$/);
  const got = await fetch(base + a.body.url);
  assert.equal(got.status, 200);
  assert.equal(got.headers.get('content-type'), 'image/png');
  assert.equal(got.headers.get('x-content-type-options'), 'nosniff');
  assert.deepEqual(Buffer.from(await got.arrayBuffer()), png);

  assert.equal((await up('owner', Buffer.from('<script>alert(1)</script>'))).body.code, 'UNSUPPORTED_MEDIA_TYPE', 'HTML đội lốt ảnh');
  assert.equal((await up('owner', png, 'text/html')).status, 415);
  assert.equal((await up('owner', Buffer.concat([png, Buffer.alloc(2 * 1024 * 1024)]))).status, 413);
  assert.equal((await up('sv', png)).status, 403);
  assert.equal((await up(null, png)).status, 401);
  assert.equal((await fetch(`${base}/uploads/khong-co.png`)).status, 404);
  assert.equal((await fetch(`${base}/uploads/..%2F..%2Frestaurant.db`)).status, 404);

  const patchR = (json) => api('PATCH', `/api/restaurants/${rid}`, { headers: H('owner'), json });
  assert.equal((await patchR({ image_url: a.body.url })).body.image_url, a.body.url);
  for (const bad of ['javascript:alert(1)', '/uploads/../restaurant.db', 'data:image/png;base64,AA==']) {
    assert.equal((await patchR({ image_url: bad })).status, 422, bad);
  }
  assert.equal((await patchR({ image_url: 'https://example.com/anh.jpg' })).status, 200);
  await new Promise((ok) => setTimeout(ok, 50));                       // xóa tệp chạy nền
  assert.equal((await fetch(base + a.body.url)).status, 404, 'ảnh cũ không còn dùng thì bị xóa');

  const b = await up('owner', png);
  const m = await api('POST', `/api/restaurants/${rid}/menu`, { headers: H('owner'),
    json: { name: 'Trà tắc', price: 10000, category: '  Đồ uống ', image_url: b.body.url } });
  assert.deepEqual([m.status, m.body.category, m.body.image_url], [201, 'Đồ uống', b.body.url]);
  assert.equal((await api('GET', `/api/restaurants/${rid}/menu`)).body.find((x) => x.id === m.body.id).category, 'Đồ uống');
  const cleared = await api('PATCH', `/api/menu-items/${i1}`, { headers: H('owner'), json: { category: 'Món chính' } });
  assert.equal(cleared.body.category, 'Món chính');
  assert.equal((await api('PATCH', `/api/menu-items/${i1}`, { headers: H('owner'), json: { category: 'x'.repeat(51) } })).status, 422);
  assert.equal((await api('PATCH', `/api/menu-items/${i1}`, { headers: H('owner'), json: { category: null } })).body.category, null);

  // xóa món -> ảnh của món bị gỡ và tệp được dọn
  assert.equal((await api('DELETE', `/api/menu-items/${m.body.id}`, { headers: H('owner') })).status, 204);
  await new Promise((ok) => setTimeout(ok, 50));
  assert.equal((await fetch(base + b.body.url)).status, 404);

  // ảnh tải lên mà không gán vào đâu: được dọn sau 1 giờ
  const orphan = await up('owner', png);
  const { sweepUploads } = require('../src/app');
  const file = path.join(tmp, 'uploads', path.basename(orphan.body.url));
  sweepUploads();
  await new Promise((ok) => setTimeout(ok, 50));
  assert.ok(fs.existsSync(file), 'ảnh mới tải chưa bị dọn');
  const old = new Date(Date.now() - 2 * 3600e3);
  fs.utimesSync(file, old, old);
  sweepUploads();
  await new Promise((ok) => setTimeout(ok, 50));
  assert.ok(!fs.existsSync(file), 'ảnh mồ côi quá 1 giờ bị dọn');
});

test('ảnh nằm trong thư mục có dấu chấm vẫn phục vụ được', async () => {
  const png = Buffer.from('89504e470d0a1a0a0000000d49484452000000040000000308020000003b963991000000104944415478' +
    '9c6310f5980b470c383900de4b0bb9545d06570000000049454e44ae426082', 'hex');
  const r = await fetch(`${base}/api/uploads`, { method: 'POST', headers: { ...H('owner'), 'Content-Type': 'image/png' }, body: png });
  const { url } = await r.json();
  const prev = process.env.DATA_DIR;
  const dotDir = path.join(tmp, '.an', 'data');
  fs.mkdirSync(path.join(dotDir, 'uploads'), { recursive: true });
  fs.copyFileSync(path.join(tmp, 'uploads', path.basename(url)), path.join(dotDir, 'uploads', path.basename(url)));
  process.env.DATA_DIR = dotDir;
  try {
    assert.equal((await fetch(base + url)).status, 200);
    assert.equal((await fetch(`${base}/uploads/00000000-0000-4000-8000-000000000000.png`)).status, 404);
  } finally {
    process.env.DATA_DIR = prev;
  }
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

test('xóa dữ liệu cá nhân: gỡ mọi quán của chủ quán cùng ảnh, gọi lại an toàn', async () => {
  const png = Buffer.from('89504e470d0a1a0a0000000d49484452000000040000000308020000003b963991000000104944415478' +
    '9c6310f5980b470c383900de4b0bb9545d06570000000049454e44ae426082', 'hex');
  const upload = async () => (await (await fetch(`${base}/api/uploads`, { method: 'POST',
    headers: { ...H('owner3'), 'Content-Type': 'image/png' }, body: png })).json()).url;
  const cover = await upload();
  const dish = await upload();
  const r = await api('POST', '/api/restaurants', { headers: H('owner3'),
    json: { name: 'Quán Sẽ Xóa', address: '1 Nguyễn Hữu Thọ, Q7', image_url: cover } });
  assert.equal(r.status, 201);
  const m = await api('POST', `/api/restaurants/${r.body.id}/menu`, { headers: H('owner3'),
    json: { name: 'Bánh mì', price: 20000, image_url: dish } });
  assert.equal(m.status, 201);

  const url = `/internal/users/${USERS.owner3.id}/erase`;
  assert.equal((await api('POST', url)).status, 403);
  assert.equal((await api('POST', '/internal/users/khong-phai-uuid/erase', { headers: INTERNAL })).status, 422);
  const e = await api('POST', url, { headers: INTERNAL });
  assert.deepEqual([e.status, e.body.restaurants_removed], [200, 1]);
  assert.equal((await api('GET', `/internal/owners/${USERS.owner3.id}/restaurant-count`, { headers: INTERNAL })).body.count, 0);
  assert.deepEqual((await api('GET', '/api/restaurants/mine', { headers: H('owner3') })).body, []);
  await new Promise((ok) => setTimeout(ok, 50));                       // xóa tệp chạy nền
  assert.equal((await fetch(base + cover)).status, 404, 'ảnh quán bị xóa');
  assert.equal((await fetch(base + dish)).status, 404, 'ảnh món bị xóa');
  assert.equal((await api('POST', url, { headers: INTERNAL })).body.restaurants_removed, 0);
  assert.equal((await api('POST', `/internal/users/${USERS.sv.id}/erase`, { headers: INTERNAL })).body.restaurants_removed, 0);
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
