#!/usr/bin/env bash
# Linux/macOS. Dùng:  ./run.sh setup | doctor | pg-setup | start | seed | stop | status | reset-demo --yes | test
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
VENV_PY=".venv/bin/python"
case "${1:-}" in
  setup)
    "$PY" -m venv .venv
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    "$VENV_PY" -m pip install -r requirements.txt
    "$VENV_PY" manage.py init-env
    "$VENV_PY" manage.py build
    "$VENV_PY" manage.py init-db
    "$VENV_PY" manage.py doctor || true
    echo "Tiếp theo: tạo DB PostgreSQL (./run.sh pg-setup hoặc docker compose, xem README), rồi ./run.sh start và ./run.sh seed";;
  test)
    "$VENV_PY" -m pip install -r requirements-dev.txt >/dev/null
    "$VENV_PY" manage.py test-services
    "$VENV_PY" -m pytest tests/unit tests/integration tests/e2e;;
  "")
    echo "Dùng: ./run.sh setup | doctor | pg-setup | start | seed | stop | status | reset-demo --yes | test"; exit 1;;
  *)
    [ -x "$VENV_PY" ] || { echo "Chưa cài đặt, chạy ./run.sh setup trước"; exit 1; }
    exec "$VENV_PY" manage.py "$@";;
esac
