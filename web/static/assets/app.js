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

// ---------------- Cài lên điện thoại như app (PWA)
const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
let installPrompt = null;
window.addEventListener("beforeinstallprompt", e => {        // Chrome / Edge / Samsung Internet trên Android
  e.preventDefault();
  installPrompt = e;
  document.dispatchEvent(new Event("tdtu:installable"));
});
window.addEventListener("appinstalled", () => { installPrompt = null; document.dispatchEvent(new Event("tdtu:installable")); });
if (isStandalone()) document.documentElement.classList.add("standalone");
if ("serviceWorker" in navigator && (location.protocol === "https:" || /^(localhost|127\.0\.0\.1)$/.test(location.hostname))) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("sw.js").catch(() => {}); });
}
/** Có thể mời cài app không: trình duyệt cho cài (Android) hoặc iPhone / iPad (cài bằng Thêm vào MH chính). */
const canInstall = () => !isStandalone() && (!!installPrompt || isIOS());

async function installApp() {
  if (installPrompt) {
    const p = installPrompt;
    installPrompt = null;
    p.prompt();
    const r = await p.userChoice.catch(() => null);
    if (r && r.outcome === "accepted") toast("Đã cài TDTU Food lên điện thoại");
    document.dispatchEvent(new Event("tdtu:installable"));
    return;
  }
  const step = (n, text) => h("li", null, h("span", { class: "step-no" }, n), h("span", null, text));
  dialog("Cài TDTU Food lên điện thoại", [
    h("p", { class: "muted" }, "Mở TDTU Food từ màn hình chính như một app: toàn màn hình, không thanh địa chỉ."),
    isIOS() ? h("ol", { class: "install-steps" }, step(1, "Mở trang này bằng Safari."),
      step(2, "Bấm nút Chia sẻ (ô vuông có mũi tên lên) ở thanh dưới."), step(3, "Chọn “Thêm vào MH chính”, rồi bấm Thêm."))
      : h("ol", { class: "install-steps" }, step(1, "Mở trang này bằng Chrome trên Android."),
        step(2, "Bấm menu ⋮ ở góc trên."), step(3, "Chọn “Cài đặt ứng dụng” hoặc “Thêm vào màn hình chính”."))],
  [{ label: "Đã hiểu", class: "primary" }]);
}

/** Nút "Cài app": chỉ hiện khi cài được, tự ẩn khi đã cài. */
function installButton(cls = "btn sm") {
  const btn = h("button", { type: "button", class: cls + " install-btn", onclick: () => installApp() }, icon("phone"), "Cài app");
  const paint = () => btn.classList.toggle("hidden", !canInstall());
  document.addEventListener("tdtu:installable", paint);
  paint();
  return btn;
}

// ---------------- Gọi API
class ApiError extends Error {
  constructor(status, code, message, body) { super(message); this.status = status; this.code = code; this.body = body; }
}

