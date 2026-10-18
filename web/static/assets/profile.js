/* Trang Profile (theo kiểu trang Tài khoản của app be): thẻ đầu trang có ảnh đại diện đổi được, vài con số nhanh theo
   vai trò, các nhóm mục dạng danh sách (biểu tượng, tiêu đề, mũi tên). Dùng chung cho sinh viên, chủ quán, admin. */
"use strict";

const monthYear = s => s ? new Date(s).toLocaleDateString("vi-VN", { month: "2-digit", year: "numeric" }) : "";
const contactEmail = () => (((window.APP_CONFIG || {}).contact) || "").trim();

/** Cắt giữa thành ảnh vuông (cạnh <= side) và nén JPEG ngay trên trình duyệt trước khi tải lên. */
async function squareJpeg(file, side = 512) {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw new Error("Chỉ nhận ảnh JPG, PNG hoặc WebP");
  let bmp;
  try { bmp = await createImageBitmap(file); } catch (e) { throw new Error("Không đọc được ảnh này, hãy chọn ảnh khác"); }
  const s = Math.min(bmp.width, bmp.height), out = Math.min(side, s);
  const c = document.createElement("canvas");
  c.width = c.height = out;
  const g = c.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, out, out);
  g.drawImage(bmp, (bmp.width - s) / 2, (bmp.height - s) / 2, s, s, 0, 0, out, out);
  if (bmp.close) bmp.close();
  const blob = await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.88));
  if (!blob) throw new Error("Không xử lý được ảnh này");
  return blob;
}

/** Cập nhật người dùng trong phiên + ảnh đại diện, tên ở thanh trên mà không tải lại trang. */
function updateSessionUser(user, token) {
  const s = Session.get();
  s.user = user;
  if (token) s.token = token;
  Session.set(s);
  const who = document.querySelector(".topbar .who");
  if (who) {
    const old = who.querySelector(".avatar");
    if (old) old.replaceWith(avatarEl(user));
    const name = who.querySelector(".who-text strong");
    if (name) name.textContent = user.name;
  }
}

async function profileView(main) {
  const box = h("div", { class: "profile" });
  mount(main, box);
  load(box, async () => renderProfile(box, await api("auth", "/api/users/me")));
}

