"""Ferramentas de combinação: Join, Summarize, Union e SQL (DuckDB)."""

from __future__ import annotations

from typing import Literal

import duckdb
import polars as pl
from pydantic import BaseModel, Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

# ------------------------------------------------------------------ Join


class JoinKey(BaseModel):
    left: str = Field("", title="Esquerda [L]", json_schema_extra=ui(widget="column", port="L"))
    right: str = Field("", title="Direita [R]", json_schema_extra=ui(widget="column", port="R"))


class JoinConfig(ToolConfig):
    keys: list[JoinKey] = Field(default_factory=lambda: [JoinKey()], title="Chaves de junção")
    right_prefix: str = Field(
        "r_", title="Prefixo para colunas repetidas da direita", json_schema_extra=ui(group="Avançado")
    )


@tool(
    type="transform.join",
    name="Join",
    category="transform",
    icon="join",
    description="Junta [L] e [R] pelas chaves. Saídas: [L] só na esquerda, [J] combinados, [R] só na direita.",
    config=JoinConfig,
    inputs=[Port("L", "L", "Esquerda"), Port("R", "R", "Direita")],
    outputs=[Port("L", "L", "Só na esquerda"), Port("J", "J", "Combinados"), Port("R", "R", "Só na direita")],
    annotate=lambda c: " · ".join(f"{k.left} = {k.right}" for k in c.keys if k.left),
)
def join(ctx: NodeContext, cfg: JoinConfig) -> NodeOutput:
    left, right = ctx.input("L"), ctx.input("R")
    keys = [k for k in cfg.keys if k.left and k.right]
    if not keys:
        raise ValueError("Defina ao menos um par de chaves.")
    left_on = [k.left for k in keys]
    right_on = [k.right for k in keys]
    if missing := [c for c in left_on if c not in left.columns]:
        raise ValueError(f"Chave(s) inexistente(s) em [L]: {', '.join(missing)}")
    if missing := [c for c in right_on if c not in right.columns]:
        raise ValueError(f"Chave(s) inexistente(s) em [R]: {', '.join(missing)}")

    clashes = {c: f"{cfg.right_prefix}{c}" for c in right.columns if c not in right_on and c in left.columns}
    joined = left.join(
        right.rename(clashes), left_on=left_on, right_on=right_on, how="inner", nulls_equal=False
    )
    return NodeOutput(
        tables={
            "L": left.join(right, left_on=left_on, right_on=right_on, how="anti"),
            "J": joined,
            "R": right.join(left, left_on=right_on, right_on=left_on, how="anti"),
        }
    )


# ------------------------------------------------------------------ Summarize

AggOp = Literal[
    "sum", "mean", "median", "min", "max", "count", "count_all", "n_unique", "first", "last", "concat"
]
_AGG_LABELS = {
    "sum": "Soma",
    "mean": "Média",
    "median": "Mediana",
    "min": "Mínimo",
    "max": "Máximo",
    "count": "Contagem (não nulos)",
    "count_all": "Contagem (linhas)",
    "n_unique": "Valores distintos",
    "first": "Primeiro",
    "last": "Último",
    "concat": "Concatenar texto",
}


class Aggregation(BaseModel):
    column: str = Field("", title="Coluna", json_schema_extra=ui(widget="column"))
    agg: AggOp = Field("sum", title="Operação", json_schema_extra=ui(labels=_AGG_LABELS))
    alias: str = Field("", title="Nome da saída", json_schema_extra=ui(placeholder="automático"))


class SummarizeConfig(ToolConfig):
    group_by: list[str] = Field(
        default_factory=list, title="Agrupar por", json_schema_extra=ui(widget="columns")
    )
    aggregations: list[Aggregation] = Field(default_factory=lambda: [Aggregation()], title="Agregações")


def _agg_expr(item: Aggregation) -> pl.Expr:
    col = pl.col(item.column)
    alias = item.alias.strip() or f"{item.agg}_{item.column}"
    match item.agg:
        case "sum":
            expr = col.sum()
        case "mean":
            expr = col.mean()
        case "median":
            expr = col.median()
        case "min":
            expr = col.min()
        case "max":
            expr = col.max()
        case "count":
            expr = col.count()
        case "count_all":
            expr = pl.len()
        case "n_unique":
            expr = col.n_unique()
        case "first":
            expr = col.first()
        case "last":
            expr = col.last()
        case "concat":
            expr = col.cast(pl.String).drop_nulls().unique(maintain_order=True).str.join(", ")
    return expr.alias(alias)


