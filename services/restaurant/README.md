# Restaurant Service – Node.js / Express (TV2)

Cổng 8002. Quán, menu, duyệt/khóa quán, báo giá nội bộ cho Order. CSDL: SQLite `DATA_DIR/restaurant.db` qua `node:sqlite`.

```bash
npm ci                      # Node.js 22.13+
npm start                   # đọc .env ở thư mục gốc dự án (INTERNAL_KEY, RESTAURANT_URL, AUTH_URL, ...)
npm test                    # node --test, Auth được thay bằng server giả
```
Mã: `src/server.js` (khởi động), `src/app.js` (API), `src/db.js` (schema), `src/validate.js`, `src/auth.js`, `src/http.js`.
