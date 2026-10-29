"""Ferramentas de BI: publicam gráficos, indicadores, diagramas de Venn e tabelas no Dashboard.

Todos os cálculos (agregações, acumulado do Pareto, variação do KPI, regiões do Venn) ficam aqui,
no motor, para serem testáveis sem interface (constituição II). O dashboard só desenha.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from itertools import combinations
from typing import Any, Literal

import polars as pl
from pydantic import Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, ToolConfig, tool

ChartAgg = Literal["sum", "mean", "count", "min", "max"]
_AGG_LABELS = {"sum": "Soma", "mean": "Média", "count": "Contagem", "min": "Mínimo", "max": "Máximo"}

ChartType = Literal[
    "bar", "hbar", "line", "donut", "stacked", "grouped", "stacked100", "area", "area_stacked",
    "pareto", "funnel", "scatter",
]  # fmt: skip
_CHART_LABELS = {
    "bar": "Colunas",
    "hbar": "Barras horizontais",
    "line": "Linha",
    "donut": "Rosca",
    "stacked": "Colunas empilhadas",
    "grouped": "Colunas agrupadas",
    "stacked100": "Colunas 100%",
    "area": "Área",
    "area_stacked": "Área empilhada",
    "pareto": "Pareto",
    "funnel": "Funil",
    "scatter": "Dispersão",
}
# Gráficos com segunda dimensão (uma série por valor da coluna de série).
SERIES_CHARTS = ["stacked", "grouped", "stacked100", "line", "area", "area_stacked"]
MAX_SERIES = 8
MAX_POINTS = 2000


class ChartConfig(ToolConfig):
    title: str = Field("Novo gráfico", title="Título")
    chart_type: ChartType = Field("bar", title="Tipo", json_schema_extra=ui(labels=_CHART_LABELS))
    x_column: str = Field("", title="Categoria (eixo X)", json_schema_extra=ui(widget="column"))
    y_column: str = Field(
        "",
        title="Valor (eixo Y)",
        json_schema_extra=ui(widget="column", show_if={"agg": ["sum", "mean", "min", "max"]}),
    )
    agg: ChartAgg = Field("sum", title="Agregação", json_schema_extra=ui(labels=_AGG_LABELS))
    series_column: str = Field(
        "",
        title="Série (2ª dimensão)",
        description="Opcional: uma cor por valor desta coluna (até 8; as demais viram 'Outras').",
        json_schema_extra=ui(widget="column", show_if={"chart_type": [*SERIES_CHARTS, "scatter"]}),
    )
    sort: Literal["value_desc", "value_asc", "label"] = Field(
        "value_desc",
        title="Ordenação",
        description="O Pareto sempre ordena do maior para o menor.",
        json_schema_extra=ui(
            labels={
                "value_desc": "Maior valor primeiro",
                "value_asc": "Menor valor primeiro",
                "label": "Pela categoria",
            }
        ),
    )
    max_items: int = Field(12, ge=2, le=50, title="Máximo de categorias")
    pareto_threshold: float = Field(
        80,
        ge=1,
        le=99,
        title="Linha de corte do Pareto (%)",
        json_schema_extra=ui(show_if={"chart_type": ["pareto"]}),
    )


def _aggregate(value: str, agg: ChartAgg) -> pl.Expr:
    if agg == "count":
        return pl.len().alias("value")
    col = pl.col(value).cast(pl.Float64, strict=False)
    return getattr(col, agg)().alias("value")


def _label(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.String).fill_null("(vazio)")


def _rows(grouped: pl.DataFrame, cfg: ChartConfig) -> list[tuple[str, float]]:
    if cfg.sort == "label" and cfg.chart_type != "pareto":
        grouped = grouped.sort("label")
    else:
        descending = cfg.sort != "value_asc" or cfg.chart_type == "pareto"
        grouped = grouped.sort("value", descending=descending, nulls_last=True)
    return [(str(label), float(v or 0)) for label, v in grouped.select("label", "value").rows()]


def _limit(rows: list[tuple[str, float]], cfg: ChartConfig) -> list[dict[str, Any]]:
    series = [{"label": label, "value": round(v, 4)} for label, v in rows[: cfg.max_items]]
    if len(rows) > cfg.max_items and cfg.agg in ("sum", "count"):
        series.append({"label": "Outros", "value": round(sum(v for _, v in rows[cfg.max_items :]), 4)})
    return series


def pareto(series: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Acumulado em % e destaque das categorias até a linha de corte (inclui a que a cruza)."""
    total = sum(max(0.0, s["value"]) for s in series) or 1.0
    acc = 0.0
    out = []
    for s in series:
        before = acc
        acc += max(0.0, s["value"])
        out.append(
            {**s, "cum_pct": round(acc / total * 100, 2), "highlight": before / total * 100 < threshold}
        )
    return out


