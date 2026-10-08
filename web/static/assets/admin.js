/* Giao diện admin: tổng quan, người dùng, quán, đơn hàng, thông báo, đánh giá. */
"use strict";
(() => {
  const session = requireRole("admin");
  if (!session) return;
  let ui;

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
  const nameOf = id => userNames[id] || h("span", { class: "mono" }, short(id));

  // ------------------------------------------------------------ tổng quan
  function dashboard(main) {
    const health = h("div", { class: "stats" }), stats = h("div", { class: "stats" }), extra = h("div");
    mount(main, h("div", { class: "head" }, h("h1", null, "Tổng quan"), h("button", { onclick: () => dashboard(main) }, "Làm mới")),
      h("h3", null, "Tình trạng service"), health, h("h3", null, "Số liệu"), stats, extra);
    const services = ["auth", "restaurant", "order", "notification", "review"];
    mount(health, services.map(s => {
      const card = h("div", { class: "card stat" }, h("div", { class: "k" }, serviceName(s)), h("div", { class: "small muted" }, "Đang kiểm tra…"));
      const t0 = performance.now();
      fetch(SVC[s] + "/health", { cache: "no-store" }).then(r => r.json().then(d => ({ ok: r.ok && d.status === "ok" })))
        .catch(() => ({ ok: false })).then(({ ok }) => {
          card.lastChild.replaceWith(h("div", null, ok ? badge("active") : h("span", { class: "badge b-bad" }, "Không phản hồi"),
            ok ? h("span", { class: "small muted" }, ` ${Math.round(performance.now() - t0)} ms`) : null));
        });
      return card;
    }));
    // Mỗi chỉ số tải độc lập: service lỗi hiện “—” thay vì số 0
    const stat = (label, fn, sub) => {
      const v = h("div", { class: "v" }, h("span", { class: "spinner" })), s = h("div", { class: "small muted" });
      fn().then(([value, note]) => { v.textContent = value; s.textContent = note || ""; })
        .catch(e => { v.textContent = "—"; s.textContent = "Không tải được: " + e.message; s.style.color = "var(--bad)"; });
      return h("div", { class: "card stat" }, h("div", { class: "k" }, label), v, s);
    };
    const count = (svc, path, query) => api(svc, path, { query: { ...query, page_size: 1 } }).then(r => r.total);
    const orderStats = api("order", "/api/admin/orders/stats");
    mount(stats,
      stat("Người dùng", async () => {
        const [all, sv, cq, locked] = await Promise.all([count("auth", "/api/users"), count("auth", "/api/users", { role: "sinh_vien" }),
          count("auth", "/api/users", { role: "chu_quan" }), count("auth", "/api/users", { status: "locked" })]);
        return [all, `${sv} sinh viên · ${cq} chủ quán · ${locked} bị khóa`];
      }),
      stat("Quán ăn", async () => {
        const [all, pending, locked] = await Promise.all([count("restaurant", "/api/admin/restaurants"),
          count("restaurant", "/api/admin/restaurants", { status: "pending" }), count("restaurant", "/api/admin/restaurants", { status: "locked" })]);
        return [all, `${pending} chờ duyệt · ${locked} bị khóa`];
      }),
      stat("Đơn hàng", async () => { const s = await orderStats; return [s.total, `${s.by_status.pending} chờ xác nhận · ${s.by_status.cancelled} đã hủy`]; }),
      stat("Doanh thu (đơn hoàn thành)", async () => { const s = await orderStats; return [money(s.revenue), `${s.by_status.completed} đơn hoàn thành`]; }),
      stat("Đánh giá", async () => { const [all, hid] = await Promise.all([count("review", "/api/admin/reviews"), count("review", "/api/admin/reviews", { status: "hidden" })]);
        return [all, `${hid} đang bị ẩn`]; }),
      stat("Thông báo gửi lỗi", async () => { const s = await orderStats; return [s.notification_failed, s.notification_failed ? "Xem tab Thông báo để gửi lại" : "Không có"]; }));
    load(extra, async () => {
      const s = await orderStats;
      mount(extra, h("h3", null, "Quán nhiều đơn nhất"), h("div", { class: "card" }, table([
        { label: "Quán", render: r => r.restaurant_name }, { label: "Số đơn", num: true, render: r => r.orders },
        { label: "Doanh thu hoàn thành", num: true, render: r => money(r.revenue) }], s.top_restaurants, "Chưa có đơn")));
    });
  }

  // ------------------------------------------------------------ người dùng
  function users(main) {
    let role = "", status = "", q = "", page = 1;
    const list = h("div", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Tên hoặc email…", "aria-label": "Tìm người dùng" });
    let timer; search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { q = search.value.trim(); page = 1; draw(); }, 300); };
    const sRole = h("select", { "aria-label": "Vai trò", onchange: e => { role = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi vai trò"), ["sinh_vien", "chu_quan", "admin"].map(r => h("option", { value: r }, STATUS[r][0])));
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi trạng thái"), h("option", { value: "active" }, "Hoạt động"), h("option", { value: "locked" }, "Bị khóa"));
    mount(main, h("div", { class: "head" }, h("h1", null, "Người dùng"), h("div", { class: "row" }, search, sRole, sStatus)), list);
    const me = Session.get().user.id;
    const draw = () => load(list, async () => {
      const r = await api("auth", "/api/users", { query: { role, status, q, page, page_size: 15 } });
      mount(list, table([
        { label: "Họ tên", render: u => [h("strong", null, u.name), h("div", { class: "small muted" }, u.email)] },
        { label: "SĐT", render: u => u.phone || "" },
        { label: "Vai trò", render: u => u.id === me ? badge(u.role) : h("select", { "aria-label": "Đổi vai trò", onchange: e => changeRole(e.target, u, draw) },
          ["sinh_vien", "chu_quan", "admin"].map(x => h("option", { value: x, selected: x === u.role }, STATUS[x][0]))) },
        { label: "Trạng thái", render: u => badge(u.status === "active" ? "active" : "locked") },
        { label: "Tạo lúc", render: u => dt(u.created_at) },
        { label: "", actions: true, render: u => u.id === me ? h("span", { class: "small muted" }, "Bạn") :
          u.status === "active" ? h("button", { class: "sm danger", onclick: ev => setStatus(ev.currentTarget, u, "locked", draw) }, "Khóa")
                                : h("button", { class: "sm", onclick: ev => setStatus(ev.currentTarget, u, "active", draw) }, "Mở khóa") },
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
  async function setStatus(btn, u, status, redraw) {
    const locking = status === "locked";
    if (!await confirmBox(locking ? "Khóa tài khoản" : "Mở khóa tài khoản",
      locking ? `Khóa ${u.email}? Tài khoản bị đăng xuất ngay và không đăng nhập được. Đơn cũ vẫn được giữ.` : `Mở khóa ${u.email}?`,
      locking ? "Khóa" : "Mở khóa", locking)) return;
    await act(btn, () => api("auth", `/api/users/${u.id}/status`, { method: "PATCH", body: { status } }), locking ? "Đã khóa" : "Đã mở khóa").catch(() => {});
    redraw();
  }

  // ------------------------------------------------------------ quán ăn
  function restaurants(main) {
    let status = "", page = 1, q = "";
    const list = h("div", { class: "card" });
    const search = h("input", { type: "search", placeholder: "Tên hoặc địa chỉ…", "aria-label": "Tìm quán" });
    let timer; search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { q = search.value.trim(); page = 1; draw(); }, 300); };
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi trạng thái"), h("option", { value: "pending" }, "Chờ duyệt"),
      ["active", "closed", "locked"].map(s => h("option", { value: s }, STATUS[s][0])));
    mount(main, h("div", { class: "head" }, h("h1", null, "Quán ăn"), h("div", { class: "row" }, search, sStatus)), list);
    const draw = () => load(list, async () => {
      if (!Object.keys(userNames).length) await loadNames();
      const r = await api("restaurant", "/api/admin/restaurants", { query: { status, q, page, page_size: 15 } });
      mount(list, table([
        { label: "Quán", render: x => [h("strong", null, x.name), h("div", { class: "small muted" }, x.address)] },
        { label: "Chủ quán", render: x => nameOf(x.owner_id) },
        { label: "Số món", num: true, render: x => x.item_count },
        { label: "Trạng thái", render: x => [badge(x.status, "restaurant"), x.status_reason ? h("div", { class: "small muted" }, x.status_reason) : null] },
        { label: "Tạo lúc", render: x => dt(x.created_at) },
        { label: "", actions: true, render: x => [
          h("button", { class: "sm", onclick: () => showMenu(x) }, "Thực đơn"),
          x.status === "pending" ? h("button", { class: "sm primary", onclick: ev => setRest(ev.currentTarget, x, "active", draw) }, "Duyệt") : null,
          x.status === "locked" ? h("button", { class: "sm", onclick: ev => setRest(ev.currentTarget, x, "active", draw) }, "Mở khóa") : null,
          x.status !== "locked" ? h("button", { class: "sm danger", onclick: ev => setRest(ev.currentTarget, x, "locked", draw) }, x.status === "pending" ? "Từ chối" : "Khóa") : null] },
      ], r.items, "Không có quán phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    draw();
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
    await act(btn, () => api("restaurant", `/api/admin/restaurants/${x.id}/status`, { method: "PATCH", body: { status, reason } }),
      status === "active" ? (x.status === "pending" ? "Đã duyệt quán" : "Đã mở khóa quán") : "Đã khóa quán").catch(() => {});
    redraw();
  }

  async function showMenu(x) {
    const body = h("div");
    dialog("Thực đơn – " + x.name, body, [{ label: "Đóng" }]);
    load(body, async () => {
      const items = await api("restaurant", `/api/restaurants/${x.id}/menu`, { query: { all: true } });
      mount(body, table([{ label: "Món", render: m => m.name }, { label: "Giá", num: true, render: m => money(m.price) },
        { label: "Trạng thái", render: m => badge(m.status) }], items, "Quán chưa có món"));
    });
  }

  // ------------------------------------------------------------ đơn hàng
  function orders(main) {
    let status = "", page = 1, from = "", to = "";
    const list = h("div", { class: "card" });
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi trạng thái"), ["pending", "confirmed", "completed", "cancelled"].map(s => h("option", { value: s }, STATUS[s][0])));
    const dFrom = h("input", { type: "date", "aria-label": "Từ ngày", onchange: e => { from = e.target.value; page = 1; draw(); } });
    const dTo = h("input", { type: "date", "aria-label": "Đến ngày", onchange: e => { to = e.target.value; page = 1; draw(); } });
    mount(main, h("div", { class: "head" }, h("h1", null, "Đơn hàng"), h("div", { class: "row" }, sStatus, dFrom, dTo)), list);
    const draw = () => load(list, async () => {
      const r = await api("order", "/api/admin/orders", { query: { status, date_from: from, date_to: to, page, page_size: 15 } });
      mount(list, table([
        { label: "Mã", render: o => h("span", { class: "mono" }, "#" + short(o.id)) },
        { label: "Sinh viên", render: o => o.customer_name },
        { label: "Quán", render: o => o.restaurant_name },
        { label: "Tổng", num: true, render: o => money(o.total_price) },
        { label: "Trạng thái", render: o => [badge(o.status), o.cancelled_by ? h("div", { class: "small muted" }, "Hủy bởi " + STATUS[o.cancelled_by][0]) : null] },
        { label: "Lúc đặt", render: o => dt(o.created_at) },
        { label: "", actions: true, render: o => [h("button", { class: "sm", onclick: () => orderDetail(o) }, "Chi tiết"),
          ["pending", "confirmed"].includes(o.status) ? h("button", { class: "sm danger", onclick: ev => cancelOrder(ev.currentTarget, o, draw) }, "Hủy đơn lỗi") : null] },
      ], r.items, "Không có đơn phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    draw();
  }

  function orderDetail(o) {
    dialog("Đơn #" + short(o.id), [h("div", { class: "row", style: "margin:8px 0" }, badge(o.status), h("span", { class: "small muted" }, dt(o.created_at))),
      h("div", { class: "small" }, `${o.customer_name} ${o.customer_phone || ""} – giao tới ${o.delivery_address}`),
      o.note ? h("div", { class: "small" }, "Ghi chú: " + o.note) : null,
      o.cancel_reason ? h("div", { class: "small", style: "color:var(--bad)" }, "Lý do hủy: " + o.cancel_reason) : null,
      table([{ label: "Món", render: i => i.item_name }, { label: "SL", num: true, render: i => i.quantity },
        { label: "Đơn giá", num: true, render: i => money(i.price) }, { label: "Thành tiền", num: true, render: i => money(i.line_total) }], o.items),
      h("div", { class: "row", style: "justify-content:flex-end;margin-top:8px" }, h("strong", null, "Tổng: " + money(o.total_price)))], [{ label: "Đóng" }]);
  }

  async function cancelOrder(btn, o, redraw) {
    const input = h("input", { maxlength: 300, placeholder: "VD: Đơn lỗi, quán không phản hồi" });
    const ok = await dialog("Hủy đơn #" + short(o.id), [h("p", null, "Admin chỉ hủy đơn lỗi; sinh viên và chủ quán đều nhận thông báo."), field("Lý do", input)],
      [{ label: "Quay lại", value: false }, { label: "Hủy đơn", class: "danger", value: true }]);
    if (!ok) return;
    await act(btn, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH", body: { status: "cancelled", reason: input.value.trim() || null } }), "Đã hủy đơn").catch(() => {});
    redraw();
  }

  // ------------------------------------------------------------ thông báo
  function notificationsAdmin(main) {
    let page = 1;
    const outboxBox = h("div"), list = h("div", { class: "card" });
    mount(main, h("div", { class: "head" }, h("h1", null, "Thông báo hệ thống")), outboxBox, h("h3", null, "Thông báo đã gửi"), list);
    const drawOutbox = () => load(outboxBox, async () => {
      const failed = await api("order", "/api/admin/outbox", { query: { status: "failed" } });
      mount(outboxBox, h("div", { class: "card pad", style: "margin-bottom:16px" },
        h("div", { class: "row" }, h("strong", { class: "grow" }, failed.length ? `${failed.length} thông báo gửi lỗi đang chờ gửi lại` : "Không có thông báo gửi lỗi"),
          h("button", { disabled: !failed.length, onclick: ev => act(ev.currentTarget, () => api("order", "/api/admin/outbox/retry", { method: "POST" }))
            .then(r => { toast(`Gửi lại: ${r.sent} thành công, ${r.failed} lỗi`, r.failed > 0); drawOutbox(); draw(); }).catch(() => {}) }, "Gửi lại ngay")),
        failed.length ? table([{ label: "Sự kiện", render: e => e.event_key.split(":")[1] }, { label: "Đơn", render: e => "#" + short(e.order_id) },
          { label: "Số lần", num: true, render: e => e.attempts }, { label: "Lỗi gần nhất", render: e => e.last_error || "" }], failed) : null));
    });
    const draw = () => load(list, async () => {
      if (!Object.keys(userNames).length) await loadNames();
      const r = await api("notification", "/api/admin/notifications", { query: { page, page_size: 15 } });
      mount(list, table([
        { label: "Người nhận", render: n => nameOf(n.user_id) },
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

  // ------------------------------------------------------------ đánh giá
  function reviews(main) {
    let status = "", maxRating = "", page = 1;
    const list = h("div", { class: "card" });
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi trạng thái"), h("option", { value: "visible" }, "Đang hiển thị"), h("option", { value: "hidden" }, "Đã ẩn"));
    const sRating = h("select", { "aria-label": "Số sao", onchange: e => { maxRating = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Mọi số sao"), h("option", { value: "2" }, "Từ 2 sao trở xuống"), h("option", { value: "1" }, "Chỉ 1 sao"));
    mount(main, h("div", { class: "head" }, h("h1", null, "Kiểm duyệt đánh giá"), h("div", { class: "row" }, sStatus, sRating)), list);
    const draw = () => load(list, async () => {
      const r = await api("review", "/api/admin/reviews", { query: { status, max_rating: maxRating, page, page_size: 15 } });
      mount(list, table([
        { label: "Sinh viên", render: v => v.reviewer_name },
        { label: "Quán", render: v => v.restaurant_name },
        { label: "Sao", render: v => stars(v.rating) },
        { label: "Nhận xét", render: v => [v.comment || "", v.hidden_reason ? h("div", { class: "small muted" }, "Lý do ẩn: " + v.hidden_reason) : null] },
        { label: "Trạng thái", render: v => badge(v.status) },
        { label: "Thời gian", render: v => dt(v.created_at) },
        { label: "", actions: true, render: v => v.status === "visible"
          ? h("button", { class: "sm danger", onclick: ev => hide(ev.currentTarget, v, draw) }, "Ẩn")
          : h("button", { class: "sm", onclick: ev => act(ev.currentTarget, () => api("review", `/api/admin/reviews/${v.id}/status`, { method: "PATCH", body: { status: "visible" } }), "Đã hiện lại").then(draw).catch(() => {}) }, "Hiện lại") },
      ], r.items, "Không có đánh giá phù hợp"), pager(r, p => { page = p; draw(); }));
    });
    draw();
  }

  async function hide(btn, v, redraw) {
    const input = h("input", { maxlength: 300, placeholder: "VD: Ngôn từ không phù hợp" });
    const ok = await dialog("Ẩn đánh giá", [h("p", null, "Đánh giá bị ẩn khỏi trang quán và không tính vào điểm trung bình. Sinh viên không thể đánh giá lại đơn này."), field("Lý do", input)],
      [{ label: "Quay lại", value: false }, { label: "Ẩn", class: "danger", value: true }]);
    if (!ok) return;
    await act(btn, () => api("review", `/api/admin/reviews/${v.id}/status`, { method: "PATCH", body: { status: "hidden", reason: input.value.trim() || null } }), "Đã ẩn đánh giá").catch(() => {});
    redraw();
  }
  // Khởi động sau khi mọi hàm/hằng đã được khai báo
  ui = shell({
    title: "TDTU Food Booking", subtitle: "Quản trị hệ thống",
    tabs: [{ id: "dashboard", label: "Tổng quan" }, { id: "users", label: "Người dùng" }, { id: "restaurants", label: "Quán ăn" },
           { id: "orders", label: "Đơn hàng" }, { id: "notifications", label: "Thông báo" }, { id: "reviews", label: "Đánh giá" },
           { id: "profile", label: "Hồ sơ" }],
    onTab: (id, main) => ({ dashboard, users, restaurants, orders, notifications: notificationsAdmin, reviews,
                            profile: profileView })[id](main),
  });
})();
