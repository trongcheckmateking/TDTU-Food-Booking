"""E2E giao diện bằng Playwright trên hệ thống đang chạy (python manage.py start) với dữ liệu seed.

Chạy:  python -m pytest tests/ui -v      (cần: pip install -r requirements-dev.txt && python -m playwright install chromium)
Biến môi trường: UI_BASE_URL (mặc định http://127.0.0.1:8000), UI_SCREENSHOTS (thư mục lưu ảnh, tùy chọn).
Test tạo dữ liệu mới (đơn, quán) nên chạy trên dữ liệu demo; reset bằng `python manage.py reset-demo --yes`.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = os.environ.get("UI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SHOTS = os.environ.get("UI_SCREENSHOTS")


def _reachable() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
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
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="vi-VN")
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(10000)
        self.errors: list[str] = []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append("console: " + m.text))
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


def test_full_flow_three_roles(browser):
    run = uuid.uuid4().hex[:6]           # mã riêng cho lần chạy: test chạy lại nhiều lần được
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
    sv.page.get_by_placeholder("VD: KTX TDTU, phòng B305").fill("KTX TDTU, phòng B305 (UI test)")
    sv.shot("02_sinhvien_gio")
    sv.page.get_by_role("button", name=re.compile("Đặt hàng · 73.000")).click()
    expect(sv.page.locator(".toast", has_text="Đặt hàng thành công")).to_be_visible()
    sv.page.wait_for_url(re.compile(r"#orders"))
    first_row = sv.page.locator("tbody tr").first
    expect(first_row).to_contain_text("Chờ xác nhận")
    expect(first_row).to_contain_text("73.000")
    order_code = first_row.locator(".mono").inner_text().strip("#")
    sv.shot("03_sinhvien_don")

    # ---- Chủ quán nhận, xác nhận, hoàn thành
    cq = Page(browser)
    cq.login("chuquan1@demo.tdtu.vn", "Demo@123")
    cq.page.wait_for_url(re.compile(r"owner\.html"))
    order_row = cq.page.locator("tbody tr", has_text=order_code)
    expect(order_row).to_contain_text("Chờ xác nhận")
    expect(order_row).to_contain_text("KTX TDTU, phòng B305 (UI test)")
    expect(cq.page.locator("main")).not_to_contain_text("null")
    cq.shot("04_chuquan_don")
    order_row.get_by_role("button", name="Xác nhận").click()
    expect(cq.page.locator(".toast", has_text="Đã xác nhận đơn")).to_be_visible()
    cq.page.select_option("select[aria-label='Trạng thái']", "confirmed")
    cq.page.locator("tbody tr", has_text=order_code).get_by_role("button", name="Hoàn thành").click()
    expect(cq.page.locator(".toast", has_text="Đơn đã hoàn thành")).to_be_visible()
    cq.page.goto(BASE + "/owner.html#notifications")
    expect(cq.page.locator(".noti", has_text=f"#{order_code}").first).to_contain_text("đơn mới")
    # Chủ quán đăng ký quán mới qua form -> chờ duyệt (tên riêng mỗi lần chạy để test chạy lại được)
    new_rest = f"Quán UI {run}"
    cq.page.goto(BASE + "/owner.html#restaurants")
    cq.page.get_by_role("button", name="+ Thêm quán").click()
    dlg = cq.page.locator(".dialog")
    dlg.locator("input").nth(0).fill(new_rest)
    dlg.locator("input").nth(1).fill("Cổng C TDTU, Q7")
    dlg.get_by_role("button", name="Gửi đăng ký").click()
    expect(cq.page.locator("tbody tr", has_text=new_rest)).to_contain_text("Chờ duyệt")

    # ---- Sinh viên nhận thông báo, đánh giá
    sv.page.goto(BASE + "/student.html#notifications")
    expect(sv.page.locator(".noti", has_text=f"Đơn #{order_code} đã hoàn thành")).to_be_visible()
    sv.page.get_by_role("button", name="Đánh dấu tất cả đã đọc").click()
    expect(sv.page.locator(".toast", has_text="Đã đánh dấu tất cả")).to_be_visible()
    sv.page.goto(BASE + "/student.html#orders")
    sv.page.locator("tbody tr", has_text=order_code).get_by_role("button", name="Đánh giá").click()
    sv.page.get_by_role("button", name="4 sao").click()
    sv.page.get_by_placeholder(re.compile("Món ăn, thời gian giao")).fill(f"Kiểm thử giao diện {run}: ngon")
    sv.page.get_by_role("button", name="Gửi đánh giá").click()
    expect(sv.page.locator(".toast", has_text="Cảm ơn bạn đã đánh giá")).to_be_visible()
    expect(sv.page.locator("tbody tr", has_text=order_code)).to_contain_text("Đã đánh giá")

    # ---- Admin: tổng quan, duyệt quán, khóa user, ẩn đánh giá
    ad = Page(browser)
    ad.login("admin@demo.tdtu.vn", "Admin@123")
    ad.page.wait_for_url(re.compile(r"admin\.html"))
    expect(ad.page.locator(".stat", has_text="Đơn hàng").locator(".v")).to_have_text(re.compile(r"^\d+$"))
    expect(ad.page.locator(".badge", has_text="Không phản hồi")).to_have_count(0)
    ad.shot("05_admin_tongquan")
    ad.page.goto(BASE + "/admin.html#restaurants")
    ad.page.locator("tbody tr", has_text=new_rest).get_by_role("button", name="Duyệt").click()
    expect(ad.page.locator(".toast", has_text="Đã duyệt quán")).to_be_visible()
    cq.page.reload()
    expect(cq.page.locator("tbody tr", has_text=new_rest)).to_contain_text("Hoạt động")
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
    tmp.page.click("#fReg button[type=submit]")
    tmp.page.wait_for_url(re.compile(r"student\.html"))
    ad.page.goto(BASE + "/admin.html#users")
    ad.page.get_by_placeholder("Tên hoặc email…").fill(email)
    ad.page.locator("tbody tr", has_text=email).get_by_role("button", name="Khóa").click()
    ad.page.locator(".dialog").get_by_role("button", name="Khóa").click()
    expect(ad.page.locator(".toast", has_text="Đã khóa")).to_be_visible()
    tmp.page.goto(BASE + "/student.html#orders")
    tmp.page.wait_for_url(re.compile(r"index\.html\?(expired|locked)=1"))
    expect(tmp.page.locator(".notice")).to_be_visible()

    errors = sv.errors + cq.errors + ad.errors
    for p in (sv, cq, ad, tmp):
        p.close()
    assert not errors, errors


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
    p.page.goto(BASE + "/student.html#orders")
    expect(p.page.get_by_role("heading", name="Đơn của tôi")).to_be_visible()
    expect(p.page.locator("tbody tr").first).to_be_visible()
    p.shot("07_mobile_don")
    assert p.page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    assert not p.errors, p.errors
    p.close()
