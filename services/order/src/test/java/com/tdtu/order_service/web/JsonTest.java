package com.tdtu.order_service.web;

import static org.junit.jupiter.api.Assertions.*;

import java.util.Set;
import org.junit.jupiter.api.Test;

/** Kiểm tra dữ liệu vào: số nguyên thật, trường lạ, chuỗi rỗng, JSON hỏng, UUID, phân trang. */
class JsonTest {

    private static ApiError fail(Runnable r) {
        return assertThrows(ApiError.class, r::run);
    }

    @Test
    void soNguyenPhaiLaSoNguyenJsonThat() {
        for (String bad : new String[] {"1.5", "\"2\"", "true", "0", "51", "1e309", "null"}) {
            Json.Body b = Json.body("{\"quantity\":" + bad + "}", Set.of("quantity"));
            b.integer("quantity", 1, 50, null);
            ApiError e = fail(b::done);
            assertEquals(422, e.status(), bad);
            assertEquals("VALIDATION_ERROR", e.code());
        }
        Json.Body ok = Json.body("{\"quantity\":50}", Set.of("quantity"));
        assertEquals(50, ok.integer("quantity", 1, 50, null));
        ok.done();
    }

    @Test
    void truongLaVaChuoiRongBiTuChoi() {
        Json.Body b = Json.body("{\"delivery_address\":\"   \",\"owner_id\":\"x\"}", Set.of("delivery_address"));
        b.text("delivery_address", 3, 300, true);
        ApiError e = fail(b::done);
        assertTrue(e.body().get("errors").toString().contains("owner_id"));
    }

    @Test
    void chuoiDuocCatKhoangTrangVaGhiChuRongThanhNull() {
        Json.Body b = Json.body("{\"delivery_address\":\"  KTX B305  \",\"note\":\"   \"}", Set.of("delivery_address", "note"));
        assertEquals("KTX B305", b.text("delivery_address", 3, 300, true));
        assertNull(b.optText("note", 500));
        b.done();
    }

    @Test
    void jsonHongVaKhongPhaiObject() {
        assertEquals("JSON gửi lên không hợp lệ", fail(() -> Json.body("{\"a\":", Set.of())).getMessage());
        assertEquals(422, fail(() -> Json.body("[1,2]", Set.of())).status());
        assertEquals(422, fail(() -> Json.body("", Set.of())).status());
    }

    @Test
    void uuidVaThamSoTruyVan() {
        assertEquals("00000000-0000-4000-8000-00000000000a", Json.uuidParam("00000000-0000-4000-8000-00000000000A", "id"));
        fail(() -> Json.uuidParam("khong-phai-uuid", "id"));
        assertEquals(20, Json.intQuery(null, "page_size", 20, 1, 100));
        fail(() -> Json.intQuery("101", "page_size", 20, 1, 100));
        fail(() -> Json.intQuery("abc", "page", 1, 1, 100000));
        fail(() -> Json.dateQuery("07/10/2026", "date_from"));
        fail(() -> Json.dateQuery("2026-02-30", "date_from"));
        assertEquals("2026-10-07", Json.dateQuery("2026-10-07", "date_from"));
        fail(() -> Json.enumQuery("shipped", "status", java.util.List.of("pending")));
    }
}
