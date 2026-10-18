/* Thanh toán trước bằng VietQR: sinh viên chuyển khoản thẳng vào tài khoản ngân hàng của chủ quán (TDTU Food không giữ
   tiền), chủ quán thấy tiền vào thì bấm "Đã nhận tiền" và đơn mới vào bếp. Dùng chung cho form đăng ký, trang sinh viên,
   chủ quán, admin. Mã QR do máy chủ giao diện tạo ở /qr/vietqr.svg|png từ thông tin tài khoản chụp vào đơn lúc đặt. */
"use strict";

Object.assign(ICONS, {
  bank: '<path d="M3 21h18"/><path d="M4 10h16"/><path d="M12 3 4 7.5V10h16V7.5z"/><path d="M6 10v8M10 10v8M14 10v8M18 10v8"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
});

const PAY_STATUS = {
  unpaid: ["Chờ thanh toán", "b-warn"], claimed: ["Đã báo chuyển khoản", "b-info"], paid: ["Đã thanh toán", "b-ok"],
  void: ["Đã bỏ đơn", "b-muted"], failed: ["Quán chưa nhận được tiền", "b-bad"], expired: ["Quá hạn thanh toán", "b-muted"],
  refund_due: ["Chờ hoàn tiền", "b-warn"], refunded: ["Đã hoàn tiền", "b-ok"],
};
STATUS.he_thong = ["Hệ thống", "b-muted"];          // đơn quá hạn thanh toán do hệ thống tự hủy

const payOf = o => (o && o.payment && o.payment.status) || "paid";      // đơn trước khi có thanh toán trước = đã trả
const isAwaitingPay = o => o.status === "pending" && ["unpaid", "claimed"].includes(payOf(o));
const isPlaced = o => ["paid", "refund_due", "refunded"].includes(payOf(o));

function payBadge(o) {
  const [label, cls] = PAY_STATUS[payOf(o)] || [payOf(o), "b-muted"];
  return h("span", { class: "badge " + cls }, label);
}
/** Nhãn trạng thái của đơn: đang ở bước thanh toán thì hiện bước đó thay cho "Chờ xác nhận". */
function orderBadge(o) {
  if (isAwaitingPay(o)) return payBadge(o);
  const extra = ["refund_due", "refunded"].includes(payOf(o)) ? payBadge(o) : null;
  return extra ? [badge(o.status), " ", extra] : badge(o.status);
}

/** Tài khoản demo do seed tạo: cảnh báo không chuyển tiền thật. */
const isDemoAccount = holder => /\bDEMO\b/.test(holder || "");
const maskAccount = acc => acc ? "•••" + String(acc).slice(-4) : "";

/** Đường dẫn ảnh mã VietQR (cùng máy chủ giao diện). Không có số tiền: mã nhận tiền chung của quán. */
function vietqrUrl({ bin, account, amount, note }, fmt = "svg") {
  const q = new URLSearchParams({ bin, acc: account });
  if (amount) q.set("amount", String(amount));
  if (note) q.set("note", note);
  return `qr/vietqr.${fmt}?${q}`;
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {                                      // trình duyệt cũ / không cho dùng clipboard: chọn chữ rồi chép
    const t = h("textarea", { readonly: true, class: "copy-buffer" });
    t.value = text;
    document.body.append(t);
    t.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    t.remove();
    if (!ok) return toast(`Không sao chép được, hãy chép tay: ${text}`, true);
  }
  toast("Đã sao chép " + label);
}

/** Một dòng thông tin chuyển khoản, có nút Chép nếu copyAs (giá trị chép có thể khác chữ hiển thị). */
function payRow(label, shown, copyAs, copyLabel) {
  return h("div", { class: "pay-row" }, h("span", { class: "pay-k" }, label), h("strong", { class: "pay-v" }, shown),
    copyAs ? h("button", { type: "button", class: "sm pay-copy", "aria-label": `Sao chép ${copyLabel}`,
      onclick: () => copyText(String(copyAs), copyLabel) }, icon("copy"), h("span", { class: "pay-copy-text" }, "Chép")) : null);
}

