"""E2E giao diện bằng Playwright trên hệ thống đang chạy (python manage.py start) với dữ liệu seed.

Chạy:  python -m pytest tests/ui -v      (cần: pip install -r requirements-dev.txt && python -m playwright install chromium)
Biến môi trường: UI_BASE_URL (mặc định http://127.0.0.1:8000), UI_SCREENSHOTS (thư mục lưu ảnh, tùy chọn),
UI_IGNORE_HTTPS_ERRORS=1 khi chạy qua gateway Docker có chứng chỉ tự ký (UI_BASE_URL=https://localhost:8443).
Test tạo dữ liệu mới (đơn, quán) nên chạy trên dữ liệu demo; reset bằng `python manage.py reset-demo --yes`.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

# Ảnh PNG 4x3 hợp lệ (màu xanh TDTU) để thử tải ảnh bìa quán / ảnh món
PNG_SMALL = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000040000000308020000003b963991000000104944415478"
                          "9c6310f5980b470c383900de4b0bb9545d06570000000049454e44ae426082")

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = os.environ.get("UI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SHOTS = os.environ.get("UI_SCREENSHOTS")
INSECURE = os.environ.get("UI_IGNORE_HTTPS_ERRORS") == "1"


def _reachable() -> bool:
    import ssl
    import urllib.request
    try:
        ctx = ssl._create_unverified_context() if INSECURE else None
        with urllib.request.urlopen(BASE + "/health", timeout=2, context=ctx) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason=f"UI chưa chạy tại {BASE} (python manage.py start)")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


class Page:
    """Trang có ghi lại lỗi console và request lỗi 5xx/mất kết nối."""
    def __init__(self, browser, viewport=(1366, 900)):
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="vi-VN",
                                       ignore_https_errors=INSECURE)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(10000)
        self.errors: list[str] = []
        # chứng chỉ tự ký (gateway Docker chạy thử): Chrome không cho đăng ký service worker và tự ghi lỗi này
        self.page.on("console", lambda m: m.type == "error" and not (INSECURE and "SSL certificate error" in m.text)
                     and self.errors.append("console: " + m.text))
        self.page.on("pageerror", lambda e: self.errors.append("pageerror: " + str(e)))
        self.page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url}"))
        self.page.on("response", lambda r: r.status >= 500 and self.errors.append(f"HTTP {r.status}: {r.url}"))

    def login(self, email, password):
        self.page.goto(BASE + "/index.html")
        self.page.fill("#lEmail", email)
        self.page.fill("#lPw", password)
        self.page.click("#fLogin button[type=submit]")

    def shot(self, name):
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(SHOTS) / f"{name}.png"), full_page=True)

    def close(self):
        self.ctx.close()


# ---------------------------------------------------------------- xác nhận email bằng OTP
def _cfg(name: str, default: str | None = None) -> str | None:
    """Cấu hình của hệ thống đang chạy: biến môi trường UI_<tên> trước, rồi .env ở thư mục gốc."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from common import config
    return os.environ.get("UI_" + name) or config.get(name, default)


def _http():
    import requests
    s = requests.Session()
    s.trust_env = False
    s.verify = not INSECURE
    return s


def read_otp(email: str) -> str:
    """Mã OTP mới nhất gửi tới email, đọc từ hộp thư của nhà cung cấp email giả lập (GET /api/emails)."""
    r = _http().get(_cfg("MOCK_EMAIL_URL", "http://127.0.0.1:9000").rstrip("/") + "/api/emails",
                    headers={"X-API-Key": _cfg("EMAIL_API_KEY") or ""}, params={"to": email}, timeout=5)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, f"chưa có email nào gửi tới {email}"
    return re.search(r"\b(\d{6})\b", items[0]["content"]).group(1)


def wait_signup_result(p: Page) -> bool:
    """Sau khi bấm Tạo tài khoản: True nếu hiện form nhập mã OTP, False nếu vào thẳng trang (OTP tắt)."""
    for _ in range(100):
        if re.search(r"(student|owner)\.html", p.page.url):
            return False
        try:
            if p.page.locator("#fOtp").is_visible():
                return True
        except Exception:                      # trang đang chuyển: thử lại
            pass
        p.page.wait_for_timeout(100)
    raise AssertionError("không thấy form OTP cũng không chuyển trang sau khi đăng ký")


def finish_signup(p: Page, email: str):
    """OTP bật: nhập mã từ hộp thư rồi vào trang; OTP tắt: đã vào trang luôn."""
    if wait_signup_result(p):
        expect(p.page.locator("#msg")).to_contain_text("Đã gửi mã xác nhận")
        expect(p.page.locator("#oEmail")).to_have_value(email)
        p.page.fill("#oCode", read_otp(email))
        p.page.click("#fOtp button[type=submit]")
    p.page.wait_for_url(re.compile(r"(student|owner)\.html"))