def _multi_series(df: pl.DataFrame, cfg: ChartConfig) -> tuple[list[dict[str, Any]], list[str]]:
    """Categorias × séries. As 8 séries de maior total ficam; as demais somam em 'Outras'."""
    data = df.with_columns(_label(cfg.x_column).alias("label"), _label(cfg.series_column).alias("serie"))
    cells = data.group_by("label", "serie").agg(_aggregate(cfg.y_column, cfg.agg))
    totals = cells.group_by("serie").agg(pl.col("value").sum()).sort("value", descending=True)
    names = totals["serie"].to_list()
    keep = names[:MAX_SERIES] if len(names) <= MAX_SERIES else names[: MAX_SERIES - 1]
    folds = len(names) > len(keep) and cfg.agg in ("sum", "count")
    cells = cells.with_columns(
        pl.when(pl.col("serie").is_in(keep)).then(pl.col("serie")).otherwise(pl.lit("Outras")).alias("serie")
    )
    if not folds:
        cells = cells.filter(pl.col("serie") != "Outras")
    cells = cells.group_by("label", "serie").agg(pl.col("value").sum())
    by_label = cells.group_by("label").agg(pl.col("value").sum())
    order = _rows(by_label, cfg)[: cfg.max_items]
    values: dict[str, dict[str, float]] = {}
    for label, serie, v in cells.rows():
        values.setdefault(label, {})[serie] = round(float(v or 0), 4)
    series = [
        {"label": label, "value": round(total, 4), "values": values.get(label, {})} for label, total in order
    ]
    return series, [*keep, *(["Outras"] if folds else [])]


def _scatter(df: pl.DataFrame, cfg: ChartConfig) -> dict[str, Any]:
    cols = [
        pl.col(cfg.x_column).cast(pl.Float64, strict=False).alias("x"),
        pl.col(cfg.y_column).cast(pl.Float64, strict=False).alias("y"),
    ]
    if cfg.series_column:
        cols.append(_label(cfg.series_column).alias("s"))
    points = df.select(cols).drop_nulls(["x", "y"])
    total = points.height
    if total > MAX_POINTS:
        points = points.sample(MAX_POINTS, seed=42)  # semente fixa: a mesma amostra a cada execução
    return {"points": points.to_dicts(), "point_count": total, "sampled": total > MAX_POINTS}


@tool(
    type="bi.chart",
    name="Chart",
    category="bi",
    icon="chart",
    description="Agrega os dados e publica um gráfico no Dashboard: colunas, linhas, rosca, empilhados, "
    "Pareto, funil e dispersão. Repassa a entrada sem alteração.",
    config=ChartConfig,
    annotate=lambda c: c.title,
)
def chart(ctx: NodeContext, cfg: ChartConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.x_column not in df.columns:
        raise ValueError("Escolha a coluna de categoria (eixo X).")
    if (cfg.agg != "count" or cfg.chart_type == "scatter") and cfg.y_column not in df.columns:
        raise ValueError("Escolha a coluna de valor (eixo Y).")
    if cfg.series_column and cfg.series_column not in df.columns:
        raise ValueError(f"Coluna de série não encontrada: {cfg.series_column}")

    widget: dict[str, Any] = {
        "widget_type": "chart",
        "title": cfg.title,
        "chart_type": cfg.chart_type,
        "x_column": cfg.x_column,
        "y_column": cfg.y_column if cfg.agg != "count" else "",
        "series_column": cfg.series_column,
        "agg": cfg.agg,
        "row_count": df.height,
        "series": [],
    }
    if cfg.chart_type == "scatter":
        widget.update(_scatter(df, cfg), agg="none", y_column=cfg.y_column)
    elif cfg.series_column and cfg.chart_type in SERIES_CHARTS:
        widget["series"], widget["series_names"] = _multi_series(df, cfg)
    else:
        grouped = df.group_by(_label(cfg.x_column).alias("label")).agg(_aggregate(cfg.y_column, cfg.agg))
        series = _limit(_rows(grouped, cfg), cfg)
        if cfg.chart_type == "pareto":
            series = pareto(series, cfg.pareto_threshold)
            widget["threshold"] = cfg.pareto_threshold
        widget["series"] = series
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})