/** Đếm ngược tới hạn thanh toán; tự dừng khi phần tử bị gỡ khỏi trang. */
function countdown(deadline, onEnd) {
  const el = h("span", { class: "pay-timer", role: "timer" });
  const end = new Date(deadline).getTime();
  let timer = null;
  const tick = () => {
    if (timer && !el.isConnected) return clearInterval(timer);
    const left = Math.max(0, end - Date.now());
    const m = Math.floor(left / 60000), s = Math.floor(left / 1000) % 60;
    el.textContent = `${m}:${String(s).padStart(2, "0")}`;
    el.classList.toggle("late", left < 120000);
    if (!left) { clearInterval(timer); if (onEnd) onEnd(); }
  };
  tick();
  timer = setInterval(tick, 1000);
  return el;
}

// ------------------------------------------------------------ ngân hàng (form đăng ký chủ quán, Profile)
let banksPromise = null;
function loadBanks() {
  banksPromise = banksPromise || api("auth", "/api/banks", { auth: false }).catch(e => { banksPromise = null; throw e; });
  return banksPromise;
}
async function fillBankSelect(select, current) {
  const banks = await loadBanks();
  mount(select, h("option", { value: "" }, "Chọn ngân hàng"),
    banks.map(b => h("option", { value: b.bin, selected: b.bin === current }, `${b.name} (${b.code})`)));
}
/** Tên chủ tài khoản như app ngân hàng hiện: in hoa, không dấu ("Trần Thị Bé" -> "TRAN THI BE"). */
const toHolder = s => String(s || "").replace(/đ/g, "d").replace(/Đ/g, "D").normalize("NFD").replace(/[̀-ͯ]/g, "")
  .toUpperCase().replace(/[^A-Z ]/g, "").replace(/\s+/g, " ").trim();

/** 3 ô ngân hàng / số tài khoản / tên chủ tài khoản; trả về { nodes, read() } (read() báo lỗi bằng toast, trả null). */
function bankFields(current = {}) {
  const sel = h("select", { "aria-label": "Ngân hàng" }, h("option", { value: "" }, "Đang tải danh sách ngân hàng…"));
  fillBankSelect(sel, current.bank_bin).catch(e => mount(sel, h("option", { value: "" }, "Không tải được danh sách: " + e.message)));
  const acc = h("input", { inputmode: "numeric", maxlength: 19, autocomplete: "off", placeholder: "Chỉ gồm chữ số",
    value: current.bank_account || "" });
  const holder = h("input", { maxlength: 60, autocomplete: "off", placeholder: "VD: NGUYEN VAN AN", value: current.bank_holder || "" });
  acc.oninput = () => { const v = acc.value.replace(/\D/g, ""); if (v !== acc.value) acc.value = v; };
  holder.onblur = () => { holder.value = toHolder(holder.value); };
  const read = () => {
    holder.value = toHolder(holder.value);
    if (!sel.value) { toast("Chọn ngân hàng nhận tiền", true); sel.focus(); return null; }
    if (!/^\d{6,19}$/.test(acc.value)) { toast("Số tài khoản gồm 6-19 chữ số", true); acc.focus(); return null; }
    if (holder.value.length < 2) { toast("Nhập tên chủ tài khoản (như in trong app ngân hàng)", true); holder.focus(); return null; }
    return { bank_bin: sel.value, bank_account: acc.value, bank_holder: holder.value };
  };
  return { sel, acc, holder, read, nodes: [field("Ngân hàng", sel), field("Số tài khoản", acc),
    field("Tên chủ tài khoản", holder, "In hoa không dấu, đúng như app ngân hàng hiện khi chuyển tiền")] };
}

