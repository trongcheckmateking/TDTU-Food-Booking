# Container sao lưu: pg_dump / pg_restore cùng phiên bản với PostgreSQL của Notification + python3 cho scripts/backup.py.
# Build từ thư mục gốc dự án: docker build -f deploy/backup/Dockerfile -t tdtu-food/backup .
FROM postgres:16-alpine

RUN apk add --no-cache python3 tzdata su-exec \
 && mkdir -p /data/auth /data/restaurant /data/order /data/review /backups \
 && chown -R 10001:10001 /data /backups
WORKDIR /app
COPY common/__init__.py common/config.py common/
COPY scripts/backup.py scripts/
COPY deploy/backup/entrypoint.sh /usr/local/bin/tdtu-backup
RUN sed -i 's/\r$//' /usr/local/bin/tdtu-backup && chmod 755 /usr/local/bin/tdtu-backup

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 TDTU_ROOT=/app BACKUP_DIR=/backups \
    AUTH_DATA_DIR=/data/auth RESTAURANT_DATA_DIR=/data/restaurant ORDER_DATA_DIR=/data/order REVIEW_DATA_DIR=/data/review
ENTRYPOINT ["tdtu-backup"]
CMD ["create", "--loop"]
