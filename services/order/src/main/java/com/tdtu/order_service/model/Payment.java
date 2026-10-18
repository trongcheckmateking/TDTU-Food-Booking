package com.tdtu.order_service.model;

import com.tdtu.order_service.web.ApiError;
import java.util.List;
import java.util.Set;

/**
 * Thanh toán của đơn, sinh viên chọn 1 trong 2 cách khi đặt (method):
 * <ul>
 *   <li>transfer: chuyển khoản trước thẳng vào tài khoản của chủ quán bằng mã VietQR (app không giữ tiền). Tài khoản nhận
 *       được chụp lại lúc đặt đơn, đổi tài khoản sau đó không ảnh hưởng đơn cũ.</li>
 *   <li>cash: trả tiền mặt khi nhận món. Đơn tới quán ngay (status cash), quán báo hoàn thành = đã thu tiền (paid);
 *       hủy thì void, không cần hoàn tiền.</li>
 * </ul>
 *
 * <pre>
 * chuyển khoản:
 * unpaid  --sinh viên bấm "Tôi đã chuyển khoản"--> claimed --quán "Đã nhận tiền"--> paid --quán / admin hủy--> refund_due --> refunded
 *    |                                                 |--quán "Chưa nhận được tiền"--> failed
 *    |                                                 '--admin hủy (quán không phản hồi)--> refund_due
 *    |--sinh viên / quán / admin hủy--> void
 *    '--quá PAYMENT_TIMEOUT_MINUTES phút--> expired
 * tiền mặt:  cash --quán báo hoàn thành--> paid ;  cash --hủy--> void
 * </pre>
 */
public record Payment(String method, String status, String bankBin, String bankName, String account, String holder,
                      String note, String deadline, String claimedAt, String paidAt) {

    public static final String TRANSFER = "transfer";
    public static final String CASH_METHOD = "cash";
    public static final List<String> METHODS = List.of(TRANSFER, CASH_METHOD);

    public static final String UNPAID = "unpaid";
    public static final String CLAIMED = "claimed";
    public static final String PAID = "paid";
    public static final String VOID = "void";
    public static final String FAILED = "failed";
    public static final String EXPIRED = "expired";
    public static final String REFUND_DUE = "refund_due";
    public static final String REFUNDED = "refunded";
    /** Tiền mặt: đơn đã đặt, sinh viên trả khi nhận món. */
    public static final String CASH = "cash";
    public static final Set<String> ALL = Set.of(UNPAID, CLAIMED, PAID, VOID, FAILED, EXPIRED, REFUND_DUE, REFUNDED, CASH);

    /** Đơn được tính là "đã đặt thành công": đã chuyển khoản (kể cả đã hủy, hoàn tiền sau đó) hoặc chọn tiền mặt. */
    public static final String PLACED_SQL = "payment_status IN ('paid','refund_due','refunded','cash')";

    /** Query ?payment_status=unpaid,claimed -> danh sách đã kiểm tra (rỗng = không lọc). */
    public static List<String> parseFilter(String raw) {
        if (raw == null || raw.isBlank()) return List.of();
        List<String> out = List.of(raw.split(",")).stream().map(String::strip).distinct().toList();
        for (String x : out) {
            if (!ALL.contains(x)) throw ApiError.field("payment_status", "phải thuộc " + String.join(", ", ALL.stream().sorted().toList()));
        }
        return out;
    }

    /** Điều kiện SQL "payment_status IN (?,?)" cho danh sách đã kiểm tra. */
    public static String inSql(List<String> values) {
        return "payment_status IN (" + String.join(",", values.stream().map(x -> "?").toList()) + ")";
    }

    public boolean isCash() {
        return CASH_METHOD.equals(method);
    }

    public boolean is(String s) {
        return s.equals(status);
    }
}