// ------------------------------------------------------------ chủ quán: tài khoản nhận tiền
/** Đổi tài khoản nhận tiền (cần mật khẩu). Đơn đã đặt giữ tài khoản cũ, đơn mới dùng tài khoản này. */
function payoutDialog(me, after) {
  const f = bankFields(me);
  const pw = h("input", { type: "password", autocomplete: "current-password" });
  return dialog(me.bank_account ? "Đổi tài khoản nhận tiền" : "Khai báo tài khoản nhận tiền", [
    h("p", { class: "small muted" }, "Sinh viên quét mã VietQR để chuyển tiền thẳng vào tài khoản này trước khi đơn được gửi tới quán. ",
      "TDTU Food không giữ tiền và không thu phí."),
    ...f.nodes, field("Mật khẩu đăng nhập", pw, "Nhập lại mật khẩu để xác nhận đổi nơi nhận tiền")],
  [{ label: "Hủy", value: false }, { label: "Lưu", class: "primary", run: async () => {
    const body = f.read();
    if (!body) return false;
    if (!pw.value) { toast("Nhập mật khẩu để xác nhận", true); pw.focus(); return false; }
    const u = await api("auth", "/api/users/me/payout", { method: "PUT", body: { ...body, password: pw.value } });
    toast("Đã lưu tài khoản nhận tiền");
    if (after) after(u);
  } }]);
}

/** Mã QR nhận tiền chung của quán (không kèm số tiền): in dán ở quầy nếu muốn. */
function payoutQrDialog(me) {
  const p = { bin: me.bank_bin, account: me.bank_account };
  dialog("Mã QR nhận tiền của quán", [
    h("div", { class: "pay-qr" }, h("img", { src: vietqrUrl(p), width: 220, height: 220,
      alt: `Mã VietQR nhận tiền: ${me.bank_name || ""} ${me.bank_account}` })),
    h("div", { class: "pay-info" }, payRow("Ngân hàng", me.bank_name || me.bank_bin),
      payRow("Số tài khoản", me.bank_account, me.bank_account, "số tài khoản"), payRow("Chủ tài khoản", me.bank_holder || "")),
    h("p", { class: "small muted" }, "Đơn đặt trên app có mã QR riêng kèm số tiền và nội dung chuyển khoản; mã này dùng khi khách trả tại quầy."),
  ], [{ label: "Đóng" }, { label: "Tải ảnh PNG", class: "primary", run: () => {
    const a = h("a", { href: vietqrUrl(p, "png"), download: "tdtu-food-qr-nhan-tien.png" });
    document.body.append(a); a.click(); a.remove();
  } }]);
}

/** Thông báo đầu trang khi chủ quán chưa có tài khoản nhận tiền: sinh viên chưa đặt được món. */
function payoutMissingBanner(me, after) {
  if (!me || me.bank_account) return null;
  return h("div", { class: "notice warn payout-warn" }, h("strong", null, "Chưa có tài khoản nhận tiền. "),
    "Sinh viên phải thanh toán trước nên hiện chưa đặt được món ở quán của bạn. ",
    h("button", { type: "button", class: "sm primary", onclick: () => payoutDialog(me, after) }, "Khai báo ngay"));
}

// ------------------------------------------------------------ sinh viên: trang thanh toán của một đơn
const PAY_REFRESH_MS = 5000;

/** #pay/<mã đơn>: mã VietQR + thông tin chuyển khoản -> "Tôi đã chuyển khoản" -> chờ quán xác nhận -> đặt thành công. */
function studentPayPage(main, oid) {
  const box = h("div", { class: "pay-page" });
  mount(main, h("div", { class: "row", style: "margin-bottom:12px" }, h("a", { href: "#orders" }, "‹ Đơn của tôi")), box);
  let lastSig = null, timer = null;
  const show = o => {
    const sig = o.status + payOf(o);
    if (sig === lastSig) return;
    lastSig = sig;
    mount(box, payCard(o, show));
  };
  const refresh = async () => {
    if (!box.isConnected) return clearInterval(timer);
    try { show(await api("order", `/api/orders/${oid}`)); } catch (e) { /* mạng chập chờn: lần sau thử lại */ }
  };
  load(box, async () => {
    show(await api("order", `/api/orders/${oid}`));
    timer = setInterval(refresh, PAY_REFRESH_MS);
  });
}