# ------------------------------------------------------------------ KPI (RF-1420..RF-1423)

Period = Literal["day", "week", "month", "quarter", "year"]
_TRUNC = {"day": "1d", "week": "1w", "month": "1mo", "quarter": "1q", "year": "1y"}
_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


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
    number_format: Literal["auto", "compact", "full", "percent"] = Field(
        "auto",
        title="Formato do número",
        json_schema_extra=ui(
            labels={
                "auto": "Automático (compacto acima de 1 milhão)",
                "compact": "Compacto (1,2 mi)",
                "full": "Completo (1.234.567)",
                "percent": "Percentual (0,25 → 25%)",
            }
        ),
    )
    compare: Literal["none", "target", "previous"] = Field(
        "none",
        title="Comparar com",
        json_schema_extra=ui(
            group="Comparação e tendência",
            labels={"none": "Nada", "target": "Uma meta", "previous": "O período anterior"},
        ),
    )
    target: float = Field(
        0, title="Meta", json_schema_extra=ui(group="Comparação e tendência", show_if={"compare": ["target"]})
    )
    date_column: str = Field(
        "",
        title="Coluna de data",
        description="Data ou texto como 2026-10 / 2026-10-29 / 29/10/2026.",
        json_schema_extra=ui(widget="column", group="Comparação e tendência"),
    )
    period: Period = Field(
        "month",
        title="Período",
        json_schema_extra=ui(
            group="Comparação e tendência",
            labels={"day": "Dia", "week": "Semana", "month": "Mês", "quarter": "Trimestre", "year": "Ano"},
        ),
    )
    higher_is_better: bool = Field(
        True, title="Maior é melhor", json_schema_extra=ui(group="Comparação e tendência")
    )
    sparkline: bool = Field(
        False, title="Minigráfico de tendência", json_schema_extra=ui(group="Comparação e tendência")
    )
    sparkline_periods: int = Field(
        12,
        ge=3,
        le=60,
        title="Períodos no minigráfico",
        json_schema_extra=ui(group="Comparação e tendência", show_if={"sparkline": [True]}),
    )
    display: Literal["number", "gauge"] = Field(
        "number",
        title="Exibir como",
        json_schema_extra=ui(labels={"number": "Número (big number)", "gauge": "Medidor"}),
    )
    gauge_max: float = Field(
        0,
        title="Máximo do medidor",
        description="0 = automático (a meta ou o valor, com folga).",
        json_schema_extra=ui(show_if={"display": ["gauge"]}),
    )


def _metric(series: pl.Series, metric: str) -> float:
    if metric == "count":
        return float(series.len())
    if metric == "n_unique":
        return float(series.n_unique())
    numeric = series.cast(pl.Float64, strict=False).drop_nulls()
    return float(getattr(numeric, metric)() or 0) if numeric.len() else 0.0


def as_date(series: pl.Series) -> pl.Series:
    """Coluna de data em Date; texto aceita 2026-10-29, 29/10/2026, 2026-10 e 2026-10-29 13:45:00."""
    if series.dtype == pl.Date:
        return series
    if isinstance(series.dtype, pl.Datetime):
        return series.dt.date()
    text = series.cast(pl.String).str.strip_chars()
    candidates = (
        lambda: text.str.to_date("%Y-%m-%d", strict=False),
        lambda: text.str.to_date("%d/%m/%Y", strict=False),
        lambda: (text + "-01").str.to_date("%Y-%m-%d", strict=False),
        lambda: text.str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False).dt.date(),
    )
    for parse in candidates:
        parsed = parse()
        if parsed.null_count() == series.null_count():
            return parsed
    raise ValueError(
        "A coluna de data tem valores que não são datas (use 2026-10-29, 2026-10 ou 29/10/2026)."
    )


