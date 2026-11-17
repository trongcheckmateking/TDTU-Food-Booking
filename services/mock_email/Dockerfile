# Mock Email Provider "MockMail" (Python/FastAPI, cổng 9000) - dịch vụ email bên thứ ba GIẢ LẬP (Unit 20).
# Build từ thư mục gốc dự án:
#   docker build -f services/mock_email/Dockerfile -t tdtu-food/mock-email .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY common/ common/
COPY services/__init__.py services/__init__.py
COPY services/mock_email/ services/mock_email/
RUN useradd --system --uid 10001 --home-dir /app app
USER app

ENV TDTU_ROOT=/app BIND_HOST=0.0.0.0
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "services.mock_email.app:app", "--host", "0.0.0.0", "--port", "9000", "--no-server-header"]
