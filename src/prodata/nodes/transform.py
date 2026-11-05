"""Ferramentas de combinação: Join, Summarize, Union e SQL (DuckDB)."""

from __future__ import annotations

from typing import Literal

import duckdb
import polars as pl
from pydantic import BaseModel, Field

from prodata.engine import sandbox
from prodata.engine.profiling import simple_type
from prodata.engine.sql.fragment import (
    ROW_POSITION,
    Fragment,
    NoTranslationError,
    SqlContext,
    join_list,
    numbered,
    q,
    single_select,
    sql_for,
)
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool
from prodata.nodes.prep import SelectField, apply_select
from prodata.nodes.prep_sql import ORDER_NOTE, select_items

# ------------------------------------------------------------------ Join


class JoinKey(BaseModel):
    left: str = Field("", title="Esquerda [L]", json_schema_extra=ui(widget="column", port="L"))
    right: str = Field("", title="Direita [R]", json_schema_extra=ui(widget="column", port="R"))


class JoinConfig(ToolConfig):
    keys: list[JoinKey] = Field(default_factory=lambda: [JoinKey()], title="Chaves de junção")
    keys_mode: Literal["both", "left", "right"] = Field(
        "both",
        title="Colunas da chave no J",
        json_schema_extra=ui(
            labels={
                "both": "As duas (esquerda e direita)",
                "left": "Só da esquerda",
                "right": "Só da direita",
            }
        ),
    )
    # Select embutido no J (spec 019), como no Alteryx: manter, renomear, converter e ordenar.
    fields: list[SelectField] = Field(
        default_factory=list,
        title="Colunas do J",
        description="Colunas não listadas são mantidas como estão.",
        json_schema_extra=ui(widget="select_columns", source="join"),
    )
    order: list[str] = Field(default_factory=list, title="Ordem", json_schema_extra=ui(widget="hidden"))
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
    explainer="join",
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

    # Colunas da direita com nome repetido (chaves inclusive) ganham o prefixo. Por padrão o J mantém as
    # chaves dos dois lados (spec 018): uma coluna calculada usada como chave na direita não pode sumir.
    clashes = {c: f"{cfg.right_prefix}{c}" for c in right.columns if c in left.columns}
    renamed_right_keys = [clashes.get(k, k) for k in right_on]
    joined = left.join(
        right.rename(clashes),
        left_on=left_on,
        right_on=renamed_right_keys,
        how="inner",
        nulls_equal=False,
        coalesce=False,
    )
    joined = _keep_key_side(joined, cfg.keys_mode, left_on, right_on, renamed_right_keys)
    joined, warnings = apply_select(joined, cfg.fields, cfg.order)
    return NodeOutput(
        tables={
            "L": left.join(right, left_on=left_on, right_on=right_on, how="anti"),
            "J": joined,
            "R": right.join(left, left_on=right_on, right_on=left_on, how="anti"),
        },
        extra={"warnings": warnings} if warnings else {},
    )


def _keep_key_side(
    joined: pl.DataFrame, mode: str, left_on: list[str], right_on: list[str], renamed: list[str]
) -> pl.DataFrame:
    """Chaves no J (spec 019): as duas, só a da esquerda (como até a 0.3.8) ou só a da direita.
    Sobrando um lado só, a chave da direita volta ao nome original."""
    if mode == "left":
        return joined.drop(list(dict.fromkeys(renamed)))
    if mode == "right":
        joined = joined.drop(list(dict.fromkeys(left_on)))
        back = {r: o for r, o in zip(renamed, right_on, strict=True) if r != o and o not in joined.columns}
        return joined.rename(back)
    return joined


# ------------------------------------------------------------------ Summarize

AggOp = Literal[
    "sum",
    "mean",
    "median",
    "mode",
    "std",
    "min",
    "max",
    "count",
    "count_all",
    "n_unique",
    "first",
    "last",
    "concat",
]
_AGG_LABELS = {
    "sum": "Soma",
    "mean": "Média",
    "median": "Mediana",
    "mode": "Moda (mais frequente)",
    "std": "Desvio padrão",
    "min": "Mínimo",
    "max": "Máximo",
    "count": "Contagem (não nulos)",
    "count_all": "Contagem (linhas)",
    "n_unique": "Valores distintos",
    "first": "Primeiro",
    "last": "Último",
    "concat": "Concatenar texto",
}


