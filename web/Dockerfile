# Máy chủ giao diện web (Python/FastAPI, cổng 8000). Build từ thư mục gốc dự án:
#   docker build -f web/Dockerfile -t tdtu-food/web .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY common/ common/
COPY web/ web/
RUN useradd --system --uid 10001 --home-dir /app app
USER app

ENV TDTU_ROOT=/app BIND_HOST=0.0.0.0
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
