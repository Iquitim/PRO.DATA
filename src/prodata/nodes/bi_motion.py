"""Bolhas e Sankey (spec 030, RF-3053 e RF-3054). O espelho no navegador fica em dash_compute.js."""

from __future__ import annotations

from typing import Any

import polars as pl

MAX_LINKS = 40


def _label(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String).fill_null("(vazio)")


def _value(column: str, agg: str, name: str) -> pl.Expr:
    if agg == "count" or not column:
        return pl.len().cast(pl.Float64).alias(name)
    return getattr(pl.col(column).cast(pl.Float64, strict=False), agg)().alias(name)


def bubble(
    df: pl.DataFrame, category: str, x: str, y: str, size: str, agg: str, max_items: int
) -> dict[str, Any]:
    """Uma bolha por categoria: posição nos dois valores e tamanho no terceiro (ou na quantidade de linhas)."""
    grouped = df.group_by(_label(category).alias("label")).agg(
        _value(x, agg, "x"), _value(y, agg, "y"), _value(size, agg, "size")
    )
    valid = grouped.drop_nulls(["x", "y"]).with_columns(pl.col("size").fill_null(0.0))
    top = valid.sort(["size", "label"], descending=[True, False]).head(max_items)
    points = [
        {"label": r["label"], "x": round(r["x"], 4), "y": round(r["y"], 4), "size": round(r["size"], 4)}
        for r in top.to_dicts()
    ]
    return {"points": points, "point_count": valid.height, "sampled": False}


def sankey(df: pl.DataFrame, source: str, target: str, value: str, agg: str) -> dict[str, Any]:
    """Quanto passa de cada origem para cada destino. Só fluxos positivos: largura negativa não existe."""
    data = df.with_columns(_label(source).alias("source"), _label(target).alias("target"))
    grouped = data.group_by("source", "target").agg(_value(value, agg, "value")).filter(pl.col("value") > 0)
    top = grouped.sort(["value", "source", "target"], descending=[True, False, False]).head(MAX_LINKS)
    links = [
        {"source": r["source"], "target": r["target"], "value": round(r["value"], 4)} for r in top.to_dicts()
    ]
    return {"links": links, "link_count": grouped.height}
