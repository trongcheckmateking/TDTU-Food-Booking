/* Trang Điều khoản / Quyền riêng tư: điền email liên hệ từ cấu hình (CONTACT_EMAIL) nếu có. */
"use strict";
(() => {
  const email = ((window.APP_CONFIG || {}).contact || "").trim();
  if (!/^[^\s@<>"]+@[^\s@<>"]+$/.test(email)) return;
  document.querySelectorAll("[data-contact]").forEach(el => {
    const a = document.createElement("a");
    a.href = "mailto:" + email;
    a.textContent = email;
    el.replaceChildren(a);
  });
})();
