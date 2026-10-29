"""Ferramentas de BI: publicam gráficos e indicadores no Dashboard."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, ToolConfig, tool

ChartAgg = Literal["sum", "mean", "count", "min", "max"]
_AGG_LABELS = {"sum": "Soma", "mean": "Média", "count": "Contagem", "min": "Mínimo", "max": "Máximo"}


class ChartConfig(ToolConfig):
    title: str = Field("Novo gráfico", title="Título")
    chart_type: Literal["bar", "hbar", "line", "donut"] = Field(
        "bar",
        title="Tipo",
        json_schema_extra=ui(
            labels={"bar": "Colunas", "hbar": "Barras horizontais", "line": "Linha", "donut": "Rosca"}
        ),
    )
    x_column: str = Field("", title="Categoria (eixo X)", json_schema_extra=ui(widget="column"))
    y_column: str = Field(
        "",
        title="Valor (eixo Y)",
        json_schema_extra=ui(widget="column", show_if={"agg": ["sum", "mean", "min", "max"]}),
    )
    agg: ChartAgg = Field("sum", title="Agregação", json_schema_extra=ui(labels=_AGG_LABELS))
    sort: Literal["value_desc", "value_asc", "label"] = Field(
        "value_desc",
        title="Ordenação",
        json_schema_extra=ui(
            labels={
                "value_desc": "Maior valor primeiro",
                "value_asc": "Menor valor primeiro",
                "label": "Pela categoria",
            }
        ),
    )
    max_items: int = Field(12, ge=2, le=50, title="Máximo de categorias")


def _aggregate(df: pl.DataFrame, value: str, agg: ChartAgg) -> pl.Expr:
    if agg == "count":
        return pl.len().alias("value")
    col = pl.col(value).cast(pl.Float64, strict=False)
    return getattr(col, agg)().alias("value")


@tool(
    type="bi.chart",
    name="Chart",
    category="bi",
    icon="chart",
    description="Agrega os dados e publica um gráfico no Dashboard. Repassa a entrada sem alteração.",
    config=ChartConfig,
    annotate=lambda c: c.title,
)
def chart(ctx: NodeContext, cfg: ChartConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.x_column not in df.columns:
        raise ValueError("Escolha a coluna de categoria (eixo X).")
    if cfg.agg != "count" and cfg.y_column not in df.columns:
        raise ValueError("Escolha a coluna de valor (eixo Y).")

    grouped = df.group_by(cfg.x_column).agg(_aggregate(df, cfg.y_column, cfg.agg))
    grouped = grouped.with_columns(pl.col(cfg.x_column).cast(pl.String).fill_null("(vazio)").alias("label"))
    if cfg.sort == "label":
        grouped = grouped.sort("label")
    else:
        grouped = grouped.sort("value", descending=cfg.sort == "value_desc", nulls_last=True)

    rows = grouped.select("label", "value").rows()
    series = [{"label": label, "value": round(float(v or 0), 4)} for label, v in rows[: cfg.max_items]]
    others = sum(float(v or 0) for _, v in rows[cfg.max_items :])
    if len(rows) > cfg.max_items and cfg.agg in ("sum", "count"):
        series.append({"label": "Outros", "value": round(others, 4)})

    widget = {
        "widget_type": "chart",
        "title": cfg.title,
        "chart_type": cfg.chart_type,
        "x_column": cfg.x_column,
        "y_column": cfg.y_column if cfg.agg != "count" else "",
        "agg": cfg.agg,
        "series": series,
        "row_count": df.height,
    }
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})


class KpiConfig(ToolConfig):
    title: str = Field("Indicador", title="Título")
    column: str = Field(
        "",
        title="Coluna",
        json_schema_extra=ui(widget="column", show_if={"metric": ["sum", "mean", "min", "max", "n_unique"]}),
    )
    metric: Literal["sum", "mean", "min", "max", "count", "n_unique"] = Field(
        "sum",
        title="Métrica",
        json_schema_extra=ui(
            labels={**_AGG_LABELS, "count": "Contagem de linhas", "n_unique": "Valores distintos"}
        ),
    )
    prefix: str = Field("", title="Prefixo", json_schema_extra=ui(placeholder="R$ "))
    suffix: str = Field("", title="Sufixo")
    decimals: int = Field(0, ge=0, le=6, title="Casas decimais")


@tool(
    type="bi.kpi_card",
    name="KPI Card",
    category="bi",
    icon="gauge",
    description="Calcula um indicador (soma, média, contagem...) e publica como cartão no Dashboard.",
    config=KpiConfig,
    annotate=lambda c: c.title,
)
def kpi_card(ctx: NodeContext, cfg: KpiConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.metric == "count":
        value = float(df.height)
    else:
        if cfg.column not in df.columns:
            raise ValueError("Escolha a coluna do indicador.")
        series = df[cfg.column]
        if cfg.metric == "n_unique":
            value = float(series.n_unique())
        else:
            numeric = series.cast(pl.Float64, strict=False).drop_nulls()
            value = float(getattr(numeric, cfg.metric)() or 0) if numeric.len() else 0.0

    widget = {
        "widget_type": "kpi",
        "title": cfg.title,
        "column": cfg.column,
        "metric": cfg.metric,
        "value": value,
        "prefix": cfg.prefix,
        "suffix": cfg.suffix,
        "decimals": cfg.decimals,
        "row_count": df.height,
    }
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})
