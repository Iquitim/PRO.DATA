"""Controles de conciliação (spec 033): conferência de totais e comparação com a execução anterior."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

# ------------------------------------------------------------------ Reconcile

Measure = Literal["count", "sum", "n_unique"]
MEASURES = {"count": "Linhas", "sum": "Soma", "n_unique": "Valores distintos"}


class Control(BaseModel):
    measure: Measure = Field("count", title="Conferir", json_schema_extra=ui(labels=MEASURES))
    column_a: str = Field(
        "",
        title="Coluna em [A]",
        json_schema_extra=ui(widget="column", port="A", show_if={"measure": ["sum", "n_unique"]}),
    )
    column_b: str = Field(
        "",
        title="Coluna em [B]",
        description="Vazio = a mesma de [A].",
        json_schema_extra=ui(widget="column", port="B", show_if={"measure": ["sum", "n_unique"]}),
    )
    tolerance: float = Field(
        0.01,
        ge=0,
        title="Diferença aceita",
        description="Em valor absoluto. Centavos de arredondamento costumam pedir 0,01.",
    )


class ReconcileConfig(ToolConfig):
    controls: list[Control] = Field(
        default_factory=lambda: [Control()],
        title="Controles",
        description="Cada controle compara o mesmo número calculado em [A] e em [B].",
    )
    on_fail: Literal["stop", "warn"] = Field(
        "stop",
        title="Se não fechar",
        json_schema_extra=ui(
            labels={"stop": "Interromper o fluxo aqui", "warn": "Só avisar e seguir"},
        ),
    )


def _measure(df: pl.DataFrame, measure: str, column: str, side: str) -> float:
    if measure == "count":
        return float(df.height)
    if column not in df.columns:
        raise InvalidInputError(
            f"Coluna '{column}' não existe em [{side}]." if column else f"Escolha a coluna em [{side}]."
        )
    if measure == "n_unique":
        return float(df[column].drop_nulls().n_unique())
    values = df[column].cast(pl.Float64, strict=False)
    return float(values.sum() or 0.0)


def _show(value: float) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text.removesuffix(",00")


def reconcile_table(a: pl.DataFrame, b: pl.DataFrame, controls: list[Control]) -> pl.DataFrame:
    if not controls:
        raise InvalidInputError("Adicione ao menos um controle.")
    rows = []
    for control in controls:
        col_b = control.column_b or control.column_a
        value_a = _measure(a, control.measure, control.column_a, "A")
        value_b = _measure(b, control.measure, col_b, "B")
        diff = value_b - value_a
        name = MEASURES[control.measure]
        if control.measure != "count":
            name += f" de {control.column_a}" + (f" × {col_b}" if col_b != control.column_a else "")
        rows.append(
            {
                "controle": name,
                "valor_a": value_a,
                "valor_b": value_b,
                "diferenca": diff,
                "tolerancia": control.tolerance,
                "situacao": "fecha" if abs(diff) <= control.tolerance + 1e-9 else "não fecha",
            }
        )
    return pl.DataFrame(rows)


@tool(
    type="control.reconcile",
    explainer="reconcile",
    name="Reconcile",
    category="control",
    icon="check-circle",
    description="Confere se [A] e [B] fecham: linhas, soma ou valores distintos. Pode interromper o fluxo quando não fecha.",
    config=ReconcileConfig,
    inputs=[Port("A", "A", "Referência (antes)"), Port("B", "B", "A conferir (depois)")],
    outputs=[Port("out", "O", "Dados de [B], conferidos"), Port("check", "C", "Conferência")],
    annotate=lambda c: f"{len(c.controls)} controle(s)",
)
def reconcile(ctx: NodeContext, cfg: ReconcileConfig) -> NodeOutput:
    a, b = ctx.input("A"), ctx.input("B")
    table = reconcile_table(a, b, cfg.controls)
    failed = table.filter(pl.col("situacao") != "fecha")
    lines = [
        f"{r['controle']}: A {_show(r['valor_a'])}, B {_show(r['valor_b'])} (diferença {_show(r['diferenca'])})"
        for r in failed.iter_rows(named=True)
    ]
    if lines and cfg.on_fail == "stop":
        raise InvalidInputError("A conferência não fechou. " + "; ".join(lines) + ".")
    extra: dict[str, Any] = {"reconcile_failed": failed.height, "reconcile_total": table.height}
    if lines:
        extra["warnings"] = [f"Não fechou: {line}." for line in lines]
    return NodeOutput(tables={"out": b, "check": table}, extra=extra)


# ------------------------------------------------------------------ Compare Runs

MAX_SNAPSHOT_ROWS = 2_000_000
KEEP_DAYS = 62
KEEP_MONTHS = 13
_DIFF_SCHEMA = {"situacao": pl.String, "coluna": pl.String, "antes": pl.String, "agora": pl.String}


class CompareRunsConfig(ToolConfig):
    baseline: Literal["day", "month"] = Field(
        "day",
        title="Comparar com",
        json_schema_extra=ui(
            labels={
                "day": "A última execução de um dia anterior",
                "month": "A última execução de um mês anterior",
            }
        ),
    )
    keys: list[str] = Field(
        default_factory=list,
        title="Colunas que identificam cada linha",
        description="Com elas, a saída D lista o que entrou, o que saiu e o que mudou. Vazio = só os totais.",
        json_schema_extra=ui(widget="columns"),
    )
    columns: list[str] = Field(
        default_factory=list,
        title="Colunas a comparar",
        description="Vazio = todas as que não são chave.",
        json_schema_extra=ui(widget="columns"),
    )


def today() -> date:
    return date.today()


def _snapshots(folder: Path) -> list[tuple[date, Path]]:
    found = []
    for path in folder.glob("*.parquet"):
        try:
            found.append((date.fromisoformat(path.stem), path))
        except ValueError:
            continue
    return sorted(found)


def _baseline(folder: Path, mode: str, now: date) -> tuple[date, Path] | None:
    older = [
        (d, p)
        for d, p in _snapshots(folder)
        if (d < now if mode == "day" else (d.year, d.month) < (now.year, now.month))
    ]
    return older[-1] if older else None


def _prune(folder: Path, now: date) -> None:
    """Ficam os últimos 62 dias e o último de cada mês por 13 meses."""
    last_of_month: dict[tuple[int, int], date] = {}
    for d, _ in _snapshots(folder):
        last_of_month[(d.year, d.month)] = d
    oldest_month = (now.year * 12 + now.month - 1) - KEEP_MONTHS
    for d, path in _snapshots(folder):
        recent = (now - d).days <= KEEP_DAYS
        month_end = last_of_month[(d.year, d.month)] == d and d.year * 12 + d.month - 1 >= oldest_month
        if not recent and not month_end:
            path.unlink(missing_ok=True)


def _compare_signature(ctx: NodeContext, cfg: CompareRunsConfig) -> str:
    try:
        folder = ctx.state_dir()
    except InvalidInputError:
        return ""
    now = today()
    base = _baseline(folder, cfg.baseline, now)
    return f"{now.isoformat()}|{base[1].name}:{base[1].stat().st_mtime_ns}" if base else now.isoformat()


def totals(before: pl.DataFrame | None, now: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    def numbers(df: pl.DataFrame | None, column: str) -> float | None:
        if df is None or column not in df.columns:
            return None
        return float(df[column].cast(pl.Float64, strict=False).sum() or 0.0)

    rows: list[dict[str, Any]] = [
        {
            "medida": "linhas",
            "antes": None if before is None else float(before.height),
            "agora": float(now.height),
        }
    ]
    numeric = [c for c in columns if c in now.columns and now[c].dtype.is_numeric()]
    rows += [
        {"medida": f"soma de {c}", "antes": numbers(before, c), "agora": numbers(now, c)} for c in numeric
    ]
    table = pl.DataFrame(rows, schema={"medida": pl.String, "antes": pl.Float64, "agora": pl.Float64})
    diff = pl.col("agora") - pl.col("antes")
    return table.with_columns(
        diff.alias("diferenca"),
        pl.when(pl.col("antes") != 0)
        .then((diff / pl.col("antes").abs() * 100).round(2))
        .alias("variacao_pct"),
    )


def _unique_keys(df: pl.DataFrame, keys: list[str], when: str) -> None:
    if df.select(keys).is_duplicated().any():
        raise InvalidInputError(
            f"A chave {', '.join(keys)} repete na tabela {when}: escolha colunas que identifiquem cada linha."
        )


def differences(before: pl.DataFrame, now: pl.DataFrame, keys: list[str], columns: list[str]) -> pl.DataFrame:
    """Uma linha por novidade: o que entrou, o que saiu e, para o que mudou, uma linha por coluna."""
    for key in keys:
        if key not in now.columns:
            raise InvalidInputError(f"Coluna-chave '{key}' não existe na entrada.")
        if key not in before.columns:
            raise InvalidInputError(f"A execução guardada não tem a coluna-chave '{key}'.")
    _unique_keys(now, keys, "de agora")
    _unique_keys(before, keys, "guardada")
    # Chaves comparadas como texto: o tipo pode ter mudado de uma execução para a outra.
    as_text = [pl.col(k).cast(pl.String) for k in keys]
    old, new = before.with_columns(as_text), now.with_columns(as_text)
    empty = {name: pl.lit(None, dtype=pl.String).alias(name) for name in ("coluna", "antes", "agora")}
    parts = [
        new.join(old, on=keys, how="anti", nulls_equal=True).select(
            *keys, pl.lit("novo").alias("situacao"), *empty.values()
        ),
        old.join(new, on=keys, how="anti", nulls_equal=True).select(
            *keys, pl.lit("saiu").alias("situacao"), *empty.values()
        ),
    ]
    both = new.join(old, on=keys, how="inner", suffix="__antes", nulls_equal=True)
    for column in columns:
        if column not in new.columns or column not in old.columns:
            continue
        was, is_now = pl.col(f"{column}__antes").cast(pl.String), pl.col(column).cast(pl.String)
        parts.append(
            both.filter(was.ne_missing(is_now)).select(
                *keys,
                pl.lit("mudou").alias("situacao"),
                pl.lit(column).alias("coluna"),
                was.alias("antes"),
                is_now.alias("agora"),
            )
        )
    return pl.concat(parts, how="vertical_relaxed").sort(keys, maintain_order=True)


@tool(
    type="control.compare_runs",
    explainer="compare_runs",
    name="Compare Runs",
    category="control",
    icon="clock",
    description="Guarda a tabela a cada dia de execução e mostra o que mudou desde um dia ou um mês anterior: totais em [T], linhas em [D].",
    config=CompareRunsConfig,
    outputs=[Port("out", "O", "Dados"), Port("D", "D", "Diferenças"), Port("T", "T", "Totais")],
    annotate=lambda c: "desde o mês anterior" if c.baseline == "month" else "desde o dia anterior",
    fingerprint=_compare_signature,
)
def compare_runs(ctx: NodeContext, cfg: CompareRunsConfig) -> NodeOutput:
    df = ctx.input()
    if df.height > MAX_SNAPSHOT_ROWS:
        raise InvalidInputError(
            f"A tabela tem mais de {MAX_SNAPSHOT_ROWS:,} linhas: resuma antes de comparar.".replace(",", ".")
        )
    folder = ctx.state_dir()
    now = today()
    base = _baseline(folder, cfg.baseline, now)
    before = pl.read_parquet(base[1]) if base else None
    compared = cfg.columns or [c for c in df.columns if c not in cfg.keys]
    warnings: list[str] = []
    diff = pl.DataFrame(schema={**{k: pl.String for k in cfg.keys}, **_DIFF_SCHEMA})
    if before is None:
        warnings.append("Primeira execução guardada: a comparação começa na próxima, em outro dia.")
    else:
        gone = [c for c in before.columns if c not in df.columns]
        new = [c for c in df.columns if c not in before.columns]
        if gone or new:
            warnings.append(
                "As colunas mudaram desde a execução guardada"
                + (f": saiu {', '.join(gone)}" if gone else "")
                + (f"{';' if gone else ':'} entrou {', '.join(new)}" if new else "")
                + "."
            )
        if cfg.keys:
            diff = differences(before, df, cfg.keys, compared)
    # A de hoje substitui a anterior de hoje: a última execução do dia é a que vale para amanhã.
    target = folder / f"{now.isoformat()}.parquet"
    tmp = target.with_suffix(".tmp")
    df.write_parquet(tmp)
    os.replace(tmp, target)
    _prune(folder, now)
    extra: dict[str, Any] = {
        "compare_baseline": base[0].isoformat() if base else None,
        "compare_changes": diff.height,
    }
    if warnings:
        extra["warnings"] = warnings
    return NodeOutput(tables={"out": df, "D": diff, "T": totals(before, df, compared)}, extra=extra)
