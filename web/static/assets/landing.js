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
  let otpTimer = null;
  const stopTimer = () => { if (otpTimer) { clearInterval(otpTimer); otpTimer = null; } };
  const tab = reg => {
    stopTimer(); $("#fOtp").classList.add("hidden");
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

  const signedIn = r => {
    Session.set({ token: r.access_token, user: r.user, exp: Date.now() + r.expires_in * 1000 });
    location.href = HOME[r.user.role];
  };
  async function doLogin(email, password, btn) {
    signedIn(await act(btn, () => api("auth", "/api/users/login", { method: "POST", auth: false, body: { email, password } })));
  }

  // ---------------- Xác nhận email bằng mã OTP 6 số (đăng ký xong, hoặc đăng nhập khi chưa xác nhận)
  /** Đếm ngược nút "Gửi lại mã": hết giờ mới bấm được (server vẫn kiểm tra lại và trả retry_after nếu quá sớm). */
  const countdown = seconds => {
    stopTimer();
    const btn = $("#oResend");
    let left = Math.max(0, Math.round(Number(seconds) || 0));
    const paint = () => { btn.disabled = left > 0; btn.textContent = left > 0 ? `Gửi lại mã (${left}s)` : "Gửi lại mã"; };
    paint();
    if (left > 0) otpTimer = setInterval(() => { left -= 1; paint(); if (left <= 0) stopTimer(); }, 1000);
  };
  /** Hiện form nhập mã. sent: true / false (gửi email lỗi) / null (đến từ đăng nhập, không biết lúc gửi). */
  function showOtp(email, sent, resendAfter) {
    $("#fLogin").classList.add("hidden"); $("#fReg").classList.add("hidden"); $("#fOtp").classList.remove("hidden");
    $("#tLogin").classList.remove("on"); $("#tReg").classList.remove("on");
    $("#authTitle").textContent = "Xác nhận email";
    $("#authTitle").nextElementSibling.textContent = "Nhập mã 6 số TDTU Food vừa gửi tới email của bạn";
    $("#oEmail").value = email; $("#oCode").value = "";
    if (sent === true) show("Đã gửi mã xác nhận tới " + email + ". Mã có hiệu lực 5 phút, kiểm tra cả thư mục Spam.");
    else if (sent === false) show("Tài khoản đã tạo nhưng chưa gửi được email xác nhận. Chờ hết giờ rồi bấm Gửi lại mã.", true);
    else show("Email chưa được xác nhận. Nhập mã đã gửi tới email, hoặc bấm Gửi lại mã để nhận mã mới.", true);
    countdown(resendAfter);
    $("#oCode").focus();
  }
  $("#oCode").oninput = e => { const v = e.target.value.replace(/\D/g, "").slice(0, 6); if (v !== e.target.value) e.target.value = v; };
  $("#fOtp").onsubmit = async e => {
    e.preventDefault();
    const email = $("#oEmail").value.trim(), code = $("#oCode").value.trim();
    if (!/^\d{6}$/.test(code)) { $("#oCode").focus(); return show("Nhập đủ 6 chữ số của mã xác nhận", true); }
    try {
      signedIn(await act(e.submitter, () => api("auth", "/api/users/verify-otp", { method: "POST", auth: false, body: { email, code } })));
    } catch (err) {
      if (err.code === "ALREADY_VERIFIED") { tab(false); $("#lEmail").value = email; return show(err.message); }
      show(err.message, true);                      // vd "Mã xác nhận không đúng, còn 3 lần thử"
      $("#oCode").select();
    }
  };
  $("#oResend").onclick = async e => {
    const email = $("#oEmail").value.trim();
    try {
      const r = await act(e.currentTarget, () => api("auth", "/api/users/resend-otp", { method: "POST", auth: false, body: { email } }));
      show(r.otp_sent ? "Đã gửi mã mới tới " + email + ". Mã cũ không còn dùng được." : r.detail, !r.otp_sent);
      countdown(r.resend_after);
      $("#oCode").value = ""; $("#oCode").focus();
    } catch (err) {
      show(err.message, true);
      if (err.body && err.body.retry_after) countdown(err.body.retry_after);
    }
  };
  $("#oBack").onclick = () => { const email = $("#oEmail").value; tab(false); $("#lEmail").value = email; $("#lPw").focus(); };

  $("#fLogin").onsubmit = e => {
    e.preventDefault();
    const email = $("#lEmail").value.trim(), pw = $("#lPw").value;
    if (!email || !pw) return show("Nhập email và mật khẩu", true);
    doLogin(email, pw, e.submitter).catch(err => {
      if (err.code === "EMAIL_NOT_VERIFIED") return showOtp((err.body && err.body.email) || email, null, 0);
      show(err.message, true);
    });
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
      const u = await act(e.submitter, () => api("auth", "/api/users/register", { method: "POST", auth: false, body }));
      try { localStorage.setItem("tdtu_welcome", "1"); } catch (err) { /* không có bộ nhớ: bỏ qua hướng dẫn */ }
      if (u.verification_required) return showOtp(u.email, u.otp_sent, u.resend_after);   // bật OTP: nhập mã rồi mới vào
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
