/* Trang in áp phích mã QR (tách khỏi HTML để bật CSP không cho script nhúng). */
"use strict";
document.getElementById("printBtn").addEventListener("click", () => window.print());
document.querySelectorAll("[data-link]").forEach(el => { el.textContent = qrLink(el.dataset.link); });
if (isLocalUrl(WEB_BASE)) {
  document.getElementById("hint").textContent =
    "Lưu ý: mã đang trỏ tới " + WEB_BASE + ", điện thoại sẽ không mở được. Đặt PUBLIC_WEB_URL trong .env (xem README, mục Mã QR).";
}