def register_on_page(p: Page, email: str):
    p.page.goto(BASE + "/index.html")
    p.page.click("#tReg")
    p.page.fill("#rName", "Người Kiểm Thử OTP"); p.page.fill("#rEmail", email); p.page.fill("#rPw", "matkhau123")
    p.page.check("#rTerms")
    p.page.click("#fReg button[type=submit]")


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10 ** 6:06d}"


def test_full_flow_three_roles(browser, tmp_path):
    run = uuid.uuid4().hex[:6]           # mã riêng cho lần chạy: test chạy lại nhiều lần được
    png = tmp_path / "anh.png"
    png.write_bytes(PNG_SMALL)
    # ---- Sinh viên đặt món qua giỏ hàng
    sv = Page(browser)
    sv.login("sv1@demo.tdtu.vn", "Demo@123")
    sv.page.wait_for_url(re.compile(r"student\.html"))
    expect(sv.page.get_by_role("heading", name="Quán ăn gần trường")).to_be_visible()
    sv.page.get_by_text("Cơm Tấm Cô Ba").first.click()
    expect(sv.page.get_by_role("heading", name="Thực đơn")).to_be_visible()
    sv.shot("01_sinhvien_menu")
    row = sv.page.locator(".menu-item", has_text="Cơm tấm sườn bì chả")
    row.get_by_role("button", name="Tăng").click()
    row.get_by_role("button", name="Thêm").click()
    expect(sv.page.locator(".toast", has_text="Đã thêm 2")).to_be_visible()
    sv.page.locator(".menu-item", has_text="Trà đá").get_by_role("button", name="Thêm").click()
    expect(sv.page.locator(".card", has_text="Tạm tính")).to_contain_text("73.000")   # 2×35.000 + 3.000
    sold_out = sv.page.locator(".menu-item", has_text="Canh chua cá lóc").get_by_role("button", name="Thêm")
    expect(sold_out).to_be_disabled()
    expect(sv.page.get_by_text("Món thử nghiệm (ẩn)")).to_have_count(0)
    sv.page.get_by_role("button", name="Đặt hàng").first.click()
    sv.page.wait_for_url(re.compile(r"#cart"))
    # mặc định: tự tới quán lấy (ô địa chỉ ẩn); chọn "Nhờ quán mang tới" thì mới phải nhập chỗ nhận
    expect(sv.page.get_by_role("radio", name=re.compile("Tự tới quán lấy"))).to_have_attribute("aria-checked", "true")
    expect(sv.page.get_by_placeholder("VD: KTX TDTU, phòng B305")).to_be_hidden()
    sv.page.get_by_role("radio", name=re.compile("Nhờ quán mang tới")).click()
    expect(sv.page.get_by_placeholder("VD: KTX TDTU, phòng B305")).to_be_visible()
    sv.page.get_by_role("radio", name=re.compile("Tự tới quán lấy")).click()
    sv.shot("02_sinhvien_gio")
    sv.page.get_by_role("button", name=re.compile("Đặt hàng · 73.000")).click()
    # thanh toán trước: mã VietQR chuyển thẳng vào tài khoản của quán, có nút chép số tài khoản / nội dung
    sv.page.wait_for_url(re.compile(r"#pay/"))
    pay = sv.page.locator(".pay-card")
    expect(pay.locator("h1")).to_have_text("Thanh toán để đặt món")
    expect(pay.locator(".pay-amount")).to_contain_text("73.000")
    expect(pay).to_contain_text("TAI KHOAN DEMO")                                 # tài khoản demo: có cảnh báo
    expect(pay.locator(".notice.warn")).to_contain_text("đừng chuyển tiền thật")
    sv.page.wait_for_function("(document.querySelector('.pay-qr img') || {}).naturalWidth > 0")
    order_code = re.search(r"#(\d{3})", pay.locator(".pay-head").inner_text()).group(1)   # mã đơn luôn 3 chữ số
    expect(pay.locator(".pay-row", has_text="Nội dung")).to_contain_text(f"TDTU {order_code}")
    sv.shot("03_sinhvien_thanhtoan")
    pay.get_by_role("button", name="Tôi đã chuyển khoản").click()
    expect(pay.locator("h1")).to_have_text("Chờ quán xác nhận đã nhận tiền")
    sv.page.goto(BASE + "/student.html#orders")
    tile_of = lambda code: sv.page.locator(".order-tile", has=sv.page.locator(".ot-code", has_text=f"#{code}")).filter(has_text="Cơm Tấm Cô Ba")
    first_tile = tile_of(order_code)
    expect(first_tile).to_contain_text("Chờ quán xác nhận đã nhận tiền")
    expect(first_tile).to_contain_text("73.000")
    expect(first_tile.locator(".pickup-box")).to_have_count(0)                   # chưa thanh toán xong: chưa vào bếp
    expect(first_tile.get_by_role("button", name="Hủy")).to_have_count(0)        # sinh viên không tự hủy đơn đã đặt
    # đơn thứ 2: sinh viên chưa bấm "đã chuyển khoản"; quán thấy tiền vẫn xác nhận được, sau đó admin hủy giúp
    sv.page.goto(BASE + "/student.html#restaurants")
    sv.page.get_by_text("Cơm Tấm Cô Ba").first.click()
    sv.page.locator(".menu-item", has_text="Trà đá").get_by_role("button", name="Thêm").click()
    expect(sv.page.locator(".toast", has_text="Đã thêm 1")).to_be_visible()
    sv.page.goto(BASE + "/student.html#cart")
    sv.page.get_by_role("button", name=re.compile("Đặt hàng · 3.000")).click()
    sv.page.wait_for_url(re.compile(r"#pay/"))
    code2 = re.search(r"#(\d{3})", sv.page.locator(".pay-head").inner_text()).group(1)
    sv.page.goto(BASE + "/student.html#orders")
    tile2 = tile_of(code2)
    expect(tile2).to_contain_text("Chưa thanh toán")
    expect(tile2.get_by_role("link", name="Thanh toán")).to_be_visible()

    # ---- Chủ quán: tab Chờ tiền -> Đã nhận tiền -> tab Mới -> nhận đơn -> báo hoàn thành
    cq = Page(browser)
    cq.login("chuquan1@demo.tdtu.vn", "Demo@123")
    cq.page.wait_for_url(re.compile(r"owner\.html"))
    card_of = lambda page, code=None: page.locator(".order-grid:not(.lookup-hits) .order-card",
                                                   has=page.locator(".oc-code", has_text=f"#{code or order_code}"))
    expect(cq.page.locator(".tabs a[data-tab=orders] .tab-count")).to_be_visible()      # đơn đã báo chuyển khoản
    cq.page.goto(BASE + "/owner.html#orders/pay")
    order_card = card_of(cq.page)
    expect(order_card).to_contain_text("Sinh viên báo đã chuyển 73.000")
    expect(order_card).to_contain_text(f"TDTU {order_code}")
    cq.shot("04a_chuquan_chotien")
    order_card.get_by_role("button", name="Đã nhận tiền").click()
    cq.page.locator(".dialog").get_by_role("button", name="Đã nhận tiền").click()
    expect(cq.page.locator(".toast", has_text="Đã xác nhận nhận tiền")).to_be_visible()
    card2 = card_of(cq.page, code2)
    expect(card2).to_contain_text("Chờ sinh viên chuyển 3.000")
    expect(card2.get_by_role("button", name="Chưa nhận được tiền")).to_have_count(0)    # sinh viên chưa báo chuyển
    card2.get_by_role("button", name="Đã nhận tiền").click()
    cq.page.locator(".dialog").get_by_role("button", name="Đã nhận tiền").click()
    expect(cq.page.locator(".toast", has_text="Đã xác nhận nhận tiền")).to_be_visible()
    cq.page.locator(".seg-tabs").get_by_role("link", name=re.compile("^Mới")).click()
    expect(order_card).to_contain_text("Chờ xác nhận")
    expect(order_card).to_contain_text("tự tới quán lấy")
    # sinh viên đang mở Đơn của tôi: tự cập nhật khi quán nhận tiền -> đơn đặt thành công, hiện mã nhận món
    expect(tile_of(order_code)).to_contain_text("Chờ xác nhận", timeout=15000)
    expect(tile_of(order_code).locator(".pickup-box .pickup-code")).to_have_attribute("aria-label", "Mã nhận món " + " ".join(order_code))
    sv.shot("03b_sinhvien_don")
    # sinh viên tới quầy đọc mã: chủ quán gõ mã 3 số là ra đúng đơn
    cq.page.get_by_label("Tìm đơn theo mã nhận món").fill(order_code)
    expect(cq.page.locator(".lookup-hits .order-card").first).to_contain_text("73.000")
    cq.page.get_by_label("Tìm đơn theo mã nhận món").fill("")
    expect(cq.page.locator(".tabs a[data-tab=orders] .tab-count")).to_be_visible()      # số đơn chờ trên tab
    expect(cq.page.locator("main")).not_to_contain_text("null")
    cq.shot("04_chuquan_don")
    order_card.get_by_role("button", name="Nhận đơn").click()
    expect(cq.page.locator(".toast", has_text="Đã nhận đơn")).to_be_visible()
    cq.page.locator(".seg-tabs").get_by_role("link", name=re.compile("Đang làm")).click()
    card_of(cq.page).get_by_role("button", name="Báo hoàn thành").click()
    expect(cq.page.locator(".toast", has_text="Đơn đã hoàn thành")).to_be_visible()
    cq.page.goto(BASE + "/owner.html#notifications")
    expect(cq.page.locator(".noti", has_text=f"#{order_code}").first).to_contain_text("đơn mới")

    # Tổng quan: chỉ số hôm nay + biểu đồ 7 ngày
    cq.page.goto(BASE + "/owner.html#dashboard")
    expect(cq.page.locator(".kpi", has_text="Doanh thu hôm nay").locator(".v")).to_contain_text("đ")
    expect(cq.page.locator(".chart .bar-col")).to_have_count(7)
    cq.shot("04b_chuquan_tongquan")
    # Đăng ký quán mới, chọn nền có sẵn làm ảnh bìa -> chờ duyệt (tên riêng mỗi lần chạy để test chạy lại được)
    new_rest = f"Bún Bò UI {run}"
    cq.page.goto(BASE + "/owner.html#store/new")
    cq.page.get_by_placeholder("VD: Cơm Tấm Cô Ba").fill(new_rest)
    cq.page.get_by_placeholder("VD: 19 Nguyễn Hữu Thọ, Tân Phong, Q7").fill("Cổng C TDTU, Q7")
    pv_img = cq.page.locator(".preview-card .rest-cover img")
    expect(pv_img).to_have_attribute("src", re.compile(r"^data:image/svg"))      # chưa chọn ảnh: nền theo tên quán
    preset = cq.page.get_by_role("button", name="Dùng nền Bún, phở, mì")
    preset.click()
    expect(preset).to_have_attribute("aria-pressed", "true")
    expect(pv_img).to_have_attribute("src", re.compile(r"^blob:"))              # nền đã vẽ thành ảnh, chờ tải lên
    expect(cq.page.locator(".image-picker .dropzone.has-img")).to_be_visible()
    expect(cq.page.locator(".preview-card")).to_contain_text(new_rest)
    cq.shot("04c_chuquan_chon_nen")
    cq.page.get_by_role("button", name="Gửi đăng ký").click()
    expect(cq.page.locator(".toast", has_text="Đã gửi đăng ký")).to_be_visible()
    expect(cq.page.locator("tbody tr", has_text=new_rest)).to_contain_text("Chờ duyệt")
    # Thực đơn của quán mới: thêm món có ảnh + danh mục, sửa giá tại chỗ, báo hết món
    cq.page.goto(BASE + "/owner.html#menu")
    cq.page.get_by_role("button", name="+ Thêm món", exact=True).click()
    dlg = cq.page.locator(".dialog")
    dlg.get_by_placeholder("VD: Cơm tấm sườn bì chả").fill("Trà tắc UI")
    dlg.get_by_placeholder("VD: 35.000").fill("12000")
    expect(dlg.get_by_placeholder("VD: 35.000")).to_have_value("12.000")
    dlg.get_by_placeholder("VD: Món chính, Đồ uống").fill("Đồ uống")
    dlg.locator("input[type=file]").set_input_files(str(png))
    expect(dlg.locator(".dropzone.has-img")).to_be_visible()
    dlg.get_by_role("button", name="Thêm món").click()
    expect(cq.page.locator(".toast", has_text="Đã thêm Trà tắc UI")).to_be_visible()
    row = cq.page.locator(".item-row", has_text="Trà tắc UI")
    expect(cq.page.locator(".cat-head", has_text="Đồ uống")).to_be_visible()
    expect(row.locator(".thumb img")).to_be_visible()
    row.get_by_role("button", name=re.compile("Sửa giá")).click()
    cq.page.get_by_label("Giá bán (đồng)").fill("15000")
    cq.page.get_by_label("Giá bán (đồng)").press("Enter")
    expect(cq.page.locator(".toast", has_text="Đã đổi giá Trà tắc UI")).to_be_visible()
    expect(cq.page.locator(".item-row", has_text="Trà tắc UI")).to_contain_text("15.000")
    cq.page.locator(".item-row", has_text="Trà tắc UI").get_by_role("switch").click()
    expect(cq.page.locator(".toast", has_text="Đã báo hết Trà tắc UI")).to_be_visible()
    expect(cq.page.locator(".item-row", has_text="Trà tắc UI").get_by_role("switch")).to_have_attribute("aria-checked", "false")
    cq.shot("04c_chuquan_thucdon")

    # ---- Sinh viên nhận thông báo, đánh giá
    sv.page.goto(BASE + "/student.html#notifications")
    expect(sv.page.locator(".noti", has_text=f"Đơn #{order_code} đã hoàn thành")).to_be_visible()
    sv.page.get_by_role("button", name="Đánh dấu tất cả đã đọc").click()
    expect(sv.page.locator(".toast", has_text="Đã đánh dấu tất cả")).to_be_visible()
    sv.page.goto(BASE + "/student.html#orders")
    sv.page.locator(".order-tile", has=sv.page.locator(".ot-code", has_text=f"#{order_code}")).get_by_role("button", name="Đánh giá").click()
    sv.page.get_by_role("button", name="4 sao").click()
    sv.page.get_by_placeholder(re.compile("Món ăn, thời gian giao")).fill(f"Kiểm thử giao diện {run}: ngon")
    sv.page.get_by_role("button", name="Gửi đánh giá").click()
    expect(sv.page.locator(".toast", has_text="Cảm ơn bạn đã đánh giá")).to_be_visible()
    expect(sv.page.locator(".order-tile", has=sv.page.locator(".ot-code", has_text=f"#{order_code}"))).to_contain_text("Đã đánh giá")

    # ---- Admin: tổng quan, duyệt quán, khóa user, ẩn đánh giá
    ad = Page(browser)
    ad.login("admin@demo.tdtu.vn", "Admin@123")
    ad.page.wait_for_url(re.compile(r"admin\.html"))
    expect(ad.page.locator(".kpi", has_text="Đơn hàng").locator(".v")).to_have_text(re.compile(r"^\d+$"))
    expect(ad.page.locator(".donut")).to_have_count(3)                       # biểu đồ tỉ lệ: đơn, người dùng, quán
    expect(ad.page.locator(".side-nav a.active")).to_contain_text("Bảng điều khiển")
    expect(ad.page.locator(".badge", has_text="Không phản hồi")).to_have_count(0)
    ad.shot("05_admin_tongquan")
    ad.page.goto(BASE + "/admin.html#restaurants")
    ad.page.locator("tbody tr", has_text=new_rest).get_by_role("button", name="Duyệt").click()
    expect(ad.page.locator(".toast", has_text="Đã duyệt quán")).to_be_visible()
    cq.page.goto(BASE + "/owner.html#store")
    expect(cq.page.locator("tbody tr", has_text=new_rest)).to_contain_text("Hoạt động")
    # Sinh viên thấy đúng nền chủ quán đã chọn (ảnh tải lên Restaurant), quán khác chưa có ảnh thì có nền tượng trưng
    sv.page.goto(BASE + "/student.html#restaurants")
    sv.page.get_by_placeholder("Tìm theo tên quán hoặc địa chỉ…").fill(new_rest)
    card = sv.page.locator(".card.rest", has_text=new_rest)
    expect(card.locator(".rest-cover img")).to_have_attribute("src", re.compile(r"/uploads/[0-9a-f-]+\.jpg$"))
    sv.page.get_by_placeholder("Tìm theo tên quán hoặc địa chỉ…").fill("")
    expect(sv.page.locator(".card.rest").first).to_be_visible()
    assert sv.page.locator(".card.rest").count() == sv.page.locator(".card.rest .rest-cover img").count()
    sv.shot("05b_sinhvien_anh_bia")
    # admin hủy đơn thứ 2 (theo lời nhờ của sinh viên): cả sinh viên và chủ quán được báo
    ad.page.goto(BASE + "/admin.html#orders")
    row = ad.page.locator("tbody tr", has=ad.page.locator(".mono", has_text=f"#{code2}")).filter(has_text="Cơm Tấm Cô Ba").first
    row.get_by_role("button", name="Hủy đơn").click()
    dlg = ad.page.locator(".dialog")
    dlg.get_by_role("button", name="Sinh viên nhờ hủy").click()
    dlg.get_by_role("button", name="Hủy đơn").click()
    expect(ad.page.locator(".toast", has_text="Đã hủy đơn")).to_be_visible()
    sv.page.goto(BASE + "/student.html#orders")
    expect(tile_of(code2)).to_contain_text("Đã hủy")
    expect(tile_of(code2)).to_contain_text("Quán sẽ chuyển trả 3.000")          # đã trả tiền: quán phải hoàn lại
    # chủ quán chuyển trả rồi bấm Đã hoàn tiền -> sinh viên thấy đã hoàn
    cq.page.goto(BASE + "/owner.html#orders/refund")
    cq.page.get_by_label("Chọn quán").select_option("")                        # vừa tạo quán mới: xem tất cả quán
    card_of(cq.page, code2).get_by_role("button", name="Đã hoàn tiền").click()
    cq.page.locator(".dialog").get_by_role("button", name="Đã hoàn tiền").click()
    expect(cq.page.locator(".toast", has_text="quán đã hoàn tiền")).to_be_visible()
    sv.page.reload()
    expect(tile_of(code2)).to_contain_text("Quán đã hoàn 3.000")
    ad.page.goto(BASE + "/admin.html#reviews")
    ad.page.locator("tbody tr", has_text=f"Kiểm thử giao diện {run}").get_by_role("button", name="Ẩn").click()
    ad.page.get_by_placeholder("VD: Ngôn từ không phù hợp").fill("Kiểm thử ẩn")
    ad.page.locator(".dialog").get_by_role("button", name="Ẩn").click()
    expect(ad.page.locator(".toast", has_text="Đã ẩn đánh giá")).to_be_visible()

    # Tạo 1 tài khoản tạm qua form đăng ký rồi để admin khóa -> phiên của tài khoản đó bị đá ra
    tmp = Page(browser)
    tmp.page.goto(BASE + "/index.html")
    tmp.page.click("#tReg")
    email = f"ui{uuid.uuid4().hex[:6]}@student.tdtu.edu.vn"
    tmp.page.fill("#rName", "Người Kiểm Thử"); tmp.page.fill("#rEmail", email); tmp.page.fill("#rPw", "matkhau123")
    tmp.page.click("#fReg button[type=submit]")             # chưa tick đồng ý điều khoản -> báo lỗi, không tạo tài khoản
    expect(tmp.page.locator("#msg")).to_contain_text("Điều khoản sử dụng")
    tmp.page.check("#rTerms")
    tmp.page.click("#fReg button[type=submit]")
    finish_signup(tmp, email)                                # OTP bật: nhập mã gửi qua email rồi mới vào trang
    # tài khoản vừa tạo: màn hướng dẫn nhận món (mã 3 số) hiện ra, đi hết 4 bước
    guide = tmp.page.locator(".guide")
    expect(guide).to_contain_text("Bước 1/4")
    guide.get_by_role("button", name="Tiếp").click()
    expect(guide).to_contain_text("Chuyển khoản trước")                         # bước thanh toán trước
    for _ in range(2):
        guide.get_by_role("button", name="Tiếp").click()
    expect(guide).to_contain_text("Tới quán, đọc 3 số")
    guide.get_by_role("button", name="Bắt đầu đặt món").click()
    expect(tmp.page.locator(".guide-overlay")).to_have_count(0)
    tmp.page.reload()
    expect(tmp.page.get_by_role("heading", name="Quán ăn gần trường")).to_be_visible()
    expect(tmp.page.locator(".guide-overlay")).to_have_count(0)                  # chỉ hiện một lần
    ad.page.goto(BASE + "/admin.html#users")
    ad.page.get_by_placeholder("Tên hoặc email…").fill(email)
    ad.page.locator("tbody tr", has_text=email).get_by_role("button", name="Khóa").click()
    ad.page.locator(".dialog").get_by_role("button", name="Khóa").click()
    expect(ad.page.locator(".toast", has_text="Đã khóa")).to_be_visible()
    tmp.page.goto(BASE + "/student.html#orders")
    tmp.page.wait_for_url(re.compile(r"index\.html\?(expired|locked)=1"))
    expect(tmp.page.locator(".notice")).to_be_visible()

    # Admin xóa tài khoản bằng nút "Xóa" trên hàng, phải gõ lại đúng email; tài khoản đã xóa không còn trong danh sách
    ad.page.locator("tbody tr", has_text=email).get_by_role("button", name=f"Xóa tài khoản {email}").click()
    dlg = ad.page.locator(".dialog")
    dlg.locator("input").fill("sai@email.vn")
    dlg.get_by_role("button", name="Xóa tài khoản").click()
    expect(ad.page.locator(".toast", has_text="Email xác nhận không khớp")).to_be_visible()
    dlg.locator("input").fill(email)
    dlg.get_by_role("button", name="Xóa tài khoản").click()
    expect(ad.page.locator(".toast", has_text="Đã xóa tài khoản")).to_be_visible()
    expect(ad.page.locator("tbody tr", has_text=email)).to_have_count(0)
    ad.page.get_by_placeholder("Tên hoặc email…").fill("Người dùng đã xóa")
    expect(ad.page.locator("tbody tr", has_text="Đã xóa dữ liệu")).to_have_count(0)        # mặc định ẩn tài khoản đã xóa
    ad.page.get_by_label("Trạng thái").select_option("erased")
    expect(ad.page.locator("tbody tr", has_text="Đã xóa dữ liệu").first).to_be_visible()

    errors = sv.errors + cq.errors + ad.errors
    for p in (sv, cq, ad, tmp):
        p.close()
    assert not errors, errors


