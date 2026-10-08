"""Gọi REST sang service khác với timeout, kiểm tra status/JSON và ánh xạ lỗi nhất quán.

Quy tắc ánh xạ khi upstream trả về (trừ các mã nằm trong `allow`):
- không kết nối được / quá thời gian  -> 503 UPSTREAM_UNAVAILABLE
- 5xx                                 -> 502 UPSTREAM_ERROR
- body không phải JSON object/list    -> 502 UPSTREAM_BAD_RESPONSE
- 4xx khác                            -> 502 UPSTREAM_REJECTED (lỗi hợp đồng giữa các service)
"""
from __future__ import annotations

import logging

import requests

from . import config
from .errors import ApiError

log = logging.getLogger("tdtu.http")


def call(method: str, url: str, service: str, *, token: str | None = None, internal: bool = False,
         json: dict | None = None, params: dict | None = None, allow: tuple[int, ...] = (),
         timeout: float | None = None) -> tuple[int, dict | list]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if internal:
        headers["X-Internal-Key"] = config.internal_key()
    try:
        resp = requests.request(method, url, headers=headers, json=json, params=params,
                                timeout=timeout or config.http_timeout())
    except requests.Timeout:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", f"{service} phản hồi quá thời gian chờ")
    except requests.RequestException:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", f"Không kết nối được {service}")

    try:
        body = resp.json()
    except ValueError:
        body = None

    if 200 <= resp.status_code < 300 or resp.status_code in allow:
        if resp.status_code == 204:
            return resp.status_code, {}
        if not isinstance(body, (dict, list)):
            raise ApiError(502, "UPSTREAM_BAD_RESPONSE", f"{service} trả dữ liệu không phải JSON hợp lệ")
        return resp.status_code, body
    if resp.status_code >= 500:
        log.warning("%s trả %s cho %s %s", service, resp.status_code, method, url)
        raise ApiError(502, "UPSTREAM_ERROR", f"{service} đang gặp lỗi, vui lòng thử lại")
    log.warning("%s từ chối %s %s: %s", service, method, url, resp.status_code)
    raise ApiError(502, "UPSTREAM_REJECTED", f"{service} từ chối yêu cầu nội bộ (HTTP {resp.status_code})")