function payCard(o, show) {
  const p = o.payment || {};
  const st = payOf(o);
  const head = (title, sub) => h("header", { class: "pay-head" }, h("h1", null, title),
    h("div", { class: "small muted" }, o.restaurant_name, " · đơn ", h("span", { class: "mono" }, orderCode(o)), sub ? [" · ", sub] : null));
  const backToShop = h("a", { class: "btn", href: "#restaurants/" + o.restaurant_id }, "Về quán");

  if (st === "unpaid" && o.status === "pending") {
    const claim = h("button", { type: "button", class: "primary pay-claim" }, icon("check"), "Tôi đã chuyển khoản");
    claim.onclick = () => act(claim, () => api("order", `/api/orders/${o.id}/payment/claim`, { method: "POST" }),
      "Đã báo quán. Chờ quán kiểm tra tài khoản").then(show)
      .catch(e => { if (e.code === "PAYMENT_STATE") api("order", `/api/orders/${o.id}`).then(show).catch(() => {}); });
    const drop = h("button", { type: "button", class: "ghost danger-text sm" }, "Bỏ đơn");
    drop.onclick = async () => {
      if (!await confirmBox("Bỏ đơn chưa thanh toán?", "Đơn sẽ bị hủy. Nếu bạn ĐÃ chuyển tiền thì đừng bỏ đơn, hãy bấm \"Tôi đã chuyển khoản\".",
        "Bỏ đơn", true)) return;
      act(drop, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH",
        body: { status: "cancelled", reason: "Sinh viên bỏ đơn chưa thanh toán" } }), "Đã bỏ đơn").then(show).catch(() => {});
    };
    const qr = { bin: p.bank_bin, account: p.account, amount: p.amount, note: p.note };
    return h("article", { class: "card pay-card" },
      head("Thanh toán để đặt món"),
      h("div", { class: "pay-amount" }, h("span", { class: "small" }, "Số tiền cần chuyển"), h("strong", null, money(p.amount)),
        h("span", { class: "pay-deadline" }, icon("clock"), "Còn ", countdown(p.deadline, () => setTimeout(() =>
          api("order", `/api/orders/${o.id}`).then(show).catch(() => {}), 65000)))),     // hệ thống quét hạn mỗi phút
      isDemoAccount(p.holder) ? h("div", { class: "notice warn" }, "Tài khoản DEMO dùng để chạy thử: đừng chuyển tiền thật. ",
        "Bấm \"Tôi đã chuyển khoản\" để thử tiếp luồng đặt món.") : null,
      h("div", { class: "pay-qr" },
        h("img", { src: vietqrUrl(qr), width: 232, height: 232, alt: `Mã VietQR chuyển ${money(p.amount)} tới ${p.bank_name} ${p.account}` }),
        h("a", { class: "btn sm", href: vietqrUrl(qr, "png"), download: `tdtu-food-${o.pickup_code || "don"}.png` }, icon("download"), "Lưu ảnh mã QR")),
      h("ol", { class: "pay-steps" },
        h("li", null, "Mở app ngân hàng hoặc ví (MoMo, ZaloPay…), chọn ", h("strong", null, "Quét mã QR"),
          ". Dùng một điện thoại: lưu ảnh mã QR rồi chọn ảnh từ thư viện."),
        h("li", null, "Kiểm tra đúng số tiền và nội dung chuyển khoản, rồi chuyển."),
        h("li", null, "Quay lại đây, bấm ", h("strong", null, "Tôi đã chuyển khoản"), ". Quán thấy tiền vào là đơn được gửi vào bếp.")),
      h("div", { class: "pay-info" },
        payRow("Ngân hàng", p.bank_name || p.bank_bin),
        payRow("Số tài khoản", p.account, p.account, "số tài khoản"),
        payRow("Chủ tài khoản", p.holder || ""),
        payRow("Số tiền", money(p.amount), p.amount, "số tiền"),
        payRow("Nội dung", h("span", { class: "mono" }, p.note), p.note, "nội dung chuyển khoản")),
      h("p", { class: "small muted pay-trust" }, icon("shield"),
        "Tiền chuyển thẳng vào tài khoản của quán, TDTU Food không giữ tiền. Chưa chuyển xong trong thời hạn thì đơn tự hủy."),
      h("footer", { class: "pay-actions" }, drop, claim));
  }

  if (st === "claimed" && o.status === "pending") {
    return h("article", { class: "card pay-card pay-wait" },
      h("div", { class: "pay-state" }, h("span", { class: "spinner" })),
      head("Chờ quán xác nhận đã nhận tiền"),
      h("p", null, "Quán đang kiểm tra tài khoản ngân hàng, thường chỉ 1-2 phút. Trang tự cập nhật; bạn có thể rời trang, có thông báo khi xong."),
      h("div", { class: "pay-info" }, payRow("Số tiền", money(p.amount)), payRow("Nội dung", h("span", { class: "mono" }, p.note)),
        payRow("Vào tài khoản", `${p.bank_name || ""} ${maskAccount(p.account)}`)),
      h("p", { class: "small muted" }, "Chờ lâu mà chưa thấy? Gọi quán hoặc liên hệ ban quản trị (Profile → Liên hệ hỗ trợ)."));
  }

  if (o.status !== "cancelled") {                    // đã thanh toán: đơn đặt thành công
    return h("article", { class: "card pay-card pay-ok" },
      h("div", { class: "pay-state ok" }, icon("check")),
      head("Đặt món thành công!"),
      o.pickup_code ? h("div", { class: "pickup-box" }, h("div", { class: "pickup-label" }, "Mã nhận món"), pickupCodeEl(o.pickup_code, "lg"),
        h("p", { class: "pickup-hint" }, o.delivery_address === PICKUP_AT_SHOP ? "Tới quầy, đọc 3 số này để nhận món."
          : `Quán mang tới ${o.delivery_address}. Đọc mã này khi nhận món.`)) : null,
      h("p", { class: "small muted" }, "Quán đã nhận ", money(p.amount || o.total_price), ". Bạn sẽ có thông báo khi quán bắt đầu làm món."),
      h("footer", { class: "pay-actions" }, backToShop, h("a", { class: "btn primary", href: "#orders" }, "Xem đơn của tôi")));
  }

  const why = {
    failed: "Quán chưa nhận được tiền chuyển khoản nên đơn đã bị hủy. Nếu bạn đã chuyển, hãy liên hệ quán kèm ảnh chụp giao dịch.",
    expired: "Đơn đã quá hạn thanh toán nên tự hủy. Nếu bạn đã chuyển tiền, hãy liên hệ quán để được hoàn lại.",
    void: "Bạn đã bỏ đơn này.",
    refund_due: "Đơn đã bị hủy sau khi bạn thanh toán. Quán sẽ chuyển trả tiền cho bạn.",
    refunded: "Đơn đã bị hủy và quán đã hoàn tiền cho bạn.",
  }[st] || "Đơn đã bị hủy.";
  return h("article", { class: "card pay-card pay-off" },
    head("Đơn đã hủy", payBadge(o)), h("p", null, why),
    o.cancel_reason ? h("p", { class: "small" }, "Lý do: " + o.cancel_reason) : null,
    h("footer", { class: "pay-actions" }, h("a", { class: "btn", href: "#orders" }, "Đơn của tôi"), backToShop));
}