def test_signup_otp_wrong_code_resend_and_mobile_layout(browser):
    """Điện thoại: đăng ký -> form nhập mã; sai mã báo số lần còn lại; gửi lại quá sớm bị chặn (server trả retry_after,
    nút đếm ngược lại); nhập đúng mã -> vào trang sinh viên. Không có thanh cuộn ngang."""
    p = Page(browser, viewport=(390, 844))
    email = f"uiotp{uuid.uuid4().hex[:6]}@student.tdtu.edu.vn"
    register_on_page(p, email)
    if not wait_signup_result(p):
        p.close()
        pytest.skip("hệ thống đang tắt OTP (OTP_ENABLED=false)")
    expect(p.page.locator("#authTitle")).to_have_text("Xác nhận email")
    expect(p.page.locator("#fLogin")).to_be_hidden()
    expect(p.page.locator("#oResend")).to_be_disabled()                     # vừa gửi: đếm ngược
    expect(p.page.locator("#oResend")).to_contain_text("Gửi lại mã (")
    assert p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    p.shot("08_otp_mobile")
    code = read_otp(email)
    p.page.fill("#oCode", "12ab")                                            # chỉ nhận chữ số, đủ 6 số mới gửi
    expect(p.page.locator("#oCode")).to_have_value("12")
    p.page.click("#fOtp button[type=submit]")
    expect(p.page.locator("#msg")).to_contain_text("Nhập đủ 6 chữ số")
    p.page.fill("#oCode", wrong(code))
    p.page.click("#fOtp button[type=submit]")
    expect(p.page.locator("#msg")).to_contain_text("còn 4 lần thử")
    # bấm gửi lại trước khi hết giờ (bỏ qua nút bị khóa): server từ chối, giao diện đếm ngược theo retry_after
    p.page.evaluate("document.querySelector('#oResend').disabled = false")
    p.page.click("#oResend")
    expect(p.page.locator("#msg")).to_contain_text("Vui lòng chờ")
    expect(p.page.locator("#oResend")).to_be_disabled()
    p.page.fill("#oCode", code)
    p.page.click("#fOtp button[type=submit]")
    p.page.wait_for_url(re.compile(r"student\.html"))
    assert p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    assert not [e for e in p.errors if "HTTP 5" in e or "pageerror" in e], p.errors
    p.close()


