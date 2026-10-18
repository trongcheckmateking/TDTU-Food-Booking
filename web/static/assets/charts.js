/* Biểu đồ dùng chung (HTML/SVG thuần): cột theo ngày, vòng tỉ lệ, thanh xếp hạng. Màu đã kiểm tra mù màu
   (công cụ validate_palette của kỹ năng dataviz): cột #2563c9; vòng trạng thái vàng / xanh dương / xanh lá / hồng tím. */
"use strict";

const CHART = {
  bar: "#2563c9",
  // trạng thái theo vòng: đang chờ -> đang xử lý -> tốt -> hủy/khóa (cặp kề nhau đạt ΔE mù màu >= 16)
  waiting: "#eda100", working: "#2a78d6", good: "#008300", bad: "#e87ba4",
  // nhóm (identity): 3 ô đầu của bảng màu nhóm, đạt mọi cặp
  cat: ["#2a78d6", "#eb6834", "#1baf7a"],
};

const niceMax = v => {
  if (v <= 0) return 0;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map(m => m * p).find(x => x >= v);
};
const shortMoney = n => n >= 1e6 ? (Math.round(n / 1e5) / 10).toLocaleString("vi-VN") + " tr"
  : n >= 1e3 ? Math.round(n / 1e3).toLocaleString("vi-VN") + "k" : String(Math.round(n));
const pct = (part, total) => (total ? Math.round(part / total * 1000) / 10 : 0);
const pctText = (part, total) => pct(part, total).toLocaleString("vi-VN") + "%";
const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];

/**
 * Biểu đồ cột theo ngày (một màu, cột <= 24px, đầu cột bo 4px). series: [{date, ...}] cũ -> mới, ngày cuối là hôm nay.
 * value(d) số liệu; format / short định dạng đầy đủ / rút gọn; detail(d) dòng phụ trong tooltip;
 * columns: [{label, get}] cột thêm trong bảng cho trình đọc màn hình.
 */
