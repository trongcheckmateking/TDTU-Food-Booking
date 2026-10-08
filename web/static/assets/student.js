/* Giao diện sinh viên: tìm quán, xem menu, giỏ hàng, đặt món, theo dõi đơn, đánh giá, thông báo. */
"use strict";
(() => {
  const session = requireRole("sinh_vien");
  if (!session) return;
  let checkoutKey = null;      // Idempotency-Key giữ nguyên khi bấm lại / thử lại cho tới khi đặt thành công
  let ui;


  // ------------------------------------------------------------ danh sách quán
  function restaurantList(main) {
    let q = "", page = 1;
    const grid = h("div");
    const search = h("input", { type: "search", placeholder: "Tìm theo tên hoặc địa chỉ…", "aria-label": "Tìm quán", class: "grow" });
    let timer;
    search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { q = search.value.trim(); page = 1; draw(); }, 300); };
    mount(main, h("div", { class: "head" }, h("h1", null, "Quán ăn gần trường")), h("div", { class: "row", style: "margin-bottom:14px" }, search), grid);
    const draw = () => load(grid, async () => {
      const r = await api("restaurant", "/api/restaurants", { auth: false, query: { q, page, page_size: 12 } });
      if (!r.items.length) return mount(grid, h("div", { class: "card" }, empty(q ? "Không tìm thấy quán phù hợp" : "Chưa có quán nào mở bán")));
      let sums = {};
      try {
        const list = await api("review", "/api/reviews/summary", { auth: false, query: { restaurant_ids: r.items.map(x => x.id).join(",") } });
        list.forEach(s => sums[s.restaurant_id] = s);
      } catch (e) { sums = null; }
      mount(grid, h("div", { class: "grid" }, r.items.map(x => {
        const s = sums && sums[x.id];
        return h("div", { class: "card rest", tabindex: 0, role: "link", onclick: () => location.hash = "#restaurants/" + x.id,
                          onkeydown: e => { if (e.key === "Enter") location.hash = "#restaurants/" + x.id; } },
          h("div", { class: "row" }, h("h3", { class: "grow" }, x.name), x.status !== "active" ? badge(x.status, "restaurant") : null),
          h("div", { class: "small muted" }, x.address),
          h("div", { class: "small" }, "Giờ mở cửa: " + hours(x)),
          h("div", { class: "small" }, sums === null ? h("span", { class: "muted" }, "Chưa tải được đánh giá")
            : s && s.count ? [stars(Math.round(s.average)), ` ${s.average} (${s.count} đánh giá)`] : h("span", { class: "muted" }, "Chưa có đánh giá")));
      })), r.total > 12 ? h("div", { class: "card", style: "margin-top:12px" }, pager(r, p => { page = p; draw(); })) : null);
    });
    draw();
  }

  // ------------------------------------------------------------ chi tiết quán + menu
  function restaurantDetail(main, rid) {
    const left = h("div"), right = h("div", { class: "sticky" });
    mount(main, h("div", { class: "row", style: "margin-bottom:12px" }, h("a", { href: "#restaurants" }, "‹ Danh sách quán")),
      h("div", { class: "layout-2" }, left, right));
    renderCart(right, true);
    load(left, async () => {
      const [r, menu] = await Promise.all([
        api("restaurant", `/api/restaurants/${rid}`, { auth: false }),
        api("restaurant", `/api/restaurants/${rid}/menu`, { auth: false })]);
      const reviews = h("div");
      mount(left,
        h("div", { class: "card pad", style: "margin-bottom:14px" },
          h("div", { class: "row" }, h("h1", { class: "grow" }, r.name), badge(r.status, "restaurant")),
          h("div", { class: "muted" }, r.address), r.description ? h("p", null, r.description) : null,
          h("div", { class: "small" }, "Giờ mở cửa: " + hours(r)),
          !r.accepting_orders ? h("div", { class: "notice warn", style: "margin:10px 0 0" }, "Quán đang tạm đóng, chưa nhận đơn.") : null),
        h("h2", { style: "margin:4px 0 10px" }, "Thực đơn"),
        h("div", { class: "card", style: "margin-bottom:18px" }, menu.length ? menu.map(m => menuRow(r, m, right)) : empty("Quán chưa có món")),
        h("h2", { style: "margin:4px 0 10px" }, "Đánh giá"), reviews);
      reviewList(reviews, rid);
    });
  }

  function menuRow(r, m, cartBox) {
    let qty = 1;
    const span = h("span", null, "1");
    const canBuy = r.accepting_orders && m.status === "available";
    return h("div", { class: "menu-item" },
      h("div", { class: "grow" }, h("strong", null, m.name), m.status !== "available" ? [" ", badge(m.status)] : null,
        m.description ? h("div", { class: "small muted" }, m.description) : null),
      h("div", { class: "num" }, money(m.price)),
      canBuy ? h("span", { class: "qty" },
        h("button", { "aria-label": "Giảm", onclick: () => { qty = Math.max(1, qty - 1); span.textContent = qty; } }, "−"), span,
        h("button", { "aria-label": "Tăng", onclick: () => { qty = Math.min(50, qty + 1); span.textContent = qty; } }, "+")) : null,
      h("button", { class: "primary sm", disabled: !canBuy, onclick: ev => addToCart(ev.currentTarget, r, m, qty, cartBox) }, "Thêm"));
  }

  async function addToCart(btn, r, m, qty, cartBox) {
    const body = { restaurant_id: r.id, item_id: m.id, quantity: qty };
    try {
      await act(btn, () => api("order", "/api/cart/items", { method: "POST", body }), `Đã thêm ${qty} × ${m.name}`);
    } catch (e) {
      if (e.code !== "CART_OTHER_RESTAURANT") return;
      const ok = await confirmBox("Giỏ đang có món của quán khác", "Xóa giỏ hiện tại và thêm món của " + r.name + "?", "Xóa giỏ và thêm");
      if (!ok) return;
      await act(btn, async () => {
        await api("order", "/api/cart", { method: "DELETE" });
        await api("order", "/api/cart/items", { method: "POST", body });
      }, `Đã thêm ${qty} × ${m.name}`).catch(() => {});
    }
    checkoutKey = null;
    renderCart(cartBox, true);
  }

  function reviewList(box, rid) {
    let page = 1;
    const draw = () => load(box, async () => {
      const r = await api("review", `/api/reviews/restaurant/${rid}`, { auth: false, query: { page, page_size: 5 } });
      const s = r.summary;
      mount(box, h("div", { class: "card" },
        h("div", { class: "pad row" }, s.count ? [h("strong", { style: "font-size:22px" }, s.average), stars(Math.round(s.average)),
          h("span", { class: "muted" }, `${s.count} đánh giá`)] : h("span", { class: "muted" }, "Chưa có đánh giá")),
        r.items.map(v => h("div", { class: "noti read" }, h("div", { class: "grow" },
          h("div", { class: "row" }, h("strong", null, v.reviewer_name), stars(v.rating), h("span", { class: "small muted" }, dt(v.created_at))),
          v.comment ? h("div", null, v.comment) : null))),
        r.total > 5 ? pager(r, p => { page = p; draw(); }) : null));
    });
    draw();
  }

  // ------------------------------------------------------------ giỏ hàng
  function renderCart(box, compact) {
    return load(box, async () => {
      const c = await api("order", "/api/cart");
      if (!c.items.length) {
        return mount(box, h("div", { class: "card pad" }, h("h3", null, "Giỏ hàng"), h("div", { class: "muted" }, "Giỏ đang trống. Chọn món từ một quán để bắt đầu.")));
      }
      const r = c.restaurant || {};
      const lines = c.items.map(it => h("div", { class: "menu-item" },
        h("div", { class: "grow" }, h("div", null, it.name || "Món không còn tồn tại"),
          !it.available ? h("div", { class: "small", style: "color:var(--bad)" }, "Món không còn bán") : h("div", { class: "small muted" }, money(it.price))),
        h("span", { class: "qty" },
          h("button", { "aria-label": "Giảm", disabled: it.quantity <= 1, onclick: ev => setQty(ev.currentTarget, it, it.quantity - 1, box, compact) }, "−"),
          h("span", null, it.quantity),
          h("button", { "aria-label": "Tăng", disabled: it.quantity >= 50, onclick: ev => setQty(ev.currentTarget, it, it.quantity + 1, box, compact) }, "+")),
        h("button", { class: "ghost sm", title: "Xóa món", "aria-label": "Xóa món", onclick: ev => act(ev.currentTarget, () =>
          api("order", `/api/cart/items/${it.item_id}`, { method: "DELETE" })).then(() => { checkoutKey = null; renderCart(box, compact); }).catch(() => {}) }, "✕")));
      const warn = !r.accepting_orders ? (r.deleted ? "Quán không còn tồn tại." : "Quán hiện không nhận đơn.")
                 : !c.can_checkout ? "Có món đã hết, hãy xóa món đó trước khi đặt." : null;
      const parts = [h("div", { class: "pad", style: "padding-bottom:6px" }, h("h3", null, "Giỏ hàng"), h("div", { class: "small muted" }, r.name || "")),
        lines, h("div", { class: "pad row" }, h("strong", { class: "grow" }, "Tạm tính"), h("strong", { class: "num" }, money(c.total_price))),
        warn ? h("div", { class: "notice warn", style: "margin:0 16px 12px" }, warn) : null];
      if (compact) {
        parts.push(h("div", { class: "pad row", style: "padding-top:0" },
          h("button", { class: "danger sm", onclick: ev => clearCart(ev.currentTarget, box, compact) }, "Xóa giỏ"),
          h("span", { class: "grow" }), h("button", { class: "primary", disabled: !c.can_checkout, onclick: () => location.hash = "#cart" }, "Đặt hàng")));
      } else {
        const addr = h("input", { maxlength: 300, placeholder: "VD: KTX TDTU, phòng B305", value: lastAddress() });
        const note = h("textarea", { maxlength: 500, placeholder: "Ít cay, thêm đũa…" });
        parts.push(h("div", { class: "pad", style: "padding-top:0" },
          field("Địa chỉ giao", addr), field("Ghi chú cho quán (không bắt buộc)", note),
          h("div", { class: "row", style: "margin-top:14px" },
            h("button", { class: "danger", onclick: ev => clearCart(ev.currentTarget, box, compact) }, "Xóa giỏ"), h("span", { class: "grow" }),
            h("button", { class: "primary", disabled: !c.can_checkout, onclick: ev => checkout(ev.currentTarget, addr, note) }, "Đặt hàng · " + money(c.total_price)))));
      }
      mount(box, h("div", { class: "card" }, parts));
    });
  }
  const lastAddress = () => { try { return localStorage.getItem("tdtu_addr") || ""; } catch (e) { return ""; } };

  async function setQty(btn, it, q, box, compact) {
    await act(btn, () => api("order", `/api/cart/items/${it.item_id}`, { method: "PATCH", body: { quantity: q } })).catch(() => {});
    checkoutKey = null; renderCart(box, compact);
  }
  async function clearCart(btn, box, compact) {
    if (!await confirmBox("Xóa giỏ hàng", "Xóa toàn bộ món trong giỏ?", "Xóa giỏ", true)) return;
    await act(btn, () => api("order", "/api/cart", { method: "DELETE" }), "Đã xóa giỏ").catch(() => {});
    checkoutKey = null; renderCart(box, compact);
  }

  async function checkout(btn, addr, note) {
    const address = addr.value.trim();
    if (address.length < 3) { toast("Nhập địa chỉ giao (ít nhất 3 ký tự)", true); addr.focus(); return; }
    checkoutKey = checkoutKey || uuid4();
    try {
      const o = await act(btn, () => api("order", "/api/orders/checkout", { method: "POST",
        headers: { "Idempotency-Key": checkoutKey }, body: { delivery_address: address, note: note.value.trim() || null } }));
      try { localStorage.setItem("tdtu_addr", address); } catch (e) {}
      checkoutKey = null;
      toast("Đặt hàng thành công: đơn #" + short(o.id));
      location.hash = "#orders";
    } catch (e) {
      if (["ITEMS_UNAVAILABLE", "RESTAURANT_NOT_ACCEPTING", "CART_CHANGED", "CART_EMPTY"].includes(e.code)) { checkoutKey = null; cartPage($("#main")); }
    }
  }

  function cartPage(main) {
    const box = h("div");
    mount(main, h("div", { class: "head" }, h("h1", null, "Giỏ hàng")), h("div", { style: "max-width:640px" }, box));
    renderCart(box, false);
  }

  // ------------------------------------------------------------ đơn của tôi
  function ordersPage(main) {
    let status = "", page = 1, reviewed = new Set();
    const list = h("div", { class: "card" });
    const sel = h("select", { "aria-label": "Lọc trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Tất cả trạng thái"), ["pending", "confirmed", "completed", "cancelled"].map(s => h("option", { value: s }, STATUS[s][0])));
    mount(main, h("div", { class: "head" }, h("h1", null, "Đơn của tôi"), sel), list);
    const draw = () => load(list, async () => {
      const [r, mine] = await Promise.all([
        api("order", "/api/orders/me", { query: { status, page, page_size: 10 } }),
        api("review", "/api/reviews/me").catch(() => null)]);
      if (mine) reviewed = new Set(mine.map(x => x.order_id));
      mount(list, table([
        { label: "Mã đơn", render: o => h("span", { class: "mono" }, "#" + short(o.id)) },
        { label: "Quán", render: o => o.restaurant_name },
        { label: "Món", render: o => o.items.map(i => `${i.quantity}× ${i.item_name}`).join(", ") },
        { label: "Tổng tiền", num: true, render: o => money(o.total_price) },
        { label: "Trạng thái", render: o => badge(o.status) },
        { label: "Thời gian", render: o => dt(o.created_at) },
        { label: "", actions: true, render: o => [
          h("button", { class: "sm", onclick: () => orderDialog(o) }, "Chi tiết"),
          o.status === "pending" ? h("button", { class: "sm danger", onclick: ev => cancelOrder(ev.currentTarget, o, draw) }, "Hủy") : null,
          o.status === "completed" && mine && !reviewed.has(o.id) ? h("button", { class: "sm primary", onclick: () => reviewDialog(o, draw) }, "Đánh giá") : null,
          o.status === "completed" && reviewed.has(o.id) ? h("span", { class: "small muted" }, "Đã đánh giá") : null] },
      ], r.items, status ? "Không có đơn ở trạng thái này" : "Bạn chưa có đơn nào"), r.total > 10 ? pager(r, p => { page = p; draw(); }) : null);
    });
    draw();
  }

  function orderDialog(o) {
    dialog("Đơn #" + short(o.id) + " – " + o.restaurant_name, [
      h("div", { class: "row", style: "margin:8px 0" }, badge(o.status), h("span", { class: "muted small" }, dt(o.created_at))),
      h("div", { class: "small" }, "Giao tới: " + o.delivery_address), o.note ? h("div", { class: "small" }, "Ghi chú: " + o.note) : null,
      o.cancel_reason ? h("div", { class: "small", style: "color:var(--bad)" }, "Lý do hủy: " + o.cancel_reason) : null,
      table([{ label: "Món", render: i => i.item_name }, { label: "SL", num: true, render: i => i.quantity },
             { label: "Đơn giá", num: true, render: i => money(i.price) }, { label: "Thành tiền", num: true, render: i => money(i.line_total) }], o.items),
      h("div", { class: "row", style: "justify-content:flex-end;margin-top:8px" }, h("strong", null, "Tổng: " + money(o.total_price)))], [{ label: "Đóng" }]);
  }

  async function cancelOrder(btn, o, redraw) {
    if (!await confirmBox("Hủy đơn", "Hủy đơn #" + short(o.id) + " tại " + o.restaurant_name + "?", "Hủy đơn", true)) return;
    await act(btn, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH", body: { status: "cancelled", reason: "Sinh viên hủy" } }), "Đã hủy đơn").catch(() => {});
    redraw();
  }

  function reviewDialog(o, redraw) {
    let rating = 5;
    const starBox = h("div", { class: "star-input", role: "radiogroup", "aria-label": "Số sao" });
    const paint = () => mount(starBox, [1, 2, 3, 4, 5].map(i => h("button", { type: "button", class: i <= rating ? "on" : "",
      "aria-label": i + " sao", onclick: () => { rating = i; paint(); } }, "★")));
    paint();
    const comment = h("textarea", { maxlength: 1000, placeholder: "Món ăn, thời gian giao, thái độ phục vụ…" });
    dialog("Đánh giá " + o.restaurant_name, [h("div", { class: "small muted" }, "Đơn #" + short(o.id)), field("Số sao", starBox),
      field("Nhận xét (không bắt buộc, tối đa 1.000 ký tự)", comment)],
      [{ label: "Hủy" }, { label: "Gửi đánh giá", class: "primary", run: async () => {
        await api("review", "/api/reviews", { method: "POST", body: { order_id: o.id, rating, comment: comment.value.trim() || null } });
        toast("Cảm ơn bạn đã đánh giá!"); redraw();
      } }]);
  }
  // Khởi động sau khi mọi hàm/hằng đã được khai báo
  ui = shell({
    title: "TDTU Food Booking", subtitle: "Sinh viên",
    tabs: [{ id: "restaurants", label: "Quán ăn" }, { id: "cart", label: "Giỏ hàng" }, { id: "orders", label: "Đơn của tôi" },
           { id: "notifications", label: "Thông báo" }, { id: "profile", label: "Hồ sơ" }],
    onTab: (id, main, arg) => {
      if (id === "restaurants") return arg ? restaurantDetail(main, arg) : restaurantList(main);
      if (id === "cart") return cartPage(main);
      if (id === "orders") return ordersPage(main);
      if (id === "notifications") return notificationsView(main, () => ui.refreshBell());
      if (id === "profile") return profileView(main);
    },
  });
})();
