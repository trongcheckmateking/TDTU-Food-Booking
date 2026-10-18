/* Ảnh bìa quán: ảnh chủ quán đã chọn (tải lên Restaurant Service), chưa có thì nền tượng trưng theo loại quán.
   Nền vẽ bằng SVG ngay trên trình duyệt (data: URL, CSP cho phép), không tải gì từ máy chủ khác.
   Chủ quán chọn một nền có sẵn thì nền đó được vẽ thành ảnh JPEG và tải lên như ảnh bìa bình thường,
   nên sinh viên thấy đúng nền chủ quán đã chọn. */
"use strict";

// [nền đậm, nền đậm hơn, nét vẽ sáng] - tông lấy từ bảng màu của giao diện (xanh TĐT, gỗ, đất nung...)
const COVER_PALETTES = {
  blue: ["#15489d", "#0c2f6e", "#dfe8f7"],
  wood: ["#8b5e3c", "#4a3627", "#f6ecdd"],
  terracotta: ["#c2562f", "#7f3519", "#fde7dc"],
  mustard: ["#c98a12", "#7a520a", "#fff1d6"],
  tea: ["#2f7d5b", "#174a35", "#e3f3e9"],
  leaf: ["#4f7d2f", "#2c4a17", "#edf6e2"],
  red: ["#c4161c", "#6e0c10", "#fde4e4"],
  plum: ["#7b3f6e", "#3f1f39", "#f5e6f0"],
};

// Biểu tượng nét (khung 64×64) cho từng loại quán
const COVER_ICONS = {
  com: '<path d="M8 32h48a24 21 0 0 1-48 0z"/><path d="M13 32c1-9 9-14 19-14s18 5 19 14"/><path d="M24 58h16"/>' +
    '<path d="M38 5l17 24M45 3l15 22"/><circle cx="25" cy="25" r="1.6"/><circle cx="33" cy="22" r="1.6"/><circle cx="41" cy="26" r="1.6"/>',
  bun: '<path d="M8 34h48a24 21 0 0 1-48 0z"/><path d="M12 34q4-5 8 0t8 0t8 0t8 0t8 0"/><path d="M24 58h16"/>' +
    '<path d="M24 25q-4-5 0-10t0-10M32 25q-4-5 0-10t0-10M40 25q-4-5 0-10t0-10"/>',
  banhmi: '<path d="M7 45C7 31 38 14 53 17c9 2 8 12-2 19C39 45 13 55 7 45z"/><path d="M21 39l6-8M31 34l6-8M41 28l5-7"/>',
  drink: '<path d="M17 21h30"/><path d="M19 21a13 8 0 0 1 26 0"/><path d="M19 24l4 33h18l4-33"/><path d="M34 13l6-10h7"/>' +
    '<circle cx="27" cy="50" r="2"/><circle cx="33" cy="52" r="2"/><circle cx="38" cy="48" r="2"/><circle cx="30" cy="45" r="2"/>',
  snack: '<path d="M17 30l5 27h20l5-27z"/><path d="M22 30L18 9M28 30V6M34 30V8M40 30l5-20"/><path d="M17 30h30"/>',
  chay: '<path d="M11 53C11 25 31 9 55 9c0 25-15 44-44 44z"/><path d="M13 51L45 19M27 37l-2-9M35 29l-2-9M27 37l9 1M35 29l9 1"/>',
  quan: '<circle cx="32" cy="35" r="17"/><circle cx="32" cy="35" r="10"/><path d="M6 13v14M10 13v14M14 13v14M6 27q4 5 8 0M10 30v27"/>' +
    '<ellipse cx="55" cy="20" rx="4.5" ry="8"/><path d="M55 28v29"/>',
};

const COVER_THEME_PALETTE = { com: "wood", bun: "terracotta", banhmi: "mustard", drink: "tea", snack: "red", chay: "leaf" };

/** Nền có sẵn cho chủ quán chọn: [loại, màu, nhãn] */
const COVER_PRESETS = [
  ["com", "wood", "Cơm"], ["bun", "terracotta", "Bún, phở, mì"], ["banhmi", "mustard", "Bánh mì"],
  ["drink", "tea", "Trà, cà phê"], ["snack", "red", "Ăn vặt"], ["chay", "leaf", "Món chay"],
  ["quan", "blue", "Quán ăn (xanh)"], ["quan", "plum", "Quán ăn (tím)"],
];

