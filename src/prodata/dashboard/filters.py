"""Filtros da página do dashboard e dados para o HTML exportado (spec 021).

O filtro vale para todo visual cuja tabela tem a coluna; os demais ficam como estão e avisam.
Nada aqui executa o fluxo: os visuais são recalculados a partir da tabela guardada de cada caixa de BI.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import polars as pl

from prodata.domain.dashboard import DashFilter
from prodata.nodes.bi import ChartConfig, KpiConfig, TableConfig, VennConfig, as_date

EMPTY_LABEL = "(vazio)"
MAX_OPTIONS = 500
CROSS_FILTER_CHARTS = {"bar", "hbar", "donut", "pareto"}
# Acima disso, o HTML ficaria pesado demais para abrir: o usuário pode gerar sem filtros.
MAX_EXPORT_BYTES = 40 * 1024 * 1024


def kind_for(dtype: pl.DataType) -> str:
    if dtype.is_numeric():
        return "number"
    if dtype == pl.Date or isinstance(dtype, pl.Datetime):
        return "date"
    return "list"


def is_active(f: DashFilter) -> bool:
    if f.kind == "list":
        return bool(f.selected)
    return f.min is not None or f.max is not None


def _label(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String).fill_null(EMPTY_LABEL)


def _condition(df: pl.DataFrame, f: DashFilter) -> pl.Expr:
    if f.kind == "list":
        return _label(f.column).is_in(f.selected)
    if f.kind == "number":
        value = pl.col(f.column).cast(pl.Float64, strict=False)
        lower = pl.lit(True) if f.min is None else value >= float(f.min)
        upper = pl.lit(True) if f.max is None else value <= float(f.max)
    else:
        dates = pl.lit(as_date(df[f.column]))
        lower = pl.lit(True) if f.min is None else dates >= pl.lit(str(f.min)).str.to_date("%Y-%m-%d")
        upper = pl.lit(True) if f.max is None else dates <= pl.lit(str(f.max)).str.to_date("%Y-%m-%d")
    return (lower & upper).fill_null(False)


def apply_filters(df: pl.DataFrame, filters: list[DashFilter]) -> tuple[pl.DataFrame, list[str]]:
    """Tabela filtrada e as colunas de filtros ativos que ela não tem."""
    missing = []
    for f in filters:
        if not is_active(f):
            continue
        if f.column not in df.columns:
            missing.append(f.column)
            continue
        df = df.filter(_condition(df, f))
    return df, missing


def filters_for(config: Any, filters: list[DashFilter]) -> list[DashFilter]:
    """Coluna, barra e rosca não se filtram pela própria categoria: mostram todas e apagam as de fora, para dar para trocar."""
    if isinstance(config, ChartConfig) and config.chart_type in CROSS_FILTER_CHARTS:
        return [f for f in filters if not (f.kind == "list" and f.column == config.x_column)]
    return filters


def filter_options(tables: list[pl.DataFrame]) -> list[dict[str, Any]]:
    """Colunas que podem virar filtro, em quantos visuais aparecem e seus valores."""
    columns: dict[str, dict[str, Any]] = {}
    for df in tables:
        for name, dtype in df.schema.items():
            kind = kind_for(dtype)
            entry = columns.setdefault(name, {"column": name, "kind": kind, "visuals": 0, "_parts": []})
            entry["visuals"] += 1
            if entry["kind"] == kind:
                entry["_parts"].append(df[name])
    return [
        _describe(entry) for entry in sorted(columns.values(), key=lambda e: (-e["visuals"], e["column"]))
    ]


def _describe(entry: dict[str, Any]) -> dict[str, Any]:
    parts: list[pl.Series] = entry.pop("_parts")
    if entry["kind"] == "list":
        seen: set[str] = set()
        for part in parts:
            seen.update(part.cast(pl.String).fill_null(EMPTY_LABEL).unique().to_list())
        values = sorted(seen)
        return {**entry, "values": values[:MAX_OPTIONS], "truncated": len(values) > MAX_OPTIONS}
    if entry["kind"] == "number":
        numbers = [p.cast(pl.Float64, strict=False) for p in parts]
        lows = [v for n in numbers if (v := n.min()) is not None and math.isfinite(v)]  # type: ignore[arg-type]
        highs = [v for n in numbers if (v := n.max()) is not None and math.isfinite(v)]  # type: ignore[arg-type]
        return {**entry, "min": min(lows, default=None), "max": max(highs, default=None)}
    dates = [as_date(p) for p in parts]
    low = [d.min() for d in dates if d.drop_nulls().len()]
    high = [d.max() for d in dates if d.drop_nulls().len()]
    return {
        **entry,
        "min": min(low).isoformat() if low else None,  # type: ignore[type-var,union-attr]
        "max": max(high).isoformat() if high else None,  # type: ignore[type-var,union-attr]
    }


# ------------------------------------------------------------------ dados do HTML


def used_columns(tool: str, config: Any, df: pl.DataFrame, filters: list[DashFilter]) -> list[str]:
    """Só o que o visual e os filtros precisam: o restante da tabela não entra no arquivo."""
    match config:
        case ChartConfig():
            names = [config.x_column, config.y_column, config.series_column]
        case KpiConfig():
            names = [config.column, config.date_column]
        case VennConfig():
            names = (
                [*config.flag_columns] if config.mode == "flags" else [config.key_column, config.group_column]
            )
        case TableConfig():
            names = [*(config.columns or df.columns), config.sort_column]
        case _:
            raise ValueError(f"Ferramenta sem visual: {tool}")
    names += [f.column for f in filters]
    return [c for c in dict.fromkeys(names) if c and c in df.columns]


def column_type(dtype: pl.DataType) -> str:
    if dtype == pl.Boolean:
        return "bool"
    if dtype.is_integer():
        return "int"
    if dtype.is_numeric():
        return "float"
    if dtype == pl.Date or isinstance(dtype, pl.Datetime):
        return "date"
    return "string"


def json_values(series: pl.Series) -> list[Any]:
    dtype = series.dtype
    if (
        dtype == pl.Date
        or isinstance(dtype, pl.Datetime)
        or dtype == pl.Time
        or isinstance(dtype, pl.Duration)
    ):
        return series.cast(pl.String).to_list()
    if dtype.is_decimal():
        series = series.cast(pl.Float64)
    elif not (dtype.is_numeric() or dtype in (pl.Boolean, pl.String)):
        return [None if v is None else str(v) for v in series.to_list()]
    values = series.to_list()
    if series.dtype.is_float():
        return [None if v is None or not math.isfinite(v) else v for v in values]
    return values


class ExportTables:
    """Colunas iguais entre caixas entram uma vez só no arquivo."""

    def __init__(self) -> None:
        self.columns: dict[str, list[Any]] = {}
        self.bytes = 0

    def add(self, series: pl.Series) -> str:
        values = json_values(series)
        raw = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        key = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if key not in self.columns:
            self.columns[key] = values
            self.bytes += len(raw)
        return key
