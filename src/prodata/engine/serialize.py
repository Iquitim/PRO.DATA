"""Conversão de linhas Polars para valores JSON válidos (sem NaN/Infinity)."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import polars as pl


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    return str(value)


def json_rows(df: pl.DataFrame) -> list[dict[str, Any]]:
    return [{k: json_value(v) for k, v in row.items()} for row in df.iter_rows(named=True)]
