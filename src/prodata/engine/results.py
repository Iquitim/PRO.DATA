"""Consulta paginada das tabelas em cache: busca, filtros exploratórios, ordenação e perfil."""

from __future__ import annotations

from typing import Any, Literal

import polars as pl
from pydantic import BaseModel

from prodata.engine import profiling
from prodata.engine.cache import ResultCache
from prodata.engine.serialize import json_rows
from prodata.errors import InvalidInputError, NotFoundError

FilterOp = Literal[
    "eq", "ne", "gt", "ge", "lt", "le", "between",
    "contains", "not_contains", "starts_with", "ends_with", "in",
    "is_null", "not_null",
]  # fmt: skip


class ExploreFilter(BaseModel):
    """Condição exploratória: só afeta a visualização, nunca o fluxo."""

    column: str
    op: FilterOp
    value: Any = None
    value2: Any = None


def _typed(series_dtype: pl.DataType, raw: Any, column: str) -> Any:
    if raw is None:
        raise InvalidInputError(f"Informe um valor para filtrar '{column}'.")
    if series_dtype.is_numeric():
        try:
            return float(str(raw).replace(",", "."))
        except ValueError as exc:
            raise InvalidInputError(f"'{raw}' não é um número válido para '{column}'.") from exc
    if series_dtype == pl.Boolean:
        return str(raw).strip().lower() in ("true", "1", "sim", "verdadeiro")
    return str(raw)


def _expr(f: ExploreFilter, dtype: pl.DataType) -> pl.Expr:
    col = pl.col(f.column)
    if f.op == "is_null":
        return col.is_null()
    if f.op == "not_null":
        return col.is_not_null()

    text = col.cast(pl.String).str.to_lowercase()
    needle = str(f.value or "").lower()
    match f.op:
        case "contains":
            return text.str.contains(needle, literal=True)
        case "not_contains":
            return ~text.str.contains(needle, literal=True)
        case "starts_with":
            return text.str.starts_with(needle)
        case "ends_with":
            return text.str.ends_with(needle)
        case "in":
            items = f.value if isinstance(f.value, list) else str(f.value or "").split(",")
            values = [str(v).strip() for v in items if str(v).strip()]
            return col.cast(pl.String).is_in(values)

    # Comparações: números comparam como número; datas e textos como texto (ISO ordena certo).
    target = col if dtype.is_numeric() or dtype == pl.Boolean else col.cast(pl.String)
    value = _typed(dtype, f.value, f.column)
    match f.op:
        case "eq":
            return target == value
        case "ne":
            return target != value
        case "gt":
            return target > value
        case "ge":
            return target >= value
        case "lt":
            return target < value
        case "le":
            return target <= value
        case _:  # between
            return target.is_between(value, _typed(dtype, f.value2, f.column))


def apply_filters(df: pl.DataFrame, filters: list[ExploreFilter]) -> pl.DataFrame:
    if not filters:
        return df
    missing = [f.column for f in filters if f.column not in df.columns]
    if missing:
        raise InvalidInputError(f"Coluna(s) inexistente(s) no filtro: {', '.join(missing)}")
    return df.filter(pl.all_horizontal(_expr(f, df.schema[f.column]).fill_null(False) for f in filters))


def page(
    cache: ResultCache,
    workflow_id: str,
    node_id: str,
    anchor: str,
    *,
    offset: int = 0,
    limit: int = 100,
    search: str = "",
    sort_col: str | None = None,
    sort_desc: bool = False,
    filters: list[ExploreFilter] | None = None,
) -> dict[str, Any]:
    df = cache.table(workflow_id, node_id, anchor)
    if df is None:
        raise NotFoundError("Sem resultado para esta saída. Execute o fluxo.")

    view = apply_filters(df, filters or [])
    if search.strip() and df.width:
        needle = search.strip().lower()
        view = view.filter(
            pl.any_horizontal(
                pl.col(c)
                .cast(pl.String)
                .str.to_lowercase()
                .str.contains(needle, literal=True)
                .fill_null(False)
                for c in df.columns
            )
        )
    if sort_col and sort_col in view.columns:
        view = view.sort(sort_col, descending=sort_desc, nulls_last=True)

    narrowed = bool(filters) or bool(search.strip())
    return {
        "row_count": df.height,
        "filtered_count": view.height,
        "col_count": df.width,
        "offset": offset,
        "limit": limit,
        # Com filtros/busca, o perfil descreve só as linhas visíveis (exploração).
        "profile": profiling.profile(view) if narrowed else cache.profile(workflow_id, node_id, anchor),
        "profile_scope": "filtered" if narrowed else "all",
        "rows": json_rows(view.slice(offset, limit)),
    }
