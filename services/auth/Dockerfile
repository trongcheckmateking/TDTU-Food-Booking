# Auth Service (Python/FastAPI, cổng 8001). Build từ thư mục gốc dự án:
#   docker build -f services/auth/Dockerfile -t tdtu-food/auth .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY common/ common/
COPY services/__init__.py services/__init__.py
COPY services/auth/ services/auth/
RUN useradd --system --uid 10001 --home-dir /app app && mkdir /data && chown app:app /data
USER app

ENV TDTU_ROOT=/app DATA_DIR=/data BIND_HOST=0.0.0.0
VOLUME /data
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2)"
# --proxy-headers: lấy IP thật của người dùng từ X-Forwarded-For do gateway đặt (dùng cho khóa đăng nhập sai nhiều lần).
# Auth không mở cổng ra ngoài, chỉ gateway gọi được nên tin header này.
# --no-access-log: log truy cập do middleware ghi (kèm rid=<X-Request-ID>), tránh ghi trùng.
CMD ["python", "-m", "uvicorn", "services.auth.app:app", "--host", "0.0.0.0", "--port", "8001", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", "--no-access-log"]
