/* Màn hướng dẫn nhận món (kiểu màn giới thiệu của app Grab / be): tự hiện ngay sau khi tạo tài khoản, mở lại được từ
   Profile. Sinh viên: đặt món -> chuyển khoản trước (VietQR) -> nhớ mã 3 số -> tới quán đọc mã.
   Chủ quán: sinh viên chuyển khoản -> xác nhận đã nhận tiền -> nhận đơn, làm món -> hỏi mã, giao món. */
"use strict";

const WELCOME_KEY = "tdtu_welcome";

// Hình minh họa: SVG tĩnh trong mã nguồn (không có dữ liệu người dùng)
const GUIDE_ART = {
  menu: '<rect x="18" y="12" width="44" height="58" rx="7"/><path d="M28 28h24M28 40h24M28 52h14"/><circle cx="60" cy="60" r="12" class="g-fill"/><path d="M55 60h10M60 55v10" class="g-on-fill"/>',
  code: '<rect x="10" y="22" width="60" height="36" rx="9"/><path d="M24 34v12M36 34c6 0 6 12 0 12M48 34h8l-6 12"/>',
  bell: '<path d="M58 36a18 18 0 0 0-36 0c0 20-8 26-8 26h52s-8-6-8-26"/><path d="M45 70a6 6 0 0 1-10 0"/><circle cx="60" cy="18" r="7" class="g-fill"/>',
  shop: '<path d="M12 30l5-14h46l5 14"/><path d="M12 30h56a8 8 0 0 1-14 0 8 8 0 0 1-14 0 8 8 0 0 1-14 0 8 8 0 0 1-14 0z"/><path d="M17 38v30h46V38"/><path d="M33 68V52h14v16"/>',
  bag: '<path d="M20 28h40l-4 42H24z"/><path d="M30 28v-6a10 10 0 0 1 20 0v6"/><path d="M33 48l6 6 10-12"/>',
  talk: '<path d="M14 18h40a6 6 0 0 1 6 6v20a6 6 0 0 1-6 6H32l-12 10V50h-6a6 6 0 0 1-6-6V24a6 6 0 0 1 6-6z"/><path d="M24 34h4M34 34h4M44 34h4"/>',
  search: '<circle cx="34" cy="34" r="18"/><path d="M47 47l17 17"/><path d="M27 34h14"/>',
  pay: '<rect x="12" y="12" width="22" height="22" rx="4"/><rect x="46" y="12" width="22" height="22" rx="4"/><rect x="12" y="46" width="22" height="22" rx="4"/><path d="M20 20h6v6h-6zM54 20h6v6h-6zM20 54h6v6h-6z"/><path d="M46 46h8v8M68 46v8M46 68h8M62 62h6v6"/>',
};

const GUIDES = {
  sinh_vien: {
    title: "Đặt trước, tới quán là có món",
    steps: [
      { art: "menu", tone: "blue", title: "Chọn quán, đặt món", text: "Xem thực đơn các quán quanh trường, thêm món vào giỏ, chọn “Tự tới quán lấy” rồi bấm Đặt hàng. Kiểm tra kỹ món trước khi đặt nhé." },
      { art: "pay", tone: "wood", title: "Chuyển khoản trước",
        text: "Quét mã VietQR bằng app ngân hàng, tiền vào thẳng tài khoản của quán. Chuyển xong bấm “Tôi đã chuyển khoản”; quán thấy tiền là đơn đặt thành công." },
      { art: "code", tone: "red", code: "047", title: "Nhớ mã nhận món 3 số",
        text: "Mã 3 chữ số hiện thật to ở mục Đơn của tôi, có thông báo khi quán bắt đầu làm. Đơn đã đặt thì không tự hủy được: cần hủy, hãy gọi quán hoặc liên hệ ban quản trị." },
      { art: "shop", tone: "tea", title: "Tới quán, đọc 3 số",
        text: "Đọc mã 3 số cho nhân viên như khi lấy món của Grab, be. Quán đối chiếu tên của bạn rồi giao món, bạn đã trả trước nên nhận là đi." },
    ],
    done: "Bắt đầu đặt món",
  },
  chu_quan: {
    title: "Nhận tiền trước, giao món bằng mã 3 số",
    steps: [
      { art: "pay", tone: "blue", title: "Sinh viên chuyển khoản trước",
        text: "Sinh viên quét mã VietQR, tiền vào thẳng tài khoản ngân hàng bạn khai báo. Đơn hiện ở tab Chờ tiền, có âm báo khi sinh viên báo đã chuyển." },
      { art: "bell", tone: "wood", title: "Thấy tiền thì bấm Đã nhận tiền",
        text: "Mở app ngân hàng, tìm khoản đúng số tiền và nội dung (VD: TDTU 047 AB12). Thấy thì bấm Đã nhận tiền, đơn sang tab Mới; không thấy thì bấm Chưa nhận được tiền." },
      { art: "code", tone: "red", code: "047", title: "Nhận đơn, làm món",
        text: "Bấm Nhận đơn để sinh viên biết quán đang làm. Mã nhận món 3 số hiện to trên thẻ đơn, ghi lên túi hoặc hộp món cho dễ tìm." },
      { art: "bag", tone: "tea", title: "Hỏi mã, giao món",
        text: "Sinh viên đọc mã 3 số: gõ vào ô “Tìm mã” để ra đúng đơn, đối chiếu tên rồi giao món và bấm Báo hoàn thành. Tiền đã nhận trước, không thu thêm." },
    ],
    done: "Vào trang Đơn hàng",
  },
};

