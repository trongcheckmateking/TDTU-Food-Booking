/* Trang giới thiệu + đăng nhập / đăng ký (tách khỏi HTML để bật CSP không cho script nhúng). */
"use strict";
(() => {
  const show = (text, warn) => mount($("#msg"), text ? h("div", { class: "notice" + (warn ? " warn" : "") }, text) : "");
  const params = new URLSearchParams(location.search);
  if (params.has("expired")) show("Phiên đăng nhập đã hết hạn hoặc bị thu hồi, vui lòng đăng nhập lại.", true);
  if (params.has("locked")) show("Tài khoản đã bị khóa. Liên hệ quản trị viên.", true);

  const s = Session.get();
  if (s && s.token && !params.has("expired") && !params.has("locked")) {
    api("auth", "/api/users/me", { auth: true }).then(u => { location.href = HOME[u.role]; })
      .catch(e => { if (e.status >= 400 && e.status < 500) Session.clear(); });   // lỗi mạng / 5xx: giữ phiên
  }
  const TITLES = { login: ["Chào bạn", "Đăng nhập bằng email đã đăng ký"], sinh_vien: ["Tạo tài khoản sinh viên", "Mất chưa tới một phút"],
                   chu_quan: ["Mở quán trên TDTU Food", "Tạo tài khoản chủ quán, sau đó gửi thông tin quán để được duyệt"] };
  let banksLoaded = false;
  const tab = reg => {
    $("#tLogin").classList.toggle("on", !reg); $("#tReg").classList.toggle("on", reg);
    $("#fLogin").classList.toggle("hidden", reg); $("#fReg").classList.toggle("hidden", !reg); show("");
    const [t, sub] = TITLES[reg ? $("#rRole").value : "login"] || TITLES.login;
    $("#authTitle").textContent = t; $("#authTitle").nextElementSibling.textContent = sub;
    // chủ quán: bắt buộc khai báo tài khoản nhận tiền (mã VietQR của quán tạo từ đây)
    const owner = reg && $("#rRole").value === "chu_quan";
    $("#rBank").classList.toggle("hidden", !owner);
    if (owner && !banksLoaded) {
      banksLoaded = true;
      fillBankSelect($("#rBankBin")).catch(e => { banksLoaded = false; show("Không tải được danh sách ngân hàng: " + e.message, true); });
    }
  };
  $("#rBankAcc").oninput = e => { const v = e.target.value.replace(/\D/g, ""); if (v !== e.target.value) e.target.value = v; };
  $("#rBankHolder").onblur = e => { e.target.value = toHolder(e.target.value); };
  /** Mở form theo vai trò ("login" | "sinh_vien" | "chu_quan") và cuộn tới khung đăng nhập. */
  const open = (role, byClick) => {
    if (role !== "login") $("#rRole").value = role;
    tab(role !== "login");
    $("#dang-nhap").scrollIntoView({ behavior: byClick && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "auto", block: "start" });
    if (byClick) (role === "login" ? $("#lEmail") : $("#rName")).focus({ preventScroll: true });   // mở từ QR: không bật bàn phím ngay
  };
  const nav = document.querySelector(".site-head nav");
  if (nav) nav.insertBefore(installButton("btn sm"), nav.querySelector("[data-open=login]"));
  $("#tLogin").onclick = () => tab(false);
  $("#tReg").onclick = () => tab(true);
  $("#rRole").onchange = () => tab(true);
  document.querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); open(a.dataset.open, true); });
  const fromQr = new Map([["sinh-vien", "sinh_vien"], ["chu-quan", "chu_quan"]]).get(params.get("dang-ky"));
  if (fromQr) open(fromQr, false);

  async function doLogin(email, password, btn) {
    const r = await act(btn, () => api("auth", "/api/users/login", { method: "POST", auth: false, body: { email, password } }));
    Session.set({ token: r.access_token, user: r.user, exp: Date.now() + r.expires_in * 1000 });
    location.href = HOME[r.user.role];
  }
  $("#fLogin").onsubmit = e => {
    e.preventDefault();
    const email = $("#lEmail").value.trim(), pw = $("#lPw").value;
    if (!email || !pw) return show("Nhập email và mật khẩu", true);
    doLogin(email, pw, e.submitter).catch(err => show(err.message, true));
  };
  $("#fReg").onsubmit = async e => {
    e.preventDefault();
    if (!$("#rTerms").checked) return show("Bạn cần đồng ý Điều khoản sử dụng và Chính sách quyền riêng tư để tạo tài khoản", true);
    const body = { name: $("#rName").value.trim(), email: $("#rEmail").value.trim(), password: $("#rPw").value,
                   role: $("#rRole").value, accept_terms: true };
    if ($("#rPhone").value.trim()) body.phone = $("#rPhone").value.trim();
    if (body.role === "chu_quan") {
      const holder = toHolder($("#rBankHolder").value);
      $("#rBankHolder").value = holder;
      if (!$("#rBankBin").value) { $("#rBankBin").focus(); return show("Chọn ngân hàng nhận tiền của quán", true); }
      if (!/^\d{6,19}$/.test($("#rBankAcc").value)) { $("#rBankAcc").focus(); return show("Số tài khoản gồm 6-19 chữ số", true); }
      if (holder.length < 2) { $("#rBankHolder").focus(); return show("Nhập tên chủ tài khoản", true); }
      Object.assign(body, { bank_bin: $("#rBankBin").value, bank_account: $("#rBankAcc").value, bank_holder: holder });
    }
    try {
      await act(e.submitter, () => api("auth", "/api/users/register", { method: "POST", auth: false, body }));
      try { localStorage.setItem("tdtu_welcome", "1"); } catch (err) { /* không có bộ nhớ: bỏ qua hướng dẫn */ }
      await doLogin(body.email, body.password, null);
    } catch (err) { show(err.message, true); }
  };
  document.querySelectorAll(".demo button").forEach(b => b.onclick = () => {
    tab(false); $("#lEmail").value = b.dataset.e; $("#lPw").value = b.dataset.p;
  });

  // Bảng tin món mới + dải tin chạy ngang (cùng dữ liệu; dải tin chỉ để thu hút nên ẩn với trình đọc màn hình)
  menuBoard($("#board"), { limit: 8 }).then(items => {
    if (!items.length) return;
    const line = items.map(u => h("span", { class: "tk-item" },
      h("span", { class: "tk-kind " + u.kind }, UPDATE_KIND[u.kind] || u.kind),
      h("strong", null, u.item_name), h("span", { class: "tk-price" }, money(u.price)), h("span", { class: "tk-rest" }, u.restaurant_name)));
    const track = $("#ticker .ticker-track");
    mount(track, line, line.map(n => n.cloneNode(true)));      // lặp 2 lần để chạy liền mạch
    $("#ticker").classList.remove("hidden");
  });
})();
