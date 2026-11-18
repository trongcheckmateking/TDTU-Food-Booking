# -*- coding: utf-8 -*-
"""Sinh sơ đồ ERD, DFD, Use Case của TDTU Food Booking (bản hợp nhất) bằng Graphviz.

Chạy: python docs/diagrams/gen_diagrams.py   (cần Graphviz: lệnh `dot` trong PATH)
Kết quả PNG/SVG ghi vào docs/diagrams/{erd,dfd,usecase}/. Nội dung khớp schema trong services/*.
"""
import os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE
ACTOR = os.path.join(HERE, "actor.png")
FONT = "DejaVu Sans"

# ------------------------------------------------------------------ ERD ----
# PK = khóa chính, FK = khóa ngoại thật (cùng DB), ref = tham chiếu logic sang service khác, UK = duy nhất
ENT = {
    "USERS": [("uuid", "id", "PK"), ("string", "name", ""), ("string", "email", "UK"),
              ("string", "password_hash", ""), ("enum", "role", ""), ("string", "phone", ""),
              ("enum", "status", ""), ("int", "token_version", ""), ("timestamp", "created_at", ""),
              ("timestamp", "updated_at", ""), ("timestamp", "terms_accepted_at", ""), ("timestamp", "erased_at", ""),
              ("string", "avatar_url", ""), ("string", "bank_bin / bank_account / bank_holder", ""),
              ("timestamp", "email_verified_at", "")],
    "LOGIN_ATTEMPTS": [("string", "key (email|IP)", "PK"), ("int", "fails", ""), ("timestamp", "window_start", ""),
                       ("timestamp", "locked_until", "")],
    "OTP_CODES": [("uuid", "id", "PK"), ("uuid", "user_id", "FK"), ("enum", "purpose (verify_email)", ""),
                  ("hex", "code_hash (HMAC, không lưu mã)", ""), ("timestamp", "expires_at", ""), ("int", "attempts", ""),
                  ("timestamp", "used_at", ""), ("timestamp", "created_at", "")],
    "RESTAURANTS": [("uuid", "id", "PK"), ("uuid", "owner_id", "ref"), ("string", "name", ""),
                    ("string", "address", ""), ("string", "description", ""), ("HH:MM", "open_time", ""),
                    ("HH:MM", "close_time", ""), ("string", "image_url", ""), ("enum", "status", ""),
                    ("string", "status_reason", ""), ("timestamp", "created_at / updated_at", ""),
                    ("timestamp", "deleted_at", "")],
    "MENU_ITEMS": [("uuid", "id", "PK"), ("uuid", "restaurant_id", "FK"), ("string", "name", ""),
                   ("int VND", "price", ""), ("string", "description", ""), ("string", "category", ""), ("string", "image_url", ""),
                   ("enum", "status", ""), ("timestamp", "created_at / updated_at", ""), ("timestamp", "deleted_at", "")],
    "MENU_UPDATES": [("uuid", "item_id", "PK, FK"), ("uuid", "restaurant_id", "FK"),
                     ("enum", "kind (new/price/back)", ""), ("int VND", "old_price", ""), ("int VND", "new_price", ""),
                     ("timestamp", "created_at", "")],
    "CARTS": [("uuid", "id", "PK"), ("uuid", "user_id", "ref, UK"), ("uuid", "restaurant_id", "ref"),
              ("timestamp", "updated_at", "")],
    "CART_ITEMS": [("uuid", "id", "PK"), ("uuid", "cart_id", "FK"), ("uuid", "item_id", "ref"),
                   ("int", "quantity", ""), ("timestamp", "added_at", "")],
    "PICKUP_COUNTERS": [("uuid", "restaurant_id", "PK, ref"), ("date", "order_day", "PK"), ("int", "last_no", "")],
    "ORDERS": [("uuid", "id", "PK"), ("string 3 số", "pickup_code", ""), ("uuid", "user_id", "ref"), ("string", "customer_name / phone", ""),
               ("uuid", "restaurant_id", "ref"), ("string", "restaurant_name", ""), ("uuid", "restaurant_owner_id", "ref"),
               ("enum", "status", ""), ("int VND", "total_price", ""), ("string", "delivery_address", ""),
               ("string", "note", ""), ("string", "cancel_reason / cancelled_by", ""),
               ("string", "idempotency_key", "UK*"), ("enum", "payment_method (transfer/cash)", ""),
               ("enum", "payment_status", ""),
               ("string", "pay_bank_bin / pay_account / pay_holder", ""), ("string", "pay_note", ""),
               ("timestamp", "pay_deadline / pay_claimed_at / paid_at", ""), ("timestamp", "created_at / updated_at", "")],
    "ORDER_ITEMS": [("uuid", "id", "PK"), ("uuid", "order_id", "FK"), ("uuid", "item_id", "ref"),
                    ("string", "item_name", ""), ("int", "quantity", ""), ("int VND", "price", ""),
                    ("int VND", "line_total", "")],
    "NOTIFICATION_OUTBOX": [("uuid", "id", "PK"), ("string", "event_key", "UK"), ("uuid", "order_id", "FK"),
                            ("json", "payload", ""), ("enum", "status", ""), ("int", "attempts", ""),
                            ("string", "last_error", ""), ("timestamp", "next_attempt_at / sent_at", "")],
    "NOTIFICATIONS": [("uuid", "id", "PK"), ("uuid", "user_id", "ref"), ("uuid", "order_id", "ref"),
                      ("string", "event_key", "UK*"), ("string", "type", ""), ("string", "message", ""),
                      ("enum", "status", ""), ("timestamp", "created_at / read_at", "")],
    "EMAIL_LOGS": [("uuid", "id", "PK"), ("uuid", "user_id", "ref"), ("string ≤254", "to_email", ""),
                   ("string", "template (otp)", ""), ("enum", "status (sending/sent/delivered/failed)", ""),
                   ("string", "provider_message_id", "UK"), ("string", "idempotency_key", "UK"),
                   ("string", "last_error", ""), ("timestamp", "created_at / updated_at", "")],
    "REVIEWS": [("uuid", "id", "PK"), ("uuid", "user_id", "ref"), ("string", "reviewer_name", ""),
                ("uuid", "restaurant_id", "ref"), ("string", "restaurant_name", ""), ("uuid", "order_id", "ref, UK"),
                ("int 1–5", "rating", ""), ("string ≤1000", "comment", ""), ("enum", "status", ""),
                ("string", "hidden_reason", ""), ("timestamp", "created_at / updated_at", "")],
}
OWNER = {
    "USERS": ("Auth Service (Python · SQLite)", "#DCEBFA"), "LOGIN_ATTEMPTS": ("Auth Service (Python · SQLite)", "#DCEBFA"),
    "OTP_CODES": ("Auth Service (Python · SQLite)", "#DCEBFA"),
    "EMAIL_LOGS": ("Notification Service (Go · PostgreSQL)", "#EFE3F7"),
    "RESTAURANTS": ("Restaurant Service (Node.js · SQLite)", "#E3F4E1"), "MENU_ITEMS": ("Restaurant Service (Node.js · SQLite)", "#E3F4E1"),
    "MENU_UPDATES": ("Restaurant Service (Node.js · SQLite)", "#E3F4E1"),
    "CARTS": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"), "CART_ITEMS": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"),
    "ORDERS": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"), "ORDER_ITEMS": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"),
    "NOTIFICATION_OUTBOX": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"),
    "PICKUP_COUNTERS": ("Order Service (Java Spring Boot · H2)", "#FDEBD3"),
    "NOTIFICATIONS": ("Notification Service (Go · PostgreSQL)", "#EFE3F7"),
    "REVIEWS": ("Review Service (PHP · SQLite)", "#FBE0E0"),
}
CORE = ["USERS", "RESTAURANTS", "MENU_ITEMS", "ORDERS", "ORDER_ITEMS", "NOTIFICATIONS", "REVIEWS"]
REL = [
    ("USERS", "OTP_CODES", "verifies email", "crowodot"),
    ("USERS", "EMAIL_LOGS", "receives email", "crowodot"),
    ("USERS", "RESTAURANTS", "owns", "crowodot"),
    ("USERS", "ORDERS", "places", "crowodot"),
    ("USERS", "CARTS", "has cart", "teeodot"),
    ("USERS", "REVIEWS", "writes", "crowodot"),
    ("USERS", "NOTIFICATIONS", "receives", "crowodot"),
    ("RESTAURANTS", "MENU_ITEMS", "has", "crowodot"),
    ("MENU_ITEMS", "MENU_UPDATES", "announced in", "teeodot"),
    ("RESTAURANTS", "ORDERS", "receives", "crowodot"),
    ("RESTAURANTS", "REVIEWS", "receives", "crowodot"),
    ("CARTS", "CART_ITEMS", "contains", "crowodot"),
    ("MENU_ITEMS", "CART_ITEMS", "in cart", "crowodot"),
    ("ORDERS", "ORDER_ITEMS", "contains", "crowodot"),
    ("MENU_ITEMS", "ORDER_ITEMS", "snapshot of", "crowodot"),
    ("ORDERS", "NOTIFICATION_OUTBOX", "emits", "crowodot"),
    ("ORDERS", "REVIEWS", "reviewed_by", "teeodot"),
    ("ORDERS", "NOTIFICATIONS", "triggers", "crowodot"),
]