/** Đoán loại quán từ tên (bỏ dấu tiếng Việt). */
function coverTheme(name) {
  const s = " " + String(name || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/gi, "d").toLowerCase() + " ";
  if (/\bbanh mi\b/.test(s)) return "banhmi";
  if (/\b(chay)\b/.test(s)) return "chay";
  if (/\b(com|xoi)\b/.test(s)) return "com";
  if (/\b(bun|pho|hu tieu|mi|mien|banh canh|chao|lau)\b/.test(s)) return "bun";
  if (/\b(tra|ca phe|cafe|coffee|sinh to|nuoc|che|kem|smoothie|juice)\b/.test(s)) return "drink";
  if (/\b(an vat|snack|ga ran|xien|khoai|pizza|burger|banh trang|oc)\b/.test(s)) return "snack";
  return "quan";
}

function coverPalette(theme, seed) {
  if (COVER_THEME_PALETTE[theme]) return COVER_THEME_PALETTE[theme];
  const pool = ["blue", "plum", "wood", "terracotta", "tea", "mustard"];
  let n = 0;
  for (const ch of String(seed || "")) n = (n * 31 + ch.codePointAt(0)) >>> 0;
  return pool[n % pool.length];
}

const coverCache = new Map();

/** Nền 1600×900 (16:9) dạng data: URL. Họa tiết nhỏ lặp lại + biểu tượng lớn + nét nghiêng đỏ của TĐT. */
function coverDataUrl(theme, palette) {
  const key = theme + "/" + palette;
  if (coverCache.has(key)) return coverCache.get(key);
  const [c1, c2, ink] = COVER_PALETTES[palette] || COVER_PALETTES.blue;
  const icon = COVER_ICONS[theme] || COVER_ICONS.quan;
  const stroke = (w, op) => `fill="none" stroke="${ink}" stroke-width="${w}" stroke-opacity="${op}" stroke-linecap="round" stroke-linejoin="round"`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient>
<radialGradient id="l" cx=".68" cy=".42" r=".6"><stop offset="0" stop-color="#fff" stop-opacity=".18"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
<pattern id="p" width="190" height="190" patternUnits="userSpaceOnUse" patternTransform="rotate(-14)">
<g transform="translate(28 28) scale(1.5)" ${stroke(2.6, 0.14)}>${icon}</g>
<g transform="translate(122 118) scale(.85)" ${stroke(3.4, 0.1)}>${icon}</g>
</pattern>
</defs>
<rect width="1600" height="900" fill="url(#g)"/>
<rect width="1600" height="900" fill="url(#p)"/>
<rect width="1600" height="900" fill="url(#l)"/>
<circle cx="1060" cy="450" r="320" fill="${ink}" fill-opacity=".08"/>
<circle cx="1060" cy="450" r="245" fill="${ink}" fill-opacity=".12"/>
<g transform="translate(1060 452) scale(6.4) translate(-32 -32)" ${stroke(3.2, 0.95)}>${icon}</g>
<g transform="skewX(-14)"><rect x="330" y="-20" width="40" height="940" fill="#ed252a"/><rect x="392" y="-20" width="12" height="940" fill="${ink}" fill-opacity=".55"/></g>
</svg>`;
  const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  coverCache.set(key, url);
  return url;
}

/** Nền tượng trưng cho một quán (theo tên quán). */
function coverFor(r) {
  const theme = coverTheme(r && r.name);
  return coverDataUrl(theme, coverPalette(theme, r && (r.id || r.name)));
}

/**
 * Khung ảnh bìa quán: ảnh chủ quán tải lên, không có (hoặc tải lỗi) thì nền tượng trưng.
 * cls: lớp CSS của khung (rest-cover, rest-cover shop-cover, store-cover, thumb...).
 */
function restCover(r, cls = "rest-cover", alt = "") {
  const src = imageSrc(r.image_url);
  const art = coverFor(r);
  const box = h("div", { class: cls + (src ? "" : " art") });
  box.append(h("img", { src: src || art, alt, loading: "lazy", referrerpolicy: "no-referrer", decoding: "async",
    onerror: e => { const img = e.currentTarget; if (img.src !== art) { img.src = art; box.classList.add("art"); } } }));
  return box;
}

/** Vẽ một nền có sẵn thành ảnh JPEG 1600×900 để tải lên như ảnh bìa. */
async function coverBlob(theme, palette) {
  const img = new Image();
  img.src = coverDataUrl(theme, palette);
  await img.decode();
  const c = document.createElement("canvas");
  c.width = 1600; c.height = 900;
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  const blob = await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.88));
  if (!blob) throw new Error("Trình duyệt không tạo được ảnh nền, hãy tải ảnh lên");
  return blob;
}
