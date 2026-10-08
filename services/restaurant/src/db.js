'use strict';
/**
 * SQLite qua module node:sqlite có sẵn của Node.js (>= 22.13), không cần thư viện native.
 * Node chạy 1 luồng và các lệnh DB là đồng bộ, nên mỗi khối giao dịch chạy trọn vẹn, không xen kẽ.
 *
 * Bảng RESTAURANTS, MENU_ITEMS (khớp ERD). Quán: pending/active/closed/locked + xóa mềm deleted_at.
 * Món: available/sold_out/hidden + xóa mềm. Tiền VND là số nguyên.
 */
const path = require('node:path');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const config = require('./config');

const SCHEMA = `
CREATE TABLE IF NOT EXISTS restaurants (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL,                 -- users.id (Auth Service) - tham chiếu logic, không FK
    name          TEXT NOT NULL,
    address       TEXT NOT NULL,
    description   TEXT,
    open_time     TEXT,
    close_time    TEXT,
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','active','closed','locked')),
    status_reason TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_restaurants_owner ON restaurants(owner_id);
CREATE INDEX IF NOT EXISTS idx_restaurants_status ON restaurants(status);
CREATE TABLE IF NOT EXISTS menu_items (
    id            TEXT PRIMARY KEY,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),   -- FK thật (cùng DB)
    name          TEXT NOT NULL,
    price         INTEGER NOT NULL CHECK (price >= 0),        -- VND, số nguyên
    description   TEXT,
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','sold_out','hidden')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_menu_restaurant ON menu_items(restaurant_id);
`;

let db = null;

function open(file = path.join(config.dataDir(), 'restaurant.db')) {
  db = new DatabaseSync(file);
  db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 10000;');
  db.exec(SCHEMA);
  return db;
}

function conn() {
  if (!db) throw new Error('DB chưa được mở');
  return db;
}

const one = (sql, ...args) => conn().prepare(sql).get(...args) ?? null;
const all = (sql, ...args) => conn().prepare(sql).all(...args);
const run = (sql, ...args) => conn().prepare(sql).run(...args);

function transaction(fn) {
  const c = conn();
  c.exec('BEGIN IMMEDIATE');
  try {
    const result = fn();
    c.exec('COMMIT');
    return result;
  } catch (e) {
    c.exec('ROLLBACK');
    throw e;
  }
}

function check() {
  try { return one('SELECT 1 AS ok').ok === 1; } catch { return false; }
}

function close() {
  if (db) { db.close(); db = null; }
}

const newId = () => crypto.randomUUID();
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

function paginate(sql, args, page, pageSize, orderBy) {
  const total = one(`SELECT COUNT(*) AS n FROM (${sql})`, ...args).n;
  const items = all(`${sql} ORDER BY ${orderBy} LIMIT ? OFFSET ?`, ...args, pageSize, (page - 1) * pageSize);
  return { items, total, page, page_size: pageSize };
}

module.exports = { SCHEMA, open, close, one, all, run, transaction, check, newId, nowIso, paginate };
