"""Kiểu dữ liệu dùng chung cho Pydantic (kiểm tra chặt, không trả 500 cho dữ liệu sai)."""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator, ConfigDict, Field, StrictInt, StringConstraints

STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _not_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("không được chỉ chứa khoảng trắng")
    return v


def text(min_length: int = 1, max_length: int = 200):
    """Chuỗi đã cắt khoảng trắng hai đầu, không rỗng."""
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length),
                     AfterValidator(_not_blank)]


def _optional_text(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def optional_text(max_length: int = 1000):
    return Annotated[str | None, StringConstraints(max_length=max_length), AfterValidator(_optional_text)]


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
# Tiền VND: số nguyên không âm, tối đa 100 triệu cho 1 món (StrictInt: không nhận 1.5, "1", true)
Money = Annotated[StrictInt, Field(ge=0, le=100_000_000)]
Quantity = Annotated[StrictInt, Field(ge=1, le=50)]
Rating = Annotated[StrictInt, Field(ge=1, le=5)]

Page = Annotated[int, Query(ge=1, le=100_000, description="Trang, bắt đầu từ 1")]
PageSize = Annotated[int, Query(ge=1, le=100, description="Số mục mỗi trang (1–100)")]