_ANY_TYPE = ["count", "count_all", "n_unique", "first", "last", "mode"]
# O que faz sentido para cada tipo de coluna (spec 026). Número aceita tudo.
AGG_BY_TYPE: dict[str, list[str]] = {
    "String": [*_ANY_TYPE, "concat", "min", "max"],
    "Date": [*_ANY_TYPE, "min", "max"],
    "Boolean": [*_ANY_TYPE, "sum", "mean"],
}


class Aggregation(BaseModel):
    column: str = Field("", title="Coluna", json_schema_extra=ui(widget="column"))
    agg: AggOp = Field(
        "sum",
        title="Operação",
        json_schema_extra=ui(labels=_AGG_LABELS, options_by_type=AGG_BY_TYPE, source="column"),
    )
    alias: str = Field("", title="Nome da saída", json_schema_extra=ui(placeholder="automático"))


class SummarizeConfig(ToolConfig):
    group_by: list[str] = Field(
        default_factory=list,
        title="Agrupar por",
        description="Opcional. Vazio = calcula sobre a tabela inteira (ex.: a soma total de uma coluna).",
        json_schema_extra=ui(widget="columns"),
    )
    aggregations: list[Aggregation] = Field(default_factory=lambda: [Aggregation()], title="Agregações")


def _check_operation(item: Aggregation, df: pl.DataFrame) -> None:
    """Só recusa o que o motor não calcula, com uma mensagem clara no lugar do erro técnico."""
    if item.agg == "count_all":
        return
    kind = simple_type(df.schema[item.column])
    impossible = {"String": ("sum", "mean", "median", "std"), "Date": ("sum", "std")}.get(kind, ())
    if item.agg in impossible:
        name = {"String": "texto", "Date": "data"}[kind]
        raise ValueError(
            f'"{_AGG_LABELS[item.agg]}" não se aplica à coluna [{item.column}], que é de {name}. '
            f"Escolha outra operação, como Contagem ou Valores distintos, ou converta a coluna com um Select."
        )


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
        case "mode":
            # Valor mais frequente; empate → o menor, para o resultado não variar entre execuções.
            expr = col.drop_nulls().mode().sort().first()
        case "std":
            expr = col.std()  # amostral (n - 1), como DESVPAD.A do Excel
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
    description="Agrupa e agrega: soma, média, mediana, moda, desvio padrão, mínimo, máximo, contagens e concatenação.",
    config=SummarizeConfig,
    explainer="summarize",
    annotate=lambda c: ("Por " + ", ".join(c.group_by)) if c.group_by else "Total geral",
)
def summarize(ctx: NodeContext, cfg: SummarizeConfig) -> NodeOutput:
    df = ctx.input()
    if missing := [c for c in cfg.group_by if c not in df.columns]:
        raise ValueError(f"Coluna(s) de agrupamento inexistente(s): {', '.join(missing)}")
    items = [a for a in cfg.aggregations if a.column or a.agg == "count_all"]
    if missing := [a.column for a in items if a.agg != "count_all" and a.column not in df.columns]:
        raise ValueError(f"Coluna(s) de agregação inexistente(s): {', '.join(missing)}")
    for a in items:
        _check_operation(a, df)
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
    description="Uma consulta SELECT em memória sobre as entradas, usando DuckDB.",
    config=SqlConfig,
    inputs=[Port("in", "1", "input_1"), Port("in2", "2", "input_2", required=False)],
    annotate=lambda c: " ".join(c.sql.split())[:40],
)
def sql_query(ctx: NodeContext, cfg: SqlConfig) -> NodeOutput:
    with sandbox.sandboxed_connection() as con:
        # Um fluxo recebido de outra pessoa executa ao abrir: esta caixa consulta, nunca grava.
        if not single_select(con, cfg.sql.strip().rstrip(";")):
            raise ValueError(
                "A caixa SQL aceita só uma consulta SELECT, sem comandos que gravem ou alterem dados."
            )
        con.register("input_1", ctx.input("in"))
        if "in2" in ctx.inputs:
            con.register("input_2", ctx.inputs["in2"])
        sandbox.lock(con)
        try:
            return NodeOutput(tables={"out": con.sql(cfg.sql).pl()})
        except duckdb.Error as exc:
            if sandbox.is_blocked(exc):
                raise ValueError(sandbox.BLOCKED_MESSAGE) from exc
            raise ValueError(str(exc).split("\n\nLINE")[0]) from exc


