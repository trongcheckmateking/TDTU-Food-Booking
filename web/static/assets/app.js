/* Thư viện dùng chung cho giao diện TDTU Food Booking (không framework). */
"use strict";

const SVC = (window.APP_CONFIG && window.APP_CONFIG.services) || {};
const STORE_KEY = "tdtu_session";

// ---------------- Phiên đăng nhập (localStorage có thể bị chặn -> dùng bộ nhớ tạm)
let memSession = null;
const Session = {
  get() {
    try { const v = localStorage.getItem(STORE_KEY); return v ? JSON.parse(v) : memSession; }
    catch (e) { return memSession; }
  },
  set(s) { memSession = s; try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) {} },
  clear() { memSession = null; try { localStorage.removeItem(STORE_KEY); } catch (e) {} },
};

const HOME = { sinh_vien: "student.html", chu_quan: "owner.html", admin: "admin.html" };

// ---------------- Gọi API
class ApiError extends Error {
  constructor(status, code, message, body) { super(message); this.status = status; this.code = code; this.body = body; }
}

async function api(service, path, { method = "GET", body, headers = {}, auth = true, query } = {}) {
  const base = SVC[service];
  if (!base) throw new ApiError(0, "CONFIG", "Chưa cấu hình địa chỉ " + service);
  let url = base + path;
  if (query) {
    const qs = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") qs.set(k, v); });
    if ([...qs].length) url += "?" + qs;
  }
  const h = { Accept: "application/json", ...headers };
  const s = Session.get();
  if (auth && s && s.token) h.Authorization = "Bearer " + s.token;
  if (body !== undefined) h["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(url, { method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new ApiError(0, "NETWORK", "Không kết nối được " + serviceName(service) + ". Kiểm tra service đã chạy chưa.");
  }
  let data = null;
  if (res.status !== 204) { try { data = await res.json(); } catch (e) { data = null; } }
  if (!res.ok) {
    const code = (data && data.code) || "HTTP_" + res.status;
    const msg = (data && typeof data.detail === "string" && data.detail) || "Lỗi " + res.status;
    if (auth && res.status === 401) { sessionExpired(); }
    if (auth && res.status === 403 && code === "ACCOUNT_LOCKED") { sessionExpired("locked"); }
    const err = new ApiError(res.status, code, msg, data);
    if (data && data.errors && data.errors.length) err.message += ": " + data.errors.map(e => (e.field ? e.field + " – " : "") + e.message).join("; ");
    throw err;
  }
  return data;
}

function serviceName(s) {
  return { auth: "Auth Service", restaurant: "Restaurant Service", order: "Order Service",
           notification: "Notification Service", review: "Review Service" }[s] || s;
}

function sessionExpired(reason) {
  Session.clear();
  location.href = "index.html?" + (reason === "locked" ? "locked=1" : "expired=1");
}

function requireRole(role) {
  const s = Session.get();
  if (!s || !s.token || !s.user) { location.href = "index.html"; return null; }
  if (s.user.role !== role) { location.href = HOME[s.user.role] || "index.html"; return null; }
  return s;
}

async function logout() {
  try { await api("auth", "/api/users/logout", { method: "POST" }); } catch (e) { /* vẫn đăng xuất ở client */ }
  Session.clear();
  location.href = "index.html";
}

// ---------------- Dựng phần tử an toàn (không chèn HTML thô từ dữ liệu)
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;            // chỉ dùng cho chuỗi tĩnh của mã nguồn
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel, root = document) => root.querySelector(sel);
function mount(target, ...nodes) {
  target.replaceChildren(...nodes.flat(Infinity).filter(n => n !== null && n !== undefined && n !== false && n !== ""));
}

// ---------------- Định dạng
const money = n => (n === null || n === undefined) ? "—" : Number(n).toLocaleString("vi-VN") + " đ";
const dt = s => s ? new Date(s).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "";
const stars = n => h("span", { class: "stars", title: n + "/5" }, "★".repeat(n) + "☆".repeat(5 - n));
const STATUS = {
  pending: ["Chờ xác nhận", "b-warn"], confirmed: ["Đã xác nhận", "b-info"], completed: ["Hoàn thành", "b-ok"],
  cancelled: ["Đã hủy", "b-bad"], active: ["Hoạt động", "b-ok"], closed: ["Tạm đóng", "b-muted"],
  locked: ["Bị khóa", "b-bad"], available: ["Còn bán", "b-ok"], sold_out: ["Hết món", "b-muted"],
  hidden: ["Ẩn", "b-bad"], unread: ["Chưa đọc", "b-info"], read: ["Đã đọc", "b-muted"],
  visible: ["Hiển thị", "b-ok"], sinh_vien: ["Sinh viên", "b-ok"], chu_quan: ["Chủ quán", "b-info"],
  admin: ["Admin", "b-warn"], sent: ["Đã gửi", "b-ok"], failed: ["Gửi lỗi", "b-bad"], sending: ["Đang gửi", "b-info"],
};
STATUS.pending_r = ["Chờ duyệt", "b-warn"];
function badge(status, kind) {
  const [label, cls] = STATUS[kind === "restaurant" && status === "pending" ? "pending_r" : status] || [status, "b-muted"];
  return h("span", { class: "badge " + cls }, label);
}
const short = id => (id || "").slice(0, 8).toUpperCase();

