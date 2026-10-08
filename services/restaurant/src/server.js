'use strict';
/** Điểm khởi động: node src/server.js (hoặc npm start). Cổng lấy từ RESTAURANT_URL (mặc định 8002). */
const config = require('./config');
const db = require('./db');
const { createApp } = require('./app');

function main() {
  config.internalKey();                  // dừng sớm nếu thiếu khóa nội bộ
  db.open();
  const port = config.listenPort();
  const host = config.get('BIND_HOST', '127.0.0.1');
  const server = createApp().listen(port, host, () => {
    console.log(`Restaurant Service (Node.js ${process.version}) chạy tại http://${host}:${port}`);
  });
  server.on('error', (e) => { console.error(`Không mở được cổng ${port}: ${e.message}`); process.exit(1); });
  const stop = () => server.close(() => { db.close(); process.exit(0); });
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

try {
  main();
} catch (e) {
  console.error(e.message);
  process.exit(1);
}