def period_label(d: date, period: str) -> str:
    if period == "day":
        return d.strftime("%d/%m/%Y")
    if period == "week":
        return f"sem. {d.strftime('%d/%m')}"
    if period == "month":
        return f"{_MONTHS[d.month - 1]}/{d.year}"
    if period == "quarter":
        return f"{(d.month - 1) // 3 + 1}º tri/{d.year}"
    return str(d.year)


def by_period(df: pl.DataFrame, cfg: KpiConfig) -> list[tuple[date, float]]:
    if cfg.date_column not in df.columns:
        raise ValueError("Escolha a coluna de data para comparar períodos ou desenhar a tendência.")
    dates = as_date(df[cfg.date_column]).dt.truncate(_TRUNC[cfg.period]).alias("__periodo")
    value = pl.col(cfg.column) if cfg.metric != "count" else pl.lit(1)
    data = df.select(dates, value.alias("__v")).drop_nulls("__periodo")
    out = []
    for (start,), part in sorted(data.group_by(["__periodo"]), key=lambda kv: kv[0][0]):
        out.append(
            (
                start if isinstance(start, date) else datetime.fromisoformat(str(start)).date(),
                _metric(part["__v"], cfg.metric),
            )
        )
    return out


def comparison(value: float, reference: float, higher_is_better: bool) -> dict[str, Any]:
    delta = value - reference
    pct = None if reference == 0 else delta / abs(reference) * 100
    good = None if delta == 0 else (delta > 0) == higher_is_better
    return {
        "reference": reference,
        "delta": delta,
        "delta_pct": None if pct is None else round(pct, 2),
        "good": good,
    }


@tool(
    type="bi.kpi_card",
    name="KPI Card",
    category="bi",
    icon="gauge",
    description="Calcula um indicador (soma, média, contagem...) e publica no Dashboard como big number "
    "ou medidor, com comparação contra meta ou período anterior e tendência.",
    config=KpiConfig,
    annotate=lambda c: c.title,
)
def kpi_card(ctx: NodeContext, cfg: KpiConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.metric != "count" and cfg.column not in df.columns:
        raise ValueError("Escolha a coluna do indicador.")
    source = df[cfg.column] if cfg.metric != "count" else pl.Series([0] * df.height)
    value = _metric(source, cfg.metric)
    widget: dict[str, Any] = {
        "widget_type": "kpi",
        "title": cfg.title,
        "column": cfg.column,
        "metric": cfg.metric,
        "value": value,
        "prefix": cfg.prefix,
        "suffix": cfg.suffix,
        "decimals": cfg.decimals,
        "number_format": cfg.number_format,
        "row_count": df.height,
        "display": cfg.display,
    }
    periods = by_period(df, cfg) if cfg.compare == "previous" or cfg.sparkline else []
    if cfg.compare == "target":
        widget["compare"] = {
            "mode": "target",
            "label": "da meta",
            **comparison(value, cfg.target, cfg.higher_is_better),
        }
    elif cfg.compare == "previous":
        if len(periods) < 2:
            raise ValueError(
                "A comparação com o período anterior precisa de dados em pelo menos dois períodos."
            )
        (cur_d, cur), (prev_d, prev) = periods[-1], periods[-2]
        widget["value"] = cur  # o número passa a ser o do último período
        widget["period_label"] = period_label(cur_d, cfg.period)
        widget["compare"] = {
            "mode": "previous",
            "label": f"vs {period_label(prev_d, cfg.period)}",
            **comparison(cur, prev, cfg.higher_is_better),
        }
    if cfg.sparkline:
        widget["trend"] = [
            {"label": period_label(d, cfg.period), "value": round(v, 4)}
            for d, v in periods[-cfg.sparkline_periods :]
        ]
    if cfg.display == "gauge":
        target = cfg.target if cfg.compare == "target" else 0
        widget["gauge_max"] = cfg.gauge_max or _nice_max(max(widget["value"], target) * 1.15)
        widget["target"] = target or None
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(v))
    return next(m * p for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * p >= v)