// ---------------- Trạng thái tải / rỗng / lỗi
function loading(msg = "Đang tải…") { return h("div", { class: "state" }, h("span", { class: "spinner" }), msg); }
function empty(msg) { return h("div", { class: "state" }, msg); }
function errorBox(err, retry) {
  return h("div", { class: "state error" }, err.message || String(err),
    retry ? h("div", null, h("button", { onclick: retry }, "Thử lại")) : null);
}
async function load(target, fn, retryable = true) {
  mount(target, loading());
  try { await fn(); }
  catch (e) {
    if (e.status === 401) return;
    mount(target, errorBox(e, retryable ? () => load(target, fn, retryable) : null));
  }
}

// ---------------- Thông báo nổi, hộp thoại
function toast(msg, isError = false) {
  let box = $(".toasts");
  if (!box) { box = h("div", { class: "toasts", role: "status", "aria-live": "polite" }); document.body.append(box); }
  const t = h("div", { class: "toast" + (isError ? " err" : "") }, msg);
  box.append(t);
  setTimeout(() => t.remove(), isError ? 6000 : 3000);
}

function dialog(title, body, actions = []) {
  return new Promise(resolve => {
    const close = v => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = e => { if (e.key === "Escape") close(null); };
    const footer = actions.map(a => h("button", {
      class: a.class || "", onclick: async ev => {
        if (!a.run) return close(a.value);
        const btn = ev.currentTarget; btn.disabled = true;
        try { const r = await a.run(); if (r !== false) close(r === undefined ? a.value : r); }
        catch (e) { toast(e.message, true); }
        finally { btn.disabled = false; }
      }
    }, a.label));
    const ov = h("div", { class: "overlay", onclick: e => { if (e.target === ov) close(null); } },
      h("div", { class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title },
        h("div", { class: "dh" }, h("h3", null, title), h("button", { class: "ghost", "aria-label": "Đóng", onclick: () => close(null) }, "✕")),
        h("div", { class: "db" }, body),
        footer.length ? h("div", { class: "df" }, footer) : null));
    document.body.append(ov);
    document.addEventListener("keydown", onKey);
    const first = ov.querySelector("input,select,textarea");
    if (first) first.focus();
  });
}

function confirmBox(title, message, okLabel = "Đồng ý", danger = false) {
  return dialog(title, h("p", null, message), [
    { label: "Hủy", value: false }, { label: okLabel, class: danger ? "danger" : "primary", value: true }]);
}

// Hành động bấm nút: khóa nút trong lúc gọi API, báo lỗi rõ ràng
async function act(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { if (e.status !== 401) toast(e.message, true); throw e; }
  finally { if (btn) btn.disabled = false; }
}

function field(label, input, hint) {
  return h("div", { class: "field" }, h("label", null, label), input, hint ? h("div", { class: "small muted" }, hint) : null);
}

function pager(data, onPage) {
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  return h("div", { class: "pager small" },
    h("span", { class: "muted" }, `${data.total} mục · trang ${data.page}/${pages}`),
    h("button", { class: "sm", disabled: data.page <= 1, onclick: () => onPage(data.page - 1) }, "‹ Trước"),
    h("button", { class: "sm", disabled: data.page >= pages, onclick: () => onPage(data.page + 1) }, "Sau ›"));
}

function table(columns, items, emptyMsg = "Chưa có dữ liệu") {
  if (!items.length) return empty(emptyMsg);
  return h("div", { class: "table-wrap" }, h("table", null,
    h("thead", null, h("tr", null, columns.map(c => h("th", { class: c.num ? "num" : "" }, c.label)))),
    h("tbody", null, items.map(it => h("tr", null, columns.map(c => {
      const v = c.render(it);
      return h("td", { class: (c.num ? "num " : "") + (c.actions ? "actions" : "") }, v);
    }))))));
}

