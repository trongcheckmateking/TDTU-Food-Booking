"""Máy chủ giao diện web (cổng 8000): phục vụ HTML/CSS/JS tĩnh và /config.js chứa địa chỉ 5 service."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from common import config

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="TDTU Food Booking - Web UI", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/config.js", include_in_schema=False)
def config_js():
    services = {name.lower(): config.get(f"PUBLIC_{name}_URL", config.service_url(name))
                for name in ("AUTH", "RESTAURANT", "ORDER", "NOTIFICATION", "REVIEW")}
    body = f"window.APP_CONFIG = {json.dumps({'services': services})};"
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/health", include_in_schema=False)
def health():
    return {"service": "web", "status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "assets" / "favicon.svg", media_type="image/svg+xml")


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
