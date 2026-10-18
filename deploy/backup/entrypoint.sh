#!/bin/sh
# Chạy công cụ sao lưu bằng uid 10001 - cùng uid với các service có dữ liệu - để tệp SQLite tạo ra khi đọc
# (-wal, -shm) và tệp khôi phục vẫn thuộc service, không bị root chiếm.
set -e
mkdir -p "$BACKUP_DIR"
chown 10001:10001 "$BACKUP_DIR" 2>/dev/null || true
exec su-exec 10001:10001 python3 /app/scripts/backup.py "$@"