def ent_full(name):
    color = OWNER[name][1]
    rows = "".join(
        f'<TR><TD ALIGN="LEFT" BGCOLOR="{"#FFFFFF" if i % 2 == 0 else "#F6F6F6"}">{t}</TD>'
        f'<TD ALIGN="LEFT" BGCOLOR="{"#FFFFFF" if i % 2 == 0 else "#F6F6F6"}">'
        f'{"<B>" + c + "</B>" if k.startswith("PK") else c}</TD>'
        f'<TD BGCOLOR="{"#FFFFFF" if i % 2 == 0 else "#F6F6F6"}"><FONT POINT-SIZE="10">{k or " "}</FONT></TD></TR>'
        for i, (t, c, k) in enumerate(ENT[name]))
    return (f'<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6">'
            f'<TR><TD COLSPAN="3" BGCOLOR="{color}"><B>{name}</B></TD></TR>{rows}</TABLE>>')


def ent_ref(name):
    """Entity thuộc service khác: chỉ hiện khóa chính, viền nét đứt."""
    svc = OWNER[name][0]
    return (f'<<TABLE BORDER="1" STYLE="dashed" CELLBORDER="0" CELLSPACING="0" CELLPADDING="5" COLOR="#888888">'
            f'<TR><TD BGCOLOR="#F2F2F2"><FONT COLOR="#555555"><B>{name}</B></FONT></TD></TR>'
            f'<TR><TD><FONT COLOR="#666666" POINT-SIZE="10">id (PK)</FONT></TD></TR>'
            f'<TR><TD><FONT COLOR="#888888" POINT-SIZE="9"><I>thuộc {svc}</I></FONT></TD></TR></TABLE>>')


def erd(fname, title, own, refs, note=""):
    shown = set(own) | set(refs)
    L = ['digraph G {', f'graph [fontname="{FONT}", rankdir=TB, nodesep=0.7, ranksep=0.9, pad=0.4, '
         f'labelloc=t, fontsize=20, label=<<B>{title}</B>' +
         (f'<BR/><FONT POINT-SIZE="12">{note}</FONT>' if note else '') + '>];',
         f'node [shape=plain, fontname="{FONT}", fontsize=12];',
         f'edge [fontname="{FONT}", fontsize=11, dir=both, arrowtail=teetee, arrowsize=1.1];']
    for n in own:
        L.append(f'{n} [label={ent_full(n)}];')
    for n in refs:
        L.append(f'{n} [label={ent_ref(n)}];')
    for a, b, lab, head in REL:
        if a in shown and b in shown and (a in own or b in own):
            # nét liền = khóa ngoại thật trong cùng DB; nét đứt = tham chiếu logic xuyên service (không có FK)
            style = "solid" if OWNER[a][0] == OWNER[b][0] else "dashed"
            L.append(f'{a} -> {b} [label=" {lab} ", arrowhead={head}, style={style}];')
    L.append('}')
    write_render(os.path.join(OUT, "erd", fname), "\n".join(L))

# ------------------------------------------------------------------ DFD ----
# Ký hiệu Gane-Sarson: tiến trình = hình chữ nhật bo góc có ô số, kho = hình chữ nhật hở phải,
# tác nhân ngoài = hình chữ nhật đậm.


def proc(pid, num, text, color="#FFFFFF"):
    return (f'{pid} [shape=plain, label=<<TABLE BORDER="1.5" STYLE="rounded" CELLBORDER="0" CELLSPACING="0" '
            f'CELLPADDING="6" BGCOLOR="{color}"><TR><TD BORDER="1" SIDES="B"><B>{num}</B></TD></TR>'
            f'<TR><TD>{text}</TD></TR></TABLE>>];')


def store(sid, num, text):
    return (f'{sid} [shape=plain, label=<<TABLE BORDER="0" CELLBORDER="1.5" CELLSPACING="0" CELLPADDING="7">'
            f'<TR><TD SIDES="TBL" BGCOLOR="#F4F4F4"><B>{num}</B></TD><TD SIDES="TB" ALIGN="LEFT">{text}</TD>'
            f'</TR></TABLE>>];')


def ext(eid, text, color="#FFF6D6"):
    return (f'{eid} [shape=box, style="filled", fillcolor="{color}", penwidth=2, '
            f'margin="0.25,0.12", label=<<B>{text}</B>>];')


def dfd(fname, title, body, rankdir="LR", note="", pos=None):
    L = ['digraph G {',
         'graph [layout=neato, splines=true, overlap=true, sep="+12", esep="+6"];' if pos else '',
         f'graph [fontname="{FONT}", rankdir={rankdir}, nodesep=0.55, ranksep=1.1, pad=0.4, '
         f'splines=true, labelloc=t, fontsize=20, label=<<B>{title}</B>' +
         (f'<BR/><FONT POINT-SIZE="12">{note}</FONT>' if note else '') + '>];',
         f'node [fontname="{FONT}", fontsize=12];',
         f'edge [fontname="{FONT}", fontsize=10, arrowsize=0.8, color="#333333"];']
    L += [x for x in body if not (pos and x.startswith('{rank'))]
    for k, (x, y) in (pos or {}).items():
        L.append(f'{k} [pos="{x},{y}!"];')
    L.append('}')
    write_render(os.path.join(OUT, "dfd", fname), "\n".join(L))