# ------------------------------------------------------------------ Venn (RF-1436, RF-1437)

_TRUE = {"true", "1", "sim", "s", "yes", "y", "verdadeiro", "x"}


class VennConfig(ToolConfig):
    title: str = Field("Interseções", title="Título")
    mode: Literal["key_group", "flags"] = Field(
        "key_group",
        title="Como os conjuntos são formados",
        json_schema_extra=ui(
            labels={
                "key_group": "Chave + grupo (ex.: clientes por produto comprado)",
                "flags": "Colunas verdadeiro/falso (uma por conjunto)",
            }
        ),
    )
    key_column: str = Field(
        "",
        title="Chave (o que é contado)",
        json_schema_extra=ui(widget="column", show_if={"mode": ["key_group"]}),
    )
    group_column: str = Field(
        "", title="Coluna do grupo", json_schema_extra=ui(widget="column", show_if={"mode": ["key_group"]})
    )
    groups: list[str] = Field(
        default_factory=list,
        title="Grupos (2 ou 3 valores)",
        json_schema_extra=ui(widget="tags", show_if={"mode": ["key_group"]}, placeholder="Cloud"),
    )
    flag_columns: list[str] = Field(
        default_factory=list,
        title="Colunas (2 ou 3)",
        json_schema_extra=ui(widget="columns", show_if={"mode": ["flags"]}),
    )


def _truthy(series: pl.Series) -> pl.Series:
    if series.dtype == pl.Boolean:
        return series.fill_null(False)
    if series.dtype.is_numeric():
        return (series.fill_null(0) != 0).alias(series.name)
    return series.cast(pl.String).str.strip_chars().str.to_lowercase().is_in(list(_TRUE)).fill_null(False)


def membership(df: pl.DataFrame, cfg: VennConfig) -> tuple[list[str], pl.DataFrame]:
    """Uma linha por entidade e uma coluna booleana por conjunto."""
    if cfg.mode == "flags":
        names = cfg.flag_columns
        missing = [c for c in names if c not in df.columns]
        if missing:
            raise ValueError(f"Colunas não encontradas: {', '.join(missing)}")
        return names, pl.DataFrame([_truthy(df[c]).alias(c) for c in names])
    names = [g.strip() for g in cfg.groups if g.strip()]
    for col in (cfg.key_column, cfg.group_column):
        if col not in df.columns:
            raise ValueError("Escolha a coluna da chave e a do grupo.")
    data = df.select(
        pl.col(cfg.key_column).alias("k"), pl.col(cfg.group_column).cast(pl.String).alias("g")
    ).drop_nulls("k")
    present = set(data["g"].drop_nulls().unique().to_list())
    absent = [n for n in names if n not in present]
    if absent and len(names) in (2, 3):
        raise ValueError(f"Grupo sem nenhuma linha: {', '.join(absent)} (confira maiúsculas e acentos).")
    wide = data.group_by("k").agg([(pl.col("g") == n).any().alias(n) for n in names])
    return names, wide.select(names)


def lens_area(r1: float, r2: float, d: float) -> float:
    """Área da interseção de dois círculos de raios r1, r2 com centros a distância d."""
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return math.pi * min(r1, r2) ** 2
    a1 = r1**2 * math.acos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = r2**2 * math.acos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    k = 0.5 * math.sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))
    return a1 + a2 - k


def venn2_geometry(a: float, b: float, both: float) -> dict[str, float]:
    """Raios com área proporcional a cada conjunto e distância que faz a lente valer a interseção."""
    r1, r2 = math.sqrt(a / math.pi), math.sqrt(b / math.pi)
    target = min(both, a, b)
    lo, hi = abs(r1 - r2), r1 + r2
    for _ in range(80):  # bisseção: a área da lente diminui com a distância
        mid = (lo + hi) / 2
        if lens_area(r1, r2, mid) > target:
            lo = mid
        else:
            hi = mid
    return {"r1": r1, "r2": r2, "d": (lo + hi) / 2}


