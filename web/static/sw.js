/* Service worker của TDTU Food (cài lên điện thoại như app).
   - Trang và mã giao diện: lấy từ mạng trước (luôn là bản mới nhất), mất mạng thì dùng bản đã lưu.
   - Phông chữ, logo: dùng bản đã lưu, cập nhật ngầm.
   - API (/svc/... qua gateway, hoặc service ở cổng khác) và /config.js: không lưu, luôn hỏi mạng.
   - Mất mạng khi mở trang chưa lưu: hiện offline.html. */
"use strict";

const VERSION = "tdtu-food-v5";                     // v5: admin có nút Xóa tài khoản trên danh sách
const SHELL = [
  "/index.html", "/student.html", "/owner.html", "/offline.html", "/dieu-khoan.html", "/quyen-rieng-tu.html",
  "/assets/style.css", "/assets/fonts/fonts.css", "/assets/app.js", "/assets/covers.js", "/assets/profile.js",
  "/assets/guide.js", "/assets/payment.js", "/assets/student.js", "/assets/owner.js", "/assets/charts.js", "/assets/landing.js",
  "/assets/brand/logo.png", "/assets/brand/icon-192.png", "/assets/favicon.png", "/manifest.webmanifest",
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const keep = (req, res) => {
  if (res && res.ok && res.type === "basic") {
    const copy = res.clone();
    caches.open(VERSION).then(c => c.put(req, copy)).catch(() => {});
  }
  return res;
};

async function networkFirst(req, fallback) {
  try {
    return keep(req, await fetch(req));
  } catch (e) {
    const hit = await caches.match(req, { ignoreSearch: req.mode === "navigate" });
    if (hit) return hit;
    if (fallback) return (await caches.match(fallback)) || Response.error();
    return Response.error();
  }
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  const fresh = fetch(req).then(res => keep(req, res)).catch(() => null);
  return hit || (await fresh) || Response.error();
}

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;                 // API ở service khác: để trình duyệt tự xử lý
  if (url.pathname.startsWith("/svc/") || url.pathname === "/config.js" || url.pathname.startsWith("/qr/")) return;
  if (req.mode === "navigate") { event.respondWith(networkFirst(req, "/offline.html")); return; }
  if (url.pathname.startsWith("/assets/fonts/") || url.pathname.startsWith("/assets/brand/")) {
    event.respondWith(cacheFirst(req));
    return;
  }
  event.respondWith(networkFirst(req));
});