def test_login_unverified_account_shows_otp_form(browser):
    """Tài khoản đăng ký nhưng chưa nhập mã: đăng nhập đúng mật khẩu -> hiện form OTP (không vào trang)."""
    p = Page(browser)
    p.page.goto(BASE + "/index.html")
    cfg = p.page.evaluate("window.APP_CONFIG.services.auth")
    auth = cfg if cfg.startswith("http") else BASE + cfg
    email = f"uichua{uuid.uuid4().hex[:6]}@student.tdtu.edu.vn"
    r = _http().post(auth + "/api/users/register", json={"name": "Chưa Xác Nhận", "email": email,
                                                         "password": "matkhau123", "accept_terms": True}, timeout=10)
    assert r.status_code == 201, r.text
    if not r.json().get("verification_required"):
        p.close()
        pytest.skip("hệ thống đang tắt OTP (OTP_ENABLED=false)")
    p.login(email, "matkhau123")
    expect(p.page.locator("#fOtp")).to_be_visible()
    expect(p.page.locator("#msg")).to_contain_text("chưa được xác nhận")
    expect(p.page.locator("#oEmail")).to_have_value(email)
    p.page.click("#oBack")                                                  # quay lại đăng nhập: điền sẵn email
    expect(p.page.locator("#fOtp")).to_be_hidden()
    expect(p.page.locator("#lEmail")).to_have_value(email)
    p.page.fill("#lPw", "matkhau123")
    p.page.click("#fLogin button[type=submit]")
    p.page.fill("#oCode", read_otp(email))
    p.page.click("#fOtp button[type=submit]")
    p.page.wait_for_url(re.compile(r"student\.html"))
    p.close()


