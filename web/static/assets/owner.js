/* Giao diện chủ quán: quản lý quán, menu, xử lý đơn, xem đánh giá, thông báo. */
"use strict";
(() => {
  const session = requireRole("chu_quan");
  if (!session) return;
  let ui;

  const myRestaurants = () => api("restaurant", "/api/restaurants/mine");

  // ------------------------------------------------------------ đơn hàng
  function ordersPage(main) {
    let status = "pending", rid = "", page = 1;
    const list = h("div", { class: "card" }), stats = h("div", { class: "stats" });
    const sStatus = h("select", { "aria-label": "Trạng thái", onchange: e => { status = e.target.value; page = 1; draw(); } },
      h("option", { value: "" }, "Tất cả trạng thái"), ["pending", "confirmed", "completed", "cancelled"].map(s =>
        h("option", { value: s, selected: s === status }, STATUS[s][0])));
    const sRest = h("select", { "aria-label": "Quán", onchange: e => { rid = e.target.value; page = 1; draw(); } }, h("option", { value: "" }, "Tất cả quán"));
    myRestaurants().then(rs => rs.forEach(r => sRest.append(h("option", { value: r.id }, r.name)))).catch(() => {});
    mount(main, h("div", { class: "head" }, h("h1", null, "Đơn hàng"), h("div", { class: "row" }, sRest, sStatus,
      h("button", { onclick: () => draw() }, "Làm mới"))), stats, list);
    const draw = () => load(list, async () => {
      const [r, counts] = await Promise.all([
        api("order", "/api/orders/owner", { query: { status, restaurant_id: rid, page, page_size: 10 } }),
        Promise.all(["pending", "confirmed", "completed"].map(s => api("order", "/api/orders/owner", { query: { status: s, restaurant_id: rid, page_size: 1 } })))]);
      mount(stats, ["pending", "confirmed", "completed"].map((s, i) => h("div", { class: "card stat" },
        h("div", { class: "k" }, STATUS[s][0]), h("div", { class: "v" }, counts[i].total))));
      mount(list, table([
        { label: "Mã đơn", render: o => h("span", { class: "mono" }, "#" + short(o.id)) },
        { label: "Quán", render: o => o.restaurant_name },
        { label: "Khách", render: o => [o.customer_name, o.customer_phone ? h("div", { class: "small muted" }, o.customer_phone) : null] },
        { label: "Món", render: o => [o.items.map(i => `${i.quantity}× ${i.item_name}`).join(", "), o.note ? h("div", { class: "small muted" }, "Ghi chú: " + o.note) : null] },
        { label: "Giao tới", render: o => o.delivery_address },
        { label: "Tổng", num: true, render: o => money(o.total_price) },
        { label: "Trạng thái", render: o => badge(o.status) },
        { label: "Lúc đặt", render: o => dt(o.created_at) },
        { label: "", actions: true, render: o => actions(o, draw) },
      ], r.items, "Không có đơn phù hợp"), r.total > 10 ? pager(r, p => { page = p; draw(); }) : null);
    });
    draw();
  }

  function actions(o, redraw) {
    const set = (btn, st, msg, reason) => act(btn, () => api("order", `/api/orders/${o.id}/status`, { method: "PATCH", body: { status: st, reason } }), msg)
      .then(redraw).catch(e => { if (e.code === "STATUS_CHANGED" || e.code === "INVALID_TRANSITION") redraw(); });
    const cancel = async btn => {
      const reason = h("input", { maxlength: 300, placeholder: "VD: Hết nguyên liệu" });
      const ok = await dialog("Hủy đơn #" + short(o.id), [h("p", null, "Sinh viên sẽ nhận thông báo đơn bị hủy."), field("Lý do", reason)],
        [{ label: "Quay lại", value: false }, { label: "Hủy đơn", class: "danger", value: true }]);
      if (ok) set(btn, "cancelled", "Đã hủy đơn", reason.value.trim() || null);
    };
    if (o.status === "pending") return [h("button", { class: "sm primary", onclick: ev => set(ev.currentTarget, "confirmed", "Đã xác nhận đơn") }, "Xác nhận"),
      h("button", { class: "sm danger", onclick: ev => cancel(ev.currentTarget) }, "Hủy")];
    if (o.status === "confirmed") return [h("button", { class: "sm primary", onclick: ev => set(ev.currentTarget, "completed", "Đơn đã hoàn thành") }, "Hoàn thành"),
      h("button", { class: "sm danger", onclick: ev => cancel(ev.currentTarget) }, "Hủy")];
    return null;
  }

  // ------------------------------------------------------------ quán của tôi
  function restaurantsPage(main) {
    const list = h("div");
    mount(main, h("div", { class: "head" }, h("h1", null, "Quán của tôi"),
      h("button", { class: "primary", onclick: () => restaurantForm(null, draw) }, "+ Thêm quán")), list);
    const draw = () => load(list, async () => {
      const rs = await myRestaurants();
      if (!rs.length) return mount(list, h("div", { class: "card" }, empty("Bạn chưa có quán. Bấm “Thêm quán” để đăng ký, admin sẽ duyệt.")));
      mount(list, h("div", { class: "card" }, table([
        { label: "Tên quán", render: r => [h("strong", null, r.name), h("div", { class: "small muted" }, r.address)] },
        { label: "Giờ mở cửa", render: r => hours(r) },
        { label: "Số món", num: true, render: r => r.item_count },
        { label: "Trạng thái", render: r => [badge(r.status, "restaurant"), r.status_reason ? h("div", { class: "small muted" }, r.status_reason) : null] },
        { label: "", actions: true, render: r => [
          h("button", { class: "sm", onclick: () => location.hash = "#menu/" + r.id }, "Thực đơn"),
          r.status !== "locked" ? h("button", { class: "sm", onclick: () => restaurantForm(r, draw) }, "Sửa") : null,
          r.status === "active" ? h("button", { class: "sm", onclick: ev => setOpen(ev.currentTarget, r, "closed", draw) }, "Tạm đóng") : null,
          r.status === "closed" ? h("button", { class: "sm primary", onclick: ev => setOpen(ev.currentTarget, r, "active", draw) }, "Mở bán") : null,
          h("button", { class: "sm danger", onclick: ev => removeRestaurant(ev.currentTarget, r, draw) }, "Xóa")] },
      ], rs)), h("p", { class: "small muted" }, "Quán mới ở trạng thái “Chờ duyệt” cho tới khi admin duyệt. Quán bị khóa không thể tự mở lại."));
    });
    draw();
  }

  async function setOpen(btn, r, status, redraw) {
    await act(btn, () => api("restaurant", `/api/restaurants/${r.id}`, { method: "PATCH", body: { status } }),
      status === "active" ? "Quán đã mở bán" : "Quán đã tạm đóng").catch(() => {});
    redraw();
  }

  async function removeRestaurant(btn, r, redraw) {
    if (!await confirmBox("Xóa quán", `Xóa “${r.name}”? Quán sẽ không còn hiển thị và không nhận đơn mới. Lịch sử đơn vẫn được giữ.`, "Xóa quán", true)) return;
    await act(btn, () => api("restaurant", `/api/restaurants/${r.id}`, { method: "DELETE" }), "Đã xóa quán").catch(() => {});
    redraw();
  }

  function restaurantForm(r, redraw) {
    const f = {
      name: h("input", { maxlength: 150, value: r ? r.name : "" }),
      address: h("input", { maxlength: 300, value: r ? r.address : "" }),
      description: h("textarea", { maxlength: 1000 }, r && r.description ? r.description : ""),
      open_time: h("input", { type: "time", value: r && r.open_time ? r.open_time : "07:00" }),
      close_time: h("input", { type: "time", value: r && r.close_time ? r.close_time : "21:00" }),
      image_url: h("input", { maxlength: 500, value: r && r.image_url ? r.image_url : "", placeholder: "https://…" }),
    };
    dialog(r ? "Sửa thông tin quán" : "Đăng ký quán mới", [
      field("Tên quán", f.name), field("Địa chỉ", f.address), field("Mô tả", f.description),
      h("div", { class: "row" }, h("div", { class: "grow" }, field("Giờ mở", f.open_time)), h("div", { class: "grow" }, field("Giờ đóng", f.close_time))),
      field("Ảnh (URL, không bắt buộc)", f.image_url)],
      [{ label: "Hủy" }, { label: r ? "Lưu" : "Gửi đăng ký", class: "primary", run: async () => {
        const body = { name: f.name.value, address: f.address.value, description: f.description.value || null,
                       open_time: f.open_time.value || null, close_time: f.close_time.value || null, image_url: f.image_url.value || null };
        if (r) await api("restaurant", `/api/restaurants/${r.id}`, { method: "PATCH", body });
        else await api("restaurant", "/api/restaurants", { method: "POST", body });
        toast(r ? "Đã lưu" : "Đã gửi đăng ký, chờ admin duyệt"); redraw();
      } }]);
  }

  // ------------------------------------------------------------ thực đơn
  function menuPage(main, rid) {
    const list = h("div", { class: "card" });
    const sel = h("select", { "aria-label": "Chọn quán", onchange: e => { location.hash = "#menu/" + e.target.value; } });
    const addBtn = h("button", { class: "primary", disabled: true }, "+ Thêm món");
    mount(main, h("div", { class: "head" }, h("h1", null, "Thực đơn"), h("div", { class: "row" }, sel, addBtn)), list);
    load(list, async () => {
      const rs = await myRestaurants();
      if (!rs.length) return mount(list, empty("Bạn chưa có quán"));
      const r = rs.find(x => x.id === rid) || rs[0];
      mount(sel, rs.map(x => h("option", { value: x.id, selected: x.id === r.id }, x.name)));
      addBtn.disabled = r.status === "locked";
      addBtn.onclick = () => itemForm(r, null, draw);
      const draw = () => load(list, async () => {
        const items = await api("restaurant", `/api/restaurants/${r.id}/menu`, { query: { all: true } });
        mount(list, r.status === "locked" ? h("div", { class: "notice warn", style: "margin:12px" }, "Quán đang bị khóa, không thể sửa thực đơn.") : null,
          table([
            { label: "Món", render: m => [h("strong", null, m.name), m.description ? h("div", { class: "small muted" }, m.description) : null] },
            { label: "Giá", num: true, render: m => money(m.price) },
            { label: "Trạng thái", render: m => badge(m.status) },
            { label: "", actions: true, render: m => r.status === "locked" ? null : [
              m.status !== "available" ? h("button", { class: "sm", onclick: ev => patchItem(ev.currentTarget, m, { status: "available" }, draw) }, "Mở bán") : null,
              m.status === "available" ? h("button", { class: "sm", onclick: ev => patchItem(ev.currentTarget, m, { status: "sold_out" }, draw) }, "Hết món") : null,
              m.status !== "hidden" ? h("button", { class: "sm", onclick: ev => patchItem(ev.currentTarget, m, { status: "hidden" }, draw) }, "Ẩn") : null,
              h("button", { class: "sm", onclick: () => itemForm(r, m, draw) }, "Sửa"),
              h("button", { class: "sm danger", onclick: ev => removeItem(ev.currentTarget, m, draw) }, "Xóa")] },
          ], items, "Quán chưa có món"));
      });
      draw();
    });
  }

  const patchItem = (btn, m, body, redraw) => act(btn, () => api("restaurant", `/api/menu-items/${m.id}`, { method: "PATCH", body }), "Đã cập nhật")
    .then(redraw).catch(() => {});

  async function removeItem(btn, m, redraw) {
    if (!await confirmBox("Xóa món", `Xóa “${m.name}” khỏi thực đơn? Đơn cũ vẫn giữ tên và giá đã đặt.`, "Xóa món", true)) return;
    await act(btn, () => api("restaurant", `/api/menu-items/${m.id}`, { method: "DELETE" }), "Đã xóa món").catch(() => {});
    redraw();
  }

  function itemForm(r, m, redraw) {
    const name = h("input", { maxlength: 150, value: m ? m.name : "" });
    const price = h("input", { type: "number", min: 0, max: 100000000, step: 1000, value: m ? m.price : "" });
    const desc = h("textarea", { maxlength: 1000 }, m && m.description ? m.description : "");
    const status = h("select", null, ["available", "sold_out", "hidden"].map(s => h("option", { value: s, selected: m ? m.status === s : s === "available" }, STATUS[s][0])));
    dialog(m ? "Sửa món" : "Thêm món – " + r.name, [field("Tên món", name), field("Giá (VND)", price, "Số nguyên, ví dụ 35000"),
      field("Mô tả", desc), field("Trạng thái", status)],
      [{ label: "Hủy" }, { label: "Lưu", class: "primary", run: async () => {
        const p = Number(price.value);
        if (!Number.isInteger(p) || p < 0) throw new Error("Giá phải là số nguyên không âm");
        const body = { name: name.value, price: p, description: desc.value || null, status: status.value };
        if (m) await api("restaurant", `/api/menu-items/${m.id}`, { method: "PATCH", body });
        else await api("restaurant", `/api/restaurants/${r.id}/menu`, { method: "POST", body });
        toast("Đã lưu món"); redraw();
      } }]);
  }

  // ------------------------------------------------------------ đánh giá
  function reviewsPage(main) {
    const box = h("div");
    mount(main, h("div", { class: "head" }, h("h1", null, "Đánh giá các quán")), box);
    load(box, async () => {
      const rs = await myRestaurants();
      if (!rs.length) return mount(box, h("div", { class: "card" }, empty("Bạn chưa có quán")));
      const cards = await Promise.all(rs.map(async r => {
        const d = await api("review", `/api/reviews/restaurant/${r.id}`, { auth: false, query: { page_size: 5 } });
        const s = d.summary;
        return h("div", { class: "card", style: "margin-bottom:14px" },
          h("div", { class: "pad row" }, h("h3", { class: "grow" }, r.name),
            s.count ? [h("strong", null, s.average), stars(Math.round(s.average)), h("span", { class: "muted" }, `${s.count} đánh giá`)] : h("span", { class: "muted" }, "Chưa có đánh giá")),
          s.count ? h("div", { class: "pad small muted", style: "padding-top:0" }, [5, 4, 3, 2, 1].map(k => `${k}★: ${s.distribution[k]}`).join(" · ")) : null,
          d.items.map(v => h("div", { class: "noti read" }, h("div", { class: "grow" },
            h("div", { class: "row" }, h("strong", null, v.reviewer_name), stars(v.rating), h("span", { class: "small muted" }, dt(v.created_at))),
            v.comment ? h("div", null, v.comment) : null))));
      }));
      mount(box, cards);
    });
  }
  // Khởi động sau khi mọi hàm/hằng đã được khai báo
  ui = shell({
    title: "TDTU Food Booking", subtitle: "Chủ quán",
    tabs: [{ id: "orders", label: "Đơn hàng" }, { id: "restaurants", label: "Quán của tôi" }, { id: "menu", label: "Thực đơn" },
           { id: "reviews", label: "Đánh giá" }, { id: "notifications", label: "Thông báo" }, { id: "profile", label: "Hồ sơ" }],
    onTab: (id, main, arg) => {
      if (id === "orders") return ordersPage(main);
      if (id === "restaurants") return restaurantsPage(main);
      if (id === "menu") return menuPage(main, arg);
      if (id === "reviews") return reviewsPage(main);
      if (id === "notifications") return notificationsView(main, () => ui.refreshBell());
      if (id === "profile") return profileView(main);
    },
  });
})();