def e(a, b, lab, extra=""):
    return f'{a} -> {b} [label=<{lab}>{", " + extra if extra else ""}];'

# -------------------------------------------------------------- USE CASE ---


def usecase(fname, title, system, actors_left, actors_right, cases, links, rels=()):
    L = ['digraph G {', f'graph [fontname="{FONT}", rankdir=LR, nodesep=0.35, ranksep=1.0, pad=0.4, '
         f'labelloc=t, fontsize=20, label=<<B>{title}</B>>];',
         f'node [fontname="{FONT}", fontsize=12];', f'edge [fontname="{FONT}", fontsize=10, arrowhead=none];']
    for a in actors_left + actors_right:
        L.append(f'{a[0]} [shape=none, image="{ACTOR}", labelloc=b, height=1.5, width=0.8, '
                 f'imagescale=true, fixedsize=true, label="{a[1]}"];')
    L.append(f'subgraph cluster_sys {{ label=<<B>{system}</B>>; style="rounded"; penwidth=1.8; '
             f'margin=18; fontsize=14;')
    for cid, text in cases:
        L.append(f'  {cid} [shape=ellipse, style=filled, fillcolor="#EEF4FB", label="{text}"];')
    L.append('}')
    if actors_left:
        L.append('{rank=same; ' + "; ".join(a[0] for a in actors_left) + '}')
    if actors_right:
        L.append('{rank=same; ' + "; ".join(a[0] for a in actors_right) + '}')
    for a, b in links:
        L.append(f'{a} -> {b};')
    for a, b, kind in rels:
        L.append(f'{a} -> {b} [style=dashed, arrowhead=vee, label="«{kind}»", constraint=false];')
    L.append('}')
    write_render(os.path.join(OUT, "usecase", fname), "\n".join(L))


def write_render(path_noext, src):
    with open(path_noext + ".dot", "w", encoding="utf-8") as f:
        f.write(src)
    for fmt in ("png", "svg"):
        args = ["dot", f"-T{fmt}", path_noext + ".dot", "-o", f"{path_noext}.{fmt}"]
        if fmt == "png":
            args.insert(1, "-Gdpi=150")
        subprocess.run(args, check=True)




# =================================================================== BUILD ==
def build_erd():
    erd("ERD_0_tong_the", "ERD tổng thể – TDTU Food Booking (bản hợp nhất)", list(ENT), [],
        "7 bảng lõi + CARTS, CART_ITEMS, NOTIFICATION_OUTBOX, MENU_UPDATES, OTP_CODES, EMAIL_LOGS. Màu = service sở hữu: "
        "xanh dương Auth (Python, SQLite), xanh lá Restaurant (Node.js, SQLite), cam Order (Java Spring Boot, H2), "
        "tím Notification (Go, PostgreSQL), hồng Review (PHP, SQLite). Nét liền = FK thật cùng DB; "
        "nét đứt = tham chiếu logic xuyên service (không có FK)")
    erd("ERD_1_auth", "ERD – Auth Service (Python · SQLite)", ["USERS", "LOGIN_ATTEMPTS", "OTP_CODES"],
        ["RESTAURANTS", "ORDERS", "CARTS", "REVIEWS", "NOTIFICATIONS", "EMAIL_LOGS"],
        "Sở hữu USERS. status active/locked; token_version tăng khi khóa, đổi vai trò, đăng xuất → token cũ hết hiệu lực. "
        "LOGIN_ATTEMPTS: đếm đăng nhập sai theo email + IP để tạm khóa. OTP_CODES: mã xác nhận email chỉ lưu HMAC, "
        "sai đủ OTP_MAX_ATTEMPTS lần thì khóa mã; email_verified_at = đã xác nhận")
    erd("ERD_2_restaurant", "ERD – Restaurant Service (Node.js · SQLite)", ["RESTAURANTS", "MENU_ITEMS", "MENU_UPDATES"], ["USERS"],
        "status quán: pending / active / closed / locked; món: available / sold_out / hidden; xóa = deleted_at. "
        "MENU_UPDATES = bảng tin món mới, mỗi món một tin (thêm món, đổi giá, bán lại)")
    erd("ERD_3_order", "ERD – Order Service (Java Spring Boot · H2)", ["CARTS", "CART_ITEMS", "ORDERS", "ORDER_ITEMS", "NOTIFICATION_OUTBOX", "PICKUP_COUNTERS"],
        ["USERS", "RESTAURANTS", "MENU_ITEMS"],
        "Đơn lưu ảnh chụp tên quán, tên món, đơn giá. UK* = UNIQUE(user_id, idempotency_key)")
    erd("ERD_4_notification", "ERD – Notification Service (Go · PostgreSQL)", ["NOTIFICATIONS", "EMAIL_LOGS"], ["USERS", "ORDERS"],
        "UK* = UNIQUE(event_key, user_id): gửi lại cùng sự kiện không tạo thông báo trùng. EMAIL_LOGS: email gửi qua nhà "
        "cung cấp (không lưu mã OTP); idempotency_key UNIQUE chống gửi trùng, provider_message_id để webhook cập nhật")
    erd("ERD_5_review", "ERD – Review Service (PHP · SQLite)", ["REVIEWS"], ["USERS", "RESTAURANTS", "ORDERS"],
        "Mỗi đơn tối đa 1 đánh giá (order_id UNIQUE); admin ẩn (status=hidden) thay vì xóa")