def test_session_expired_redirects(browser):
    p = Page(browser)
    p.page.goto(BASE + "/index.html")
    p.page.evaluate("""localStorage.setItem('tdtu_session', JSON.stringify({token:'het-han', user:{role:'sinh_vien',name:'X',email:'x'}}))""")
    p.page.goto(BASE + "/student.html#orders")
    p.page.wait_for_url(re.compile(r"index\.html\?expired=1"))
    expect(p.page.locator(".notice")).to_contain_text("hết hạn")
    p.close()


def test_mobile_layout_no_horizontal_scroll(browser):
    p = Page(browser, viewport=(390, 844))
    p.login("sv2@demo.tdtu.vn", "Demo@123")
    p.page.wait_for_url(re.compile(r"student\.html"))
    expect(p.page.get_by_role("heading", name="Quán ăn gần trường")).to_be_visible()
    p.page.get_by_text("Bún Bò Huế O Hà").first.click()
    expect(p.page.get_by_role("heading", name="Thực đơn")).to_be_visible()
    p.shot("06_mobile_menu")
    overflow = p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"trang tràn ngang {overflow}px"
    # điện thoại: thêm món thì có thanh "Xem giỏ hàng" nổi trên thanh tab, khung giỏ hàng bên phải ẩn
    p.page.locator(".menu-item", has_text="Nước sâm").get_by_role("button", name="Thêm").click()
    bar = p.page.locator(".cart-bar")
    expect(bar).to_be_visible()
    expect(p.page.locator(".cart-side .card")).to_be_hidden()
    bar.click()
    p.page.wait_for_url(re.compile(r"#cart"))
    p.page.get_by_role("button", name="Xóa giỏ").click()
    p.page.locator(".dialog").get_by_role("button", name="Xóa giỏ").click()
    expect(p.page.locator(".toast", has_text="Đã xóa giỏ")).to_be_visible()
    p.page.goto(BASE + "/student.html#orders")
    expect(p.page.get_by_role("heading", name="Đơn của tôi")).to_be_visible()
    expect(p.page.locator(".order-tile").first).to_be_visible()
    p.shot("07_mobile_don")
    assert p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    assert not p.errors, p.errors
    p.close()


