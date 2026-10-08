"""Sinh bảng endpoint trong docs/API.md từ docs/openapi/*.json (giữ phần viết tay phía trên dấu mốc)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "API.md"
MARK = "<!-- BẢNG ENDPOINT SINH TỰ ĐỘNG - chạy scripts/gen_api_md.py để cập nhật -->"
PORTS = {"auth": 8001, "restaurant": 8002, "order": 8003, "notification": 8004, "review": 8005}


PUB, OPT, ANY, SV, CQ, AD, INT = ("Công khai", "Công khai (token tùy chọn)", "Đã đăng nhập", "Sinh viên",
                                  "Chủ quán", "Admin", "Nội bộ (X-Internal-Key)")
ROLES = {
    "GET /": PUB, "GET /health": PUB,
    "POST /api/users/register": PUB, "POST /api/users/login": PUB, "GET /api/users/me": ANY,
    "PATCH /api/users/me": ANY, "POST /api/users/logout": ANY, "GET /api/users": AD, "GET /api/users/{user_id}": AD,
    "PATCH /api/users/{user_id}/role": AD, "PATCH /api/users/{user_id}/status": AD,
    "GET /api/restaurants": PUB, "GET /api/restaurants/mine": CQ, "GET /api/restaurants/{rid}": OPT,
    "GET /api/restaurants/{rid}/menu": OPT + "; all=true: chủ quán/admin", "GET /api/menu-items/{mid}": OPT,
    "POST /api/restaurants": CQ, "PATCH /api/restaurants/{rid}": CQ + " (của mình)",
    "DELETE /api/restaurants/{rid}": CQ + " (của mình) / Admin", "POST /api/restaurants/{rid}/menu": CQ + " (của mình)",
    "PATCH /api/menu-items/{mid}": CQ + " (của mình)", "DELETE /api/menu-items/{mid}": CQ + " (của mình)",
    "GET /api/admin/restaurants": AD, "PATCH /api/admin/restaurants/{rid}/status": AD, "POST /internal/quote": INT,
    "GET /internal/owners/{owner_id}/restaurant-count": INT,
    "GET /api/cart": SV, "POST /api/cart/items": SV, "PATCH /api/cart/items/{item_id}": SV,
    "DELETE /api/cart/items/{item_id}": SV, "DELETE /api/cart": SV, "POST /api/orders/checkout": SV,
    "GET /api/orders/me": ANY, "GET /api/orders/owner": CQ, "GET /api/orders/{oid}": "Người đặt / chủ quán của đơn / Admin",
    "PATCH /api/orders/{oid}/status": "Chủ quán của đơn; SV hủy khi pending; Admin chỉ hủy",
    "GET /api/admin/orders": AD, "GET /api/admin/orders/stats": AD, "GET /api/admin/outbox": AD,
    "POST /api/admin/outbox/retry": AD, "GET /internal/orders/{oid}": INT,
    "POST /internal/notifications/events": INT, "GET /api/notifications/me": ANY,
    "PATCH /api/notifications/me/read-all": ANY, "PATCH /api/notifications/{nid}/read": ANY + " (người nhận)",
    "GET /api/admin/notifications": AD, "DELETE /api/admin/notifications/{nid}": AD,
    "POST /api/reviews": SV + " (đơn completed của mình)", "GET /api/reviews/me": ANY, "GET /api/reviews/summary": PUB,
    "GET /api/reviews/restaurant/{rid}": PUB, "GET /api/reviews/restaurant/{rid}/summary": PUB,
    "GET /api/admin/reviews": AD, "PATCH /api/admin/reviews/{review_id}/status": AD,
}


def who(path: str, method: str) -> str:
    key = f"{method.upper()} {path}"
    if key not in ROLES:
        raise SystemExit(f"Chưa khai báo quyền cho {key} trong scripts/gen_api_md.py")
    return ROLES[key]


def main():
    lines = [MARK, ""]
    for svc, port in PORTS.items():
        spec = json.loads((ROOT / "docs" / "openapi" / f"{svc}.json").read_text(encoding="utf-8"))
        lines += [f"### {spec['info']['title']} – cổng {port}", "", "| Method | Đường dẫn | Quyền | Mô tả |", "| --- | --- | --- | --- |"]
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                lines.append(f"| {method.upper()} | `{path}` | {who(path, method)} | {op.get('summary', '')} |")
        lines.append("")
    text = DOC.read_text(encoding="utf-8")
    head = text.split(MARK)[0] if MARK in text else text
    DOC.write_text(head + "\n".join(lines), encoding="utf-8")
    print("Đã cập nhật", DOC)


if __name__ == "__main__":
    main()
