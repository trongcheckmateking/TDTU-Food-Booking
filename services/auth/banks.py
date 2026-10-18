"""Ngân hàng nhận tiền qua mã VietQR (chuyển khoản nhanh Napas 247) và chuẩn hóa tên chủ tài khoản.

BIN là mã 6 số Napas cấp cho ngân hàng, nằm trong mã VietQR (tag 38) để ứng dụng ngân hàng của sinh viên biết chuyển
vào ngân hàng nào. Danh sách gồm các ngân hàng phổ biến, đã đối chiếu với danh sách công khai của VietQR.
"""
from __future__ import annotations

import re
import unicodedata

BANKS: list[dict[str, str]] = [
    {"bin": "970436", "code": "VCB", "name": "Vietcombank"},
    {"bin": "970415", "code": "ICB", "name": "VietinBank"},
    {"bin": "970418", "code": "BIDV", "name": "BIDV"},
    {"bin": "970405", "code": "VBA", "name": "Agribank"},
    {"bin": "970407", "code": "TCB", "name": "Techcombank"},
    {"bin": "970422", "code": "MB", "name": "MB Bank"},
    {"bin": "970416", "code": "ACB", "name": "ACB"},
    {"bin": "970432", "code": "VPB", "name": "VPBank"},
    {"bin": "970423", "code": "TPB", "name": "TPBank"},
    {"bin": "970403", "code": "STB", "name": "Sacombank"},
    {"bin": "970437", "code": "HDB", "name": "HDBank"},
    {"bin": "970441", "code": "VIB", "name": "VIB"},
    {"bin": "970443", "code": "SHB", "name": "SHB"},
    {"bin": "970431", "code": "EIB", "name": "Eximbank"},
    {"bin": "970426", "code": "MSB", "name": "MSB"},
    {"bin": "970448", "code": "OCB", "name": "OCB"},
    {"bin": "970440", "code": "SEAB", "name": "SeABank"},
    {"bin": "970449", "code": "LPB", "name": "LPBank"},
    {"bin": "970428", "code": "NAB", "name": "Nam A Bank"},
    {"bin": "970409", "code": "BAB", "name": "Bac A Bank"},
    {"bin": "970427", "code": "VAB", "name": "VietABank"},
    {"bin": "970452", "code": "KLB", "name": "KienlongBank"},
    {"bin": "970412", "code": "PVCB", "name": "PVcomBank"},
    {"bin": "970429", "code": "SCB", "name": "SCB"},
    {"bin": "970454", "code": "VCCB", "name": "BVBank"},
    {"bin": "970425", "code": "ABB", "name": "ABBANK"},
    {"bin": "970419", "code": "NCB", "name": "NCB"},
    {"bin": "970400", "code": "SGICB", "name": "Saigonbank"},
    {"bin": "970430", "code": "PGB", "name": "PGBank"},
    {"bin": "970438", "code": "BVB", "name": "BaoViet Bank"},
    {"bin": "970433", "code": "VIETBANK", "name": "Vietbank"},
    {"bin": "970408", "code": "GPB", "name": "GPBank"},
]
BY_BIN = {b["bin"]: b for b in BANKS}

ACCOUNT = r"^[0-9]{6,19}$"
_HOLDER = re.compile(r"^[A-Z]+( [A-Z]+)*$")


def bank_name(bin_: str | None) -> str | None:
    b = BY_BIN.get(bin_ or "")
    return b["name"] if b else None


def check_bin(v: str) -> str:
    if v not in BY_BIN:
        raise ValueError("ngân hàng không có trong danh sách hỗ trợ (xem GET /api/banks)")
    return v


def normalize_holder(v: str) -> str:
    """Tên chủ tài khoản như ngân hàng in: chữ in hoa không dấu ("Nguyễn Văn Đạt" -> "NGUYEN VAN DAT")."""
    s = unicodedata.normalize("NFD", v.replace("đ", "d").replace("Đ", "D"))
    s = " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").upper().split())
    if not (2 <= len(s) <= 50) or not _HOLDER.match(s):
        raise ValueError("tên chủ tài khoản chỉ gồm chữ cái và khoảng trắng, 2-50 ký tự")
    return s
