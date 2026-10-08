<?php
declare(strict_types=1);

/**
 * Nghiệp vụ đánh giá (giữ tên lớp Reviews của bản TV5).
 *  - Chỉ sinh viên đặt đơn, đơn completed; người viết lấy từ token, quán lấy từ đơn đã xác minh qua Order.
 *  - Admin ẩn đánh giá vi phạm (không xóa cứng) -> đơn đó không thể được đánh giá lại.
 *  - Điểm trung bình làm tròn 1 chữ số (half-up), chỉ tính đánh giá đang hiển thị; chưa có -> null.
 */
final class Reviews
{
    private const PUBLIC_FIELDS = ['id', 'reviewer_name', 'rating', 'comment', 'created_at'];
    private const MY_FIELDS = ['id', 'reviewer_name', 'rating', 'comment', 'created_at', 'order_id', 'restaurant_id',
        'restaurant_name', 'status'];
    private const ADMIN_FIELDS = ['id', 'reviewer_name', 'rating', 'comment', 'created_at', 'order_id', 'restaurant_id',
        'restaurant_name', 'status', 'user_id', 'hidden_reason'];

    public function __construct(private PDO $db) {}

    private static function pick(array $row, array $fields): array
    {
        $out = [];
        foreach ($fields as $f) {
            $out[$f] = $f === 'rating' ? (int) $row[$f] : ($row[$f] ?? null);
        }
        return $out;
    }

    /** Kiểm tra body tạo đánh giá: {order_id: UUID, rating: số nguyên 1–5, comment?: ≤ 1000 ký tự}. */
    public static function validate(array $body): array
    {
        $errors = [];
        rejectUnknown($body, ['order_id', 'rating', 'comment'], $errors);
        $orderId = $body['order_id'] ?? null;
        if (!array_key_exists('order_id', $body)) {
            $errors[] = ['field' => 'order_id', 'message' => 'bắt buộc'];
        } elseif (!isUuid(is_string($orderId) ? trim($orderId) : $orderId)) {
            $errors[] = ['field' => 'order_id', 'message' => 'phải là UUID'];
        }
        $rating = $body['rating'] ?? null;
        if (!array_key_exists('rating', $body)) {
            $errors[] = ['field' => 'rating', 'message' => 'bắt buộc'];
        } elseif (!is_int($rating)) {                 // không nhận 4.5, "5", true
            $errors[] = ['field' => 'rating', 'message' => 'phải là số nguyên'];
        } elseif ($rating < 1 || $rating > 5) {
            $errors[] = ['field' => 'rating', 'message' => 'phải trong khoảng 1–5'];
        }
        $comment = optionalText($body, 'comment', 1000, $errors);
        if ($errors) {
            throw validationError($errors);
        }
        return ['order_id' => strtolower(trim($orderId)), 'rating' => $rating, 'comment' => $comment];
    }

    public function create(array $input, array $user, array $order): array
    {
        $id = newUuid();
        $ts = nowIso();
        try {
            $stmt = $this->db->prepare('INSERT INTO reviews (id,user_id,reviewer_name,restaurant_id,restaurant_name,'
                . "order_id,rating,comment,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'visible', ?, ?)");
            $stmt->execute([$id, $user['id'], $user['name'], strtolower($order['restaurant_id']), $order['restaurant_name'],
                $input['order_id'], $input['rating'], $input['comment'], $ts, $ts]);
        } catch (PDOException $e) {
            if (str_contains($e->getMessage(), 'reviews.order_id')) {    // đúng ràng buộc 1 đơn 1 đánh giá
                throw new ApiError(409, 'REVIEW_EXISTS', 'Đơn hàng này đã được đánh giá');
            }
            throw $e;
        }
        return self::pick($this->find($id), self::MY_FIELDS);
    }

    private function find(string $id): ?array
    {
        $stmt = $this->db->prepare('SELECT * FROM reviews WHERE id=?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    public function mine(string $userId): array
    {
        $stmt = $this->db->prepare('SELECT * FROM reviews WHERE user_id=? ORDER BY created_at DESC');
        $stmt->execute([$userId]);
        return array_map(fn($r) => self::pick($r, self::MY_FIELDS), $stmt->fetchAll());
    }

    public function summary(string $restaurantId): array
    {
        $dist = ['1' => 0, '2' => 0, '3' => 0, '4' => 0, '5' => 0];
        $stmt = $this->db->prepare("SELECT rating, COUNT(*) AS n FROM reviews WHERE restaurant_id=? AND status='visible' "
            . 'GROUP BY rating');
        $stmt->execute([$restaurantId]);
        foreach ($stmt->fetchAll() as $r) {
            $dist[(string) $r['rating']] = (int) $r['n'];
        }
        $count = array_sum($dist);
        $average = null;
        if ($count > 0) {
            $sum = 0;
            foreach ($dist as $sao => $n) {
                $sum += (int) $sao * $n;
            }
            // làm tròn half-up 1 chữ số bằng số nguyên (tránh sai số dấu phẩy động): floor(sum*10/count + 0.5)
            $average = intdiv($sum * 20 + $count, 2 * $count) / 10;
        }
        return ['restaurant_id' => $restaurantId, 'average' => $average === null ? null : (float) $average,
            'count' => $count, 'distribution' => (object) $dist];
    }

    private function paginate(string $where, array $args, int $page, int $size, array $fields): array
    {
        $count = $this->db->prepare("SELECT COUNT(*) FROM reviews WHERE $where");
        $count->execute($args);
        $stmt = $this->db->prepare("SELECT * FROM reviews WHERE $where ORDER BY created_at DESC, id LIMIT ? OFFSET ?");
        $stmt->execute([...$args, $size, ($page - 1) * $size]);
        return ['items' => array_map(fn($r) => self::pick($r, $fields), $stmt->fetchAll()),
            'total' => (int) $count->fetchColumn(), 'page' => $page, 'page_size' => $size];
    }

    public function forRestaurant(string $restaurantId, int $page, int $size): array
    {
        $res = $this->paginate("restaurant_id=? AND status='visible'", [$restaurantId], $page, $size, self::PUBLIC_FIELDS);
        $res['summary'] = $this->summary($restaurantId);
        return $res;
    }

    public function adminList(?string $status, ?int $maxRating, ?string $restaurantId, int $page, int $size): array
    {
        $where = '1=1';
        $args = [];
        if ($status !== null) {
            $where .= ' AND status=?';
            $args[] = $status;
        }
        if ($maxRating !== null) {
            $where .= ' AND rating<=?';
            $args[] = $maxRating;
        }
        if ($restaurantId !== null) {
            $where .= ' AND restaurant_id=?';
            $args[] = $restaurantId;
        }
        return $this->paginate($where, $args, $page, $size, self::ADMIN_FIELDS);
    }

    public function setVisibility(string $id, string $status, ?string $reason): array
    {
        $stmt = $this->db->prepare('UPDATE reviews SET status=?, hidden_reason=?, updated_at=? WHERE id=?');
        $stmt->execute([$status, $status === 'hidden' ? $reason : null, nowIso(), $id]);
        if ($stmt->rowCount() === 0) {
            throw new ApiError(404, 'REVIEW_NOT_FOUND', 'Không tìm thấy đánh giá');
        }
        return self::pick($this->find($id), self::ADMIN_FIELDS);
    }
}