def build_dfd():
    b = [ext("SV", "Sinh viên"), ext("CQ", "Chủ quán"), ext("AD", "Admin"),
         'P0 [shape=circle, width=2.6, fixedsize=true, style=filled, fillcolor="#DCEBFA", penwidth=2, '
         'label=<<B>0</B><BR/>Hệ thống<BR/>TDTU Food Booking>];',
         e("SV", "P0", "Đăng ký/đăng nhập, giỏ hàng,<BR/>đặt món, hủy đơn, đánh giá"),
         e("P0", "SV", "Token, quán/menu, giỏ, trạng thái<BR/>đơn, thông báo, điểm đánh giá"),
         e("CQ", "P0", "Đăng ký quán, menu, giá,<BR/>xác nhận/hoàn thành/hủy đơn"),
         e("P0", "CQ", "Đơn mới, thông báo,<BR/>đánh giá của quán"),
         e("AD", "P0", "Duyệt/khóa quán, khóa/đổi vai trò user,<BR/>hủy đơn lỗi, ẩn đánh giá, gửi lại thông báo"),
         e("P0", "AD", "Thống kê, danh sách<BR/>user/quán/đơn/đánh giá"),
         '{rank=same; CQ; AD}']
    dfd("DFD_0_ngu_canh", "DFD mức 0 – Sơ đồ ngữ cảnh", b, rankdir="TB")

    C = {"1": "#DCEBFA", "2": "#E3F4E1", "3": "#FDEBD3", "4": "#EFE3F7", "5": "#FBE0E0"}
    b = [ext("SV", "Sinh viên"), ext("CQ", "Chủ quán"), ext("AD", "Admin"),
         proc("P1", "1.0", "Quản lý tài khoản<BR/>&amp; xác thực<BR/><I>(Auth Service)</I><BR/><FONT POINT-SIZE='9'>Python · SQLite</FONT>", C["1"]),
         proc("P2", "2.0", "Quản lý quán<BR/>&amp; menu<BR/><I>(Restaurant Service)</I><BR/><FONT POINT-SIZE='9'>Node.js · SQLite</FONT>", C["2"]),
         proc("P3", "3.0", "Giỏ hàng<BR/>&amp; đơn hàng<BR/><I>(Order Service)</I><BR/><FONT POINT-SIZE='9'>Java Spring Boot · H2</FONT>", C["3"]),
         proc("P4", "4.0", "Quản lý<BR/>thông báo<BR/><I>(Notification Service)</I><BR/><FONT POINT-SIZE='9'>Go · PostgreSQL</FONT>", C["4"]),
         proc("P5", "5.0", "Quản lý<BR/>đánh giá<BR/><I>(Review Service)</I><BR/><FONT POINT-SIZE='9'>PHP · SQLite</FONT>", C["5"]),
         store("D1", "D1", "USERS"), store("D2", "D2", "RESTAURANTS"), store("D3", "D3", "MENU_ITEMS"),
         store("D4", "D4", "ORDERS, ORDER_ITEMS"), store("D5", "D5", "CARTS, CART_ITEMS"),
         store("D8", "D8", "NOTIFICATION_OUTBOX"), store("D6", "D6", "NOTIFICATIONS"), store("D7", "D7", "REVIEWS"),
         e("SV", "P1", "Đăng ký,<BR/>đăng nhập"), e("CQ", "P1", "Đăng ký,<BR/>đăng nhập"),
         e("P1", "SV", "Token", 'style=dashed'), e("P1", "D1", "User"), e("D1", "P1", "TT user"),
         e("AD", "P1", "Khóa / đổi<BR/>vai trò"), e("P1", "AD", "DS user"),
         e("CQ", "P2", "Quán, món, giá"), e("P2", "SV", "DS quán, menu"),
         e("P2", "D2", "Quán"), e("P2", "D3", "Món"), e("D3", "P2", "Menu"),
         e("AD", "P2", "Duyệt / khóa quán"),
         e("P1", "P2", "User + role<BR/>(xác thực token)", 'style=dashed, color="#1f5fa8"'),
         e("SV", "P3", "Giỏ hàng,<BR/>checkout"), e("P3", "SV", "Trạng thái đơn"),
         e("CQ", "P3", "Xác nhận /<BR/>hoàn thành / hủy"), e("AD", "P3", "Hủy đơn lỗi"),
         e("P2", "P3", "Báo giá nội bộ<BR/>(giá, tên món, chủ quán)"),
         e("P3", "D4", "Đơn + ảnh chụp giá"), e("P3", "D5", "Giỏ"), e("P3", "D8", "Sự kiện"), e("D8", "P3", "Sự kiện<BR/>chờ gửi"),
         e("P1", "P3", "User + role", 'style=dashed, color="#1f5fa8"'),
         e("P3", "P4", "Sự kiện đơn<BR/>(nội bộ, gửi lại<BR/>khi lỗi)"),
         e("P4", "D6", "Thông báo"), e("D6", "P4", "Lịch sử"),
         e("P4", "CQ", "TB đơn mới"), e("P4", "SV", "TB xác nhận,<BR/>hoàn thành, hủy"),
         e("SV", "P5", "Số sao, nhận xét"), e("P3", "P5", "Đơn đã<BR/>completed"),
         e("P5", "D7", "Đánh giá"), e("D7", "P5", "DS đánh giá"),
         e("P5", "CQ", "Đánh giá,<BR/>điểm TB"), e("AD", "P5", "Ẩn đánh giá<BR/>vi phạm")]
    dfd("DFD_1_tong_the", "DFD mức 1 tổng thể – TDTU Food Booking", b, rankdir="TB",
        pos=dict(SV=(9, 11.6), AD=(0, 6), CQ=(18, 6), P1=(4, 8.5), D1=(0.8, 10.8), P2=(14, 8.5),
                 D2=(12, 11.2), D3=(16.8, 11.2), P3=(9, 6), D4=(6.4, 3.9), D5=(9, 3.0), D8=(11.8, 3.9),
                 P5=(4, 3.2), D7=(4, 0.6), P4=(14, 3.2), D6=(14, 0.6)),
        note="5 tiến trình con = 5 service. Nét đứt xanh: gọi Auth GET /api/users/me để xác thực token")

    AUTH = ext("AUTHS", "Auth Service<BR/><FONT POINT-SIZE='10'>(1.0)</FONT>", "#DCEBFA")
    b = [ext("ND", "Sinh viên /<BR/>Chủ quán"), ext("AD", "Admin"),
         ext("SVC", "Service khác<BR/><FONT POINT-SIZE='10'>(2.0 – 5.0)</FONT>", "#EEEEEE"),
         proc("P11", "1.1", "Kiểm tra dữ liệu<BR/>đăng ký"), proc("P12", "1.2", "Băm mật khẩu<BR/>(bcrypt) &amp; lưu user"),
         proc("P13", "1.3", "Kiểm tra email,<BR/>mật khẩu, trạng thái"), proc("P14", "1.4", "Sinh JWT<BR/>(sub, role, ver, exp)"),
         proc("P15", "1.5", "Kiểm tra token,<BR/>phiên bản &amp; khóa"), proc("P16", "1.6", "Khóa / mở khóa,<BR/>đổi vai trò (admin)"),
         proc("P17", "1.7", "Đăng xuất<BR/>(thu hồi token)"), store("D1", "D1", "USERS"),
         e("ND", "P11", "Họ tên, email,<BR/>mật khẩu, vai trò"), e("D1", "P11", "Email đã tồn tại?"),
         e("P11", "ND", "Lỗi 409/422", 'style=dashed'), e("P11", "P12", "Dữ liệu hợp lệ"),
         e("P12", "D1", "User mới"), e("ND", "P13", "Email, mật khẩu"), e("D1", "P13", "Hash, status"),
         e("P13", "P14", "user"), e("P14", "ND", "access_token"), e("P13", "ND", "401 / 403 bị khóa", 'style=dashed'),
         e("ND", "P15", "Token"), e("SVC", "P15", "Bearer token"), e("D1", "P15", "role, status,<BR/>token_version"),
         e("P15", "SVC", "User + role / 401 / 403"), e("ND", "P17", "Token"), e("P17", "D1", "token_version + 1"),
         e("AD", "P16", "Khóa, đổi vai trò"), e("D1", "P16", "Số admin còn lại"),
         e("P16", "D1", "status / role,<BR/>token_version + 1"), e("P16", "SVC", "Hỏi số quán<BR/>của chủ quán"),
         e("P16", "AD", "Kết quả / 409")]
    dfd("DFD_2_1_auth", "DFD mức 2 – 1.0 Auth Service", b,
        pos=dict(ND=(0, 5), P11=(4, 8.5), P12=(9, 8.5), D1=(9, 5), P13=(4, 1.5), P14=(9, 0.2), P17=(4, 5),
                 P15=(13.5, 6.5), SVC=(17.5, 8.5), P16=(13.5, 2), AD=(17.5, 2)),
        note="Không cho tự đăng ký admin; không cho khóa/hạ admin hoạt động cuối cùng")

    b = [ext("CQ", "Chủ quán"), ext("SV", "Sinh viên /<BR/>khách"), ext("AD", "Admin"), AUTH,
         ext("OS", "Order Service<BR/><FONT POINT-SIZE='10'>(3.0)</FONT>", "#FDEBD3"),
         proc("P21", "2.1", "Xác thực &amp;<BR/>kiểm tra chủ quán"), proc("P22", "2.2", "Đăng ký quán<BR/>(pending)"),
         proc("P23", "2.3", "Sửa quán,<BR/>mở / tạm đóng, xóa mềm"), proc("P24", "2.4", "Thêm món"),
         proc("P25", "2.5", "Sửa giá, trạng thái,<BR/>ẩn / xóa mềm món"), proc("P26", "2.6", "Tra cứu quán<BR/>&amp; menu công khai"),
         proc("P27", "2.7", "Duyệt / khóa<BR/>(admin)"), proc("P28", "2.8", "Báo giá nội bộ"),
         store("D2", "D2", "RESTAURANTS"), store("D3", "D3", "MENU_ITEMS"),
         e("CQ", "P21", "Token + yêu cầu"), e("P21", "AUTHS", "GET /api/users/me"), e("AUTHS", "P21", "id, role"),
         e("P21", "P22", "owner_id = id"), e("P22", "D2", "Quán pending"),
         e("P21", "P23", "Quyền chủ quán"), e("D2", "P23", "Quán"), e("P23", "D2", "Quán đã sửa"),
         e("P21", "P24", "Quyền chủ quán"), e("P24", "D3", "Món mới"), e("P21", "P25", "Quyền"),
         e("P25", "D3", "Món đã sửa"), e("SV", "P26", "Từ khóa"), e("D2", "P26", "Quán active/closed"),
         e("D3", "P26", "Món không ẩn"), e("P26", "SV", "DS quán, menu"),
         e("AD", "P27", "Duyệt / khóa + lý do"), e("P27", "D2", "status"),
         e("OS", "P28", "restaurant_id,<BR/>món, số lượng"), e("D3", "P28", "Giá, trạng thái"), e("D2", "P28", "Nhận đơn?"),
         e("P28", "OS", "Giá, tên món,<BR/>owner_id, còn bán?")]
    dfd("DFD_2_2_restaurant", "DFD mức 2 – 2.0 Restaurant Service", b,
        pos=dict(AUTHS=(0, 10), CQ=(0, 5.5), P21=(4, 8.5), P22=(8, 11), P23=(8, 8), D2=(12, 8.8),
                 P24=(8, 5), P25=(8, 2.2), D3=(12, 3), P26=(15.8, 6), SV=(19.5, 7.5), AD=(15.8, 11),
                 P27=(12.5, 11.3), P28=(15.5, 1), OS=(19.5, 1.5)))

    b = [ext("SV", "Sinh viên"), ext("CQ", "Chủ quán"), ext("AD", "Admin"), AUTH,
         ext("RS", "Restaurant Service<BR/><FONT POINT-SIZE='10'>(2.0)</FONT>", "#E3F4E1"),
         ext("NS", "Notification Service<BR/><FONT POINT-SIZE='10'>(4.0)</FONT>", "#EFE3F7"),
         ext("VS", "Review Service<BR/><FONT POINT-SIZE='10'>(5.0)</FONT>", "#FBE0E0"),
         proc("P31", "3.1", "Xác thực<BR/>người dùng"), proc("P32", "3.2", "Quản lý giỏ<BR/>(1 quán / giỏ)"),
         proc("P33", "3.3", "Checkout: báo giá lại,<BR/>tạo đơn nguyên tử"), proc("P34", "3.4", "Cập nhật trạng thái<BR/>(chống ghi đè)"),
         proc("P35", "3.5", "Tra cứu, lọc,<BR/>thống kê"), proc("P36", "3.6", "Gửi sự kiện<BR/>(outbox, gửi lại)"),
         store("D5", "D5", "CARTS, CART_ITEMS"), store("D4", "D4", "ORDERS, ORDER_ITEMS"), store("D8", "D8", "OUTBOX"),
         e("SV", "P31", "Token"), e("CQ", "P31", "Token"), e("P31", "AUTHS", "GET /api/users/me"),
         e("AUTHS", "P31", "id, role, tên"), e("SV", "P32", "Thêm / đổi SL /<BR/>xóa món"), e("P32", "RS", "Báo giá"),
         e("RS", "P32", "Giá, còn bán"), e("P32", "D5", "Giỏ"), e("SV", "P33", "Địa chỉ,<BR/>Idempotency-Key"),
         e("D5", "P33", "Món trong giỏ"), e("P33", "RS", "Báo giá"), e("RS", "P33", "Giá hiện tại"),
         e("P33", "D4", "Đơn + ảnh chụp"), e("P33", "D8", "order_created"), e("P33", "SV", "Đơn #mã"),
         e("CQ", "P34", "confirmed / completed /<BR/>cancelled"), e("SV", "P34", "cancelled (pending)"),
         e("AD", "P34", "cancelled (đơn lỗi)"), e("D4", "P34", "Trạng thái"), e("P34", "D4", "UPDATE … WHERE status=cũ"),
         e("P34", "D8", "Sự kiện"), e("D8", "P36", "Sự kiện chờ gửi"), e("P36", "NS", "POST nội bộ"),
         e("P36", "D8", "sent / failed"), e("D4", "P35", "Đơn"), e("P35", "SV", "Đơn của tôi"),
         e("P35", "CQ", "Đơn của quán"), e("P35", "AD", "Mọi đơn, thống kê"), e("VS", "P35", "GET đơn (nội bộ)")]
    dfd("DFD_2_3_order", "DFD mức 2 – 3.0 Order Service", b,
        pos=dict(SV=(0, 6), AUTHS=(0, 10.8), P31=(4.5, 9.8), P32=(4.5, 6.2), RS=(4.5, 2), D5=(8, 4.2),
                 P33=(9, 7.6), D4=(13, 7.2), P35=(13, 10.6), P34=(16, 4.2), D8=(12.2, 2.4), P36=(15.5, 0.4),
                 NS=(19.5, 0.4), CQ=(20, 7.5), AD=(20, 11.2), VS=(17, 12)),
        note="pending → confirmed → completed; pending/confirmed → cancelled. Giỏ chỉ bị xóa khi tạo đơn thành công")

    b = [ext("OS", "Order Service<BR/><FONT POINT-SIZE='10'>(3.0)</FONT>", "#FDEBD3"),
         ext("ND", "Sinh viên /<BR/>Chủ quán"), ext("AD", "Admin"), AUTH,
         proc("P41", "4.1", "Nhận sự kiện<BR/>(khóa nội bộ)"), proc("P42", "4.2", "Xác định người nhận<BR/>theo sự kiện + người hủy"),
         proc("P43", "4.3", "Lưu thông báo<BR/>(bỏ qua trùng)"), proc("P44", "4.4", "Tra cứu, lọc<BR/>chưa đọc"),
         proc("P45", "4.5", "Đánh dấu đã đọc<BR/>(1 / tất cả)"), store("D6", "D6", "NOTIFICATIONS"),
         e("OS", "P41", "event_key, sự kiện,<BR/>student_id, owner_id"), e("P41", "P42", "Sự kiện hợp lệ"),
         e("P42", "P43", "Người nhận + nội dung"), e("P43", "D6", "INSERT OR IGNORE<BR/>(event_key, user_id)"),
         e("P41", "OS", "201 / 200 trùng"), e("ND", "P44", "Token"), e("P44", "AUTHS", "GET /api/users/me"),
         e("AUTHS", "P44", "id"), e("D6", "P44", "TB của user"), e("P44", "ND", "Lịch sử, số chưa đọc"),
         e("ND", "P45", "notification_id"), e("P45", "D6", "status = read"), e("AD", "P44", "Xem / xóa"),
         e("P44", "AD", "Mọi thông báo")]
    dfd("DFD_2_4_notification", "DFD mức 2 – 4.0 Notification Service", b,
        pos=dict(OS=(0, 6), P41=(3.8, 6), P42=(7.6, 6), P43=(11.4, 6), D6=(11.4, 2.8), ND=(16, 7.5),
                 P44=(15.5, 2.5), P45=(11.4, 0), AUTHS=(19.5, 0.5), AD=(19.5, 4)))

    b = [ext("SV", "Sinh viên"), ext("CQ", "Chủ quán /<BR/>khách"), ext("AD", "Admin"), AUTH,
         ext("OS", "Order Service<BR/><FONT POINT-SIZE='10'>(3.0)</FONT>", "#FDEBD3"),
         proc("P51", "5.1", "Xác thực<BR/>sinh viên"), proc("P52", "5.2", "Kiểm tra đơn<BR/>(của mình, completed)"),
         proc("P53", "5.3", "Lưu đánh giá<BR/>(UNIQUE order_id)"), proc("P54", "5.4", "Tra cứu công khai<BR/>(phân trang)"),
         proc("P55", "5.5", "Tính điểm TB,<BR/>phân bố sao"), proc("P56", "5.6", "Ẩn / hiện<BR/>đánh giá"),
         store("D7", "D7", "REVIEWS"),
         e("SV", "P51", "Token"), e("P51", "AUTHS", "GET /api/users/me"), e("AUTHS", "P51", "id, tên"),
         e("SV", "P52", "order_id, số sao,<BR/>nhận xét"), e("P51", "P52", "user_id"),
         e("P52", "OS", "GET /internal/orders/{id}"), e("OS", "P52", "user_id, quán,<BR/>status"),
         e("P52", "SV", "403 / 409 / 404", 'style=dashed'), e("P52", "P53", "Hợp lệ"), e("P53", "D7", "Đánh giá"),
         e("P53", "SV", "409 đã đánh giá", 'style=dashed'), e("CQ", "P54", "restaurant_id"),
         e("D7", "P54", "Đánh giá hiển thị"), e("P54", "CQ", "Tên người viết,<BR/>sao, nhận xét"),
         e("D7", "P55", "rating"), e("P55", "CQ", "TB (1 chữ số), số lượt"),
         e("AD", "P56", "Ẩn + lý do"), e("P56", "D7", "status = hidden")]
    dfd("DFD_2_5_review", "DFD mức 2 – 5.0 Review Service", b,
        pos=dict(SV=(0, 6), AUTHS=(0, 10.5), P51=(4, 9.8), P52=(4.5, 5.2), OS=(4.5, 1.2), P53=(8.5, 5.2),
                 D7=(12, 5.2), P54=(12, 9.5), P55=(12, 1.2), CQ=(17, 7.5), P56=(16, 3.2), AD=(19.5, 2)),
        note="Đánh giá bị ẩn vẫn giữ order_id nên đơn đó không thể đánh giá lại")