function columnChart(series, { value, format = String, short = format, detail = () => "", columns = [], caption = "Số liệu theo ngày" }) {
  const max = niceMax(Math.max(0, ...series.map(value)));
  const last = series.length - 1;
  const peak = series.reduce((b, d, i) => (value(d) > value(series[b]) ? i : b), 0);
  const every = series.length > 10 ? Math.ceil(series.length / 6) : 1;
  const dayLabel = d => { const [, m, dd] = d.date.split("-"); return `${dd}/${m}`; };
  const wd = d => WEEKDAY[new Date(d.date + "T00:00:00").getDay()];
  const cols = series.map((d, i) => {
    const v = value(d), name = i === last ? "Hôm nay" : `${wd(d)} ${dayLabel(d)}`;
    const extra = detail(d);
    return h("div", { class: "bar-col", role: "listitem", tabindex: series.length <= 10 ? 0 : null, style: `--h:${max ? v / max * 100 : 0}%`,
      "aria-label": `${name}: ${format(v)}${extra ? ", " + extra : ""}` },
    h("div", { class: "bar-area" },
      h("div", { class: "bar" }),
      (i === last || i === peak) && v ? h("span", { class: "bar-val", "aria-hidden": "true" }, short(v)) : null,
      h("div", { class: "bar-tip", "aria-hidden": "true" }, h("strong", null, format(v)), h("span", null, extra ? `${name}, ${extra}` : name))),
    h("span", { class: "bar-x", "aria-hidden": "true" }, i === last ? "Hôm nay" : i % every === 0 ? (series.length > 10 ? dayLabel(d) : wd(d)) : ""));
  });
  return h("div", { class: "chart" },
    // nhãn giữa trục chỉ hiện khi là số tròn (tránh "1 / 1 / 0" khi max = 1)
    h("div", { class: "chart-y", "aria-hidden": "true" }, max ? [h("span", null, short(max)),
      h("span", null, Number.isInteger(max / 2) || max / 2 >= 10 ? short(max / 2) : ""), h("span", null, "0")] : null),
    h("div", { class: "chart-plot" },
      h("div", { class: "chart-grid", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      h("div", { class: "bars", role: "list" }, cols),
      max ? null : h("div", { class: "chart-empty" }, "Chưa có số liệu trong khoảng này")),
    h("table", { class: "sr-only" }, h("caption", null, caption),
      h("thead", null, h("tr", null, h("th", null, "Ngày"), h("th", null, "Giá trị"), columns.map(c => h("th", null, c.label)))),
      h("tbody", null, series.map(d => h("tr", null, h("td", null, d.date), h("td", null, format(value(d))), columns.map(c => h("td", null, c.get(d))))))));
}

/**
 * Biểu đồ vòng cho tỉ lệ của một tổng (<= 6 phần): khe 2px giữa các phần, tổng ở giữa; rê / chạm vào một phần hoặc
 * dòng chú thích thì giữa vòng hiện phần đó. parts: [{label, value, color, href?}]; chú thích là danh sách có số và %.
 */
function donutChart(parts, { totalLabel = "Tổng", format = n => Number(n).toLocaleString("vi-VN") } = {}) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  const NS = "http://www.w3.org/2000/svg", R = 46, C = 2 * Math.PI * R, GAP = parts.filter(p => p.value).length > 1 ? 2 : 0;
  const el = (tag, attrs) => { const n = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); return n; };
  const svg = el("svg", { viewBox: "0 0 120 120", class: "donut-svg", "aria-hidden": "true" });
  svg.append(el("circle", { cx: 60, cy: 60, r: R, fill: "none", stroke: "#efe5d6", "stroke-width": 16 }));
  const big = h("strong", null, format(total)), small = h("span", null, totalLabel);
  const center = h("div", { class: "donut-center" }, big, small);
  const show = p => {
    if (!p) { big.textContent = format(total); small.textContent = totalLabel; return; }
    big.textContent = pctText(p.value, total); small.textContent = `${p.label}: ${format(p.value)}`;
  };
  let offset = 0;
  const segs = parts.map(p => {
    if (!p.value) return null;
    const len = p.value / total * C;
    const vis = Math.max(1, len - GAP);                       // phần rất nhỏ vẫn thấy được
    const seg = el("circle", { cx: 60, cy: 60, r: R, fill: "none", stroke: p.color, "stroke-width": 16, class: "donut-seg",
      "stroke-dasharray": `${vis} ${C - vis}`, "stroke-dashoffset": String(-offset),
      transform: "rotate(-90 60 60)" });
    seg.addEventListener("mouseenter", () => show(p));
    seg.addEventListener("mouseleave", () => show(null));
    offset += len;
    svg.append(seg);
    return seg;
  });
  const legend = h("ul", { class: "donut-legend" }, parts.map((p, i) => {
    const inner = [h("span", { class: "swatch", style: `background:${p.color}`, "aria-hidden": "true" }),
      h("span", { class: "grow" }, p.label), h("span", { class: "num" }, format(p.value)),
      h("span", { class: "num muted small donut-pct" }, pctText(p.value, total))];
    const row = p.href ? h("a", { href: p.href }, inner) : h("span", { class: "donut-row" }, inner);
    const on = () => { show(p); if (segs[i]) segs[i].classList.add("on"); };
    const off = () => { show(null); if (segs[i]) segs[i].classList.remove("on"); };
    row.addEventListener("mouseenter", on); row.addEventListener("mouseleave", off);
    row.addEventListener("focus", on); row.addEventListener("blur", off);
    return h("li", null, row);
  }));
  return h("div", { class: "donut" + (total ? "" : " is-empty") },
    h("div", { class: "donut-ring", role: "img", "aria-label": `${totalLabel}: ${format(total)}. ` +
      parts.map(p => `${p.label} ${format(p.value)} (${pctText(p.value, total)})`).join(", ") }, svg, center),
    legend);
}

/** Danh sách thanh ngang xếp hạng (một màu): rows [{label, value, note?, href?}], độ dài theo giá trị lớn nhất. */
function barList(rows, { format = n => Number(n).toLocaleString("vi-VN"), emptyText = "Chưa có dữ liệu" } = {}) {
  if (!rows.length) return empty(emptyText);
  const max = Math.max(...rows.map(r => r.value)) || 1;
  return h("ol", { class: "bar-list" }, rows.map(r => h("li", null,
    h("div", { class: "row" }, r.href ? h("a", { class: "grow", href: r.href }, r.label) : h("strong", { class: "grow" }, r.label),
      h("span", { class: "num" }, format(r.value))),
    h("div", { class: "meter" }, h("span", { style: `width:${r.value / max * 100}%` })),
    r.note ? h("div", { class: "small muted" }, r.note) : null)));
}
