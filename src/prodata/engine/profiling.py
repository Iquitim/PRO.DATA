"""Perfil de colunas: barra de qualidade (OK/vazio/nulo), estatísticas e histogramas."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

HISTOGRAM_BINS = 8
TOP_VALUES = 6


def simple_type(dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return "Int64"
    if dtype.is_float() or dtype.is_decimal():
        return "Float64"
    if dtype == pl.Boolean:
        return "Boolean"
    if dtype.is_temporal():
        return "Date"
    return "String"


def schema_of(df: pl.DataFrame) -> list[dict[str, str]]:
    return [{"name": name, "type": simple_type(dtype)} for name, dtype in df.schema.items()]


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _numeric_profile(series: pl.Series) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = series.drop_nulls().cast(pl.Float64).to_numpy()
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {}, []
    stats = {
        "min": round(float(values.min()), 4),
        "max": round(float(values.max()), 4),
        "mean": round(float(values.mean()), 4),
        "median": round(float(np.median(values)), 4),
        "std": round(float(values.std()), 4),
        "sum": round(float(values.sum()), 4),
    }
    if stats["min"] == stats["max"]:
        return stats, [{"label": f"{stats['min']:g}", "count": int(values.size), "pct": 100.0}]
    counts, edges = np.histogram(values, bins=HISTOGRAM_BINS)
    peak = max(int(counts.max()), 1)
    hist = [
        {"label": f"{edges[i]:,.4g} – {edges[i + 1]:,.4g}", "count": int(c), "pct": _pct(int(c), peak)}
        for i, c in enumerate(counts)
    ]
    return stats, hist


def _categorical_profile(series: pl.Series) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts = series.drop_nulls().cast(pl.String).value_counts(sort=True).head(TOP_VALUES)
    rows = counts.rows()
    if not rows:
        return {}, []
    peak = max(int(rows[0][1]), 1)
    hist = [{"label": str(v)[:40], "count": int(c), "pct": _pct(int(c), peak)} for v, c in rows]
    return {"top": str(rows[0][0]), "top_count": int(rows[0][1])}, hist


def profile_column(series: pl.Series) -> dict[str, Any]:
    total = series.len()
    kind = simple_type(series.dtype)
    nulls = int(series.null_count())
    empties = 0
    if kind == "String" and total:
        empties = int(series.drop_nulls().cast(pl.String).str.strip_chars().eq("").sum())
    ok = max(0, total - nulls - empties)

    stats: dict[str, Any] = {}
    hist: list[dict[str, Any]] = []
    if ok:
        stats, hist = (
            _numeric_profile(series) if kind in ("Int64", "Float64") else _categorical_profile(series)
        )

    return {
        "name": series.name,
        "type": kind,
        "raw_type": str(series.dtype),
        "total": total,
        "ok_count": ok,
        "null_count": nulls,
        "empty_count": empties,
        "ok_pct": _pct(ok, total) if total else 100.0,
        "null_pct": _pct(nulls, total),
        "empty_pct": _pct(empties, total),
        "unique_count": int(series.n_unique()),
        "stats": stats,
        "histogram": hist,
    }


def profile(df: pl.DataFrame) -> dict[str, Any]:
    return {
        "row_count": df.height,
        "col_count": df.width,
        "columns": [profile_column(df[c]) for c in df.columns],
    }
