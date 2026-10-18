/* Giao diện chủ quán (theo mô hình GrabMerchant / beFood Merchant): đơn hàng, tổng quan doanh thu,
   thực đơn có ảnh và danh mục, hồ sơ cửa hàng, đánh giá; thông báo và hồ sơ cá nhân mở từ thanh trên. */
"use strict";
(() => {
  const session = requireRole("chu_quan");
  if (!session) return;
  let ui, baseTitle;
  let stores = [];                                   // quán của tôi (tải lại khi vào mỗi trang)
  let pageTimer = null;                              // làm mới định kỳ của trang đang mở
  let navSeq = 0;                                    // tăng mỗi lần vẽ trang; trang cũ tải xong muộn thì bỏ
  let dashDays = 7;
  /** Bắt đầu vẽ một trang: dừng làm mới của trang trước, trả về số thứ tự để kiểm tra trang còn hiện không. */
  function startPage() { clearInterval(pageTimer); pageTimer = null; return ++navSeq; }
  const stale = seq => seq !== navSeq;

  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* bỏ qua */ } },
  };
  let rid = ls.get("tdtu_owner_rid") || "";          // quán đang chọn; "" = tất cả quán

  Object.assign(ICONS, {
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
  });

  // ============================================================ quán của tôi, chọn quán
  async function loadStores() {
    stores = await api("restaurant", "/api/restaurants/mine");
    if (rid && !stores.some(r => r.id === rid)) rid = "";
    return stores;
  }
  const storeOf = id => stores.find(r => r.id === id) || null;
  /** Trang cần đúng một quán (thực đơn, cửa hàng): đang chọn "Tất cả" thì lấy quán đầu tiên. */
  const oneStore = () => storeOf(rid) || stores[0] || null;
  const choose = id => { rid = id; ls.set("tdtu_owner_rid", id); };

  function pickStore(allowAll, onChange) {
    if (stores.length < 2) return null;
    const cur = allowAll ? rid : oneStore().id;
    return h("select", { class: "store-pick", "aria-label": "Chọn quán", onchange: e => { choose(e.target.value); onChange(); } },
      allowAll ? h("option", { value: "", selected: !cur }, "Tất cả quán") : null,
      stores.map(r => h("option", { value: r.id, selected: r.id === cur }, r.name)));
  }

  /** Chủ quán mới chưa có quán: hướng dẫn 3 bước mở quán. */
  function welcome() {
    return h("section", { class: "card welcome" },
      h("h1", null, `Chào ${session.user.name}!`),
      h("p", { class: "muted" }, "Mở quán trên TDTU Food để nhận đơn đặt trước từ sinh viên quanh trường."),
      h("ol", { class: "steps" },
        h("li", null, "Gửi thông tin quán: tên, địa chỉ, giờ mở cửa và ảnh bìa."),
        h("li", null, "Thêm món kèm giá, ảnh và danh mục."),
        h("li", null, "Ban quản trị duyệt quán, sau đó bạn bắt đầu nhận đơn.")),
      h("a", { class: "btn hot", href: "#store/new" }, "Tạo quán của bạn"));
  }

  // ============================================================ thành phần dùng chung
  /** Công tắc bật/tắt (role=switch). onChange(trạng thái mới) có thể là async. */
  function toggle(on, text, onChange, ariaLabel) {
    const btn = h("button", { type: "button", class: "switch" + (on ? " on" : ""), role: "switch", "aria-checked": String(on),
      "aria-label": ariaLabel || null,
      onclick: async () => { btn.disabled = true; try { await onChange(!on); } catch (e) { /* đã báo lỗi */ } finally { btn.disabled = false; } } },
    h("span", { class: "knob", "aria-hidden": "true" }), h("span", { class: "switch-label" }, text));
    return btn;
  }

  /** Ô nhập giá có dấu chấm ngăn cách hàng nghìn; value() trả về số nguyên hoặc NaN. */
  function priceInput(v) {
    const el = h("input", { inputmode: "numeric", autocomplete: "off", placeholder: "VD: 35.000", "aria-label": "Giá bán (đồng)",
      value: Number.isInteger(v) ? v.toLocaleString("vi-VN") : "" });
    el.oninput = () => {
      const d = el.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "").slice(0, 9);
      el.value = d ? Number(d).toLocaleString("vi-VN") : "";
    };
    return { el, value: () => { const d = el.value.replace(/\D/g, ""); return d ? Number(d) : NaN; } };
  }

  /** Thu nhỏ ảnh ngay trên trình duyệt (cạnh dài <= maxSide) và chuyển sang JPEG trước khi tải lên. */
  async function shrinkImage(file, maxSide) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw new Error("Chỉ nhận ảnh JPG, PNG hoặc WebP");
    let bmp;
    try { bmp = await createImageBitmap(file); } catch (e) { throw new Error("Không đọc được ảnh này, hãy chọn ảnh khác"); }
    const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k));
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);          // ảnh PNG trong suốt -> nền trắng
    g.drawImage(bmp, 0, 0, c.width, c.height);
    if (bmp.close) bmp.close();
    const blob = await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.85));
    if (!blob) throw new Error("Không xử lý được ảnh này");
    if (blob.size > 2 * 1024 * 1024) throw new Error("Ảnh vẫn lớn hơn 2 MB sau khi nén, hãy chọn ảnh khác");
    return blob;
  }

  /**
   * Ô chọn ảnh: bấm hoặc kéo thả, xem trước, gỡ ảnh. value() tải ảnh mới lên Restaurant Service (nếu có) và trả về
   * image_url; changed() cho biết ảnh có đổi không; onChange(src) báo ảnh xem trước để cập nhật bản xem trước khác.
   */
  function imagePicker({ url, wide, maxSide, label, onChange, onManual }) {
    let current = url || null, pending = null, preview = null;
    const img = h("img", { alt: "" });
    const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "hidden", "aria-label": label });
    const err = h("div", { class: "small field-error", role: "alert" });
    const removeBtn = h("button", { type: "button", class: "sm ghost" }, "Gỡ ảnh");
    const box = h("div", { class: "dropzone" + (wide ? " wide" : ""), tabindex: 0, role: "button", "aria-label": label + ": chọn ảnh" },
      img, h("div", { class: "dz-empty" }, icon("image"), h("strong", null, "Chọn ảnh"), h("span", { class: "small" }, "hoặc kéo thả vào đây")),
      h("span", { class: "dz-change" }, "Đổi ảnh"));
    const src = () => preview || imageSrc(current);
    const render = () => {
      const s = src();
      box.classList.toggle("has-img", !!s);
      if (s) img.src = s; else img.removeAttribute("src");
      removeBtn.classList.toggle("hidden", !s);
      if (onChange) onChange(s);
    };
    const useBlob = blob => {
      pending = blob;
      if (preview) URL.revokeObjectURL(preview);
      preview = URL.createObjectURL(blob);
      render();
    };
    const take = async file => {
      err.textContent = "";
      try {
        useBlob(await shrinkImage(file, maxSide));
        if (onManual) onManual();
      } catch (e) { err.textContent = e.message; }
    };
    input.onchange = () => { if (input.files[0]) take(input.files[0]); input.value = ""; };
    box.onclick = () => input.click();
    box.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
    box.ondragover = e => { e.preventDefault(); box.classList.add("over"); };
    box.ondragleave = () => box.classList.remove("over");
    box.ondrop = e => { e.preventDefault(); box.classList.remove("over"); if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0]); };
    removeBtn.onclick = () => {
      pending = null; current = null; if (preview) URL.revokeObjectURL(preview); preview = null; render();
      if (onManual) onManual();
    };
    render();
    return {
      el: h("div", { class: "image-picker" }, box, input,
        h("div", { class: "row", style: "justify-content:space-between;min-height:30px" },
          h("span", { class: "small muted" }, "JPG, PNG, WebP; ảnh được tự thu nhỏ trước khi tải lên"), removeBtn), err),
      changed: () => pending !== null || current !== (url || null),
      setBlob: blob => { err.textContent = ""; useBlob(blob); },
      async value() {
        if (pending) {
          const r = await api("restaurant", "/api/uploads", { method: "POST", raw: pending });
          current = r.url; pending = null;
        }
        return current;
      },
    };
  }

  // ============================================================ âm báo + theo dõi đơn mới (chạy nền)
  const soundOn = () => ls.get("tdtu_owner_sound") !== "off";
  let audio = null;
  const audioReady = () => !!audio && audio.state === "running";
  function unlockAudio() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === "suspended") audio.resume().catch(() => {});
    } catch (e) { /* trình duyệt không hỗ trợ âm thanh */ }
  }
  document.addEventListener("pointerdown", unlockAudio, { once: true, capture: true });
  document.addEventListener("keydown", unlockAudio, { once: true, capture: true });
  function ding() {
    try {
      unlockAudio();
      if (!audioReady()) return;
      const t = audio.currentTime, o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(880, t); o.frequency.setValueAtTime(1320, t + 0.16);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
      o.connect(g).connect(audio.destination); o.start(t); o.stop(t + 0.6);
    } catch (e) { /* trình duyệt không hỗ trợ âm thanh */ }
  }
  function soundButton() {
    const btn = h("button", { type: "button", class: "sm", "aria-pressed": String(soundOn()) });
    const paint = () => {
      btn.replaceChildren(icon("notifications"), !soundOn() ? "Âm báo đơn mới: tắt" : audioReady() ? "Âm báo đơn mới: bật" : "Bấm để bật âm báo");
      btn.setAttribute("aria-pressed", String(soundOn()));
    };
    btn.onclick = () => {
      if (soundOn() && !audioReady()) unlockAudio();              // lần bấm đầu: chỉ mở khóa âm thanh
      else ls.set("tdtu_owner_sound", soundOn() ? "off" : "on");
      setTimeout(() => { paint(); if (soundOn()) ding(); }, 50);
    };
    paint();
    return btn;
  }

  let knownPending = null, watching = false;
  /** Số trên tab Đơn hàng = việc cần làm: đơn sinh viên báo đã chuyển khoản (kiểm tra tiền) + đơn đã trả chờ nhận.
      Có đơn sinh viên vừa báo chuyển khoản thì kêu "ding" và hiện thông báo. */
  async function watchOrders() {
    if (watching) return;
    watching = true;
    try {
      const r = await api("order", "/api/orders/owner", { query: { status: "pending", payment_status: "claimed,paid", page_size: 50 } });
      ui.setBadge("orders", r.total);
      document.title = (r.total ? `(${r.total}) ` : "") + baseTitle;
      if (knownPending) {
        const fresh = r.items.filter(o => payOf(o) === "claimed" && !knownPending.has(o.id));
        if (fresh.length) {
          toast(fresh.length === 1 ? `Đơn mới ${orderCode(fresh[0])}: sinh viên báo đã chuyển ${money(fresh[0].total_price)}, kiểm tra tài khoản`
            : `Có ${fresh.length} đơn mới đã chuyển khoản, kiểm tra tài khoản`);
          if (soundOn()) ding();
        }
      }
      knownPending = new Set(r.items.map(o => o.id));
    } catch (e) { /* mạng chập chờn: lần sau thử lại */ } finally { watching = false; }
  }

  // ============================================================ ĐƠN HÀNG
  const ORDER_TABS = [["pay", "Chờ tiền"], ["pending", "Mới"], ["confirmed", "Đang làm"], ["completed", "Hoàn thành"],
    ["cancelled", "Đã hủy"], ["refund", "Cần hoàn tiền"]];
  /** Lọc của từng tab: "Chờ tiền" = đơn đang ở bước thanh toán; "Mới" chỉ gồm đơn đã thanh toán (đặt thành công). */
  const TAB_QUERY = { pay: { status: "pending", payment_status: "unpaid,claimed" }, pending: { status: "pending", payment_status: "paid" },
    confirmed: { status: "confirmed" }, completed: { status: "completed" }, cancelled: { status: "cancelled" },
    refund: { payment_status: "refund_due" } };

  function ordersPage(main, arg) {
    const seq = startPage();
    const status = ORDER_TABS.some(t => t[0] === arg) ? arg : "pending";
    let page = 1, lastSig = null;
    load(main, async () => {
      const [, me] = await Promise.all([loadStores(), api("auth", "/api/users/me").catch(() => null)]);
      if (stale(seq)) return;
      if (!stores.length) return mount(main, welcome());
      const seg = h("nav", { class: "seg-tabs", "aria-label": "Trạng thái đơn" });
      const list = h("div");
      mount(main, h("div", { class: "head" }, h("h1", null, "Đơn hàng"),
        h("div", { class: "row" }, pickStore(true, () => ordersPage(main, status)), soundButton())),
        payoutMissingBanner(me, () => ordersPage(main, status)), codeLookup(), seg, list);
      const draw = async () => {
        const q = { restaurant_id: rid };
        const count = key => api("order", "/api/orders/owner", { query: { ...q, ...TAB_QUERY[key], page_size: 1 } }).then(x => x.total);
        const [r, nPay, nPending, nConfirmed, nRefund] = await Promise.all([
          api("order", "/api/orders/owner", { query: { ...q, ...TAB_QUERY[status], page, page_size: 12 } }),
          count("pay"), count("pending"), count("confirmed"), count("refund")]);
        if (!r.items.length && page > 1) { page = Math.max(1, Math.ceil(r.total / 12)); return draw(); }   // trang hiện tại vừa hết đơn
        const counts = { pay: nPay, pending: nPending, confirmed: nConfirmed, refund: nRefund };
        const sig = JSON.stringify([page, r.total, counts, r.items.map(o => o.id + o.status + payOf(o))]);
        if (sig === lastSig) return;                    // không có gì đổi: giữ nguyên để không mất thao tác / focus
        lastSig = sig;
        mount(seg, ORDER_TABS.filter(([s]) => s !== "refund" || counts.refund || status === "refund")
          .map(([s, label]) => h("a", { href: "#orders/" + s, class: (s === status ? "on" : "") + (s === "refund" ? " warn" : ""),
            "aria-current": s === status ? "page" : null }, label, counts[s] ? h("span", { class: "seg-count" }, counts[s]) : null)));
        const emptyText = { pay: "Không có đơn chờ tiền. Sinh viên đặt món phải chuyển khoản trước; đơn hiện ở đây để bạn xác nhận đã nhận tiền.",
          pending: "Chưa có đơn mới. Đơn đã thanh toán sẽ hiện ở đây để bạn nhận và làm món.",
          confirmed: "Không có đơn đang làm.", completed: "Chưa có đơn hoàn thành.", cancelled: "Không có đơn bị hủy.",
          refund: "Không có đơn cần hoàn tiền." }[status];
        mount(list, r.items.length ? h("div", { class: "order-grid" }, r.items.map(o => orderCard(o, draw))) : h("div", { class: "card" }, empty(emptyText)),
          r.total > 12 ? h("div", { class: "card", style: "margin-top:12px" }, pager(r, p => { page = p; lastSig = null; load(list, draw); })) : null);
      };
      await load(list, draw);
      if (stale(seq)) return;
      clearInterval(pageTimer);
      pageTimer = setInterval(() => draw().catch(() => {}), 15000);   // tự làm mới, không hiện vòng tải
    });
  }

  /**
   * Sinh viên tới quầy đọc mã 3 số: gõ mã để ra đúng đơn đang chờ / đang làm (của quán đang chọn), đối chiếu tên rồi giao.
   */
  function codeLookup() {
    const out = h("div", { class: "lookup-result", "aria-live": "polite" });
    const input = h("input", { type: "search", inputmode: "numeric", pattern: "[0-9]*", maxlength: 3, autocomplete: "off",
      placeholder: "Nhập mã 3 số", "aria-label": "Tìm đơn theo mã nhận món" });
    let turn = 0;
    const find = async () => {
      const code = input.value.replace(/\D/g, "").slice(0, 3);
      if (input.value !== code) input.value = code;
      const my = ++turn;
      if (code.length < 3) return mount(out);
      const q = { restaurant_id: rid, page_size: 100 };
      try {
        const lists = await Promise.all(["pending", "confirmed"].map(st => api("order", "/api/orders/owner", { query: { ...q, status: st } })));
        if (my !== turn) return;
        const hits = lists.flatMap(r => r.items).filter(o => o.pickup_code === code);
        const refresh = async () => { await find(); };
        mount(out, hits.length ? h("div", { class: "order-grid lookup-hits" }, hits.map(o => orderCard(o, refresh)))
          : h("div", { class: "notice warn" }, `Không có đơn đang chờ hoặc đang làm nào mang mã ${code}. Hỏi lại mã hoặc xem tab Hoàn thành.`));
      } catch (e) { if (my === turn) mount(out, h("div", { class: "notice warn" }, e.message)); }
    };
    input.oninput = find;
    return h("section", { class: "card lookup" },
      h("label", { class: "lookup-row" }, h("span", { class: "lookup-ic" }, icon("search")),
        h("span", { class: "grow" }, h("strong", null, "Tìm mã nhận món"), h("small", null, "Sinh viên tới quầy đọc mã 3 số")), input),
      out);
  }

  function orderCard(o, redraw) {
    const phone = o.customer_phone && /^[0-9+ ]{8,15}$/.test(o.customer_phone) ? o.customer_phone : null;
    const pickup = o.delivery_address === PICKUP_AT_SHOP;
    return h("article", { class: "card order-card s-" + o.status, "aria-label": "Đơn " + orderCode(o) },
      h("header", { class: "oc-head" },
        h("div", { class: "oc-id" }, o.pickup_code ? pickupCodeEl(o.pickup_code) : null,
          h("span", { class: "mono oc-code" + (o.pickup_code ? " sr-only" : "") }, orderCode(o)),
          h("span", { class: "small muted" }, timeAgo(o.created_at))),
        orderBadge(o)),
      isAwaitingPay(o) ? payPanel(o) : null,
      payOf(o) === "refund_due" ? h("div", { class: "oc-pay refund" }, icon("bank"), h("div", { class: "grow" },
        h("strong", null, `Cần chuyển trả ${money(o.payment.amount)} cho sinh viên`),
        h("div", { class: "small" }, "Đơn đã thanh toán rồi bị hủy. Gọi khách để lấy số tài khoản, chuyển xong bấm Đã hoàn tiền."))) : null,
      stores.length > 1 ? h("div", { class: "small muted oc-store" }, o.restaurant_name) : null,
      h("div", { class: "oc-customer" }, h("strong", null, o.customer_name),
        phone ? h("a", { class: "oc-phone", href: "tel:" + phone.replace(/\s/g, "") }, icon("phone"), phone) : null),
      h("ul", { class: "oc-items" }, o.items.map(i => h("li", null,
        h("span", { class: "oc-qty" }, i.quantity + "×"), h("span", { class: "grow" }, i.item_name), h("span", { class: "num" }, money(i.line_total))))),
      o.note ? h("div", { class: "oc-note" }, h("strong", null, "Ghi chú: "), o.note) : null,
      pickup ? h("div", { class: "oc-recv pickup" }, icon("store"), "Sinh viên tự tới quán lấy: hỏi mã 3 số, đối chiếu tên")
        : h("div", { class: "oc-recv" }, icon("pin"), h("span", null, h("span", { class: "muted" }, "Mang tới: "), o.delivery_address)),
      o.status === "cancelled" && o.cancel_reason ? h("div", { class: "small oc-cancel" }, "Lý do hủy: " + o.cancel_reason) : null,
      h("footer", { class: "oc-foot" },
        h("div", null, h("span", { class: "small muted" }, "Tổng tiền "), h("strong", { class: "oc-total" }, money(o.total_price))),
        h("div", { class: "row" }, orderActions(o, redraw))));
  }

  /** Đơn đang ở bước thanh toán: quán đối chiếu số tiền + nội dung chuyển khoản trong app ngân hàng của mình. */
  function payPanel(o) {
    const p = o.payment, claimed = payOf(o) === "claimed";
    return h("div", { class: "oc-pay" + (claimed ? " claimed" : "") }, icon("bank"), h("div", { class: "grow" },
      h("strong", null, claimed ? `Sinh viên báo đã chuyển ${money(p.amount)}` : `Chờ sinh viên chuyển ${money(p.amount)}`),
      h("div", { class: "small" }, "Nội dung: ", h("span", { class: "mono" }, p.note), ` · vào ${p.bank_name || ""} ${maskAccount(p.account)}`),
      h("div", { class: "small muted" }, claimed ? `Báo lúc ${dt(p.claimed_at)}. Mở app ngân hàng, tìm khoản tiền có nội dung trên.`
        : ["Sinh viên chưa báo chuyển. Đơn tự hủy sau ", countdown(p.deadline)])));
  }

  function orderActions(o, redraw) {
    const after = () => { redraw().catch(() => {}); watchOrders(); };
    const set = (btn, st, msg, reason) => act(btn, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH", body: { status: st, reason } }), msg)
      .then(after)
      .catch(e => { if (["STATUS_CHANGED", "INVALID_TRANSITION", "NOT_PAID", "PAYMENT_CHECKING"].includes(e.code)) redraw().catch(() => {}); });
    const pay = (btn, step, msg, body) => act(btn, () => api("order", `/api/orders/${o.id}/payment/${step}`, { method: "POST", body }), msg)
      .then(after)
      .catch(e => { if (["STATUS_CHANGED", "PAYMENT_STATE"].includes(e.code)) redraw().catch(() => {}); });
    const chipsFor = (input, list) => h("div", { class: "chips", style: "margin-bottom:4px" }, list.map(t =>
      h("button", { type: "button", class: "chip", onclick: () => { input.value = t; input.focus(); } }, t)));
    if (isAwaitingPay(o)) {
      const p = o.payment;
      const confirmPaid = async btn => {
        const ok = await confirmBox(`Đã nhận ${money(p.amount)}?`, `Chỉ bấm khi tài khoản ${p.bank_name || ""} ${maskAccount(p.account)} đã nhận `
          + `${money(p.amount)} với nội dung "${p.note}". Đơn sẽ sang tab Mới để bạn nhận và làm món.`, "Đã nhận tiền");
        if (ok) pay(btn, "confirm", "Đã xác nhận nhận tiền, đơn chuyển sang tab Mới");
      };
      const reject = async btn => {
        const reason = h("input", { maxlength: 300, placeholder: "VD: Chưa thấy tiền vào tài khoản" });
        const ok = await dialog("Chưa nhận được tiền – " + orderCode(o), [
          h("p", null, "Đơn sẽ bị hủy, sinh viên nhận thông báo kèm lý do. Nếu sau đó tiền mới vào, hãy liên hệ sinh viên để hoàn lại."),
          chipsFor(reason, ["Chưa thấy tiền vào tài khoản", "Sai số tiền", "Không tìm thấy giao dịch có nội dung này"]), field("Lý do", reason)],
        [{ label: "Quay lại", value: false }, { label: "Hủy đơn", class: "danger", value: true }]);
        if (ok) pay(btn, "reject", "Đã hủy đơn chưa nhận được tiền", { reason: reason.value.trim() || null });
      };
      return [payOf(o) === "claimed" ? h("button", { class: "danger", onclick: ev => reject(ev.currentTarget) }, "Chưa nhận được tiền") : null,
        h("button", { class: "primary", onclick: ev => confirmPaid(ev.currentTarget) }, icon("check"), "Đã nhận tiền")];
    }
    if (payOf(o) === "refund_due") {
      return h("button", { class: "primary", onclick: async ev => {
        const btn = ev.currentTarget;
        if (await confirmBox("Đã hoàn tiền?", `Xác nhận đã chuyển trả ${money(o.payment.amount)} cho ${o.customer_name}. Sinh viên sẽ nhận thông báo.`,
          "Đã hoàn tiền")) pay(btn, "refunded", "Đã báo sinh viên: quán đã hoàn tiền");
      } }, "Đã hoàn tiền");
    }
    const cancel = async (btn, title) => {
      const reason = h("input", { maxlength: 300, placeholder: "VD: Hết nguyên liệu" });
      const chips = ["Hết món", "Quán đang quá tải", "Sắp đóng cửa", "Không liên lạc được khách"].map(t =>
        h("button", { type: "button", class: "chip", onclick: () => { reason.value = t; reason.focus(); } }, t));
      const ok = await dialog(title + " " + orderCode(o), [h("p", null, "Sinh viên sẽ nhận thông báo kèm lý do.",
          isPlaced(o) ? ` Đơn đã thanh toán: bạn cần chuyển trả ${money(o.total_price)} cho sinh viên (đơn sẽ ở tab Cần hoàn tiền).` : ""),
        h("div", { class: "chips", style: "margin-bottom:4px" }, chips), field("Lý do", reason)],
        [{ label: "Quay lại", value: false }, { label: title, class: "danger", value: true }]);
      if (ok) set(btn, "cancelled", "Đã hủy đơn", reason.value.trim() || null);
    };
    if (o.status === "pending") {
      return [h("button", { class: "danger", onclick: ev => cancel(ev.currentTarget, "Từ chối đơn") }, "Từ chối"),
        h("button", { class: "primary", onclick: ev => set(ev.currentTarget, "confirmed", "Đã nhận đơn, bắt đầu làm món") }, "Nhận đơn")];
    }
    if (o.status === "confirmed") {
      return [h("button", { class: "danger", onclick: ev => cancel(ev.currentTarget, "Hủy đơn") }, "Hủy"),
        h("button", { class: "primary", onclick: ev => set(ev.currentTarget, "completed", "Đơn đã hoàn thành") }, "Báo hoàn thành")];
    }
    return null;
  }

  // ============================================================ TỔNG QUAN
  function dashboardPage(main) {
    const seq = startPage();
    load(main, async () => {
      await loadStores();
      if (stale(seq)) return;
      if (!stores.length) return mount(main, welcome());
      const body = h("div");
      mount(main, h("div", { class: "head" }, h("h1", null, "Tổng quan"), pickStore(true, () => dashboardPage(main))), body);
      const draw = () => load(body, async () => {
        const ids = rid ? [rid] : stores.map(r => r.id);
        const st = storeOf(rid) || (stores.length === 1 ? stores[0] : null);
        const [stats, sums, menu, me] = await Promise.all([
          api("order", "/api/orders/owner/stats", { query: { restaurant_id: rid, days: dashDays } }),
          api("review", "/api/reviews/summary", { auth: false, query: { restaurant_ids: ids.join(",") } }).catch(() => null),
          st ? api("restaurant", `/api/restaurants/${st.id}/menu`, { query: { all: true } }).catch(() => null) : null,
          api("auth", "/api/users/me").catch(() => null)]);
        const count = sums ? sums.reduce((a, s) => a + s.count, 0) : 0;
        const avg = count ? Math.round(sums.reduce((a, s) => a + s.average * s.count, 0) / count * 10) / 10 : null;
        const range = h("div", { class: "seg small-seg", role: "group", "aria-label": "Khoảng thời gian" },
          [7, 30].map(n => h("button", { type: "button", class: n === dashDays ? "on" : "", "aria-pressed": String(n === dashDays),
            onclick: () => { dashDays = n; draw(); } }, `${n} ngày`)));
        mount(body,
          payoutMissingBanner(me, () => dashboardPage(main)),
          st ? storeHero(st, () => dashboardPage(main)) : null,
          st && menu ? setupChecklist(st, menu) : null,
          h("div", { class: "kpis" },
            kpi("Doanh thu hôm nay", money(stats.today.revenue), `${stats.today.completed} đơn hoàn thành`),
            kpi("Đơn hôm nay", stats.today.orders, stats.today.cancelled ? `${stats.today.cancelled} đơn bị hủy` : "Không có đơn bị hủy"),
            kpi("Chờ xác nhận", stats.open.pending, stats.open.pending ? "Bấm để xử lý ngay" : "Không có đơn chờ", "#orders/pending", stats.open.pending > 0),
            kpi("Đang làm", stats.open.confirmed, "Đơn đã nhận, chưa xong", "#orders/confirmed"),
            kpi("Đánh giá", avg !== null ? avg.toLocaleString("vi-VN") + " ★" : "—", count ? `${count} lượt đánh giá` : "Chưa có đánh giá", "#reviews")),
          h("div", { class: "dash-grid" },
            h("section", { class: "card pad" },
              h("div", { class: "row", style: "justify-content:space-between" }, h("h2", null, `Doanh thu ${dashDays} ngày`), range),
              h("p", { class: "small muted", style: "margin:2px 0 14px" },
                `Tổng ${money(stats.period.revenue)} từ ${stats.period.completed} đơn hoàn thành, tính theo ngày đặt đơn.`),
              columnChart(stats.series, { value: d => d.revenue, format: money, short: shortMoney, caption: "Doanh thu theo ngày",
                detail: d => `${d.completed}/${d.orders} đơn xong`,
                columns: [{ label: "Đơn", get: d => d.orders }, { label: "Hoàn thành", get: d => d.completed }] })),
            h("section", { class: "card pad" }, h("h2", { style: "margin-bottom:12px" }, `Món bán chạy ${dashDays} ngày`), topItems(stats.top_items))));
      });
      draw();
    });
  }

  function kpi(label, value, sub, href, hot) {
    return h(href ? "a" : "div", { class: "card kpi" + (hot ? " hot" : ""), href: href || null },
      h("div", { class: "k" }, label), h("div", { class: "v" }, value), h("div", { class: "small muted" }, sub));
  }

  function storeHero(r, redraw) {
    const canToggle = r.status === "active" || r.status === "closed";
    return h("section", { class: "card store-hero" },
      restCover(r, "store-cover", "Ảnh bìa " + r.name),
      h("div", { class: "store-info" },
        h("div", { class: "row" }, h("h2", { class: "grow" }, r.name), badge(r.status, "restaurant")),
        h("div", { class: "small muted" }, `${r.address}. Giờ mở cửa ${hours(r)}.`),
        r.status === "pending" ? h("div", { class: "small", style: "margin-top:6px" },
          "Quán đang chờ ban quản trị duyệt. Trong lúc chờ, hãy thêm ảnh bìa và món để quán sẵn sàng bán.") : null,
        r.status === "locked" ? h("div", { class: "small oc-cancel", style: "margin-top:6px" },
          "Quán bị khóa" + (r.status_reason ? ": " + r.status_reason : "") + ". Liên hệ ban quản trị để mở lại.") : null),
      canToggle ? h("div", { class: "store-toggle" },
        toggle(r.status === "active", "Nhận đơn", on =>
          act(null, () => api("restaurant", `/api/restaurants/${r.id}`, { method: "PATCH", body: { status: on ? "active" : "closed" } }),
            on ? "Quán đã mở, bắt đầu nhận đơn" : "Đã tạm ngưng nhận đơn").then(redraw), "Nhận đơn"),
        h("span", { class: "small muted" }, r.status === "active" ? "Sinh viên đang đặt được món" : "Sinh viên chưa đặt được món")) : null);
  }

  function setupChecklist(r, menu) {
    const steps = [
      [!!r.image_url, "Thêm ảnh bìa cho quán", "#store/" + r.id],
      [!!(r.open_time && r.close_time), "Cập nhật giờ mở cửa", "#store/" + r.id],
      [menu.length >= 3, "Thêm ít nhất 3 món", "#menu/" + r.id],
      [menu.some(m => m.image_url), "Thêm ảnh cho món ăn", "#menu/" + r.id],
      [r.status !== "pending", "Được ban quản trị duyệt", null],
    ];
    const done = steps.filter(s => s[0]).length;
    if (done === steps.length) return null;
    return h("section", { class: "card pad checklist" },
      h("div", { class: "row", style: "justify-content:space-between" }, h("h2", null, "Hoàn thiện quán"),
        h("span", { class: "small muted" }, `${done}/${steps.length} việc đã xong`)),
      h("div", { class: "meter", style: "margin:10px 0 6px" }, h("span", { style: `width:${done / steps.length * 100}%` })),
      h("ul", null, steps.map(([ok, text, href]) => h("li", { class: ok ? "done" : "" },
        h("span", { class: "tick", "aria-hidden": "true" }, ok ? icon("check") : null),
        ok || !href ? h("span", null, text, ok ? h("span", { class: "sr-only" }, " (đã xong)") : null) : h("a", { href }, text)))));
  }

  function topItems(items) {
    if (!items.length) return empty("Chưa có món nào được bán trong khoảng này");
    const max = Math.max(...items.map(t => t.quantity));
    return h("ol", { class: "top-items" }, items.map(t => h("li", null,
      h("div", { class: "row" }, h("strong", { class: "grow" }, t.item_name), h("span", { class: "num" }, `${t.quantity} phần`)),
      h("div", { class: "meter" }, h("span", { style: `width:${t.quantity / max * 100}%` })),
      h("div", { class: "small muted" }, money(t.revenue)))));
  }

  // ============================================================ THỰC ĐƠN
  function menuPage(main, arg) {
    const seq = startPage();
    load(main, async () => {
      await loadStores();
      if (stale(seq)) return;
      if (!stores.length) return mount(main, welcome());
      if (arg && storeOf(arg)) choose(arg);
      const r = oneStore();
      const locked = r.status === "locked";
      let items = [], filter = "all", q = "";
      const chips = h("div", { class: "chips", role: "group", "aria-label": "Lọc món" });
      const listBox = h("div");
      const search = h("input", { type: "search", placeholder: "Tìm món hoặc danh mục…", "aria-label": "Tìm món", class: "grow",
        oninput: e => { q = e.target.value.trim().toLowerCase(); render(); } });
      const fetchItems = async () => { items = await api("restaurant", `/api/restaurants/${r.id}/menu`, { query: { all: true } }); };
      /** Tải lại không hiện vòng tải (giữ vị trí cuộn); focusSel: đặt lại focus vào nút vừa bấm. */
      const reload = async focusSel => {
        try {
          await fetchItems();
          render();
          const el = focusSel && listBox.querySelector(focusSel);
          if (el) el.focus({ preventScroll: true });
        } catch (e) { toast(e.message, true); }
      };
      mount(main,
        h("div", { class: "head" }, h("h1", null, "Thực đơn"),
          h("div", { class: "row" }, pickStore(false, () => menuPage(main)),
            locked ? null : h("button", { class: "primary", onclick: () => itemForm(r, null, items, reload) }, "+ Thêm món"))),
        locked ? h("div", { class: "notice warn" }, "Quán đang bị khóa, chưa sửa được thực đơn.")
          : h("div", { class: "notice" }, "Món mới, món đổi giá và món bán lại sẽ tự lên Bảng tin món mới mà sinh viên thấy khi mở app."),
        h("div", { class: "row menu-tools" }, search, chips), listBox);

      function render() {
        const n = s => items.filter(m => m.status === s).length;
        mount(chips, [["all", "Tất cả", items.length], ["available", "Đang bán", n("available")], ["sold_out", "Hết món", n("sold_out")],
          ["hidden", "Đang ẩn", n("hidden")]].map(([k, label, c]) => h("button", { type: "button", class: "chip" + (filter === k ? " on" : ""),
          "aria-pressed": String(filter === k), onclick: () => { filter = k; render(); } }, `${label} (${c})`)));
        if (!items.length) {
          return mount(listBox, h("div", { class: "card state" }, h("p", null, "Quán chưa có món nào. Thêm món đầu tiên để quán lên Bảng tin món mới."),
            locked ? null : h("button", { class: "primary", onclick: () => itemForm(r, null, items, reload) }, "+ Thêm món đầu tiên")));
        }
        const shown = items.filter(m => (filter === "all" || m.status === filter)
          && (!q || m.name.toLowerCase().includes(q) || (m.category || "").toLowerCase().includes(q)));
        if (!shown.length) return mount(listBox, h("div", { class: "card" }, empty("Không có món phù hợp")));
        mount(listBox, menuGroups(shown).map(g => h("section", { class: "menu-cat" },
          h("h2", { class: "cat-head" }, g.name, h("span", { class: "small muted" }, `${g.items.length} món`)),
          h("div", { class: "card" }, g.items.map(m => itemRow(r, m, items, reload, locked))))));
      }
      load(listBox, async () => { await fetchItems(); render(); });
    });
  }

  const patchItem = (m, body, msg, reload, focusSel) =>
    act(null, () => api("restaurant", `/api/menu-items/${m.id}`, { method: "PATCH", body }), msg).then(() => reload(focusSel));

  function itemRow(r, m, all, reload, locked) {
    const src = imageSrc(m.image_url);
    const at = sel => `[data-id="${m.id}"] ${sel}`;
    const more = h("details", { class: "more" },
      h("summary", { "aria-label": "Thao tác khác với " + m.name }, "⋯"));
    const pick = fn => () => { more.open = false; fn(); };
    more.append(h("div", { class: "more-pop" },
      h("button", { type: "button", onclick: pick(() => itemForm(r, m, all, reload)) }, "Sửa món"),
      m.status !== "hidden" ? h("button", { type: "button", onclick: pick(() => patchItem(m, { status: "hidden" }, "Đã ẩn món khỏi thực đơn", reload, at("button.sm")).catch(() => {})) }, "Ẩn khỏi thực đơn") : null,
      h("button", { type: "button", class: "danger", onclick: pick(() => removeItem(m, reload)) }, "Xóa món")));
    return h("div", { class: "item-row" + (m.status === "hidden" ? " is-hidden" : ""), "data-id": m.id },
      h("div", { class: "thumb" + (src ? "" : " empty") }, src ? photo(src) : icon("image")),
      h("div", { class: "item-main" },
        h("div", { class: "row", style: "gap:6px" }, h("strong", null, m.name),
          m.status === "hidden" ? badge("hidden") : m.status === "sold_out" ? badge("sold_out") : null),
        m.description ? h("div", { class: "small muted clamp" }, m.description) : null,
        locked ? h("strong", { class: "item-price" }, money(m.price)) : priceEditor(m, reload)),
      locked ? null : h("div", { class: "item-actions" },
        m.status === "hidden"
          ? h("button", { class: "sm", onclick: () => patchItem(m, { status: "available" }, "Món đã hiện lại", reload, at(".switch")).catch(() => {}) }, "Hiện lại")
          : toggle(m.status === "available", "Còn món",
            on => patchItem(m, { status: on ? "available" : "sold_out" }, on ? `Đã mở bán lại ${m.name}` : `Đã báo hết ${m.name}`, reload, at(".switch")),
            `Còn món: ${m.name}`),
        h("button", { class: "sm ghost", onclick: () => itemForm(r, m, all, reload) }, "Sửa"), more));
  }

  /** Bấm vào giá để sửa ngay tại chỗ: Enter hoặc nút ✓ để lưu, Esc hoặc bấm ra ngoài để hủy. */
  function priceEditor(m, reload) {
    const show = h("button", { type: "button", class: "price-edit", "aria-label": `Sửa giá ${m.name}, đang là ${money(m.price)}` },
      money(m.price), icon("edit"));
    show.onclick = () => {
      const pi = priceInput(m.price);
      const ok = h("button", { type: "button", class: "sm primary price-ok", "aria-label": "Lưu giá mới" }, icon("check"));
      const wrap = h("span", { class: "price-edit-row" }, h("span", { class: "input-suffix price-input" }, pi.el, h("span", null, "đ")), ok);
      let finished = false;
      const done = async (save, refocus) => {
        if (finished) return;
        const v = pi.value();
        if (save && (!Number.isInteger(v) || v > 100000000)) { toast("Giá phải là số từ 0 đến 100.000.000 đ", true); pi.el.focus(); return; }
        finished = true;
        if (!save || v === m.price) { wrap.replaceWith(show); if (refocus) show.focus(); return; }
        try { await patchItem(m, { price: v }, `Đã đổi giá ${m.name}: ${money(v)}`, reload, `[data-id="${m.id}"] .price-edit`); }
        catch (e) { finished = false; pi.el.focus(); }
      };
      ok.onmousedown = e => e.preventDefault();                       // giữ focus ở ô nhập
      ok.onclick = () => done(true, true);
      pi.el.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); done(true, true); } if (e.key === "Escape") done(false, true); };
      // bấm ra chỗ khác trên trang: hủy (không lưu giá gõ dở); chuyển cửa sổ / ứng dụng: giữ nguyên để gõ tiếp
      pi.el.onblur = () => setTimeout(() => { if (document.hasFocus() && document.activeElement !== ok) done(false, false); }, 0);
      show.replaceWith(wrap);
      pi.el.focus(); pi.el.select();
    };
    return show;
  }

  async function removeItem(m, reload) {
    if (!await confirmBox("Xóa món", `Xóa “${m.name}” khỏi thực đơn? Đơn cũ vẫn giữ tên và giá đã đặt.`, "Xóa món", true)) return;
    await act(null, () => api("restaurant", `/api/menu-items/${m.id}`, { method: "DELETE" }), "Đã xóa món").catch(() => {});
    reload();
  }

  function itemForm(r, m, all, reload) {
    const pic = imagePicker({ url: m && m.image_url, maxSide: 900, label: "Ảnh món" });
    const name = h("input", { maxlength: 150, value: m ? m.name : "", placeholder: "VD: Cơm tấm sườn bì chả" });
    const price = priceInput(m ? m.price : null);
    const cats = [...new Set([...MENU_CATEGORIES, ...all.map(x => x.category).filter(Boolean)])];
    const catList = "cat-list-" + Date.now();
    const cat = h("input", { maxlength: 50, list: catList, value: m && m.category ? m.category : "", placeholder: "VD: Món chính, Đồ uống" });
    const desc = h("textarea", { maxlength: 1000, placeholder: "Thành phần, khẩu phần, độ cay…" }, m && m.description ? m.description : "");
    let st = m ? m.status : "available";
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Trạng thái món" });
    const paintSeg = () => mount(seg, [["available", "Còn món"], ["sold_out", "Hết món"], ["hidden", "Ẩn"]].map(([v, l]) =>
      h("button", { type: "button", class: st === v ? "on" : "", "aria-pressed": String(st === v), onclick: () => { st = v; paintSeg(); } }, l)));
    paintSeg();
    dialog(m ? "Sửa món" : "Thêm món – " + r.name, [
      h("div", { class: "form-2" },
        h("div", null, field("Ảnh món", pic.el)),
        h("div", null, field("Tên món", name), field("Giá bán", h("div", { class: "input-suffix" }, price.el, h("span", null, "đ"))),
          field("Danh mục", cat, "Món cùng danh mục được xếp chung một nhóm"),
          h("datalist", { id: catList }, cats.map(c => h("option", { value: c }))))),
      field("Mô tả", desc), field("Trạng thái", seg)],
    [{ label: "Hủy" }, { label: m ? "Lưu thay đổi" : "Thêm món", class: "primary", run: async () => {
      const p = price.value();
      if (!name.value.trim()) throw new Error("Nhập tên món");
      if (!Number.isInteger(p)) throw new Error("Nhập giá bán");
      const body = { name: name.value, price: p, category: cat.value.trim() || null, description: desc.value.trim() || null, status: st };
      if (pic.changed()) body.image_url = await pic.value();
      if (m) await api("restaurant", `/api/menu-items/${m.id}`, { method: "PATCH", body });
      else await api("restaurant", `/api/restaurants/${r.id}/menu`, { method: "POST", body });
      toast(m ? "Đã lưu món" : `Đã thêm ${body.name}`);
      reload();
    } }]);
  }

  // ============================================================ CỬA HÀNG
  function storePage(main, arg) {
    const seq = startPage();
    load(main, async () => {
      await loadStores();
      if (stale(seq)) return;
      const creating = arg === "new" || !stores.length;
      if (!creating && arg && storeOf(arg)) choose(arg);
      const r = creating ? null : oneStore();
      mount(main,
        h("div", { class: "head" }, h("h1", null, creating ? "Đăng ký quán mới" : "Cửa hàng"),
          creating ? null : h("div", { class: "row" }, pickStore(false, () => storePage(main)), h("a", { class: "btn", href: "#store/new" }, "+ Thêm quán"))),
        stores.length > 1 || (creating && stores.length) ? storeList(r) : null,
        storeForm(r, main),
        r ? qrCard() : null,
        r ? h("section", { class: "card pad danger-zone" }, h("h2", null, "Xóa quán"),
          h("p", { class: "small muted" }, "Quán bị xóa sẽ không còn hiển thị và không nhận đơn mới. Lịch sử đơn vẫn được giữ."),
          h("button", { class: "danger", onclick: ev => removeRestaurant(ev.currentTarget, r, main) }, "Xóa quán này")) : null);
    });
  }

  function storeList(cur) {
    return h("div", { class: "card section-gap" }, table([
      { label: "Quán của bạn", render: r => [h("strong", null, r.name), h("div", { class: "small muted" }, r.address)] },
      { label: "Số món", num: true, render: r => r.item_count },
      { label: "Trạng thái", render: r => [badge(r.status, "restaurant"), r.status_reason ? h("div", { class: "small muted" }, r.status_reason) : null] },
      { label: "", actions: true, render: r => cur && r.id === cur.id ? h("span", { class: "small muted" }, "Đang xem")
        : h("a", { class: "btn sm", href: "#store/" + r.id }, "Xem") },
    ], stores));
  }

  function storeForm(r, main) {
    const f = {
      name: h("input", { maxlength: 150, value: r ? r.name : "", placeholder: "VD: Cơm Tấm Cô Ba" }),
      address: h("input", { maxlength: 300, value: r ? r.address : "", placeholder: "VD: 19 Nguyễn Hữu Thọ, Tân Phong, Q7" }),
      description: h("textarea", { maxlength: 1000, placeholder: "Món đặc trưng, phong cách quán, ưu đãi cho sinh viên…" }, r && r.description ? r.description : ""),
      open_time: h("input", { type: "time", value: r && r.open_time ? r.open_time : "07:00" }),
      close_time: h("input", { type: "time", value: r && r.close_time ? r.close_time : "21:00" }),
    };
    // bản xem trước thẻ quán như sinh viên thấy
    const pvCover = h("div", { class: "rest-cover" }), pvName = h("h3"), pvAddr = h("div", { class: "small muted" }), pvHours = h("div", { class: "small" });
    const preview = h("div", { class: "card rest preview-card", "aria-hidden": "true" }, pvCover, h("div", { class: "sign" }, pvName), h("div", { class: "body" }, pvAddr, pvHours));
    let coverSrc = null;
    const paint = () => {
      pvName.textContent = f.name.value.trim() || "Tên quán";
      pvAddr.textContent = f.address.value.trim() || "Địa chỉ quán";
      pvHours.textContent = "Giờ mở cửa: " + (f.open_time.value && f.close_time.value ? `${f.open_time.value} – ${f.close_time.value}` : "chưa cập nhật");
      const art = coverFor({ id: r && r.id, name: f.name.value.trim() });
      if (pvImg.getAttribute("src") !== (coverSrc || art)) pvImg.src = coverSrc || art;
    };
    const pvImg = h("img", { alt: "" });
    pvCover.append(pvImg);
    let presetBtns = [];
    const markPreset = btn => presetBtns.forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
    const pic = imagePicker({ url: r && r.image_url, wide: true, maxSide: 1600, label: "Ảnh bìa quán",
      onChange: s => { coverSrc = s; paint(); }, onManual: () => markPreset(null) });
    presetBtns = COVER_PRESETS.map(([theme, pal, label]) => h("button", { type: "button", class: "cover-preset",
      "aria-pressed": "false", "aria-label": "Dùng nền " + label, title: label,
      onclick: ev => {
        const btn = ev.currentTarget;
        act(btn, async () => { pic.setBlob(await coverBlob(theme, pal)); markPreset(btn); }).catch(() => {});
      } }, h("img", { src: coverDataUrl(theme, pal), alt: "" }), h("span", null, label)));
    Object.values(f).forEach(el => el.addEventListener("input", paint));
    paint();

    const save = h("button", { class: "primary", type: "button" }, r ? "Lưu thay đổi" : "Gửi đăng ký");
    save.onclick = () => act(save, async () => {
      const body = { name: f.name.value, address: f.address.value, description: f.description.value.trim() || null,
        open_time: f.open_time.value || null, close_time: f.close_time.value || null };
      if (pic.changed()) body.image_url = await pic.value();
      if (r) {
        await api("restaurant", `/api/restaurants/${r.id}`, { method: "PATCH", body });
        toast("Đã lưu thông tin quán");
        storePage(main, r.id);
      } else {
        const created = await api("restaurant", "/api/restaurants", { method: "POST", body });
        toast("Đã gửi đăng ký, chờ ban quản trị duyệt");
        choose(created.id);
        location.hash = "#store/" + created.id;
      }
    }).catch(() => {});

    const statusBox = r ? h("div", { class: "card pad" }, h("h3", null, "Trạng thái"),
      h("div", { class: "row" }, badge(r.status, "restaurant"),
        r.status === "pending" ? h("span", { class: "small muted" }, "Chờ ban quản trị duyệt") : null),
      r.status_reason ? h("p", { class: "small oc-cancel" }, r.status_reason) : null,
      r.status === "active" || r.status === "closed" ? h("div", { class: "store-toggle", style: "margin-top:10px" },
        toggle(r.status === "active", "Nhận đơn", on =>
          act(null, () => api("restaurant", `/api/restaurants/${r.id}`, { method: "PATCH", body: { status: on ? "active" : "closed" } }),
            on ? "Quán đã mở, bắt đầu nhận đơn" : "Đã tạm ngưng nhận đơn").then(() => storePage(main, r.id)), "Nhận đơn"),
        h("span", { class: "small muted" }, r.status === "active" ? "Sinh viên đang đặt được món" : "Đang tạm ngưng, sinh viên chưa đặt được món")) : null) : null;

    return h("div", { class: "store-layout section-gap" },
      h("section", { class: "card pad" },
        field("Ảnh bìa quán", pic.el, "Nên dùng ảnh ngang (tỉ lệ 16:9): mặt tiền quán hoặc món đặc trưng"),
        h("div", { class: "field" }, h("label", null, "Chưa có ảnh đẹp? Chọn một nền có sẵn"),
          h("div", { class: "cover-presets", role: "group", "aria-label": "Nền có sẵn" }, presetBtns),
          h("div", { class: "small muted" }, "Nền được lưu thành ảnh bìa khi bấm lưu; sinh viên thấy ngay trong danh sách quán.")),
        field("Tên quán", f.name), field("Địa chỉ", f.address), field("Giới thiệu", f.description),
        h("div", { class: "row" }, h("div", { class: "grow" }, field("Giờ mở cửa", f.open_time)), h("div", { class: "grow" }, field("Giờ đóng cửa", f.close_time))),
        h("div", { class: "row", style: "justify-content:flex-end;margin-top:16px" },
          r ? null : h("span", { class: "small muted grow" }, "Quán mới cần ban quản trị duyệt trước khi nhận đơn."), save)),
      h("aside", { class: "store-side" }, h("div", { class: "small muted", style: "margin-bottom:8px" }, "Sinh viên sẽ thấy quán của bạn như sau"), preview, statusBox));
  }

  function qrCard() {
    return h("div", { class: "card qr-card section-gap" },
      h("img", { src: "qr/sinh-vien.svg", alt: "Mã QR mở app cho sinh viên", width: 148, height: 148 }),
      h("div", null, h("h3", null, "Dán mã QR tại quán"),
        h("p", { class: "muted", style: "margin:0 0 12px" }, "Sinh viên quét mã để mở app, tạo tài khoản rồi đặt món ở quán của bạn mà không cần xếp hàng."),
        h("a", { class: "btn sm", href: "qr.html", target: "_blank", rel: "noopener" }, "In áp phích QR")));
  }

  async function removeRestaurant(btn, r, main) {
    if (!await confirmBox("Xóa quán", `Xóa “${r.name}”? Quán sẽ không còn hiển thị và không nhận đơn mới. Lịch sử đơn vẫn được giữ.`, "Xóa quán", true)) return;
    try { await act(btn, () => api("restaurant", `/api/restaurants/${r.id}`, { method: "DELETE" }), "Đã xóa quán"); }
    catch (e) { return; }                                         // lỗi đã báo, ở lại trang
    choose("");
    if (location.hash === "#store") storePage(main); else location.hash = "#store";
  }

  // ============================================================ ĐÁNH GIÁ
  function reviewsPage(main) {
    const seq = startPage();
    load(main, async () => {
      await loadStores();
      if (stale(seq)) return;
      if (!stores.length) return mount(main, welcome());
      const box = h("div");
      mount(main, h("div", { class: "head" }, h("h1", null, "Đánh giá"), pickStore(true, () => reviewsPage(main))), box);
      load(box, async () => {
        const scope = rid ? [storeOf(rid)] : stores;
        const data = await Promise.all(scope.map(r => api("review", `/api/reviews/restaurant/${r.id}`, { auth: false, query: { page_size: 10 } })));
        const rows = scope.map((r, i) => [r, data[i]]);
        const rated = rows.filter(([, d]) => d.summary.count), unrated = rows.filter(([, d]) => !d.summary.count);
        mount(box, rated.map(([r, d]) => reviewBlock(r, d)),
          unrated.length ? h("div", { class: "card" }, unrated.map(([r]) => h("div", { class: "noti read" },
            h("strong", { class: "grow" }, r.name), h("span", { class: "small muted" }, "Chưa có đánh giá")))) : null);
      });
    });
  }

  function reviewBlock(r, d) {
    const s = d.summary;
    return h("section", { class: "card section-gap" },
      h("div", { class: "pad review-sum" },
        h("div", { class: "review-avg" }, h("div", { class: "v" }, s.count ? s.average.toLocaleString("vi-VN") : "—"),
          s.count ? stars(Math.round(s.average)) : null, h("div", { class: "small muted" }, s.count ? `${s.count} đánh giá` : "Chưa có đánh giá")),
        h("div", { class: "grow" }, h("h2", { style: "margin-bottom:8px" }, r.name),
          [5, 4, 3, 2, 1].map(k => h("div", { class: "dist-row" }, h("span", { class: "small" }, `${k}★`),
            h("div", { class: "meter grow" }, h("span", { style: `width:${s.count ? s.distribution[k] / s.count * 100 : 0}%` })),
            h("span", { class: "small muted num" }, s.distribution[k]))))),
      d.items.map(v => h("div", { class: "noti read" }, h("div", { class: "grow" },
        h("div", { class: "row" }, h("strong", null, v.reviewer_name), stars(v.rating), h("span", { class: "small muted" }, dt(v.created_at))),
        v.comment ? h("div", null, v.comment) : null))));
  }

  // ============================================================ khởi động
  ui = shell({
    title: "TDTU Food Booking", subtitle: "Chủ quán",
    tabs: [{ id: "orders", label: "Đơn hàng" }, { id: "dashboard", label: "Tổng quan" }, { id: "menu", label: "Thực đơn" },
           { id: "store", label: "Cửa hàng" }, { id: "reviews", label: "Đánh giá" },
           { id: "notifications", label: "Thông báo", hidden: true }, { id: "profile", label: "Profile", hidden: true }],
    onTab: (id, main, arg) => {
      if (id === "notifications" || id === "profile") startPage();
      if (id === "orders") return ordersPage(main, arg);
      if (id === "dashboard") return dashboardPage(main);
      if (id === "menu") return menuPage(main, arg);
      if (id === "store") return storePage(main, arg);
      if (id === "reviews") return reviewsPage(main);
      if (id === "notifications") return notificationsView(main, () => ui.refreshBell());
      if (id === "profile") return profileView(main);
    },
  });
  baseTitle = document.title;
  maybeWelcome("chu_quan");                                                   // tài khoản vừa tạo: hướng dẫn giao món
  watchOrders();
  setInterval(watchOrders, 15000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) watchOrders(); });   // quay lại tab: kiểm tra đơn ngay
  // đóng menu "⋯" khi bấm ra ngoài hoặc nhấn Esc (trả focus về nút ⋯)
  document.addEventListener("click", e => document.querySelectorAll("details.more[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.more[open]").forEach(d => { d.open = false; d.querySelector("summary").focus(); });
  });
})();