function renderProfile(box, me) {
  const redraw = u => { updateSessionUser(u); renderProfile(box, u); };
  const fileIn = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "hidden",
    "aria-label": "Chọn ảnh đại diện" });
  const camBtn = h("button", { type: "button", class: "avatar-edit", title: "Đổi ảnh đại diện", "aria-label": "Đổi ảnh đại diện",
    onclick: () => fileIn.click() }, icon("camera"));
  fileIn.onchange = () => {
    const f = fileIn.files[0];
    fileIn.value = "";
    if (f) act(camBtn, async () => redraw(await uploadAvatar(f)), "Đã đổi ảnh đại diện").catch(() => {});
  };

  const hero = h("section", { class: "card profile-hero" },
    h("div", { class: "ph-avatar" }, avatarEl(me, "xl"), camBtn, fileIn),
    h("div", { class: "ph-info" },
      h("h1", null, me.name),
      h("div", { class: "ph-line" }, me.email),
      h("div", { class: "ph-line" }, me.phone || h("span", { class: "ph-dim" }, "Chưa có số điện thoại")),
      h("div", { class: "ph-tags" }, h("span", { class: "ph-role" }, STATUS[me.role] ? STATUS[me.role][0] : me.role),
        h("span", { class: "ph-since" }, "Thành viên từ " + monthYear(me.created_at)))),
    h("button", { type: "button", class: "ph-edit", onclick: () => editInfo(me, redraw) }, icon("edit"), "Sửa"));

  const stats = h("div", { class: "profile-stats" });
  loadStats(stats, me.role);

  const go = hash => () => { location.hash = hash; };
  const activity = {
    sinh_vien: [
      { ic: "orders", title: "Đơn của tôi", sub: "Mã nhận món, theo dõi đơn, đánh giá quán", onClick: go("#orders") },
      { ic: "cart", title: "Giỏ hàng", sub: "Món đang chờ đặt", onClick: go("#cart") },
      { ic: "notifications", title: "Thông báo", sub: "Quán nhận tiền, xác nhận, làm xong, hủy đơn", onClick: go("#notifications") },
      { ic: "pin", title: "Chỗ nhận hay dùng", sub: "Điền sẵn khi đặt món", value: savedAddress() || "Chưa có",
        onClick: () => editAddress(() => renderProfile(box, me)) }],
    chu_quan: [
      { ic: "orders", title: "Đơn hàng", sub: "Xác nhận tiền, nhận đơn, báo hoàn thành", onClick: go("#orders") },
      { ic: "store", title: "Cửa hàng", sub: "Ảnh bìa, giờ mở cửa, nhận đơn", onClick: go("#store") },
      { ic: "menu", title: "Thực đơn", sub: "Món, giá, còn / hết món", onClick: go("#menu") },
      { ic: "reviews", title: "Đánh giá", sub: "Sinh viên nói gì về quán", onClick: go("#reviews") },
      { ic: "notifications", title: "Thông báo", onClick: go("#notifications") }],
    admin: [
      { ic: "dashboard", title: "Bảng điều khiển", onClick: go("#dashboard") },
      { ic: "users", title: "Tài khoản", sub: "Khóa, đổi vai trò, xóa dữ liệu theo yêu cầu", onClick: go("#users") },
      { ic: "qr", title: "Mã QR", sub: "In áp phích giới thiệu app", onClick: go("#qr") }],
  }[me.role] || [];

  const contact = contactEmail();
  mount(box,
    hero,
    stats,
    menuGroup("Tài khoản", [
      { ic: "profile", title: "Thông tin cá nhân", sub: "Họ tên, số điện thoại", onClick: () => editInfo(me, redraw) },
      { ic: "image", title: "Ảnh đại diện", sub: me.avatar_url ? "Đổi hoặc gỡ ảnh" : "Chưa có ảnh, thêm để quán dễ nhận ra bạn",
        onClick: () => avatarDialog(me, fileIn, redraw) },
      { ic: "lock", title: "Đổi mật khẩu", sub: "Các thiết bị khác sẽ bị đăng xuất", onClick: () => changePassword() }]),
    me.role === "chu_quan" ? menuGroup("Nhận tiền", [
      { ic: "bank", title: "Tài khoản nhận tiền",
        sub: me.bank_account ? "Sinh viên chuyển khoản trước vào tài khoản này (mã VietQR)" : "Chưa khai báo: sinh viên chưa đặt được món",
        value: me.bank_account ? `${me.bank_name || ""} ${maskAccount(me.bank_account)}` : "Khai báo",
        onClick: () => payoutDialog(me, redraw) },
      me.bank_account ? { ic: "qr", title: "Mã QR nhận tiền của quán", sub: "Xem, tải ảnh để in dán ở quầy",
        onClick: () => payoutQrDialog(me) } : null]) : null,
    activity.length ? menuGroup("Hoạt động", activity) : null,
    canInstall() ? menuGroup("Ứng dụng", [{ ic: "phone", title: "Cài TDTU Food lên điện thoại",
      sub: "Mở nhanh từ màn hình chính, toàn màn hình như app", onClick: () => installApp() }]) : null,
    menuGroup("Hỗ trợ và pháp lý", [
      me.role !== "admin" ? { ic: "help", title: me.role === "chu_quan" ? "Hướng dẫn giao món" : "Hướng dẫn nhận món",
        sub: "Mã đơn 3 số: đọc khi tới quán, như Grab, be", onClick: () => showGuide(me.role) } : null,
      { ic: "mail", title: "Liên hệ hỗ trợ", value: contact || null, href: contact ? "mailto:" + contact : null,
        onClick: contact ? null : () => toast("Nhóm chưa cấu hình email hỗ trợ (CONTACT_EMAIL)", true) },
      { ic: "doc", title: "Điều khoản sử dụng", href: "dieu-khoan.html", external: true },
      { ic: "shield", title: "Chính sách quyền riêng tư", href: "quyen-rieng-tu.html", external: true },
      { ic: "trash", title: "Yêu cầu xóa tài khoản", sub: "Gửi từ chính email đăng ký, phản hồi trong 72 giờ",
        href: contact ? `mailto:${contact}?subject=${encodeURIComponent("Yêu cầu xóa dữ liệu cá nhân")}&body=${
          encodeURIComponent("Tôi muốn xóa tài khoản TDTU Food: " + me.email)}` : "quyen-rieng-tu.html#quyen",
        external: !contact }]),
    h("div", { class: "card pm-list" }, menuRow({ ic: "logout", title: "Đăng xuất", danger: true, onClick: logout })),
    h("p", { class: "profile-foot" }, "TDTU Food",
      me.terms_accepted_at ? ` · Đồng ý điều khoản lúc ${dt(me.terms_accepted_at)}` : "",
      " · Tạo tài khoản lúc " + dt(me.created_at)));
}

function menuRow({ ic, title, sub, value, onClick, href, external, danger }) {
  const tag = href ? "a" : "button";
  return h(tag, { class: "pm-row" + (danger ? " danger" : ""), href: href || null, type: href ? null : "button",
    target: href && external ? "_blank" : null, rel: href && external ? "noopener" : null, onclick: onClick || null },
  h("span", { class: "pm-ic" }, icon(ic)),
  h("span", { class: "pm-text" }, h("strong", null, title), sub ? h("span", null, sub) : null),
  value ? h("span", { class: "pm-value" }, value) : null,
  danger ? null : h("span", { class: "pm-chev", "aria-hidden": "true" }, external ? "↗" : "›"));
}

function menuGroup(title, rows) {
  return h("section", { class: "pm-group" }, h("h2", null, title), h("div", { class: "card pm-list" }, rows.filter(Boolean).map(menuRow)));
}