/** Mở màn hướng dẫn cho vai trò; onDone chạy khi bấm nút cuối. */
function showGuide(role, onDone) {
  const g = GUIDES[role];
  if (!g || document.querySelector(".guide-overlay")) return;
  let i = 0;
  const prev = document.activeElement;
  const body = h("div", { class: "guide-body", "aria-live": "polite" });
  const dots = h("div", { class: "guide-dots", role: "tablist", "aria-label": "Các bước" });
  const back = h("button", { type: "button", class: "ghost" }, "Quay lại");
  const next = h("button", { type: "button", class: "primary guide-next" });
  const skip = h("button", { type: "button", class: "ghost guide-skip" }, "Bỏ qua");
  const sheet = h("div", { class: "guide", role: "dialog", "aria-modal": "true", "aria-label": g.title },
    h("div", { class: "guide-top" }, h("span", { class: "guide-kicker" }, g.title), skip), body, dots,
    h("div", { class: "guide-actions" }, back, next));
  const ov = h("div", { class: "guide-overlay" }, sheet);
  const close = finished => {
    ov.remove();
    document.removeEventListener("keydown", onKey);
    if (prev && prev.focus) prev.focus();
    if (finished && onDone) onDone();
  };
  const paint = () => {
    const st = g.steps[i];
    const art = h("div", { class: "guide-art tone-" + st.tone });
    art.append(h("span", { class: "guide-ring", "aria-hidden": "true" }));
    const svg = h("div", { class: "guide-svg", "aria-hidden": "true",
      html: `<svg viewBox="0 0 80 80" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">${GUIDE_ART[st.art]}</svg>` });
    art.append(st.code ? h("div", { class: "guide-code", "aria-label": "Ví dụ mã " + st.code.split("").join(" ") },
      st.code.split("").map(d => h("span", null, d))) : svg);
    mount(body, art, h("div", { class: "guide-step" }, `Bước ${i + 1}/${g.steps.length}`), h("h2", null, st.title),
      h("p", null, st.text));
    mount(dots, g.steps.map((_, k) => h("button", { type: "button", class: k === i ? "on" : "", role: "tab",
      "aria-selected": String(k === i), "aria-label": `Bước ${k + 1}`, onclick: () => { i = k; paint(); } })));
    back.classList.toggle("invisible", i === 0);
    next.textContent = i === g.steps.length - 1 ? g.done : "Tiếp";
    skip.classList.toggle("invisible", i === g.steps.length - 1);
  };
  back.onclick = () => { if (i > 0) { i--; paint(); } };
  next.onclick = () => { if (i < g.steps.length - 1) { i++; paint(); } else close(true); };
  skip.onclick = () => close(false);
  const onKey = e => {
    if (e.key === "Escape") close(false);
    else if (e.key === "ArrowRight") next.click();
    else if (e.key === "ArrowLeft") back.click();
  };
  // vuốt ngang trên điện thoại để chuyển bước
  let x0 = null;
  sheet.addEventListener("touchstart", e => { x0 = e.touches[0].clientX; }, { passive: true });
  sheet.addEventListener("touchend", e => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    x0 = null;
    if (dx < -50 && i < g.steps.length - 1) { i++; paint(); }
    else if (dx > 50 && i > 0) { i--; paint(); }
  }, { passive: true });
  document.addEventListener("keydown", onKey);
  document.body.append(ov);
  paint();
  next.focus();
}

/** Ngay sau khi tạo tài khoản (trang đăng ký đặt cờ), mở hướng dẫn một lần. */
function maybeWelcome(role, onDone) {
  let flag = null;
  try { flag = localStorage.getItem(WELCOME_KEY); localStorage.removeItem(WELCOME_KEY); } catch (e) { /* bỏ qua */ }
  if (flag) showGuide(role, onDone);
}