# ------------------------------------------------------------------ tradução para SQL (spec 020)


@sql_for("transform.join")
def join_sql(ctx: SqlContext, cfg: JoinConfig) -> dict[str, Fragment]:
    left, right = ctx.input("L"), ctx.input("R")
    keys = [k for k in cfg.keys if k.left and k.right]
    if not keys:
        raise ValueError("Defina ao menos um par de chaves.")
    if missing := [k.left for k in keys if k.left not in left.columns]:
        raise ValueError(f"Chave(s) inexistente(s) em [L]: {', '.join(missing)}")
    if missing := [k.right for k in keys if k.right not in right.columns]:
        raise ValueError(f"Chave(s) inexistente(s) em [R]: {', '.join(missing)}")

    condition = " AND ".join(f"l.{q(k.left)} = r.{q(k.right)}" for k in keys)
    renamed = {c: f"{cfg.right_prefix}{c}" if c in left.columns else c for c in right.columns}
    left_keys = {k.left for k in keys}
    right_keys = {k.right for k in keys}
    # (nome como sai do Join, expressão, família), na mesma ordem do motor; o lado das chaves vem depois.
    columns = [
        (c, f"l.{q(c)}", left.kinds[c])
        for c in left.columns
        if not (cfg.keys_mode == "right" and c in left_keys)
    ]
    taken = {c[0] for c in columns}
    for c in right.columns:
        name = renamed[c]
        if c in right_keys:
            if cfg.keys_mode == "left":
                continue
            if cfg.keys_mode == "right" and c not in taken:
                name = c  # sobrou um lado só: a chave volta ao nome original
        columns.append((name, f"r.{q(c)}", right.kinds[c]))
    items, what = select_items(columns, cfg.fields, cfg.order)
    if not items:
        raise ValueError("Todas as colunas do J foram descartadas: sobrou uma tabela sem colunas.")
    label = ", ".join(k.left if k.left == k.right else f"{k.left} = {k.right}" for k in keys)
    sides = f"FROM {q(left.block)} AS l\nINNER JOIN {q(right.block)} AS r\n  ON {condition}"
    only = "SELECT l.*\nFROM {a} AS l\nWHERE NOT EXISTS (\n  SELECT 1 FROM {b} AS r WHERE {c}\n)"
    only_right = "SELECT r.*\nFROM {b} AS r\nWHERE NOT EXISTS (\n  SELECT 1 FROM {a} AS l WHERE {c}\n)"
    names = {"a": q(left.block), "b": q(right.block), "c": condition}
    explain = f"Junta por {label} e mantém as linhas que casaram" + (f"; {', '.join(what)}" if what else "")
    return {
        "L": Fragment(only.format(**names), f"Linhas da esquerda sem par em {label}"),
        "J": Fragment(f"SELECT\n  {join_list(items)}\n{sides}", explain),
        "R": Fragment(only_right.format(**names), f"Linhas da direita sem par em {label}"),
    }


def _agg_sql(item: Aggregation) -> str:
    col = q(item.column) if item.column else ""
    positioned = f"ORDER BY {ROW_POSITION}"
    return {
        # Soma de um grupo só com vazios dá 0 no motor, e NULL no SQL puro.
        "sum": f"COALESCE(sum({col}), 0)",
        "mean": f"avg({col})",
        "median": f"median({col})",
        "mode": f"pd_moda(histogram({col}))",
        "std": f"stddev_samp({col})",
        "min": f"min({col})",
        "max": f"max({col})",
        "count": f"count({col})",
        "count_all": "count(*)",
        # O motor conta o vazio como um valor distinto; COUNT(DISTINCT) não.
        "n_unique": f"count(DISTINCT {col}) + CASE WHEN count(*) > count({col}) THEN 1 ELSE 0 END",
        "first": f"first({col} {positioned})",
        "last": f"last({col} {positioned})",
        "concat": f"COALESCE(array_to_string(pd_distintos(list(CAST({col} AS VARCHAR) {positioned}) FILTER (WHERE {col} IS NOT NULL)), ', '), '')",
    }[item.agg]