/** Vài con số nhanh dưới thẻ đầu trang; lỗi một service thì hiện "—" chứ không làm hỏng trang. */
async function loadStats(box, role) {
  const total = (svc, path, query) => api(svc, path, { query: { page_size: 1, ...query } }).then(r => r.total);
  const items = {
    sinh_vien: [["Đơn đã đặt", () => total("order", "/api/orders/me")],
      ["Hoàn thành", () => total("order", "/api/orders/me", { status: "completed" })],
      ["Đánh giá đã viết", () => api("review", "/api/reviews/me").then(r => r.length)]],
    chu_quan: [["Quán", () => api("restaurant", "/api/restaurants/mine").then(r => r.length)],
      ["Đơn đã nhận", () => total("order", "/api/orders/owner")],
      ["Hoàn thành", () => total("order", "/api/orders/owner", { status: "completed" })]],
    admin: [["Tài khoản", () => total("auth", "/api/users")],
      ["Quán chờ duyệt", () => total("restaurant", "/api/admin/restaurants", { status: "pending" })],
      ["Đơn hàng", () => total("order", "/api/admin/orders")]],
  }[role] || [];
  const cells = items.map(([label]) => {
    const v = h("strong", null, "…");
    return { v, el: h("div", { class: "card pstat" }, v, h("span", null, label)) };
  });
  mount(box, cells.map(c => c.el));
  await Promise.all(items.map(([, get], i) => get()
    .then(n => { cells[i].v.textContent = Number(n).toLocaleString("vi-VN"); })
    .catch(() => { cells[i].v.textContent = "—"; })));
}

async function uploadAvatar(file) {
  return api("auth", "/api/users/me/avatar", { method: "PUT", raw: await squareJpeg(file) });
}

function avatarDialog(me, fileIn, redraw) {
  dialog("Ảnh đại diện", [
    h("div", { class: "avatar-preview" }, avatarEl(me, "xxl")),
    h("p", { class: "small muted", style: "text-align:center" },
      "Ảnh được cắt vuông ở giữa và thu nhỏ trước khi tải lên. Chỉ bạn và ban quản trị thấy ảnh này.")],
  [{ label: "Đóng", value: false },
    me.avatar_url ? { label: "Gỡ ảnh", class: "danger", run: async () => {
      redraw(await api("auth", "/api/users/me/avatar", { method: "DELETE" }));
      toast("Đã gỡ ảnh đại diện");
    } } : null,
    { label: me.avatar_url ? "Chọn ảnh khác" : "Chọn ảnh", class: "primary", run: () => { fileIn.click(); } }].filter(Boolean));
}

function editInfo(me, redraw) {
  const name = h("input", { value: me.name, maxlength: 100, required: true, autocomplete: "name" });
  const phone = h("input", { value: me.phone || "", placeholder: "0xxxxxxxxx", maxlength: 10, inputmode: "numeric", autocomplete: "tel" });
  dialog("Thông tin cá nhân", [
    field("Email", h("input", { value: me.email, disabled: true }), "Email dùng để đăng nhập, không đổi được"),
    field("Họ tên", name), field("Số điện thoại", phone, "10 số, bắt đầu bằng 0. Quán gọi số này khi giao món")],
  [{ label: "Hủy", value: false }, { label: "Lưu", class: "primary", run: async () => {
    const u = await api("auth", "/api/users/me", { method: "PATCH", body: { name: name.value, phone: phone.value.trim() || null } });
    redraw(u);
    toast("Đã lưu thông tin");
  } }]);
}

function changePassword() {
  const cur = h("input", { type: "password", autocomplete: "current-password" });
  const pw = h("input", { type: "password", autocomplete: "new-password", minlength: 8 });
  const pw2 = h("input", { type: "password", autocomplete: "new-password" });
  dialog("Đổi mật khẩu", [field("Mật khẩu hiện tại", cur), field("Mật khẩu mới", pw, "Từ 8 ký tự, có cả chữ và số"),
    field("Nhập lại mật khẩu mới", pw2)],
  [{ label: "Hủy", value: false }, { label: "Đổi mật khẩu", class: "primary", run: async () => {
    if (pw.value !== pw2.value) { toast("Hai lần nhập mật khẩu mới chưa khớp", true); pw2.focus(); return false; }
    const r = await api("auth", "/api/users/me/password", { method: "POST",
      body: { current_password: cur.value, new_password: pw.value } });
    updateSessionUser(r.user, r.access_token);
    toast("Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất");
  } }]);
}

const ADDR_KEY = "tdtu_addr";
function savedAddress() { try { return localStorage.getItem(ADDR_KEY) || ""; } catch (e) { return ""; } }

function editAddress(after) {
  const input = h("input", { value: savedAddress(), maxlength: 300, placeholder: "VD: Cổng C TDTU, KTX khu B phòng 305" });
  dialog("Chỗ nhận hay dùng", [field("Chỗ nhận", input, "Lưu trên máy này, tự điền khi đặt món")],
    [{ label: "Hủy", value: false },
      { label: "Xóa", run: () => { try { localStorage.removeItem(ADDR_KEY); } catch (e) { /* bỏ qua */ } after(); } },
      { label: "Lưu", class: "primary", run: () => {
        try { localStorage.setItem(ADDR_KEY, input.value.trim()); } catch (e) { /* bỏ qua */ }
        after();
      } }]);
}