@tool(
    type="bi.venn",
    name="Venn",
    category="bi",
    icon="venn",
    description="Diagrama de Venn de 2 ou 3 conjuntos no Dashboard: quantos estão em cada combinação "
    "(ex.: clientes que compraram Cloud e AutoML). Repassa a entrada sem alteração.",
    config=VennConfig,
    annotate=lambda c: c.title,
)
def venn(ctx: NodeContext, cfg: VennConfig) -> NodeOutput:
    df = ctx.input()
    names, sets = membership(df, cfg)
    if len(names) not in (2, 3):
        raise ValueError("Escolha 2 ou 3 conjuntos.")
    cols = [sets[n] for n in names]
    in_any = pl.any_horizontal(cols)
    union = int(sets.filter(in_any).height)
    regions: list[dict[str, Any]] = []
    for size in range(1, len(names) + 1):
        for combo in combinations(range(len(names)), size):
            mask = pl.all_horizontal([cols[i] if i in combo else ~cols[i] for i in range(len(names))])
            count = int(sets.filter(mask).height)
            regions.append(
                {"sets": list(combo), "count": count, "pct": round(count / union * 100, 2) if union else 0.0}
            )
    sizes = [int(c.sum()) for c in cols]
    widget: dict[str, Any] = {
        "widget_type": "venn",
        "title": cfg.title,
        "sets": [{"name": n, "size": s} for n, s in zip(names, sizes, strict=True)],
        "regions": regions,
        "union": union,
        "outside": int(sets.height - union),
        "row_count": df.height,
        "proportional": len(names) == 2,
    }
    if len(names) == 2 and sizes[0] and sizes[1]:
        both = next(r["count"] for r in regions if r["sets"] == [0, 1])
        widget["geometry"] = venn2_geometry(sizes[0], sizes[1], both)
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})


# ------------------------------------------------------------------ Table (RF-1433)


class TableConfig(ToolConfig):
    title: str = Field("Tabela", title="Título")
    columns: list[str] = Field(
        default_factory=list,
        title="Colunas",
        description="Vazio = todas.",
        json_schema_extra=ui(widget="columns"),
    )
    sort_column: str = Field("", title="Ordenar por", json_schema_extra=ui(widget="column"))
    sort_desc: bool = Field(True, title="Do maior para o menor")
    max_rows: int = Field(50, ge=1, le=500, title="Máximo de linhas")
    totals: bool = Field(True, title="Linha de totais (colunas numéricas)")


@tool(
    type="bi.table",
    name="Table",
    category="bi",
    icon="table",
    description="Publica uma tabela formatada no Dashboard, com totais e cores por faixa de valor. "
    "Repassa a entrada sem alteração.",
    config=TableConfig,
    annotate=lambda c: c.title,
)
def table(ctx: NodeContext, cfg: TableConfig) -> NodeOutput:
    df = ctx.input()
    cols = cfg.columns or df.columns
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas não encontradas: {', '.join(missing)}")
    view = df.select(cols)
    if cfg.sort_column:
        if cfg.sort_column not in df.columns:
            raise ValueError(f"Coluna de ordenação não encontrada: {cfg.sort_column}")
        view = df.sort(cfg.sort_column, descending=cfg.sort_desc, nulls_last=True).select(cols)
    numeric = [c for c in cols if view.schema[c].is_numeric()]
    rows = view.head(cfg.max_rows)
    widget: dict[str, Any] = {
        "widget_type": "table",
        "title": cfg.title,
        "columns": [{"name": c, "numeric": c in numeric} for c in cols],
        "rows": [[_cell(v) for v in row] for row in rows.rows()],
        "row_count": df.height,
        "truncated": df.height > cfg.max_rows,
    }
    if cfg.totals and numeric:
        widget["totals"] = {c: _cell(view[c].cast(pl.Float64, strict=False).sum()) for c in numeric}
    return NodeOutput(tables={"out": df}, extra={"bi_widget": widget})


def _cell(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)