_AGG_WORDS = {"sum": "Soma", "mean": "Média", "median": "Mediana", "mode": "Moda", "std": "Desvio padrão", "min": "Mínimo", "max": "Máximo",
              "count": "Conta", "count_all": "Conta as linhas", "n_unique": "Distintos", "first": "Primeiro", "last": "Último", "concat": "Junta"}  # fmt: skip


@sql_for("transform.summarize")
def summarize_sql(ctx: SqlContext, cfg: SummarizeConfig) -> dict[str, Fragment]:
    source = ctx.input()
    if missing := [c for c in cfg.group_by if c not in source.columns]:
        raise ValueError(f"Coluna(s) de agrupamento inexistente(s): {', '.join(missing)}")
    items = [a for a in cfg.aggregations if a.column or a.agg == "count_all"]
    if missing := [a.column for a in items if a.agg != "count_all" and a.column not in source.columns]:
        raise ValueError(f"Coluna(s) de agregação inexistente(s): {', '.join(missing)}")
    aggs = [f"{_agg_sql(a)} AS {q(a.alias.strip() or f'{a.agg}_{a.column}')}" for a in items] or [
        "count(*) AS linhas"
    ]
    ordered = any(a.agg in ("first", "last", "concat") for a in items)
    origin = numbered(source.block) if ordered else q(source.block)
    groups = ", ".join(q(c) for c in cfg.group_by)
    sql = f"SELECT\n  {join_list([*[q(c) for c in cfg.group_by], *aggs])}\nFROM {origin}"
    if groups:
        sql += f"\nGROUP BY {groups}"
    words = [f"{_AGG_WORDS[a.agg]} {a.column}".strip() for a in items] or ["Conta as linhas"]
    explain = ", ".join(words) + (
        f", por {', '.join(cfg.group_by)}" if cfg.group_by else ", na tabela inteira"
    )
    return {"out": Fragment(sql, explain, [ORDER_NOTE] if ordered else [])}


@sql_for("transform.union")
def union_sql(ctx: SqlContext, cfg: UnionConfig) -> dict[str, Fragment]:
    frames = [ctx.inputs[p] for p in ("in1", "in2") if p in ctx.inputs]
    if not frames:
        raise ValueError("Conecte ao menos uma entrada.")
    if cfg.mode == "by_position" and any(len(f.columns) != len(frames[0].columns) for f in frames):
        raise ValueError("Para alinhar pela posição as entradas precisam ter o mesmo número de colunas.")
    extra = f", {{i}} AS {q(cfg.source_column)}" if cfg.source_column else ""
    selects = [f"SELECT *{extra.format(i=i + 1)} FROM {q(f.block)}" for i, f in enumerate(frames)]
    glue = "\nUNION ALL\n" if cfg.mode == "by_position" else "\nUNION ALL BY NAME\n"
    how = "pela posição das colunas" if cfg.mode == "by_position" else "pelo nome das colunas"
    return {"out": Fragment(glue.join(selects), f"Empilha {len(frames)} tabelas {how}")}


@sql_for("transform.sql_query")
def sql_query_sql(ctx: SqlContext, cfg: SqlConfig) -> dict[str, Fragment]:
    """A consulta do usuário entra como está, desde que seja um único SELECT (RF-2032)."""
    source = cfg.sql.strip().rstrip(";").strip()
    if not source:
        raise ValueError("Escreva a consulta.")
    with duckdb.connect(":memory:") as con:
        try:
            statements = con.extract_statements(source)
        except duckdb.Error as exc:
            raise ValueError(str(exc).split("\n")[0]) from exc
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise NoTranslationError("Só uma consulta SELECT pode entrar no código gerado.")
    names = {"in": "input_1", "in2": "input_2"}
    aliases = [
        f"{alias} AS (SELECT * FROM {q(ctx.inputs[port].block)})"
        for port, alias in names.items()
        if port in ctx.inputs
    ]
    head = "WITH " + ",\n".join(aliases) + "\n" if aliases else ""
    return {
        "out": Fragment(
            f"{head}SELECT * FROM (\n{source}\n)",
            "Consulta SQL escrita no fluxo",
            ["A consulta foi escrita à mão: revise se ela depende de algo do DuckDB."],
        )
    }