def test_legal_pages_csp_and_profile_links(browser):
    p = Page(browser, viewport=(390, 844))
    for path, title in (("/dieu-khoan.html", "Điều khoản sử dụng"), ("/quyen-rieng-tu.html", "Chính sách quyền riêng tư")):
        resp = p.page.goto(BASE + path)
        assert "script-src 'self'" in resp.headers["content-security-policy"], path
        expect(p.page.get_by_role("heading", level=1)).to_have_text(title)
        assert p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1, f"{path} tràn ngang"
    p.shot("08_mobile_quyen_rieng_tu")
    p.login("sv2@demo.tdtu.vn", "Demo@123")
    p.page.wait_for_url(re.compile(r"student\.html"))
    p.page.goto(BASE + "/student.html#profile")
    expect(p.page.locator(".pm-row", has_text="Chính sách quyền riêng tư")).to_be_visible()
    expect(p.page.locator("a[data-tab=profile]")).to_have_text("Profile")
    expect(p.page.locator(".pstat strong").first).to_have_text(re.compile(r"^\d+$"))       # số đơn đã đặt
    # Đổi ảnh đại diện: hiện ở thẻ đầu trang và thanh trên; gỡ ảnh thì trở về chữ cái đầu
    p.page.locator(".profile-hero input[type=file]").set_input_files(
        {"name": "anh.png", "mimeType": "image/png", "buffer": PNG_SMALL})
    expect(p.page.locator(".toast", has_text="Đã đổi ảnh đại diện")).to_be_visible()
    expect(p.page.locator(".topbar .avatar img")).to_have_attribute("src", re.compile(r"/avatars/[0-9a-f]{32}\.jpg$"))
    expect(p.page.locator(".profile-hero .avatar img")).to_be_visible()
    p.shot("09_profile")
    p.page.locator(".pm-row", has_text="Ảnh đại diện").click()
    p.page.locator(".dialog").get_by_role("button", name="Gỡ ảnh").click()
    expect(p.page.locator(".toast", has_text="Đã gỡ ảnh đại diện")).to_be_visible()
    expect(p.page.locator(".topbar .avatar img")).to_have_count(0)
    assert not p.errors, p.errors          # gồm cả lỗi vi phạm CSP (Chromium ghi ra console)
    p.close()


