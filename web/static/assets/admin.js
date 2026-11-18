/* Giao diện admin (bố cục kiểu AdminLTE / CoreUI: menu bên trái): bảng điều khiển có biểu đồ tỉ lệ, quản lý sinh viên,
   chủ quán và mọi tài khoản, quán ăn, đơn hàng, đánh giá, thông báo, mã QR. */
"use strict";
(() => {
  const session = requireRole("admin");
  if (!session) return;
  let ui;
  let navSeq = 0;                                    // trang cũ tải xong muộn thì không vẽ đè trang mới
  let closeDrawer = null, searchTimer = null;
  /** Bắt đầu vẽ một trang: đóng bảng chi tiết đang mở, hủy lần tìm kiếm đang chờ. */
  const startPage = () => { if (closeDrawer) closeDrawer(); clearTimeout(searchTimer); return ++navSeq; };
  const stale = seq => seq !== navSeq;
  /** turn = latest(seq); mỗi lần tải gọi ok = turn(): ok() đúng khi đó vẫn là lần tải mới nhất của trang
      (gõ tìm nhanh / bấm lọc liên tục thì kết quả cũ về chậm không đè kết quả mới). */
  const latest = seq => { let n = 0; return () => { const my = ++n; return () => my === n && !stale(seq); }; };
  /** Chạy fn(ok) cho một khối nhỏ (ví dụ nút lọc): lỗi hiện thành dòng báo lỗi thay vì promise bị bỏ lửng. */
  const safe = (box, turn, fn) => { const ok = turn(); return fn(ok).catch(e => { if (ok()) mount(box, h("div", { class: "small field-error" }, "Không tải được: " + e.message)); }); };
  const debounced = fn => () => { clearTimeout(searchTimer); searchTimer = setTimeout(fn, 300); };
  /** Chạy tối đa n tác vụ cùng lúc, giữ thứ tự kết quả. */
  async function pool(items, n, fn) {
    const out = new Array(items.length);
    let i = 0;
    await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => { while (i < items.length) { const k = i++; out[k] = await fn(items[k]); } }));
    return out;
  }
  const me = session.user.id;

  Object.assign(ICONS, {
    menu: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
    students: '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/>',
    owners: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
    alert: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  });

  const userNames = {};
  async function loadNames() {
    try {
      for (let page = 1; page <= 5; page++) {
        const r = await api("auth", "/api/users", { query: { page, page_size: 100 } });
        r.items.forEach(u => userNames[u.id] = u.name);
        if (page * 100 >= r.total) break;
      }
    } catch (e) { /* tên người dùng chỉ để hiển thị */ }
  }
  const count = (svc, path, query) => api(svc, path, { query: { ...query, page_size: 1 } }).then(r => r.total);
  const panel = (title, body, { sub, action, cls = "" } = {}) => h("section", { class: "card pad panel " + cls },
    h("div", { class: "panel-head" }, h("div", null, h("h2", null, title), sub ? h("p", { class: "small muted" }, sub) : null), action || null), body);
  const personCell = u => h("div", { class: "person" }, avatarEl(u),
    h("div", null, h("strong", null, u.name), h("div", { class: "small muted" }, u.email)));
  /** Nhóm nút lọc có số đếm (thay cho ô chọn): items [[giá trị, nhãn, số]] */
  const filterChips = (items, current, onPick) => h("div", { class: "chips", role: "group", "aria-label": "Lọc" },
    items.map(([v, label, n]) => h("button", { type: "button", class: "chip" + (v === current ? " on" : ""), "aria-pressed": String(v === current),
      onclick: () => onPick(v) }, label, n === undefined || n === null ? null : h("span", { class: "chip-count" }, n))));

  // ============================================================ menu trái: số việc cần xử lý + tình trạng dịch vụ
  async function refreshSide() {
    try { ui.setBadge("restaurants", await count("restaurant", "/api/admin/restaurants", { status: "pending" })); } catch (e) { /* bỏ qua */ }
    try { ui.setBadge("notifications", (await api("order", "/api/admin/orders/stats")).notification_failed); } catch (e) { /* bỏ qua */ }
    sideHealth().catch(() => {});
  }
  const SERVICES = ["auth", "restaurant", "order", "notification", "review"];
  const ping = s => {
    const t0 = performance.now();
    return fetch(SVC[s] + "/health", { cache: "no-store" }).then(r => r.json().then(d => ({ s, ok: r.ok && d.status === "ok", ms: Math.round(performance.now() - t0) })))
      .catch(() => ({ s, ok: false, ms: null }));
  };
  async function sideHealth() {
    const res = await Promise.all(SERVICES.map(ping));
    const down = res.filter(r => !r.ok).length;
    mount(ui.sideFooter, h("a", { href: "#dashboard", class: "side-health" + (down ? " bad" : "") }, h("span", { class: "dot", "aria-hidden": "true" }),
      down ? `${down} dịch vụ không phản hồi` : "5/5 dịch vụ hoạt động"));
    return res;
  }

  // ============================================================ BẢNG ĐIỀU KHIỂN
  let dashDays = 7, dashMetric = "revenue";

  function dashboard(main, focusKey) {
    const seq = startPage();
    const P = {
      stats: api("order", "/api/admin/orders/stats"),
      report: api("order", "/api/admin/orders/report", { query: { days: dashDays } }),
      users: Promise.all([count("auth", "/api/users"), ...["sinh_vien", "chu_quan", "admin"].map(role => count("auth", "/api/users", { role })),
        count("auth", "/api/users", { status: "locked" })]).then(([all, sv, cq, ad, locked]) => ({ all, sv, cq, ad, locked })),
      rest: Promise.all(["active", "closed", "pending", "locked"].map(status => count("restaurant", "/api/admin/restaurants", { status })))
        .then(([active, closed, pending, locked]) => ({ active, closed, pending, locked, all: active + closed + pending + locked })),
      // số đánh giá đang hiển thị có <= k sao (k = 1..5) -> phân bố từng mức sao
      ratings: Promise.all([1, 2, 3, 4, 5].map(k => count("review", "/api/admin/reviews", { status: "visible", max_rating: k })))
        .then(c => { const dist = { 1: c[0] }; for (let k = 2; k <= 5; k++) dist[k] = c[k - 1] - c[k - 2]; return { dist, total: c[4] }; }),
    };
    Object.values(P).forEach(p => p.catch(() => {}));      // lỗi được hiện ở từng ô, tránh cảnh báo promise chưa xử lý
    const avgRating = r => (r.total ? Math.round([1, 2, 3, 4, 5].reduce((a, k) => a + k * r.dist[k], 0) / r.total * 10) / 10 : null);

    const kpi = (label, fn, href) => {
      const v = h("div", { class: "v" }, h("span", { class: "spinner" })), s = h("div", { class: "small muted" });
      fn().then(([value, sub, link]) => { v.textContent = value; s.textContent = sub || ""; if (link) card.setAttribute("href", link); })
        .catch(e => { v.textContent = "—"; s.textContent = "Không tải được"; s.title = e.message; });
      const card = h(href ? "a" : "div", { class: "card kpi", href: href || null }, h("div", { class: "k" }, label), v, s);
      return card;
    };
    const trendBox = h("div"), todoBox = h("div"), dOrders = h("div"), dUsers = h("div"), dRest = h("div"),
      topBox = h("div"), ratingBox = h("div"), healthBox = h("div", { class: "health-row" });
    const trendCtl = h("div", { class: "row" });

    mount(main,
      h("div", { class: "head" }, h("div", null, h("h1", null, "Bảng điều khiển"),
        h("p", { class: "small muted", style: "margin:0" }, "Số liệu toàn hệ thống TDTU Food tại thời điểm mở trang.")),
      h("button", { onclick: () => dashboard(main) }, icon("refresh"), "Làm mới")),
      h("div", { class: "kpis" },
        kpi("Doanh thu hôm nay", async () => { const [r, s] = await Promise.all([P.report, P.stats]); return [money(r.today.revenue), `Tổng đã hoàn thành: ${money(s.revenue)}`]; }),
        kpi("Đơn hàng", async () => { const [s, r] = await Promise.all([P.stats, P.report]); return [String(s.total), `Hôm nay ${r.today.orders} đơn`]; }, "#orders"),
        kpi("Tỉ lệ hoàn thành", async () => { const b = (await P.stats).by_status, done = b.completed + b.cancelled;
          return [done ? pctText(b.completed, done) : "—", `${b.completed} hoàn thành, ${b.cancelled} bị hủy`]; }),
        kpi("Người dùng", async () => { const u = await P.users; return [String(u.all), `${u.sv} sinh viên, ${u.cq} chủ quán`]; }, "#users"),
        kpi("Quán đang bán", async () => { const r = await P.rest;
          return [`${r.active}/${r.all}`, r.pending ? `${r.pending} quán chờ duyệt` : "Không có quán chờ duyệt", r.pending ? "#restaurants/pending" : "#restaurants"]; }, "#restaurants"),
        kpi("Điểm đánh giá", async () => { const r = await P.ratings, a = avgRating(r);
          return [a === null ? "—" : a.toLocaleString("vi-VN") + " ★", `${r.total} đánh giá đang hiển thị`]; }, "#reviews")),
      h("div", { class: "dash-grid" },
        panel(dashMetric === "revenue" ? "Doanh thu theo ngày" : "Số đơn theo ngày", trendBox, { action: trendCtl, cls: "trend-panel" }),
        panel("Cần xử lý", todoBox, { sub: "Việc đang chờ ban quản trị" })),
      h("div", { class: "grid-3" },
        panel("Trạng thái đơn hàng", dOrders, { sub: "Tỉ lệ trên tổng số đơn" }),
        panel("Cơ cấu người dùng", dUsers, { sub: "Tỉ lệ theo vai trò" }),
        panel("Tình trạng quán ăn", dRest, { sub: "Tỉ lệ theo trạng thái" })),
      h("div", { class: "grid-2" },
        panel("Top quán theo doanh thu", topBox, { sub: "Phần trăm trên tổng doanh thu đơn hoàn thành" }),
        panel("Phân bố đánh giá", ratingBox, { sub: "Đánh giá đang hiển thị" })),
      panel("Tình trạng dịch vụ", healthBox, { sub: "5 service, mỗi service một ngôn ngữ" }));

    // xu hướng theo ngày: chọn chỉ số và khoảng thời gian
    const seg = (items, cur, pick, label) => h("div", { class: "seg small-seg", role: "group", "aria-label": label },
      items.map(([v, l]) => h("button", { type: "button", class: v === cur ? "on" : "", "aria-pressed": String(v === cur), "data-focus": "seg-" + v,
        onclick: () => pick(v) }, l)));
    mount(trendCtl,
      seg([["revenue", "Doanh thu"], ["orders", "Số đơn"]], dashMetric, v => { dashMetric = v; dashboard(main, "seg-" + v); }, "Chỉ số"),
      seg([[7, "7 ngày"], [30, "30 ngày"]], dashDays, v => { dashDays = v; dashboard(main, "seg-" + v); }, "Khoảng thời gian"));
    if (focusKey) { const b = trendCtl.querySelector(`[data-focus="${focusKey}"]`); if (b) b.focus(); }
    load(trendBox, async () => {
      const r = await P.report;
      const rev = dashMetric === "revenue";
      mount(trendBox,
        h("p", { class: "small muted", style: "margin:0 0 14px" },
          `${dashDays} ngày: ${money(r.period.revenue)} doanh thu từ ${r.period.completed} đơn hoàn thành; ${r.period.orders} đơn đặt, ${r.period.cancelled} bị hủy.`),
        columnChart(r.series, rev
          ? { value: d => d.revenue, format: money, short: shortMoney, caption: "Doanh thu theo ngày", detail: d => `${d.completed}/${d.orders} đơn xong`,
              columns: [{ label: "Đơn", get: d => d.orders }] }
          : { value: d => d.orders, format: n => `${n} đơn`, short: n => String(Math.round(n)), caption: "Số đơn theo ngày",
              detail: d => `${d.completed} hoàn thành, ${d.cancelled} hủy`, columns: [{ label: "Doanh thu", get: d => money(d.revenue) }] }));
    });

    load(todoBox, async () => {
      const [s, r, u, rt] = await Promise.all([P.stats, P.rest, P.users, P.ratings]);
      const items = [
        ["restaurants", "Quán chờ duyệt", r.pending, "#restaurants/pending"],
        ["orders", "Đơn chờ quán xác nhận", s.by_status.pending, "#orders/pending"],
        ["alert", "Thông báo gửi lỗi", s.notification_failed, "#notifications"],
        ["reviews", "Đánh giá 1–2 sao đang hiển thị", rt.dist[1] + rt.dist[2], "#reviews/low"],
        ["users", "Tài khoản bị khóa", u.locked, "#users/locked"],
      ];
      mount(todoBox, h("ul", { class: "todo" }, items.map(([ic, label, n, href]) => h("li", null,
        h("a", { href, class: n ? "has" : "" }, icon(ic), h("span", { class: "grow" }, label),
          h("span", { class: "todo-count" }, n), icon("chevron"))))));
    });

    load(dOrders, async () => {
      const b = (await P.stats).by_status;
      mount(dOrders, donutChart([
        { label: "Chờ xác nhận", value: b.pending, color: CHART.waiting, href: "#orders/pending" },
        { label: "Đã xác nhận", value: b.confirmed, color: CHART.working, href: "#orders/confirmed" },
        { label: "Hoàn thành", value: b.completed, color: CHART.good, href: "#orders/completed" },
        { label: "Đã hủy", value: b.cancelled, color: CHART.bad, href: "#orders/cancelled" }], { totalLabel: "đơn hàng" }));
    });
    load(dUsers, async () => {
      const u = await P.users;
      mount(dUsers, donutChart([
        { label: "Sinh viên", value: u.sv, color: CHART.cat[0], href: "#students" },
        { label: "Chủ quán", value: u.cq, color: CHART.cat[1], href: "#owners" },
        { label: "Quản trị viên", value: u.ad, color: CHART.cat[2], href: "#users/admin" }], { totalLabel: "tài khoản" }),
      h("p", { class: "small muted donut-note" }, `${u.locked} tài khoản đang bị khóa (${pctText(u.locked, u.all)}).`));
    });
    load(dRest, async () => {
      const r = await P.rest;
      mount(dRest, donutChart([
        { label: "Hoạt động", value: r.active, color: CHART.good, href: "#restaurants/active" },
        { label: "Tạm đóng", value: r.closed, color: CHART.working, href: "#restaurants/closed" },
        { label: "Chờ duyệt", value: r.pending, color: CHART.waiting, href: "#restaurants/pending" },
        { label: "Bị khóa", value: r.locked, color: CHART.bad, href: "#restaurants/locked" }], { totalLabel: "quán ăn" }));
    });
    load(topBox, async () => {
      const s = await P.stats;
      const rows = [...s.top_restaurants].sort((a, b) => b.revenue - a.revenue || b.orders - a.orders);
      mount(topBox, barList(rows.map(x => ({ label: x.restaurant_name, value: x.revenue,
        note: `${x.orders} đơn, ${pctText(x.revenue, s.revenue)} doanh thu toàn hệ thống` })), { format: money, emptyText: "Chưa có đơn hàng" }));
    });
    load(ratingBox, async () => {
      const r = await P.ratings;
      mount(ratingBox, r.total ? barList([5, 4, 3, 2, 1].map(k => ({ label: `${k} sao`, value: r.dist[k], note: pctText(r.dist[k], r.total) })))
        : empty("Chưa có đánh giá"));
    });
    load(healthBox, async () => {
      const res = await sideHealth();
      if (stale(seq)) return;
      mount(healthBox, res.map(x => h("div", { class: "health" }, h("strong", null, serviceName(x.s)),
        x.ok ? h("span", null, badge("active"), h("span", { class: "small muted" }, ` ${x.ms} ms`)) : h("span", { class: "badge b-bad" }, "Không phản hồi"))));
    });
  }

  // ============================================================ bảng chi tiết trượt từ bên phải
  function drawer(title, build) {
    if (closeDrawer) closeDrawer();
    const prev = document.activeElement;
    const body = h("div", { class: "drawer-body" });
    const behind = [...document.body.children].filter(c => !c.classList.contains("toasts"));   // nền: không bấm / Tab vào được
    const panelEl = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "dh" }, h("h3", null, title), h("button", { class: "ghost", "aria-label": "Đóng", onclick: () => close() }, "✕")), body);
    const onKey = e => {
      if (document.querySelector(".overlay")) return;            // đang mở hộp thoại: để hộp thoại xử lý trước
      if (e.key === "Escape") close();
      if (e.key === "Tab") {                                      // giữ focus trong bảng chi tiết
        const f = [...panelEl.querySelectorAll("button:not(:disabled),a[href],input,select,textarea,[tabindex='0']")].filter(x => x.offsetParent);
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    const close = () => {
      ov.remove(); behind.forEach(c => { c.inert = false; });
      document.removeEventListener("keydown", onKey);
      closeDrawer = null;
      if (prev && prev.isConnected && prev.focus) prev.focus();
    };
    const ov = h("div", { class: "drawer-overlay", onclick: e => { if (e.target === ov) close(); } }, panelEl);
    document.body.append(ov);
    behind.forEach(c => { c.inert = true; });
    closeDrawer = close;
    document.addEventListener("keydown", onKey);
    ov.querySelector(".dh button").focus();
    build(body, close);
    return close;
  }
  const mini = (label, value) => h("div", { class: "mini" }, h("div", { class: "small muted" }, label), h("strong", null, value));
  const profileHead = u => h("div", { class: "profile-head" }, avatarEl(u, "lg"),
    h("div", { class: "grow" }, h("h2", null, u.name), h("div", { class: "small muted" }, u.email + (u.phone ? ", " + u.phone : "")),
      h("div", { class: "row", style: "margin-top:6px;gap:6px" }, badge(u.role), badge(u.status === "active" ? "active" : "locked"),
        h("span", { class: "small muted" }, "Tham gia " + dt(u.created_at)))));

  /** Nút khóa / mở khóa, đổi vai trò, xóa dữ liệu cá nhân trong bảng chi tiết; done() chạy sau khi thành công. */
  function accountActions(u, toRole, toLabel, done) {
    if (u.id === me) return h("p", { class: "small muted" }, "Đây là tài khoản của bạn.");
    if (u.erased_at) return h("p", { class: "small muted" }, `Đã xóa dữ liệu cá nhân theo yêu cầu lúc ${dt(u.erased_at)}. Tài khoản không khôi phục được.`);
    return h("div", { class: "row drawer-actions" },
      u.status === "active"
        ? h("button", { class: "danger", onclick: ev => setStatus(ev.currentTarget, u, "locked", done) }, "Khóa tài khoản")
        : h("button", { onclick: ev => setStatus(ev.currentTarget, u, "active", done) }, "Mở khóa tài khoản"),
      h("button", { onclick: ev => changeRoleTo(ev.currentTarget, u, toRole, done) }, toLabel),
      h("button", { class: "danger ghost", onclick: () => eraseUser(u, done) }, "Xóa tài khoản"));
  }

  /** Nút "Xóa" trên hàng danh sách: cùng hộp xác nhận gõ lại email; không hiện với admin, chính mình, tài khoản đã xóa. */
  const deleteButton = (u, done) => u.id === me || u.role === "admin" || u.erased_at ? null
    : h("button", { class: "sm danger ghost", "aria-label": "Xóa tài khoản " + u.email, onclick: () => eraseUser(u, done) }, "Xóa");

  /** Yêu cầu xóa dữ liệu (Chính sách quyền riêng tư, mục 8): gõ lại email để xác nhận, Auth điều phối 4 service còn lại. */
  async function eraseUser(u, done) {
    const input = h("input", { autocomplete: "off", spellcheck: "false", placeholder: u.email });
    let tried = false;
    const ok = await dialog("Xóa tài khoản", [
      h("p", null, `Chỉ làm khi người dùng gửi yêu cầu từ chính email ${u.email}. Không hoàn tác được.`),
      h("ul", { class: "small erase-list" },
        h("li", null, "Tài khoản bị khóa và đăng xuất ngay."),
        h("li", null, "Họ tên, email, số điện thoại trong tài khoản, đơn hàng và đánh giá đổi thành “Người dùng đã xóa”; thông báo bị xóa."),
        u.role === "chu_quan" ? h("li", null, "Mọi quán của chủ quán bị gỡ khỏi ứng dụng, ảnh quán và ảnh món bị xóa.") : null,
        h("li", null, "Số tiền, số đơn và số sao được giữ để thống kê không sai."),
        h("li", null, "Còn đơn đang chờ hoặc đã xác nhận thì phải hoàn thành hay hủy đơn trước.")),
      field("Gõ lại email để xác nhận", input)],
      [{ label: "Hủy", value: false }, { label: "Xóa tài khoản", class: "danger", run: async () => {
        if (input.value.trim().toLowerCase() !== u.email) { toast("Email xác nhận không khớp", true); input.focus(); return false; }
        tried = true;
        await api("auth", `/api/users/${u.id}/erase`, { method: "POST" });
        return true;
      } }]);
    if (ok) toast("Đã xóa tài khoản " + u.email);
    if (ok || tried) done();          // lần thử bị từ chối vẫn đã khóa tài khoản: vẽ lại danh sách
  }

  function studentDetail(u, redraw) {
    drawer("Sinh viên", (body, close) => {
      const statsBox = h("div"), ordersBox = h("div");
      const after = () => { close(); redraw(); };
      mount(body, profileHead(u), accountActions(u, "chu_quan", "Chuyển thành chủ quán", after),
        h("h4", null, "Hoạt động đặt món"), statsBox, h("h4", null, "Đơn gần đây"), ordersBox);
      load(statsBox, async () => {
        const q = { user_id: u.id };
        const [r, done, nCancelled] = await Promise.all([
          api("order", "/api/admin/orders", { query: { ...q, page_size: 100 } }),
          api("order", "/api/admin/orders", { query: { ...q, status: "completed", page_size: 100 } }),
          count("order", "/api/admin/orders", { ...q, status: "cancelled" })]);
        const byRest = {};
        r.items.forEach(o => { byRest[o.restaurant_name] = (byRest[o.restaurant_name] || 0) + 1; });
        const fav = Object.entries(byRest).sort((a, b) => b[1] - a[1])[0];
        const spent = done.items.reduce((a, o) => a + o.total_price, 0);
        mount(statsBox, h("div", { class: "minis" }, mini("Tổng đơn", r.total), mini("Hoàn thành", done.total), mini("Bị hủy", nCancelled),
          mini("Đã chi", money(spent) + (done.total > 100 ? "+" : ""))),
        done.total > 100 ? h("p", { class: "small muted" }, "Số tiền đã chi tính trên 100 đơn hoàn thành gần nhất.") : null,
        fav ? h("p", { class: "small muted" }, `Đặt nhiều nhất ở ${fav[0]} (${fav[1]} đơn${r.total > 100 ? " trong 100 đơn gần nhất" : ""}).`) : null);
        mount(ordersBox, r.items.length ? h("div", { class: "card" }, table([
          { label: "Mã", render: o => h("button", { class: "linkish mono", onclick: () => orderDetail(o) }, orderCode(o)) },
          { label: "Quán", render: o => o.restaurant_name },
          { label: "Tổng", num: true, render: o => money(o.total_price) },
          { label: "Trạng thái", render: o => orderBadge(o) },
          { label: "Ngày", render: o => dt(o.created_at) }], r.items.slice(0, 8))) : empty("Chưa đặt đơn nào"));
      });
    });
  }

  function ownerDetail(u, redraw) {
    drawer("Chủ quán", (body, close) => {
      const sumBox = h("div"), restBox = h("div");
      const after = () => { close(); redraw(); };
      mount(body, profileHead(u), accountActions(u, "sinh_vien", "Chuyển thành sinh viên", after),
        h("h4", null, "Tài khoản nhận tiền"),
        u.bank_account ? h("p", { class: "small" }, `${u.bank_name || u.bank_bin} · `, h("span", { class: "mono" }, u.bank_account), ` · ${u.bank_holder || ""}`,
          isDemoAccount(u.bank_holder) ? h("span", { class: "badge b-warn", style: "margin-left:6px" }, "DEMO") : null)
          : h("div", { class: "notice warn" }, "Chưa khai báo: sinh viên chưa đặt được món ở quán của chủ quán này."),
        h("h4", null, "Kinh doanh 30 ngày"), sumBox, h("h4", null, "Quán của chủ quán này"), restBox);
      const draw = () => load(restBox, async () => {
        const r = await api("restaurant", "/api/admin/restaurants", { query: { owner_id: u.id, page_size: 100 } });
        const reps = await pool(r.items, 5, x => api("order", "/api/admin/orders/report", { query: { restaurant_id: x.id, days: 30 } }).catch(() => null));
        const sum = k => reps.reduce((a, x) => a + (x ? x.period[k] : 0), 0);
        mount(sumBox, h("div", { class: "minis" }, mini("Số quán", r.total), mini("Đơn", sum("orders")), mini("Hoàn thành", sum("completed")),
          mini("Doanh thu", money(sum("revenue")))));
        mount(restBox, r.items.length ? h("div", { class: "card" }, r.items.map((x, i) => h("div", { class: "rest-line" },
          restCover(x, "thumb"),
          h("div", { class: "grow" }, h("div", { class: "row", style: "gap:6px" }, h("strong", null, x.name), badge(x.status, "restaurant")),
            h("div", { class: "small muted" }, x.address),
            h("div", { class: "small" }, `${x.item_count} món; 30 ngày: ${reps[i] ? reps[i].period.orders : "—"} đơn, ${reps[i] ? money(reps[i].period.revenue) : "—"}`),
            x.status_reason ? h("div", { class: "small muted" }, "Lý do: " + x.status_reason) : null),
          h("div", { class: "row rest-actions" }, h("button", { class: "sm", onclick: () => showMenu(x) }, "Thực đơn"), restActions(x, () => { draw(); redraw(); }))))) : empty("Chủ quán chưa đăng ký quán nào"));
      });
      draw();
    });
  }

  async function openPerson(id, redraw) {
    try {
      const u = await api("auth", `/api/users/${id}`);
      (u.role === "chu_quan" ? ownerDetail : studentDetail)(u, redraw);
    } catch (e) { toast(e.message, true); }
  }

  // ============================================================ SINH VIÊN / CHỦ QUÁN
  function people(main, role, arg) {
    const seq = startPage();
    const isOwner = role === "chu_quan";
    let status = arg === "locked" ? "locked" : "", q = "", page = 1, restByOwner = null;
    const chips = h("div"), list = h("div", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Tên hoặc email…", "aria-label": "Tìm " + (isOwner ? "chủ quán" : "sinh viên") });
    search.oninput = debounced(() => { q = search.value.trim(); page = 1; draw(); });
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, isOwner ? "Chủ quán" : "Sinh viên"),
      h("p", { class: "small muted", style: "margin:0" }, isOwner ? "Theo dõi quán và doanh thu của từng chủ quán, duyệt hoặc khóa quán, khóa tài khoản."
        : "Theo dõi lịch sử đặt món, khóa tài khoản vi phạm hoặc chuyển sinh viên thành chủ quán.")), search), chips, list);
    const chipTurn = latest(seq);
    const drawChips = () => safe(chips, chipTurn, async ok => {
      const [all, active, locked] = await Promise.all([count("auth", "/api/users", { role, erased: false }),
        count("auth", "/api/users", { role, status: "active", erased: false }), count("auth", "/api/users", { role, status: "locked", erased: false })]);
      if (!ok()) return;
      mount(chips, filterChips([["", "Tất cả", all], ["active", "Đang hoạt động", active], ["locked", "Bị khóa", locked]], status,
        v => { status = v; page = 1; drawChips(); draw(); }));
    });
    const restSummary = rs => {
      if (!rs || !rs.length) return h("span", { class: "small muted" }, "Chưa có quán");
      const by = {};
      rs.forEach(x => { by[x.status] = (by[x.status] || 0) + 1; });
      return h("div", null, h("strong", null, `${rs.length} quán`), h("div", { class: "row", style: "gap:4px;margin-top:3px" },
        ["active", "pending", "closed", "locked"].filter(s => by[s]).map(s => h("span", { class: "badge " + STATUS[s === "pending" ? "pending_r" : s][1] },
          `${by[s]} ${STATUS[s === "pending" ? "pending_r" : s][0].toLowerCase()}`))));
    };
    const redraw = () => { restByOwner = null; drawChips(); draw(); refreshSide(); };
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      const r = await api("auth", "/api/users", { query: { role, status, q, page, page_size: 15, erased: false } });
      if (isOwner && !restByOwner) {                // quán của mọi chủ quán, gom theo chủ; tải 1 lần mỗi lần mở trang / sau thao tác
        const map = {};
        for (let p = 1; p <= 10; p++) {
          const rs = await api("restaurant", "/api/admin/restaurants", { query: { page: p, page_size: 100 } });
          rs.items.forEach(x => (map[x.owner_id] = map[x.owner_id] || []).push(x));
          if (p * 100 >= rs.total) break;
        }
        restByOwner = map;
      }
      if (!ok()) return;
      mount(list, table([
        { label: isOwner ? "Chủ quán" : "Sinh viên", render: u => personCell(u) },
        { label: "Số điện thoại", render: u => u.phone || h("span", { class: "muted" }, "—") },
        isOwner ? { label: "Quán", render: u => restSummary(restByOwner[u.id]) } : null,
        { label: "Tham gia", render: u => dt(u.created_at) },
        { label: "Trạng thái", render: u => u.erased_at ? h("span", { class: "badge b-muted" }, "Đã xóa dữ liệu") : badge(u.status === "active" ? "active" : "locked") },
        { label: "", actions: true, render: u => [
          h("button", { class: "sm", onclick: () => (isOwner ? ownerDetail : studentDetail)(u, redraw) }, "Chi tiết"),
          u.erased_at ? null : u.status === "active" ? h("button", { class: "sm danger", onclick: ev => setStatus(ev.currentTarget, u, "locked", redraw) }, "Khóa")
            : h("button", { class: "sm", onclick: ev => setStatus(ev.currentTarget, u, "active", redraw) }, "Mở khóa"),
          deleteButton(u, redraw)] },
      ].filter(Boolean), r.items, isOwner ? "Không có chủ quán phù hợp" : "Không có sinh viên phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    drawChips(); draw();
  }

  // ============================================================ TẤT CẢ TÀI KHOẢN
  function users(main, arg) {
    const seq = startPage();
    let role = ["sinh_vien", "chu_quan", "admin"].includes(arg) ? arg : "", status = arg === "locked" ? "locked" : "", q = "", page = 1;
    const list = h("div", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Tên hoặc email…", "aria-label": "Tìm người dùng" });
    search.oninput = debounced(() => { q = search.value.trim(); page = 1; draw(); });
    const sRole = h("select", { "aria-label": "Vai trò", onchange: e => { role = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi vai trò"), ["sinh_vien", "chu_quan", "admin"].map(x => h("option", { value: x, selected: x === role }, STATUS[x][0])));
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi trạng thái"), h("option", { value: "active" }, "Hoạt động"), h("option", { value: "locked", selected: status === "locked" }, "Bị khóa"),
      h("option", { value: "erased" }, "Đã xóa"));
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, "Tất cả tài khoản"),
      h("p", { class: "small muted", style: "margin:0" }, "Đổi vai trò, khóa / mở khóa mọi tài khoản, kể cả quản trị viên.")),
    h("div", { class: "row" }, search, sRole, sStatus)), list);
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      const erased = status === "erased";
      const r = await api("auth", "/api/users", { query: { role, status: erased ? "" : status, q, page, page_size: 15, erased } });
      if (!ok()) return;
      mount(list, table([
        { label: "Người dùng", render: u => personCell(u) },
        { label: "Số điện thoại", render: u => u.phone || "" },
        { label: "Vai trò", render: u => u.id === me || u.erased_at ? badge(u.role) : h("select", { "aria-label": "Đổi vai trò " + u.email, onchange: e => changeRole(e.target, u, draw) },
          ["sinh_vien", "chu_quan", "admin"].map(x => h("option", { value: x, selected: x === u.role }, STATUS[x][0]))) },
        { label: "Trạng thái", render: u => u.erased_at ? h("span", { class: "badge b-muted" }, "Đã xóa dữ liệu") : badge(u.status === "active" ? "active" : "locked") },
        { label: "Tạo lúc", render: u => dt(u.created_at) },
        { label: "", actions: true, render: u => u.id === me ? h("span", { class: "small muted" }, "Bạn") : [
          u.role !== "admin" ? h("button", { class: "sm", onclick: () => (u.role === "chu_quan" ? ownerDetail : studentDetail)(u, draw) }, "Chi tiết") : null,
          u.erased_at ? null : u.status === "active" ? h("button", { class: "sm danger", onclick: ev => setStatus(ev.currentTarget, u, "locked", draw) }, "Khóa")
            : h("button", { class: "sm", onclick: ev => setStatus(ev.currentTarget, u, "active", draw) }, "Mở khóa"),
          deleteButton(u, draw)] },
      ], r.items, "Không có người dùng phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    draw();
  }

  async function changeRole(sel, u, redraw) {
    const role = sel.value;
    if (!await confirmBox("Đổi vai trò", `Đổi ${u.email} thành ${STATUS[role][0]}? Người này sẽ phải đăng nhập lại.`, "Đổi vai trò")) { sel.value = u.role; return; }
    await act(sel, () => api("auth", `/api/users/${u.id}/role`, { method: "PATCH", body: { role } }), "Đã đổi vai trò").catch(() => {});
    redraw();
  }
  async function changeRoleTo(btn, u, role, done) {
    const note = role === "sinh_vien" ? " Chủ quán còn quán thì phải xóa hoặc chuyển quán trước." : "";
    if (!await confirmBox("Đổi vai trò", `Chuyển ${u.email} thành ${STATUS[role][0].toLowerCase()}? Người này sẽ phải đăng nhập lại.${note}`, "Đổi vai trò")) return;
    try { await act(btn, () => api("auth", `/api/users/${u.id}/role`, { method: "PATCH", body: { role } }), "Đã đổi vai trò"); done(); }
    catch (e) { /* đã báo lỗi */ }
  }
  async function setStatus(btn, u, status, redraw) {
    const locking = status === "locked";
    if (!await confirmBox(locking ? "Khóa tài khoản" : "Mở khóa tài khoản",
      locking ? `Khóa ${u.email}? Tài khoản bị đăng xuất ngay và không đăng nhập được. Đơn cũ vẫn được giữ.` : `Mở khóa ${u.email}?`,
      locking ? "Khóa" : "Mở khóa", locking)) return;
    try { await act(btn, () => api("auth", `/api/users/${u.id}/status`, { method: "PATCH", body: { status } }), locking ? "Đã khóa" : "Đã mở khóa"); }
    catch (e) { return; }
    redraw();
  }

  // ============================================================ QUÁN ĂN
  function restaurants(main, arg) {
    const seq = startPage();
    let status = ["pending", "active", "closed", "locked"].includes(arg) ? arg : "", page = 1, q = "";
    const chips = h("div"), list = h("div", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Tên hoặc địa chỉ…", "aria-label": "Tìm quán" });
    search.oninput = debounced(() => { q = search.value.trim(); page = 1; draw(); });
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, "Quán ăn"),
      h("p", { class: "small muted", style: "margin:0" }, "Duyệt quán mới, khóa quán vi phạm, xem thực đơn và chủ quán.")), search), chips, list);
    const chipTurn = latest(seq);
    const drawChips = () => safe(chips, chipTurn, async ok => {
      const n = await Promise.all(["", "pending", "active", "closed", "locked"].map(s => count("restaurant", "/api/admin/restaurants", s ? { status: s } : {})));
      if (!ok()) return;
      mount(chips, filterChips([["", "Tất cả", n[0]], ["pending", "Chờ duyệt", n[1]], ["active", "Hoạt động", n[2]], ["closed", "Tạm đóng", n[3]],
        ["locked", "Bị khóa", n[4]]], status, v => { status = v; page = 1; drawChips(); draw(); }));
    });
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      if (!Object.keys(userNames).length) await loadNames();
      const r = await api("restaurant", "/api/admin/restaurants", { query: { status, q, page, page_size: 15 } });
      if (!ok()) return;
      const after = () => { drawChips(); draw(); refreshSide(); };
      mount(list, table([
        { label: "Quán", render: x => h("div", { class: "person" },
          restCover(x, "thumb sm"),
          h("div", null, h("strong", null, x.name), h("div", { class: "small muted" }, x.address))) },
        { label: "Chủ quán", render: x => h("button", { class: "linkish", onclick: () => openPerson(x.owner_id, after) }, userNames[x.owner_id] || short(x.owner_id)) },
        { label: "Số món", num: true, render: x => x.item_count },
        { label: "Trạng thái", render: x => [badge(x.status, "restaurant"), x.status_reason ? h("div", { class: "small muted" }, x.status_reason) : null] },
        { label: "Tạo lúc", render: x => dt(x.created_at) },
        { label: "", actions: true, render: x => [h("button", { class: "sm", onclick: () => showMenu(x) }, "Thực đơn"), restActions(x, after)] },
      ], r.items, "Không có quán phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    drawChips(); draw();
  }

  /** Nút duyệt / từ chối / khóa / mở khóa quán. */
  function restActions(x, after) {
    return [
      x.status === "pending" ? h("button", { class: "sm primary", onclick: ev => setRest(ev.currentTarget, x, "active", after) }, "Duyệt") : null,
      x.status === "locked" ? h("button", { class: "sm", onclick: ev => setRest(ev.currentTarget, x, "active", after) }, "Mở khóa") : null,
      x.status !== "locked" ? h("button", { class: "sm danger", onclick: ev => setRest(ev.currentTarget, x, "locked", after) }, x.status === "pending" ? "Từ chối" : "Khóa") : null];
  }

  async function setRest(btn, x, status, redraw) {
    let reason = null;
    if (status === "locked") {
      const input = h("input", { maxlength: 300, placeholder: "VD: Vi phạm an toàn thực phẩm" });
      const ok = await dialog((x.status === "pending" ? "Từ chối " : "Khóa ") + x.name, [h("p", null, "Quán bị ẩn khỏi danh sách công khai và không nhận đơn."), field("Lý do", input)],
        [{ label: "Quay lại", value: false }, { label: "Xác nhận", class: "danger", value: true }]);
      if (!ok) return;
      reason = input.value.trim() || null;
    }
    try {
      await act(btn, () => api("restaurant", `/api/admin/restaurants/${x.id}/status`, { method: "PATCH", body: { status, reason } }),
        status === "active" ? (x.status === "pending" ? "Đã duyệt quán" : "Đã mở khóa quán") : "Đã khóa quán");
    } catch (e) { return; }
    redraw();
  }

  async function showMenu(x) {
    const body = h("div");
    dialog("Thực đơn – " + x.name, body, [{ label: "Đóng" }]);
    load(body, async () => {
      const items = await api("restaurant", `/api/restaurants/${x.id}/menu`, { query: { all: true } });
      mount(body, table([{ label: "Món", render: m => [m.name, m.category ? h("div", { class: "small muted" }, m.category) : null] },
        { label: "Giá", num: true, render: m => money(m.price) }, { label: "Trạng thái", render: m => badge(m.status) }], items, "Quán chưa có món"));
    });
  }

  // ============================================================ ĐƠN HÀNG
  function orders(main, arg) {
    const seq = startPage();
    let status = ["pending", "confirmed", "completed", "cancelled", "pay", "notplaced"].includes(arg) ? arg : "", page = 1, from = "", to = "";
    // chip trạng thái chỉ tính đơn đặt thành công (đã thanh toán); 2 chip riêng cho đơn đang / không thanh toán xong
    const filter = st => st === "pay" ? { status: "pending", payment_status: "unpaid,claimed" }
      : st === "notplaced" ? { payment_status: "void,failed,expired" } : { status: st, payment_status: "paid,refund_due,refunded" };
    const chips = h("div"), list = h("div", { class: "card" });
    const dFrom = h("input", { type: "date", "aria-label": "Từ ngày", onchange: e => { from = e.target.value; page = 1; draw(); } });
    const dTo = h("input", { type: "date", "aria-label": "Đến ngày", onchange: e => { to = e.target.value; page = 1; draw(); } });
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, "Đơn hàng"),
      h("p", { class: "small muted", style: "margin:0" }, "Theo dõi đơn giữa sinh viên và quán; chỉ hủy đơn lỗi. Sinh viên trả tiền trước vào tài khoản của quán.")),
    h("div", { class: "row" }, dFrom, dTo)), chips, list);
    const chipTurn = latest(seq);
    const drawChips = () => safe(chips, chipTurn, async ok => {
      const stats = await api("order", "/api/admin/orders/stats"), b = stats.by_status;
      if (!ok()) return;
      const all = b.pending + b.confirmed + b.completed + b.cancelled;
      mount(chips, filterChips([["", "Tất cả", all], ...["pending", "confirmed", "completed", "cancelled"].map(s => [s, STATUS[s][0], b[s]]),
        ["pay", "Chờ thanh toán", stats.awaiting_payment], ["notplaced", "Không thanh toán xong", stats.not_placed]], status,
        v => { status = v; page = 1; drawChips(); draw(); }));
    });
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      const r = await api("order", "/api/admin/orders", { query: { ...filter(status), date_from: from, date_to: to, page, page_size: 15 } });
      if (!ok()) return;
      mount(list, table([
        { label: "Mã", render: o => h("span", { class: "mono" }, orderCode(o)) },
        { label: "Sinh viên", render: o => h("button", { class: "linkish", onclick: () => openPerson(o.user_id, draw) }, o.customer_name) },
        { label: "Quán", render: o => o.restaurant_name },
        { label: "Tổng", num: true, render: o => money(o.total_price) },
        { label: "Trạng thái", render: o => [orderBadge(o), o.cancelled_by ? h("div", { class: "small muted" }, "Hủy bởi " + (STATUS[o.cancelled_by] || [o.cancelled_by])[0]) : null] },
        { label: "Lúc đặt", render: o => dt(o.created_at) },
        { label: "", actions: true, render: o => [h("button", { class: "sm", onclick: () => orderDetail(o) }, "Chi tiết"),
          ["pending", "confirmed"].includes(o.status) ? h("button", { class: "sm danger", onclick: ev => cancelOrder(ev.currentTarget, o, () => { drawChips(); draw(); }) }, "Hủy đơn") : null] },
      ], r.items, "Không có đơn phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    drawChips(); draw();
  }

  /** Chỉ admin hủy được đơn đã đặt (sinh viên không tự hủy): theo yêu cầu của sinh viên, quán, hoặc đơn lỗi. */
  async function cancelOrder(btn, o, redraw) {
    const input = h("input", { maxlength: 300, placeholder: "VD: Sinh viên nhờ hủy, quán không phản hồi" });
    const chips = ["Sinh viên nhờ hủy", "Quán không phản hồi", "Đơn đặt nhầm", "Đơn lỗi"].map(t =>
      h("button", { type: "button", class: "chip", onclick: () => { input.value = t; input.focus(); } }, t));
    const ok = await dialog("Hủy đơn " + orderCode(o), [
      h("p", null, `${o.restaurant_name} · ${o.customer_name} · ${money(o.total_price)}. Sinh viên và chủ quán đều nhận thông báo kèm lý do.`),
      ["paid", "claimed"].includes(payOf(o)) ? h("div", { class: "notice warn" }, payOf(o) === "paid"
        ? "Đơn đã thanh toán: sau khi hủy, quán phải chuyển trả tiền cho sinh viên (đơn chuyển sang Chờ hoàn tiền)."
        : "Sinh viên đã báo chuyển khoản nhưng quán chưa xác nhận: sau khi hủy, quán kiểm tra tài khoản và hoàn tiền nếu đã nhận.") : null,
      h("div", { class: "chips", style: "margin-bottom:4px" }, chips), field("Lý do", input)],
    [{ label: "Quay lại", value: false }, { label: "Hủy đơn", class: "danger", value: true }]);
    if (!ok) return;
    try {
      await act(btn, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH", body: { status: "cancelled", reason: input.value.trim() || null } }), "Đã hủy đơn");
    } catch (e) { return; }
    redraw();
  }

  function orderDetail(o) {
    const p = o.payment;
    dialog("Đơn " + orderCode(o), [h("div", { class: "row", style: "margin:8px 0" }, orderBadge(o), h("span", { class: "small muted" }, dt(o.created_at))),
      p && p.account ? h("div", { class: "small" }, "Thanh toán: ", payBadge(o), ` ${money(p.amount)} vào ${p.bank_name || p.bank_bin} ${p.account}`,
        p.holder ? ` (${p.holder})` : "", " · nội dung ", h("span", { class: "mono" }, p.note),
        p.claimed_at ? ` · SV báo chuyển ${dt(p.claimed_at)}` : "", p.paid_at ? ` · quán nhận ${dt(p.paid_at)}` : "") : null,
      h("div", { class: "small" }, `${o.customer_name} ${o.customer_phone || ""} – ${o.delivery_address === PICKUP_AT_SHOP ? "tự tới quán lấy" : "mang tới " + o.delivery_address}`),
      h("div", { class: "small muted" }, "Mã hệ thống: ", h("span", { class: "mono" }, o.id)),
      h("div", { class: "small" }, "Quán: " + o.restaurant_name),
      o.note ? h("div", { class: "small" }, "Ghi chú: " + o.note) : null,
      o.cancel_reason ? h("div", { class: "small", style: "color:var(--bad)" }, "Lý do hủy: " + o.cancel_reason) : null,
      table([{ label: "Món", render: i => i.item_name }, { label: "SL", num: true, render: i => i.quantity },
        { label: "Đơn giá", num: true, render: i => money(i.price) }, { label: "Thành tiền", num: true, render: i => money(i.line_total) }], o.items),
      h("div", { class: "row", style: "justify-content:flex-end;margin-top:8px" }, h("strong", null, "Tổng: " + money(o.total_price)))], [{ label: "Đóng" }]);
  }

  // ============================================================ THÔNG BÁO
  function notificationsAdmin(main) {
    const seq = startPage();
    let page = 1;
    const outboxBox = h("div"), list = h("div", { class: "card" });
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, "Thông báo hệ thống"),
      h("p", { class: "small muted", style: "margin:0" }, "Thông báo gửi tới sinh viên và chủ quán; gửi lại thông báo bị lỗi."))),
    outboxBox, h("h3", null, "Thông báo đã gửi"), list);
    const drawOutbox = () => load(outboxBox, async () => {
      const failed = await api("order", "/api/admin/outbox", { query: { status: "failed" } });
      if (stale(seq)) return;
      mount(outboxBox, h("div", { class: "card pad", style: "margin-bottom:16px" },
        h("div", { class: "row" }, h("strong", { class: "grow" }, failed.length ? `${failed.length} thông báo gửi lỗi đang chờ gửi lại` : "Không có thông báo gửi lỗi"),
          h("button", { disabled: !failed.length, onclick: ev => act(ev.currentTarget, () => api("order", "/api/admin/outbox/retry", { method: "POST" }))
            .then(r => { toast(`Gửi lại: ${r.sent} thành công, ${r.failed} lỗi`, r.failed > 0); drawOutbox(); draw(); refreshSide(); }).catch(() => {}) }, "Gửi lại ngay")),
        failed.length ? table([{ label: "Sự kiện", render: e => e.event_key.split(":")[1] }, { label: "Đơn", render: e => "#" + short(e.order_id) },
          { label: "Số lần", num: true, render: e => e.attempts }, { label: "Lỗi gần nhất", render: e => e.last_error || "" }], failed) : null));
    });
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      if (!Object.keys(userNames).length) await loadNames();
      const r = await api("notification", "/api/admin/notifications", { query: { page, page_size: 15 } });
      if (!ok()) return;
      mount(list, table([
        { label: "Người nhận", render: n => userNames[n.user_id] || h("span", { class: "mono" }, short(n.user_id)) },
        { label: "Nội dung", render: n => n.message },
        { label: "Trạng thái", render: n => badge(n.status) },
        { label: "Thời gian", render: n => dt(n.created_at) },
        { label: "", actions: true, render: n => h("button", { class: "sm danger", onclick: async ev => {
          if (!await confirmBox("Xóa thông báo", "Xóa thông báo này?", "Xóa", true)) return;
          act(ev.currentTarget, () => api("notification", `/api/admin/notifications/${n.id}`, { method: "DELETE" }), "Đã xóa").then(draw).catch(() => {});
        } }, "Xóa") },
      ], r.items, "Chưa có thông báo"), pager(r, p => { page = p; draw(); }));
    });
    drawOutbox(); draw();
  }

  // ============================================================ ĐÁNH GIÁ
  function reviews(main, arg) {
    const seq = startPage();
    let status = "", maxRating = arg === "low" ? "2" : "", page = 1;
    const chips = h("div"), list = h("div", { class: "card" });
    const sRating = h("select", { "aria-label": "Số sao", onchange: e => { maxRating = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi số sao"), h("option", { value: "2", selected: maxRating === "2" }, "Từ 2 sao trở xuống"), h("option", { value: "1" }, "Chỉ 1 sao"));
    mount(main, h("div", { class: "head" }, h("div", null, h("h1", null, "Kiểm duyệt đánh giá"),
      h("p", { class: "small muted", style: "margin:0" }, "Đánh giá của sinh viên về quán; ẩn đánh giá vi phạm.")), sRating), chips, list);
    const chipTurn = latest(seq);
    const drawChips = () => safe(chips, chipTurn, async ok => {
      const [all, vis, hid] = await Promise.all([count("review", "/api/admin/reviews"), count("review", "/api/admin/reviews", { status: "visible" }),
        count("review", "/api/admin/reviews", { status: "hidden" })]);
      if (!ok()) return;
      mount(chips, filterChips([["", "Tất cả", all], ["visible", "Đang hiển thị", vis], ["hidden", "Đã ẩn", hid]], status,
        v => { status = v; page = 1; drawChips(); draw(); }));
    });
    const listTurn = latest(seq);
    const draw = () => load(list, async () => {
      const ok = listTurn();
      const r = await api("review", "/api/admin/reviews", { query: { status, max_rating: maxRating, page, page_size: 15 } });
      if (!ok()) return;
      const after = () => { drawChips(); draw(); };
      mount(list, table([
        { label: "Sinh viên", render: v => v.user_id ? h("button", { class: "linkish", onclick: () => openPerson(v.user_id, after) }, v.reviewer_name) : v.reviewer_name },
        { label: "Quán", render: v => v.restaurant_name },
        { label: "Sao", render: v => stars(v.rating) },
        { label: "Nhận xét", render: v => [v.comment || "", v.hidden_reason ? h("div", { class: "small muted" }, "Lý do ẩn: " + v.hidden_reason) : null] },
        { label: "Trạng thái", render: v => badge(v.status) },
        { label: "Thời gian", render: v => dt(v.created_at) },
        { label: "", actions: true, render: v => v.status === "visible"
          ? h("button", { class: "sm danger", onclick: ev => hide(ev.currentTarget, v, after) }, "Ẩn")
          : h("button", { class: "sm", onclick: ev => act(ev.currentTarget, () => api("review", `/api/admin/reviews/${v.id}/status`, { method: "PATCH", body: { status: "visible" } }), "Đã hiện lại").then(after).catch(() => {}) }, "Hiện lại") },
      ], r.items, "Không có đánh giá phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    drawChips(); draw();
  }

  async function hide(btn, v, redraw) {
    const input = h("input", { maxlength: 300, placeholder: "VD: Ngôn từ không phù hợp" });
    const ok = await dialog("Ẩn đánh giá", [h("p", null, "Đánh giá bị ẩn khỏi trang quán và không tính vào điểm trung bình. Sinh viên không thể đánh giá lại đơn này."), field("Lý do", input)],
      [{ label: "Quay lại", value: false }, { label: "Ẩn", class: "danger", value: true }]);
    if (!ok) return;
    try { await act(btn, () => api("review", `/api/admin/reviews/${v.id}/status`, { method: "PATCH", body: { status: "hidden", reason: input.value.trim() || null } }), "Đã ẩn đánh giá"); }
    catch (e) { return; }
    redraw();
  }

  // ============================================================ khởi động
  ui = shell({
    title: "TDTU Food Booking", subtitle: "Quản trị", sidebar: true,
    tabs: [
      { id: "dashboard", label: "Bảng điều khiển" },
      { id: "students", label: "Sinh viên", group: "Người dùng" }, { id: "owners", label: "Chủ quán", group: "Người dùng" },
      { id: "users", label: "Tất cả tài khoản", group: "Người dùng" },
      { id: "restaurants", label: "Quán ăn", group: "Vận hành" }, { id: "orders", label: "Đơn hàng", group: "Vận hành" },
      { id: "reviews", label: "Đánh giá", group: "Vận hành" },
      { id: "notifications", label: "Thông báo", group: "Hệ thống" }, { id: "qr", label: "Mã QR", group: "Hệ thống" },
      { id: "profile", label: "Profile", group: "Hệ thống" }],
    onTab: (id, main, arg) => {
      if (id === "students") return people(main, "sinh_vien", arg);
      if (id === "owners") return people(main, "chu_quan", arg);
      if (id === "qr" || id === "profile") { startPage(); return (id === "qr" ? qrView : profileView)(main); }
      return ({ dashboard, users, restaurants, orders, notifications: notificationsAdmin, reviews })[id](main, arg);
    },
  });
  refreshSide();
  setInterval(refreshSide, 60000);
})();