async function api(service, path, { method = "GET", body, raw, headers = {}, auth = true, query } = {}) {
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
  if (raw !== undefined) h["Content-Type"] = raw.type;             // raw: Blob (ví dụ ảnh)
  let res;
  try {
    res = await fetch(url, { method, headers: h, body: raw !== undefined ? raw : body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new ApiError(0, "NETWORK", "Không kết nối được " + serviceName(service) + ". Kiểm tra service đã chạy chưa.");
  }
  let data = null;
  // luôn đọc hết phản hồi (kể cả 204 rỗng): bỏ dở thì trình duyệt coi yêu cầu là bị hủy (net::ERR_ABORTED)
  const text = await res.text().catch(() => "");
  if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
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
/** Mã đơn hiển thị: mã nhận món 3 chữ số (đọc khi tới quán, như Grab / be); đơn cũ chưa có mã thì 8 ký tự đầu của ID. */
const orderCode = o => "#" + ((o && o.pickup_code) || short(o && o.id));
const PICKUP_AT_SHOP = "Tự tới quán lấy";          // chỗ nhận khi sinh viên tự tới quán (delivery_address)
/** Ô mã nhận món thật to: mỗi chữ số một ô, trình đọc màn hình đọc từng số. */
function pickupCodeEl(code, size = "") {
  return h("span", { class: "pickup-code" + (size ? " " + size : ""), role: "img", "aria-label": "Mã nhận món " + String(code).split("").join(" ") },
    String(code).split("").map(d => h("span", { "aria-hidden": "true" }, d)));
}

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
    const first = ov.querySelector("input:not([type=file]):not(.hidden),select,textarea");
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

// ---------------- Biểu tượng (SVG tĩnh trong mã nguồn), logo
const ICONS = {
  restaurants: '<path d="M3 9l1.6-5h14.8L21 9"/><path d="M3 9h18a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0z"/><path d="M5 11.5V20h14v-8.5"/><path d="M10 20v-5h4v5"/>',
  cart: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  orders: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  notifications: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
  profile: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  menu: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
  reviews: '<path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
  qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M20 14v.01"/><path d="M14 20.5h.01"/><path d="M17.5 17.5H21V21h-3.5z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
};
Object.assign(ICONS, {
  store: ICONS.restaurants,
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  pin: '<path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 6l-10 7L2 6"/>',
  doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6"/><path d="M9 17h4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
});
function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.menu}</svg>`;
  return t.content.firstChild;
}
function brand(role, href = "index.html") {
  return h("a", { class: "brand", href, "aria-label": "TDTU Food – trang chủ" },
    h("img", { src: "assets/brand/logo.png", alt: "", width: 44, height: 44 }),
    h("span", { class: "wordmark" }, "TDTU ", h("i", null, "Food")),
    role ? h("span", { class: "role-tag" }, role) : null);
}
const initials = name => ((name || "?").trim().split(/\s+/).pop()[0] || "?").toUpperCase();

/** Ảnh đại diện lưu ở Auth Service (/avatars/...); khác -> null. */
function avatarSrc(url) {
  return /^\/avatars\/[0-9a-f]{32}\.(jpg|png|webp)$/.test(url || "") ? (SVC.auth || "") + url : null;
}
/** Hình tròn ảnh đại diện: ảnh người dùng tải lên, chưa có (hoặc lỗi) thì chữ cái đầu của tên. */
function avatarEl(u, size = "") {
  const src = avatarSrc(u && u.avatar_url);
  const el = h("span", { class: "avatar" + (size ? " " + size : "") + (src ? " has-img" : ""), "aria-hidden": "true" });
  if (!src) { el.textContent = initials(u && u.name); return el; }
  el.append(h("img", { src, alt: "", decoding: "async", onerror: () => {
    el.classList.remove("has-img"); el.textContent = initials(u && u.name);
  } }));
  return el;
}

/** Ảnh quán / món: không gửi referrer tới link ngoài; ảnh hỏng thì ẩn khung ảnh. */
function photo(src, alt = "") {
  return h("img", { src, alt, loading: "lazy", referrerpolicy: "no-referrer",
    onerror: e => { const box = e.currentTarget.closest(".thumb,.rest-cover,.store-cover"); if (box) box.classList.add("hidden"); } });
}

/** Đường dẫn để hiển thị ảnh: ảnh tải lên Restaurant Service (/uploads/...) hoặc link http(s); khác -> null. */
function imageSrc(url) {
  if (!url) return null;
  if (/^\/uploads\/[0-9a-f-]+\.(jpg|png|webp)$/.test(url)) return (SVC.restaurant || "") + url;
  return null;           // ảnh ở máy chủ khác: không tải (máy chủ đó sẽ biết IP người xem), hiện ảnh thay thế
}

// ---------------- Khung trang: thanh trên + tab (điện thoại: tab xuống đáy) hoặc thanh menu trái (sidebar: true, admin)
function shell({ title, subtitle, tabs, onTab, sidebar = false }) {
  const s = Session.get();
  document.title = `${subtitle} – ${title}`;
  const bellCount = h("span", { class: "count hidden" });
  const bell = h("button", { class: "bell ghost", title: "Thông báo", "aria-label": "Thông báo",
    onclick: () => { location.hash = "#notifications"; } }, icon("notifications"), bellCount);
  const top = h("header", { class: "topbar" },
    brand(subtitle, "#" + tabs[0].id),
    h("div", { class: "spacer" }),
    h(tabs.some(t => t.id === "profile") ? "a" : "div", { class: "who", href: tabs.some(t => t.id === "profile") ? "#profile" : null,
      title: "Profile" }, h("div", { class: "who-text" }, h("strong", null, s.user.name), h("span", null, s.user.email)),
      avatarEl(s.user)),
    bell,
    h("button", { class: "ghost", "aria-label": "Đăng xuất", onclick: logout }, icon("logout"), h("span", { class: "logout-label" }, "Đăng xuất")));
  const link = t => h("a", { href: "#" + t.id, "data-tab": t.id }, icon(t.id), h("span", { class: "grow" }, t.label),
    h("span", { class: "tab-count hidden", "aria-label": "mục cần xử lý" }));
  const main = h("main", { id: "main" });
  let nav, pageTitle = null, sideFooter = null, closeSide = () => {};
  if (sidebar) {
    // nhóm mục theo t.group (giữ thứ tự xuất hiện)
    const groups = [];
    tabs.filter(t => !t.hidden).forEach(t => {
      let g = groups.find(x => x.name === (t.group || ""));
      if (!g) groups.push(g = { name: t.group || "", items: [] });
      g.items.push(t);
    });
    nav = h("nav", { class: "side-nav", "aria-label": "Mục quản trị" },
      groups.map(g => h("div", { class: "side-group" }, g.name ? h("div", { class: "side-label" }, g.name) : null, g.items.map(link))));
    sideFooter = h("div", { class: "side-foot" });
    const side = h("aside", { class: "sidebar", id: "sidebar" }, h("div", { class: "side-brand" }, brand(subtitle, "#" + tabs[0].id)), nav, sideFooter);
    const toggleBtn = h("button", { class: "ghost side-toggle", "aria-label": "Mở menu", "aria-controls": "sidebar", "aria-expanded": "false" },
      icon("menu"));
    const sideMain = h("div", { class: "side-main" }, top, main);
    const setOpen = open => {
      document.body.classList.toggle("side-open", open);
      toggleBtn.setAttribute("aria-expanded", String(open));
      sideMain.inert = open;                                     // menu đang mở: phần trang phía sau không Tab vào được
      if (open) { const a = nav.querySelector("a"); if (a) a.focus(); }
    };
    closeSide = () => {
      if (!document.body.classList.contains("side-open")) return;
      const inside = side.contains(document.activeElement);
      setOpen(false);
      if (inside) toggleBtn.focus();                             // focus không kẹt ở mục menu đã ẩn
    };
    toggleBtn.onclick = () => setOpen(!document.body.classList.contains("side-open"));
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && document.body.classList.contains("side-open")) { closeSide(); toggleBtn.focus(); }
    });
    pageTitle = h("h2", { class: "page-title" });
    top.classList.replace("topbar", "admin-top");
    top.firstChild.replaceWith(toggleBtn, pageTitle);
    document.body.classList.add("layout-side");
    document.body.replaceChildren(side, h("div", { class: "side-scrim", onclick: () => closeSide() }), sideMain);
  } else {
    nav = h("nav", { class: "tabs", "aria-label": "Mục chính" }, tabs.filter(t => !t.hidden).map(link));
    document.body.classList.add("has-tabbar");
    document.body.replaceChildren(top, nav, main);
  }
  const go = () => {
    const id = (location.hash || "#" + tabs[0].id).slice(1).split("/")[0];
    const tab = tabs.find(t => t.id === id) || tabs[0];
    if (pageTitle) pageTitle.textContent = tab.label;
    closeSide();
    nav.querySelectorAll("a").forEach(a => {
      const on = a.dataset.tab === tab.id;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
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
  /** Số đếm cạnh tên tab (0 = ẩn), ví dụ số đơn chờ xác nhận. */
  const setBadge = (id, n) => {
    const el = nav.querySelector(`a[data-tab="${id}"] .tab-count`);
    if (el) { el.textContent = n > 99 ? "99+" : String(n); el.classList.toggle("hidden", !n); }
  };
  return { refreshBell, setBadge, sideFooter };
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

function uuid4() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

function timeAgo(s) {
  const sec = (Date.now() - new Date(s).getTime()) / 1000;
  if (sec < 60) return "vừa xong";
  if (sec < 3600) return Math.floor(sec / 60) + " phút trước";
  if (sec < 86400) return Math.floor(sec / 3600) + " giờ trước";
  if (sec < 2 * 86400) return "hôm qua";
  if (sec < 7 * 86400) return Math.floor(sec / 86400) + " ngày trước";
  return new Date(s).toLocaleDateString("vi-VN");
}

// ---------------- Bảng tin món mới (trang giới thiệu + trang sinh viên)
const UPDATE_KIND = { new: "Món mới", price: "Đổi giá", back: "Bán lại" };

/**
 * Vẽ bảng tin vào `target`. linkTo(u) (nếu có) trả về đường dẫn khi bấm vào tin, ví dụ trang quán.
 * Trả về danh sách tin lần tải đầu (mảng rỗng nếu lỗi), không bao giờ reject.
 */
async function menuBoard(target, { limit = 6, max = 20, linkTo } = {}) {
  const list = h("ul", { class: "board-list" });
  const more = h("div", { class: "board-more hidden" });
  mount(target, h("section", { class: "board", "aria-labelledby": "board-title" },
    h("div", { class: "board-head" }, h("div", null, h("h2", { id: "board-title" }, "Bảng tin món mới"),
      h("p", null, "Quán quanh trường vừa thêm món, đổi giá hoặc bán lại món."))),
    list, more));
  const row = u => {
    const body = [
      h("span", { class: "bi-kind " + u.kind }, UPDATE_KIND[u.kind] || u.kind),
      h("div", { class: "bi-main" }, h("div", { class: "bi-name" }, u.item_name),
        h("div", { class: "bi-meta" }, `${u.restaurant_name}, ${timeAgo(u.created_at)}`)),
      u.old_price !== null && u.old_price !== u.price ? h("span", { class: "bi-old" }, money(u.old_price)) : null,
      h("span", { class: "price-tag" }, money(u.price))];
    return h("li", { class: "board-item" }, linkTo ? h("a", { class: "board-link", href: linkTo(u) }, body) : body);
  };
  const fetchItems = async n => {
    const r = await api("restaurant", "/api/menu-updates", { auth: false, query: { limit: n } });
    return Array.isArray(r && r.items) ? r.items : [];
  };
  const showMore = (items, n) => {
    const canMore = items.length > n && n < max;          // xin thêm 1 tin để biết còn tin hay không
    mount(more, canMore ? h("button", { class: "sm", onclick: expand }, "Xem thêm tin") : null);
    more.classList.toggle("hidden", !canMore);
  };
  async function expand(ev) {
    const btn = ev.currentTarget; btn.disabled = true;
    try {
      const items = (await fetchItems(max)).slice(0, max);
      const before = list.children.length;
      mount(list, items.map(row));
      showMore([], max);
      const next = list.children[before];
      if (next) (next.querySelector("a") || next).focus({ preventScroll: true });
    } catch (e) { btn.disabled = false; toast(e.message, true); }
  }
  mount(list, h("li", { class: "state" }, h("span", { class: "spinner" }), "Đang tải bảng tin…"));
  try {
    const items = await fetchItems(limit + 1);
    mount(list, items.length ? items.slice(0, limit).map(row)
      : h("li", { class: "state" }, "Chưa có món mới. Khi quán thêm món hoặc đổi giá, tin sẽ hiện ở đây."));
    showMore(items, limit);
    return items.slice(0, limit);
  } catch (e) {
    mount(list, h("li", { class: "state error" }, e.message || "Không tải được bảng tin"));
    return [];
  }
}

// ---------------- Mã QR (ảnh do máy chủ giao diện sinh ở /qr/<loại>.svg)
const WEB_BASE = ((window.APP_CONFIG && window.APP_CONFIG.web) || location.origin).replace(/\/$/, "");
const QR = {
  "sinh-vien": { title: "Cho sinh viên", text: "Quét để tạo tài khoản và đặt món ngay trên điện thoại." },
  "chu-quan": { title: "Cho chủ quán", text: "Quét để đăng ký tài khoản chủ quán và gửi quán lên app." },
};
const qrLink = kind => `${WEB_BASE}/index.html?dang-ky=${kind}`;
const isLocalUrl = url => /^https?:\/\/(127\.\d+\.\d+\.\d+|localhost|0\.0\.0\.0|\[::1?\])(:|\/|$)/.test(url);

/** Trang quản lý mã QR (admin): xem, tải ảnh, in áp phích. */
function qrView(main) {
  const local = isLocalUrl(WEB_BASE);
  mount(main, h("div", { class: "head" }, h("h1", null, "Mã QR giới thiệu app"),
      h("a", { class: "btn primary", href: "qr.html", target: "_blank", rel: "noopener" }, icon("qr"), "In áp phích QR")),
    local ? h("div", { class: "notice warn" }, "Mã QR đang trỏ tới ", h("span", { class: "mono" }, WEB_BASE),
      " nên điện thoại sẽ không mở được. Đặt PUBLIC_WEB_URL trong .env thành địa chỉ mạng của máy chạy app ",
      "(ví dụ http://192.168.1.10:8000) rồi chạy lại bằng ", h("span", { class: "mono" }, "python manage.py start --host 0.0.0.0"),
      ". Xem README, mục Mã QR.") : null,
    h("div", { class: "qr-grid" }, Object.entries(QR).map(([kind, q]) => h("div", { class: "card qr-card" },
      h("img", { src: `qr/${kind}.svg`, alt: `Mã QR ${q.title.toLowerCase()}`, width: 148, height: 148 }),
      h("div", null, h("h3", null, q.title), h("p", { class: "muted", style: "margin:0 0 8px" }, q.text),
        h("div", { class: "small qr-url mono" }, qrLink(kind)),
        h("div", { class: "row", style: "margin-top:12px" },
          h("a", { class: "btn sm", href: `qr/${kind}.svg`, download: `tdtu-food-qr-${kind}.svg` }, "Tải ảnh QR")))))));
}

// ---------------- Danh mục món
const MENU_CATEGORIES = ["Món chính", "Món phụ", "Combo", "Ăn vặt", "Đồ uống", "Tráng miệng"];
/** Nhóm món theo danh mục: danh mục gợi ý theo thứ tự trên, danh mục khác theo ABC, món chưa có danh mục ở cuối. */
function menuGroups(items) {
  const map = new Map();
  items.forEach(m => { const k = (m.category || "").trim(); if (!map.has(k)) map.set(k, []); map.get(k).push(m); });
  const rank = k => (k === "" ? 1e9 : MENU_CATEGORIES.indexOf(k) + 1 || 1e6);
  return [...map.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b, "vi"))
    .map(k => ({ name: k || "Món khác", items: map.get(k) }));
}

/** Giờ mở cửa để hiển thị; quán chưa nhập giờ -> "chưa cập nhật". */
function hours(r) {
  return r.open_time && r.close_time ? r.open_time + " – " + r.close_time : "chưa cập nhật";
}