@tool(
    type="transform.summarize",
    name="Summarize",
    category="transform",
    icon="sigma",
    description="Agrupa e agrega: soma, média, mediana, mínimo, máximo, contagens e concatenação.",
    config=SummarizeConfig,
    annotate=lambda c: ("Por " + ", ".join(c.group_by)) if c.group_by else "Total geral",
)
def summarize(ctx: NodeContext, cfg: SummarizeConfig) -> NodeOutput:
    df = ctx.input()
    if missing := [c for c in cfg.group_by if c not in df.columns]:
        raise ValueError(f"Coluna(s) de agrupamento inexistente(s): {', '.join(missing)}")
    items = [a for a in cfg.aggregations if a.column or a.agg == "count_all"]
    if missing := [a.column for a in items if a.agg != "count_all" and a.column not in df.columns]:
        raise ValueError(f"Coluna(s) de agregação inexistente(s): {', '.join(missing)}")
    exprs = [_agg_expr(a) for a in items] or [pl.len().alias("linhas")]
    out = df.group_by(cfg.group_by, maintain_order=True).agg(exprs) if cfg.group_by else df.select(exprs)
    return NodeOutput(tables={"out": out})


# ------------------------------------------------------------------ Union


class UnionConfig(ToolConfig):
    mode: Literal["by_name", "by_position"] = Field(
        "by_name",
        title="Alinhar colunas",
        json_schema_extra=ui(labels={"by_name": "Pelo nome", "by_position": "Pela posição"}),
    )
    source_column: str = Field(
        "",
        title="Coluna de origem",
        description="Opcional: grava 1 ou 2 indicando de qual entrada veio a linha.",
    )


@tool(
    type="transform.union",
    name="Union",
    category="transform",
    icon="stack",
    description="Empilha as entradas verticalmente, alinhando colunas pelo nome ou pela posição.",
    config=UnionConfig,
    inputs=[Port("in1", "1", "Entrada 1"), Port("in2", "2", "Entrada 2", required=False)],
    annotate=lambda c: "Pelo nome" if c.mode == "by_name" else "Pela posição",
)
def union(ctx: NodeContext, cfg: UnionConfig) -> NodeOutput:
    frames = [ctx.inputs[p] for p in ("in1", "in2") if p in ctx.inputs]
    if cfg.source_column:
        frames = [f.with_columns(pl.lit(i + 1).alias(cfg.source_column)) for i, f in enumerate(frames)]
    if cfg.mode == "by_position":
        width = frames[0].width
        if any(f.width != width for f in frames):
            raise ValueError("Para alinhar pela posição as entradas precisam ter o mesmo número de colunas.")
        frames = [
            frames[0],
            *(f.rename(dict(zip(f.columns, frames[0].columns, strict=True))) for f in frames[1:]),
        ]
        return NodeOutput(tables={"out": pl.concat(frames, how="vertical_relaxed")})
    return NodeOutput(tables={"out": pl.concat(frames, how="diagonal_relaxed")})


# ------------------------------------------------------------------ DuckDB SQL


class SqlConfig(ToolConfig):
    sql: str = Field(
        "SELECT *\nFROM input_1\nLIMIT 100",
        title="Consulta",
        description="As entradas estão disponíveis como as tabelas input_1 e input_2.",
        json_schema_extra=ui(widget="sql"),
    )


@tool(
    type="transform.sql_query",
    name="SQL (DuckDB)",
    category="transform",
    icon="terminal",
    description="Consulta SQL analítica em memória sobre as entradas, usando DuckDB.",
    config=SqlConfig,
    inputs=[Port("in", "1", "input_1"), Port("in2", "2", "input_2", required=False)],
    annotate=lambda c: " ".join(c.sql.split())[:40],
)
def sql_query(ctx: NodeContext, cfg: SqlConfig) -> NodeOutput:
    with duckdb.connect(":memory:") as con:
        con.register("input_1", ctx.input("in"))
        if "in2" in ctx.inputs:
            con.register("input_2", ctx.inputs["in2"])
        try:
            return NodeOutput(tables={"out": con.sql(cfg.sql).pl()})
        except duckdb.Error as exc:
            raise ValueError(str(exc).split("\n\nLINE")[0]) from exc