def build_usecase():
    SV, CQ, AD = ("SV", "Sinh viên"), ("CQ", "Chủ quán"), ("AD", "Admin")
    usecase("UC_0_tong_quan", "Use Case tổng quan – TDTU Food Booking", "Hệ thống TDTU Food Booking", [SV, CQ], [AD],
            [("u1", "Đăng ký, đăng nhập, hồ sơ"), ("u2", "Đăng ký quán, quản lý menu"), ("u3", "Xem quán, menu, đánh giá"),
             ("u4", "Giỏ hàng, đặt món, hủy đơn"), ("u5", "Xác nhận / hoàn thành đơn"), ("u6", "Nhận, xem thông báo"),
             ("u7", "Đánh giá quán"), ("u8", "Khóa / đổi vai trò user"), ("u9", "Duyệt / khóa quán"),
             ("u10", "Hủy đơn lỗi, thống kê"), ("u11", "Ẩn đánh giá vi phạm")],
            [("SV", "u1"), ("SV", "u3"), ("SV", "u4"), ("SV", "u6"), ("SV", "u7"), ("CQ", "u1"), ("CQ", "u2"),
             ("CQ", "u5"), ("CQ", "u6"), ("CQ", "u3"), ("u1", "AD"), ("u8", "AD"), ("u9", "AD"), ("u10", "AD"), ("u11", "AD")])
    usecase("UC_1_auth", "Use Case – Auth Service", "Auth Service", [SV, CQ], [AD],
            [("a1", "Đăng ký tài khoản"), ("a2", "Đăng nhập"), ("a3", "Đăng xuất"), ("a4", "Xem, sửa hồ sơ"),
             ("a5", "Kiểm tra token"), ("a6", "Xem danh sách user"), ("a7", "Khóa / mở khóa"), ("a8", "Đổi vai trò")],
            [("SV", "a1"), ("SV", "a2"), ("SV", "a3"), ("SV", "a4"), ("CQ", "a1"), ("CQ", "a2"), ("CQ", "a3"),
             ("CQ", "a4"), ("a2", "AD"), ("a6", "AD"), ("a7", "AD"), ("a8", "AD")],
            [("a4", "a5", "include"), ("a6", "a5", "include")])
    usecase("UC_2_restaurant", "Use Case – Restaurant Service", "Restaurant Service", [CQ], [SV, AD],
            [("r1", "Đăng ký quán"), ("r2", "Sửa, mở/tạm đóng, xóa quán"), ("r3", "Thêm món"),
             ("r4", "Sửa giá, hết món, ẩn, xóa món"), ("r5", "Tìm, xem quán"), ("r6", "Xem menu"),
             ("r7", "Duyệt / khóa / mở khóa quán"), ("r0", "Xác thực token")],
            [("CQ", "r1"), ("CQ", "r2"), ("CQ", "r3"), ("CQ", "r4"), ("r5", "SV"), ("r6", "SV"), ("r7", "AD"), ("r5", "AD")],
            [("r1", "r0", "include"), ("r3", "r0", "include")])
    usecase("UC_3_order", "Use Case – Order Service", "Order Service", [SV], [CQ, AD],
            [("o1", "Quản lý giỏ hàng"), ("o2", "Checkout (đặt món)"), ("o3", "Xem đơn của tôi"), ("o4", "Hủy đơn pending"),
             ("o5", "Xác nhận / hoàn thành"), ("o6", "Hủy đơn của quán"), ("o7", "Xem đơn của quán"),
             ("o8", "Hủy đơn lỗi, thống kê"), ("o9", "Gửi lại thông báo lỗi"), ("o0", "Báo giá từ Restaurant")],
            [("SV", "o1"), ("SV", "o2"), ("SV", "o3"), ("SV", "o4"), ("o5", "CQ"), ("o6", "CQ"), ("o7", "CQ"),
             ("o8", "AD"), ("o9", "AD")],
            [("o2", "o0", "include"), ("o1", "o0", "include")])
    usecase("UC_4_notification", "Use Case – Notification Service", "Notification Service", [SV, CQ], [AD],
            [("n1", "Nhận thông báo đơn mới"), ("n2", "Nhận TB xác nhận / hoàn thành / hủy"), ("n3", "Xem, lọc chưa đọc"),
             ("n4", "Đánh dấu đã đọc / tất cả"), ("n5", "Xem, xóa thông báo")],
            [("CQ", "n1"), ("SV", "n2"), ("SV", "n3"), ("CQ", "n3"), ("SV", "n4"), ("CQ", "n4"), ("n5", "AD")],
            [("n4", "n3", "extend")])
    usecase("UC_5_review", "Use Case – Review Service", "Review Service", [SV], [CQ, AD],
            [("v1", "Viết đánh giá, chấm sao"), ("v2", "Xem đánh giá của quán"), ("v3", "Xem điểm trung bình"),
             ("v4", "Kiểm tra đơn completed"), ("v5", "Ẩn / hiện đánh giá")],
            [("SV", "v1"), ("SV", "v2"), ("SV", "v3"), ("v2", "CQ"), ("v3", "CQ"), ("v5", "AD")],
            [("v1", "v4", "include")])