def test_installable_as_phone_app(browser):
    """PWA: có manifest + biểu tượng, service worker đăng ký được, mất mạng thì có trang offline."""
    p = Page(browser, viewport=(390, 844))
    p.page.goto(BASE + "/index.html")
    href = p.page.locator("link[rel=manifest]").get_attribute("href")
    m = p.page.request.get(BASE + "/" + href)
    assert m.headers["content-type"].startswith("application/manifest+json")
    manifest = m.json()
    assert manifest["display"] == "standalone" and manifest["short_name"] == "TDTU Food"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for icon in manifest["icons"]:
        assert p.page.request.get(BASE + icon["src"]).status == 200, icon["src"]
    # trình duyệt chỉ cho service worker chạy trên HTTPS có chứng chỉ hợp lệ hoặc localhost (chứng chỉ tự ký thì không)
    if not INSECURE and (BASE.startswith("http://127.0.0.1") or BASE.startswith("https://")):
        scope = p.page.evaluate("Promise.race([navigator.serviceWorker.ready.then(r => r.scope),"
                                " new Promise(ok => setTimeout(() => ok('timeout'), 10000))])")
        assert scope.rstrip("/") == BASE, scope
    assert p.page.request.get(BASE + "/offline.html").status == 200
    assert not p.errors, p.errors
    p.close()
