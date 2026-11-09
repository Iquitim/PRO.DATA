"""Estado por período (spec 030, RF-3031..3035): de eventos para uma foto por item e por período.

Serve para qualquer tabela de eventos. O passado vem dos eventos: o que eles não explicam fica "sem histórico",
nunca com o valor de hoje. A exceção é escolhida pela pessoa: num item que nunca mudou, o estado atual é o de sempre.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal, cast

import polars as pl
from pydantic import Field

from prodata.engine.sql.fragment import Fragment, NoTranslationError, SqlContext, sql_for
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

NO_HISTORY = "sem histórico"
MAX_ROWS = 3_000_000
_EVERY = {"day": "1d", "week": "1w", "month": "1mo"}
_NAMES = {"day": "dia", "week": "semana", "month": "mês"}


class PeriodStateConfig(ToolConfig):
    item_key: str = Field("", title="Identificador do item [I]", json_schema_extra=ui(widget="column", port="in"))
    created: str = Field(
        "",
        title="Data de criação do item [I]",
        description="Opcional. Sem ela, o item aparece a partir do primeiro evento.",
        json_schema_extra=ui(widget="column", port="in"),
    )
    current_state: str = Field(
        "",
        title="Estado atual do item [I]",
        description="Opcional. Só para item que nunca mudou: se não houve evento, ele sempre esteve nesse estado.",
        json_schema_extra=ui(widget="column", port="in"),
    )
    keep: list[str] = Field(
        default_factory=list, title="Colunas do item para manter", json_schema_extra=ui(widget="columns", port="in")
    )
    event_key: str = Field("", title="Identificador do item [E]", json_schema_extra=ui(widget="column", port="E"))
    when: str = Field("", title="Quando aconteceu [E]", json_schema_extra=ui(widget="column", port="E"))
    new_state: str = Field("", title="Estado depois do evento [E]", json_schema_extra=ui(widget="column", port="E"))
    old_state: str = Field(
        "",
        title="Estado antes do evento [E]",
        description="Opcional, mas recomendado: é o que diz como o item estava antes do primeiro evento.",
        json_schema_extra=ui(widget="column", port="E"),
    )
    only_column: str = Field(
        "",
        title="Usar só eventos em que a coluna [E]",
        description="Opcional. No histórico do Jira, escolha campo.",
        json_schema_extra=ui(widget="column", port="E"),
    )
    only_value: str = Field("", title="tem o valor", description="No histórico do Jira, status.")
    period: Literal["day", "week", "month"] = Field(
        "week", title="Período", json_schema_extra=ui(labels={"day": "Dia", "week": "Semana", "month": "Mês"})
    )
    until: Literal["last_event", "today"] = Field(
        "last_event",
        title="Até quando",
        json_schema_extra=ui(labels={"last_event": "Último evento", "today": "Hoje"}),
    )


def _as_moment(frame: pl.DataFrame, column: str, label: str) -> pl.Series:
    series = frame[column]
    if series.dtype.is_temporal():
        return series.cast(pl.Datetime("us"))
    message = f"A coluna [{column}] de {label} precisa ter datas."
    try:
        parsed = series.cast(pl.String).str.to_datetime(strict=False, time_unit="us")
    except pl.exceptions.ComputeError as exc:
        raise ValueError(message) from exc
    if parsed.null_count() > series.null_count():
        raise ValueError(message)
    return parsed


def _check(cfg: PeriodStateConfig, items: pl.DataFrame, events: pl.DataFrame) -> None:
    for value, title in ((cfg.item_key, "o identificador do item"), (cfg.event_key, "o identificador nos eventos"), (cfg.when, "quando aconteceu"), (cfg.new_state, "o estado depois do evento")):
        if not value:
            raise ValueError(f"Escolha {title}.")
    for frame, port, columns in ((items, "I", [cfg.item_key, cfg.created, cfg.current_state, *cfg.keep]), (events, "E", [cfg.event_key, cfg.when, cfg.new_state, cfg.old_state, cfg.only_column])):
        for column in columns:
            if column and column not in frame.columns:
                raise ValueError(f"A coluna [{column}] não existe na entrada [{port}].")


def _clean_events(cfg: PeriodStateConfig, events: pl.DataFrame) -> pl.DataFrame:
    if cfg.only_column:
        events = events.filter(pl.col(cfg.only_column).cast(pl.String) == cfg.only_value)
    return (
        pl.DataFrame({
            "__key": events[cfg.event_key].cast(pl.String),
            "__when": _as_moment(events, cfg.when, "[E]"),
            "__new": events[cfg.new_state].cast(pl.String),
            "__old": events[cfg.old_state].cast(pl.String) if cfg.old_state else pl.repeat(None, events.height, dtype=pl.String, eager=True),
        })
        .drop_nulls(["__key", "__when"])
        .sort("__when", maintain_order=True)
    )


def _clean_items(cfg: PeriodStateConfig, items: pl.DataFrame) -> pl.DataFrame:
    out = {"__key": items[cfg.item_key].cast(pl.String)}
    out["__created"] = _as_moment(items, cfg.created, "[I]") if cfg.created else pl.repeat(None, items.height, dtype=pl.Datetime("us"), eager=True)
    out["__current"] = items[cfg.current_state].cast(pl.String) if cfg.current_state else pl.repeat(None, items.height, dtype=pl.String, eager=True)
    kept = {c: items[c] for c in cfg.keep if c != cfg.item_key}
    return pl.DataFrame({**out, **kept}).unique("__key", keep="first", maintain_order=True)


def _grid(cfg: PeriodStateConfig, first: datetime, last: datetime) -> pl.DataFrame:
    every = _EVERY[cfg.period]
    start = pl.select(pl.lit(first).dt.truncate(every)).item()
    starts = pl.datetime_range(start, last, every, eager=True, time_unit="us").alias("__start")
    return pl.DataFrame({"__start": starts}).with_columns(
        (pl.col("__start").dt.offset_by(every) - pl.duration(microseconds=1)).alias("__end")
    )


def period_state(items: pl.DataFrame, events: pl.DataFrame, cfg: PeriodStateConfig, today: date | None = None) -> tuple[pl.DataFrame, int]:
    """A tabela de fotos e quantos itens tiveram algum período sem histórico."""
    _check(cfg, items, events)
    ev = _clean_events(cfg, events)
    it = _clean_items(cfg, items)
    moments = [s for s in (it["__created"].min(), ev["__when"].min()) if s is not None]
    if not moments:
        raise ValueError("Não há datas nas entradas para montar os períodos.")
    now = datetime.combine(today or datetime.now(UTC).date(), datetime.max.time()).replace(microsecond=0)
    last_event = ev["__when"].max()
    last = now if cfg.until == "today" or last_event is None else last_event
    grid = _grid(cfg, cast(datetime, min(moments)), cast(datetime, last))
    if it.height * grid.height > MAX_ROWS:
        raise ValueError(f"{it.height:,} itens × {grid.height:,} períodos passam do limite de {MAX_ROWS:,} linhas. Use um período maior ou filtre os itens antes.".replace(",", "."))
    first_ev = ev.group_by("__key", maintain_order=True).agg(pl.col("__when").first().alias("__first"), pl.col("__old").first().alias("__before"))
    photos = (
        it.join(grid, how="cross")
        .join(first_ev, on="__key", how="left")
        .filter(pl.col("__end") >= pl.coalesce("__created", "__first"))
        .sort("__end")
        .join_asof(ev.select("__key", "__when", "__new"), left_on="__end", right_on="__when", by="__key", strategy="backward")
    )
    state = (
        pl.when(pl.col("__new").is_not_null()).then(pl.col("__new"))
        .when(pl.col("__first").is_not_null()).then(pl.coalesce("__before", pl.lit(NO_HISTORY)))
        .otherwise(pl.coalesce("__current", pl.lit(NO_HISTORY)))
    )  # fmt: skip
    horizon = pl.min_horizontal(pl.col("__end"), pl.lit(last))
    photos = photos.with_columns(state.alias("estado"), pl.coalesce("__when", "__created", "__first").alias("__since")).with_columns(
        (horizon - pl.col("__since")).dt.total_days().alias("dias_no_estado"),
        (horizon - pl.col("__created")).dt.total_days().alias("dias_desde_criacao"),
    )
    columns = [pl.col("__key").alias(cfg.item_key), pl.col("__start").dt.date().alias("periodo"), "estado", "dias_no_estado"]
    if cfg.created:
        columns.append("dias_desde_criacao")
    columns += [c for c in cfg.keep if c != cfg.item_key]
    unknown = photos.filter(pl.col("estado") == NO_HISTORY)["__key"].n_unique()
    return photos.select(columns).sort("periodo", cfg.item_key, maintain_order=True), unknown


def _annotation(cfg: PeriodStateConfig) -> str:
    return f"Uma foto por {_NAMES[cfg.period]}"


@tool(
    type="transform.period_state",
    name="Estado por período",
    category="transform",
    icon="clock",
    description="Transforma eventos em fotos: uma linha por item e por período, com o estado de cada item no fim dele.",
    config=PeriodStateConfig,
    inputs=[Port("in", "I", "Itens"), Port("E", "E", "Eventos")],
    annotate=_annotation,
    fingerprint=lambda _ctx, cfg: date.today().isoformat() if cfg.until == "today" else "",
    explainer="period_state",
)
def period_state_tool(ctx: NodeContext, cfg: PeriodStateConfig) -> NodeOutput:
    frame, unknown = period_state(ctx.input("in"), ctx.input("E"), cfg)
    extra: dict[str, object] = {"periods": frame["periodo"].n_unique(), "without_history": unknown}
    if unknown:
        extra["warnings"] = [f'{unknown} item(ns) ficaram "{NO_HISTORY}" em algum período: os eventos não dizem o estado deles.']
    return NodeOutput(tables={"out": frame}, extra=extra)


@sql_for("transform.period_state")
def period_state_sql(_ctx: SqlContext, _cfg: PeriodStateConfig) -> dict[str, Fragment]:
    raise NoTranslationError('A caixa "Estado por período" ainda não tem tradução para SQL.')