# ------------------------------------------------------------ KIẾN TRÚC ----
def _svc(node, title, lang, port, color):
    return (f'{node} [shape=box, style="rounded,filled", fillcolor="{color}", penwidth=1.6, margin="0.2,0.12", '
            f'label=<<B>{title}</B><BR/><FONT POINT-SIZE="11">{lang}</FONT><BR/><FONT POINT-SIZE="11">cổng {port}</FONT>>];')


def _db(node, engine, tables):
    rows = "<BR/>".join(tables)
    return (f'{node} [shape=cylinder, style=filled, fillcolor="#FFFFFF", penwidth=1.4, margin="0.15,0.1", '
            f'label=<<B>{engine}</B><BR/><FONT POINT-SIZE="10">{rows}</FONT>>];')


def build_arch():
    """ARCH_0: kiến trúc microservices - 5 service (5 ngôn ngữ), mỗi service một DB riêng, gateway, web, mock email."""
    L = ['digraph G {',
         f'graph [fontname="{FONT}", rankdir=TB, newrank=true, compound=true, nodesep=0.9, ranksep=1.0, pad=0.4, '
         f'splines=true, labelloc=t, fontsize=22, label=<<B>Kiến trúc microservices – TDTU Food Booking</B><BR/>'
         f'<FONT POINT-SIZE="13">5 service độc lập, 5 ngôn ngữ, mỗi service một cơ sở dữ liệu riêng, giao tiếp REST JSON; '
         f'không service nào đọc DB của service khác</FONT>>];',
         f'node [fontname="{FONT}", fontsize=12];',
         f'edge [fontname="{FONT}", fontsize=10, arrowsize=0.8, color="#333333"];',
         'USER [shape=box, style="filled", fillcolor="#FFF6D6", penwidth=2, margin="0.25,0.15", '
         'label=<<B>Người dùng</B><BR/><FONT POINT-SIZE="11">Sinh viên · Chủ quán · Admin</FONT><BR/>'
         '<FONT POINT-SIZE="11">trình duyệt / app điện thoại (PWA)</FONT>>];',
         'GW [shape=box, style="filled", fillcolor="#263238", fontcolor="white", penwidth=1.6, margin="0.25,0.15", '
         'label=<<B>API Gateway – Nginx</B><BR/><FONT POINT-SIZE="10">HTTPS 443 (80 → 443), HSTS</FONT><BR/>'
         '<FONT POINT-SIZE="10">/ → Web · /svc/&lt;service&gt;/ → service</FONT><BR/>'
         '<FONT POINT-SIZE="10">rate limit theo IP (đăng nhập, OTP, tải ảnh)</FONT><BR/>'
         '<FONT POINT-SIZE="10">chặn /internal và /docs từ Internet</FONT><BR/>'
         '<FONT POINT-SIZE="10">gắn / chuyển tiếp X-Request-ID</FONT>>];',
         'WEB [shape=box, style="rounded,filled", fillcolor="#ECEFF1", penwidth=1.4, '
         'label=<<B>Web UI</B><BR/><FONT POINT-SIZE="11">HTML/CSS/JS tĩnh (Python)</FONT><BR/>'
         '<FONT POINT-SIZE="11">cổng 8000</FONT>>];',
         'USER -> GW [label=<HTTPS>, penwidth=1.6];',
         'GW -> WEB [label=<trang tĩnh>];']
    # thứ tự trái -> phải trên hàng service: Review, Order, Restaurant, Auth, Notification (giảm đường cắt nhau)
    clusters = [
        ("review", "Review Service", "PHP 8 (thuần)", 8005, "#FBE0E0", "SQLite", ["reviews"]),
        ("order", "Order Service", "Java · Spring Boot", 8003, "#FDEBD3", "H2",
         ["carts, cart_items", "orders, order_items", "notification_outbox", "pickup_counters"]),
        ("restaurant", "Restaurant Service", "Node.js · Express", 8002, "#E3F4E1", "SQLite",
         ["restaurants", "menu_items", "menu_updates"]),
        ("auth", "Auth Service", "Python · FastAPI", 8001, "#DCEBFA", "SQLite", ["users", "otp_codes", "login_attempts"]),
        ("notification", "Notification Service", "Go · Gin + GORM", 8004, "#EFE3F7", "PostgreSQL",
         ["notifications", "email_logs"]),
    ]
    for key, title, lang, port, color, engine, tables in clusters:
        L.append(f'subgraph cluster_{key} {{ label=""; style="rounded,dashed"; color="#90A4AE"; margin=10;')
        L.append("  " + _svc(key.upper(), title, lang, port, color))
        L.append("  " + _db(key.upper() + "_DB", engine, tables))
        L.append(f'  {key.upper()} -> {key.upper()}_DB [arrowhead=none, penwidth=1.4, color="#607D8B"];')
        L.append('}')
        L.append(f'GW -> {key.upper()} [color="#90A4AE"];')            # /svc/<service>/ (ghi trong khung gateway)
    L.append('{rank=same; ' + "; ".join(k.upper() for k, *_ in clusters) + '; MOCK}')
    L.append('{rank=same; ' + "; ".join(k.upper() + "_DB" for k, *_ in clusters) + '}')
    L += ['subgraph cluster_third { label=<<B>Bên thứ ba (giả lập)</B>>; style="rounded,filled"; fillcolor="#FAFAFA"; '
          'color="#B0BEC5"; margin=14; fontsize=12;',
          '  MOCK [shape=box, style="rounded,filled", fillcolor="#FFFDE7", penwidth=1.4, '
          'label=<<B>Mock Email Provider</B><BR/><FONT POINT-SIZE="11">MockMail · Python FastAPI</FONT><BR/>'
          '<FONT POINT-SIZE="11">cổng 9000 · dữ liệu trong bộ nhớ</FONT>>];', '}']
    # REST đồng bộ (nét liền); constraint=false: không làm xáo trộn hàng service
    # cặp 2 chiều tách cổng trên / dưới để nhãn không chồng nhau
    sync = [
        ("ORDER", "RESTAURANT", "POST /internal/quote<BR/>(giá, món còn bán)", ""),
        ("ORDER", "AUTH", "GET /api/users/me<BR/>GET /internal/users/{id}/payout", "tailport=n, headport=n"),
        ("RESTAURANT", "AUTH", "GET /api/users/me", ""),
        ("REVIEW", "AUTH", "GET /api/users/me", "tailport=n, headport=n"),
        ("NOTIFICATION", "AUTH", "GET /api/users/me", "tailport=sw, headport=se"),
        ("REVIEW", "ORDER", "GET /internal/orders/{id}<BR/>(đơn completed?)", ""),
        ("AUTH", "NOTIFICATION", "POST /internal/notifications/email<BR/>(mã OTP)", "tailport=ne, headport=nw"),
        ("NOTIFICATION", "MOCK", "POST /api/send<BR/>X-API-Key, Idempotency-Key", "tailport=ne, headport=nw"),
    ]
    for a, b, lab, ports in sync:
        L.append(f'{a} -> {b} [label=<{lab}>, penwidth=1.2, constraint=false{", " + ports if ports else ""}];')
    # Auth điều phối xóa dữ liệu cá nhân: gom thành 1 ghi chú thay vì 4 mũi tên chéo
    L.append('ERASE [shape=note, style=filled, fillcolor="#F5F5F5", fontsize=10, label=<<B>Auth → erase</B><BR/>'
             'POST /internal/users/{id}/erase<BR/>lần lượt tới Order, Restaurant,<BR/>Review, Notification>];')
    L.append('AUTH_DB -> ERASE [style=invis];')                       # ghi chú nằm ngay dưới Auth
    # bất đồng bộ / gửi lại (nét đứt)
    L.append('ORDER_DB -> NOTIFICATION_DB [style=invis];')
    L.append('ORDER -> NOTIFICATION [label=<<B>outbox</B>: POST /internal/notifications/events<BR/>'
             'gửi lại khi Notification sập>, style=dashed, penwidth=1.6, color="#E65100", fontcolor="#E65100", '
             'constraint=false, tailport=s, headport=s];')
    L.append('MOCK -> NOTIFICATION [label=<<B>webhook</B> delivered / failed<BR/>ký HMAC-SHA256>, style=dashed, '
             'penwidth=1.6, color="#6A1B9A", fontcolor="#6A1B9A", constraint=false, tailport=sw, headport=se];')
    L.append('LEGEND [shape=plain, label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="2" CELLPADDING="4" COLOR="#90A4AE">'
             '<TR><TD COLSPAN="2"><B>Chú giải</B></TD></TR>'
             '<TR><TD ALIGN="LEFT">——→</TD><TD ALIGN="LEFT">REST đồng bộ (timeout, ánh xạ lỗi 503 / 502)</TD></TR>'
             '<TR><TD ALIGN="LEFT"><FONT COLOR="#E65100">- - -→</FONT></TD><TD ALIGN="LEFT">bất đồng bộ: outbox gửi lại, '
             'webhook có chữ ký</TD></TR>'
             '<TR><TD ALIGN="LEFT"><FONT COLOR="#90A4AE">——→</FONT></TD><TD ALIGN="LEFT">gateway chuyển /svc/&lt;service&gt;/... '
             'của trình duyệt tới service</TD></TR>'
             '<TR><TD ALIGN="LEFT">trụ</TD><TD ALIGN="LEFT">DB riêng của service (bảng chính)</TD></TR>'
             '<TR><TD ALIGN="LEFT">/internal</TD><TD ALIGN="LEFT">API nội bộ, header X-Internal-Key</TD></TR>'
             '<TR><TD ALIGN="LEFT">mọi lời gọi</TD><TD ALIGN="LEFT">chuyển tiếp X-Request-ID (truy vết qua log)</TD></TR>'
             '</TABLE>>];')
    L.append('}')
    write_render(os.path.join(OUT, "arch", "ARCH_0_microservices"), "\n".join(L))