// ---------------- Khung trang có thanh trên + tab
function shell({ title, subtitle, tabs, onTab }) {
  const s = Session.get();
  const bellCount = h("span", { class: "count hidden" });
  const bell = h("button", { class: "bell", title: "Thông báo", onclick: () => { location.hash = "#notifications"; } }, "🔔", bellCount);
  const top = h("header", { class: "topbar" },
    h("div", { class: "brand" }, title, h("small", null, subtitle)),
    h("div", { class: "spacer" }),
    h("div", { class: "who" }, s.user.name, h("br"), h("span", null, s.user.email)),
    bell,
    h("button", { onclick: logout }, "Đăng xuất"));
  const nav = h("nav", { class: "tabs" }, tabs.map(t => h("a", { href: "#" + t.id, "data-tab": t.id }, t.label)));
  const main = h("main", { id: "main" });
  document.body.replaceChildren(top, nav, main);
  const go = () => {
    const id = (location.hash || "#" + tabs[0].id).slice(1).split("/")[0];
    const tab = tabs.find(t => t.id === id) || tabs[0];
    nav.querySelectorAll("a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab.id));
    onTab(tab.id, main, (location.hash.slice(1).split("/")[1]) || null);
  };
  window.addEventListener("hashchange", go);
  go();
  const refreshBell = async () => {
    try {
      const r = await api("notification", "/api/notifications/me", { query: { status: "unread", page_size: 1 } });
      bellCount.textContent = r.unread; bellCount.classList.toggle("hidden", !r.unread);
    } catch (e) { bellCount.classList.add("hidden"); }
  };
  refreshBell();
  setInterval(refreshBell, 20000);
  return { refreshBell };
}

// ---------------- Màn hình dùng chung: thông báo, hồ sơ
async function notificationsView(main, refreshBell) {
  let filter = "", page = 1;
  const list = h("div", { class: "card" });
  const draw = () => load(list, async () => {
    const r = await api("notification", "/api/notifications/me", { query: { status: filter, page, page_size: 15 } });
    if (!r.items.length) return mount(list, empty(filter ? "Không có thông báo chưa đọc" : "Chưa có thông báo nào"));
    mount(list, r.items.map(n => h("div", { class: "noti " + n.status },
      h("span", { class: "dot" }),
      h("div", { class: "grow" }, h("div", null, n.message), h("div", { class: "small muted" }, dt(n.created_at))),
      n.status === "unread" ? h("button", { class: "sm", onclick: ev => act(ev.currentTarget, () =>
        api("notification", `/api/notifications/${n.id}/read`, { method: "PATCH" })).then(() => { draw(); refreshBell(); }) }, "Đã đọc") : null
    )), pager(r, p => { page = p; draw(); }));
  });
  const sel = h("select", { "aria-label": "Lọc thông báo", onchange: e => { filter = e.target.value; page = 1; draw(); } },
    h("option", { value: "" }, "Tất cả"), h("option", { value: "unread" }, "Chưa đọc"));
  mount(main, h("div", { class: "head" }, h("h1", null, "Thông báo"),
    h("div", { class: "row" }, sel, h("button", { onclick: ev => act(ev.currentTarget, () =>
      api("notification", "/api/notifications/me/read-all", { method: "PATCH" }), "Đã đánh dấu tất cả là đã đọc")
      .then(() => { draw(); refreshBell(); }) }, "Đánh dấu tất cả đã đọc"))), list);
  draw();
}

async function profileView(main) {
  const box = h("div", { class: "card pad" });
  mount(main, h("div", { class: "head" }, h("h1", null, "Hồ sơ")), box);
  load(box, async () => {
    const me = await api("auth", "/api/users/me");
    const name = h("input", { value: me.name, maxlength: 100, required: true });
    const phone = h("input", { value: me.phone || "", placeholder: "0xxxxxxxxx", maxlength: 10 });
    mount(box,
      h("div", { class: "row" }, h("strong", null, me.email), badge(me.role)),
      h("div", { class: "small muted" }, "Tạo lúc " + dt(me.created_at)),
      field("Họ tên", name), field("Số điện thoại", phone, "10 số, bắt đầu bằng 0"),
      h("div", { class: "row", style: "margin-top:14px" }, h("button", { class: "primary", onclick: ev => act(ev.currentTarget, async () => {
        const u = await api("auth", "/api/users/me", { method: "PATCH", body: { name: name.value, phone: phone.value.trim() || null } });
        const s = Session.get(); s.user = u; Session.set(s);
      }, "Đã lưu hồ sơ") }, "Lưu thay đổi")));
  });
}

function uuid4() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

/** Giờ mở cửa để hiển thị; quán chưa nhập giờ -> "chưa cập nhật". */
function hours(r) {
  return r.open_time && r.close_time ? r.open_time + " – " + r.close_time : "chưa cập nhật";
}