def build_otp_flow():
    """ARCH_1: luồng đăng ký có xác nhận email bằng mã OTP (Unit 20), các bước đánh số."""
    L = ['digraph G {',
         f'graph [fontname="{FONT}", rankdir=LR, nodesep=0.5, ranksep=0.9, pad=0.4, labelloc=t, fontsize=20, '
         f'label=<<B>Luồng xác nhận email bằng mã OTP</B><BR/><FONT POINT-SIZE="12">Notification hoặc nhà cung cấp email '
         f'lỗi thì đăng ký vẫn thành công (otp_sent=false), người dùng bấm Gửi lại mã</FONT>>];',
         f'node [fontname="{FONT}", fontsize=12];',
         f'edge [fontname="{FONT}", fontsize=10, arrowsize=0.8, color="#333333"];',
         ext("U", "Sinh viên / Chủ quán"),
         _svc("A", "Auth Service", "Python · FastAPI", 8001, "#DCEBFA"),
         _db("ADB", "SQLite (Auth)", ["users.email_verified_at", "otp_codes (HMAC, attempts)"]),
         _svc("N", "Notification Service", "Go · Gin", 8004, "#EFE3F7"),
         _db("NDB", "PostgreSQL", ["email_logs", "sending → sent → delivered/failed"]),
         'M [shape=box, style="rounded,filled", fillcolor="#FFFDE7", penwidth=1.4, '
         'label=<<B>MockMail</B><BR/><FONT POINT-SIZE="11">cổng 9000</FONT>>];',
         'BOX [shape=note, style=filled, fillcolor="#FFFFFF", label=<<B>Hộp thư</B><BR/><FONT POINT-SIZE="10">'
         'GET /api/emails (demo)</FONT>>];',
         'U -> A [label=<<B>1</B> POST /api/users/register>];',
         'A -> ADB [label=<<B>2</B> user + otp_codes<BR/>cùng transaction>];',
         'A -> N [label=<<B>3</B> sau commit: POST /internal/notifications/email<BR/>idempotency_key = otp-&lt;id&gt;>];',
         'N -> NDB [label=<<B>4</B> email_logs: sending>];',
         'N -> M [label=<<B>5</B> POST /api/send<BR/>X-API-Key, Idempotency-Key>];',
         'M -> N [label=<<B>6</B> 202 message_id → sent>, style=dashed];',
         'M -> BOX [label=<<B>7</B> thư có mã 6 số>];',
         'M -> N [label=<<B>8</B> ~1s: webhook ký HMAC<BR/>delivered / failed>, style=dashed, color="#6A1B9A", '
         'fontcolor="#6A1B9A", constraint=false];',
         'BOX -> U [label=<<B>9</B> đọc mã>, style=dotted];',
         'U -> A [label=<<B>10</B> POST /api/users/verify-otp<BR/>sai 5 lần → khóa mã; đúng → token>, color="#1565C0", '
         'fontcolor="#1565C0"];',
         '}']
    write_render(os.path.join(OUT, "arch", "ARCH_1_otp_flow"), "\n".join(L))


DIRS = ("erd", "dfd", "usecase", "arch")

if __name__ == "__main__":
    for d in DIRS:
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    build_erd(); build_dfd(); build_usecase(); build_arch(); build_otp_flow()
    for d in DIRS:                                  # chỉ giữ PNG/SVG, xóa tệp .dot trung gian
        for f in os.listdir(os.path.join(OUT, d)):
            if f.endswith(".dot"):
                os.remove(os.path.join(OUT, d, f))
    print("Đã sinh sơ đồ vào", OUT)
