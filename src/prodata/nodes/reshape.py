"""Ferramentas de reformatação (spec 013): Cross Tab, Transpose, Text To Columns, Record ID,
Running Total e Append Fields — as operações do Alteryx que faltavam no dia a dia."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

MAX_NEW_COLUMNS = 500  # proteção contra "explosão" de colunas (Cross Tab, Text To Columns)
MAX_APPEND_ROWS = 10_000_000  # Append Fields multiplica linhas


def _require(df: pl.DataFrame, *columns: str) -> None:
    if missing := [c for c in columns if c and c not in df.columns]:
        raise ValueError(f"Coluna(s) inexistente(s): {', '.join(missing)}")


# ------------------------------------------------------------------ Cross Tab

CrossAgg = Literal["sum", "mean", "count", "min", "max", "first", "concat"]
PivotAgg = Literal["sum", "mean", "len", "min", "max", "first"]
_POLARS_AGG: dict[str, PivotAgg] = {
    "sum": "sum", "mean": "mean", "count": "len", "min": "min", "max": "max", "first": "first",
}  # fmt: skip


class CrossTabConfig(ToolConfig):
    group_by: list[str] = Field(
        default_factory=list,
        title="Agrupar por (linhas)",
        description="Cada combinação vira uma linha. Vazio = uma linha só.",
        json_schema_extra=ui(widget="columns"),
    )
    header: str = Field("", title="Coluna com os novos cabeçalhos", json_schema_extra=ui(widget="column"))
    value: str = Field("", title="Coluna de valores", json_schema_extra=ui(widget="column"))
    agg: CrossAgg = Field(
        "sum",
        title="Como combinar valores repetidos",
        json_schema_extra=ui(
            labels={"sum": "Soma", "mean": "Média", "count": "Contagem", "min": "Mínimo", "max": "Máximo",
                    "first": "Primeiro", "concat": "Juntar textos"}
        ),
    )  # fmt: skip


@tool(
    type="transform.crosstab",
    name="Cross Tab",
    category="transform",
    icon="pivot",
    description="Linhas viram colunas (tabela dinâmica): os valores de uma coluna viram cabeçalhos.",
    config=CrossTabConfig,
    explainer="crosstab",
    annotate=lambda c: f"{c.header} → colunas" if c.header else "Escolha a coluna de cabeçalhos",
)
def crosstab(ctx: NodeContext, cfg: CrossTabConfig) -> NodeOutput:
    df = ctx.input()
    if not cfg.header or not cfg.value:
        raise ValueError("Escolha a coluna de cabeçalhos e a coluna de valores.")
    _require(df, cfg.header, cfg.value, *cfg.group_by)
    distinct = df.get_column(cfg.header).n_unique()
    if distinct > MAX_NEW_COLUMNS:
        raise ValueError(
            f"'{cfg.header}' tem {distinct} valores diferentes; o limite é {MAX_NEW_COLUMNS} colunas."
        )
    source = df.with_columns(pl.col(cfg.header).cast(pl.String).fill_null("(vazio)"))
    index = cfg.group_by or None
    if index is None:
        source = source.with_columns(pl.lit(1).alias("__linha"))
        index = ["__linha"]
    if cfg.agg == "concat":
        source = source.group_by([*index, cfg.header], maintain_order=True).agg(
            pl.col(cfg.value).cast(pl.String).str.join(", ")
        )
        out = source.pivot(on=cfg.header, index=index, values=cfg.value)
    else:
        out = source.pivot(
            on=cfg.header, index=index, values=cfg.value, aggregate_function=_POLARS_AGG[cfg.agg]
        )
    return NodeOutput(tables={"out": out.drop("__linha", strict=False)})


# ------------------------------------------------------------------ Transpose


class TransposeConfig(ToolConfig):
    keys: list[str] = Field(
        default_factory=list,
        title="Colunas que ficam (chave)",
        description="Repetidas em cada linha gerada, ex.: cliente, UF.",
        json_schema_extra=ui(widget="columns"),
    )
    columns: list[str] = Field(
        default_factory=list,
        title="Colunas que viram linhas",
        description="Vazio = todas as que não são chave.",
        json_schema_extra=ui(widget="columns"),
    )
    name_column: str = Field("nome", title="Nome da coluna com os cabeçalhos")
    value_column: str = Field("valor", title="Nome da coluna com os valores")


@tool(
    type="transform.transpose",
    name="Transpose",
    category="transform",
    icon="transpose",
    description="Colunas viram linhas (despivotar): cada coluna escolhida vira um par nome/valor.",
    config=TransposeConfig,
    explainer="transpose",
    annotate=lambda c: f"Chave: {', '.join(c.keys)}" if c.keys else "Todas as colunas viram linhas",
)
def transpose(ctx: NodeContext, cfg: TransposeConfig) -> NodeOutput:
    df = ctx.input()
    _require(df, *cfg.keys, *cfg.columns)
    on = cfg.columns or [c for c in df.columns if c not in cfg.keys]
    if not on:
        raise ValueError("Não sobrou nenhuma coluna para virar linha.")
    # Tipos diferentes (texto e número) não cabem numa coluna só: tudo vira texto nesse caso.
    if len({df.schema[c] for c in on}) > 1:
        df = df.with_columns(pl.col(on).cast(pl.String))
    out = df.unpivot(
        on=on, index=cfg.keys or None, variable_name=cfg.name_column, value_name=cfg.value_column
    )
    return NodeOutput(tables={"out": out})


# ------------------------------------------------------------------ Text To Columns


class TextToColumnsConfig(ToolConfig):
    column: str = Field("", title="Coluna a dividir", json_schema_extra=ui(widget="column"))
    delimiter: str = Field(",", title="Separador", description=r"Use \t para tabulação.")
    mode: Literal["columns", "rows"] = Field(
        "columns",
        title="Dividir em",
        json_schema_extra=ui(labels={"columns": "Novas colunas", "rows": "Novas linhas"}),
    )
    max_parts: int = Field(
        0,
        ge=0,
        title="Número de colunas",
        description="0 = quantas forem necessárias.",
        json_schema_extra=ui(show_if={"mode": ["columns"]}),
    )
    trim: bool = Field(True, title="Remover espaços das partes")
    keep_original: bool = Field(
        False, title="Manter a coluna original", json_schema_extra=ui(show_if={"mode": ["columns"]})
    )


@tool(
    type="prep.text_to_columns",
    name="Text To Columns",
    category="prep",
    icon="text-columns",
    description="Divide o texto de uma coluna por um separador, em novas colunas ou novas linhas.",
    config=TextToColumnsConfig,
    annotate=lambda c: f"{c.column} por '{c.delimiter}'" if c.column else "Escolha a coluna",
)
def text_to_columns(ctx: NodeContext, cfg: TextToColumnsConfig) -> NodeOutput:
    df = ctx.input()
    if not cfg.column:
        raise ValueError("Escolha a coluna a dividir.")
    if not cfg.delimiter:
        raise ValueError("Informe o separador.")
    _require(df, cfg.column)
    delimiter = cfg.delimiter.replace("\\t", "\t")
    parts = pl.col(cfg.column).cast(pl.String).str.split(delimiter)
    if cfg.trim:
        parts = parts.list.eval(pl.element().str.strip_chars())
    if cfg.mode == "rows":
        return NodeOutput(tables={"out": df.with_columns(parts.alias(cfg.column)).explode(cfg.column)})
    lengths = df.select(parts.list.len().max()).item() or 1
    n = cfg.max_parts or int(lengths)
    if n > MAX_NEW_COLUMNS:
        raise ValueError(f"A divisão geraria {n} colunas; o limite é {MAX_NEW_COLUMNS}.")
    names = [f"{cfg.column}_{i + 1}" for i in range(n)]
    new = [parts.list.get(i, null_on_oob=True).alias(name) for i, name in enumerate(names)]
    out = df.with_columns(new)
    # As novas colunas ficam no lugar da original (logo depois dela, se for mantida).
    position = df.columns.index(cfg.column)
    before = [c for c in df.columns[:position] if c not in names]
    after = [c for c in df.columns[position + 1 :] if c not in names]
    original = [cfg.column] if cfg.keep_original else []
    return NodeOutput(tables={"out": out.select([*before, *original, *names, *after])})


# ------------------------------------------------------------------ Record ID


class RecordIdConfig(ToolConfig):
    column: str = Field("record_id", title="Nome da coluna")
    start: int = Field(1, title="Começar em")
    position: Literal["first", "last"] = Field(
        "first",
        title="Posição",
        json_schema_extra=ui(labels={"first": "Primeira coluna", "last": "Última coluna"}),
    )


@tool(
    type="prep.record_id",
    name="Record ID",
    category="prep",
    icon="hash",
    description="Numera as linhas em sequência (1, 2, 3…), criando uma chave única.",
    config=RecordIdConfig,
    annotate=lambda c: f"{c.column} a partir de {c.start}",
)
def record_id(ctx: NodeContext, cfg: RecordIdConfig) -> NodeOutput:
    df = ctx.input()
    name = cfg.column.strip() or "record_id"
    if name in df.columns:
        raise ValueError(f"Já existe uma coluna chamada '{name}'.")
    out = df.with_row_index(name, offset=0).with_columns(
        (pl.col(name).cast(pl.Int64) + cfg.start).alias(name)
    )
    if cfg.position == "last":
        out = out.select([*df.columns, name])
    return NodeOutput(tables={"out": out})


# ------------------------------------------------------------------ Running Total


class RunningTotalConfig(ToolConfig):
    columns: list[str] = Field(
        default_factory=list, title="Colunas a acumular", json_schema_extra=ui(widget="columns")
    )
    group_by: list[str] = Field(
        default_factory=list,
        title="Recomeçar a cada grupo",
        description="Vazio = um acumulado só, na ordem das linhas.",
        json_schema_extra=ui(widget="columns"),
    )
    prefix: str = Field("acumulado_", title="Prefixo das novas colunas")


@tool(
    type="prep.running_total",
    name="Running Total",
    category="prep",
    icon="trending-up",
    description="Soma acumulada linha a linha, opcionalmente recomeçando a cada grupo.",
    config=RunningTotalConfig,
    annotate=lambda c: ", ".join(c.columns) or "Escolha as colunas",
)
def running_total(ctx: NodeContext, cfg: RunningTotalConfig) -> NodeOutput:
    df = ctx.input()
    if not cfg.columns:
        raise ValueError("Escolha ao menos uma coluna numérica para acumular.")
    _require(df, *cfg.columns, *cfg.group_by)
    if text := [c for c in cfg.columns if not df.schema[c].is_numeric()]:
        raise ValueError(f"Só colunas numéricas podem ser acumuladas: {', '.join(text)}")
    exprs = []
    for c in cfg.columns:
        expr = pl.col(c).cum_sum()
        exprs.append((expr.over(cfg.group_by) if cfg.group_by else expr).alias(f"{cfg.prefix}{c}"))
    return NodeOutput(tables={"out": df.with_columns(exprs)})


# ------------------------------------------------------------------ Append Fields


class AppendFieldsConfig(ToolConfig):
    prefix: str = Field("s_", title="Prefixo para colunas repetidas da fonte [S]")


@tool(
    type="transform.append_fields",
    name="Append Fields",
    category="transform",
    icon="append",
    description="Anexa as colunas de [S] a todas as linhas de [T] (combina tudo com tudo). Ideal para parâmetros.",
    config=AppendFieldsConfig,
    inputs=[Port("T", "T", "Destino"), Port("S", "S", "Fonte")],
    annotate=lambda c: "Todas as linhas × fonte",
)
def append_fields(ctx: NodeContext, cfg: AppendFieldsConfig) -> NodeOutput:
    target, source = ctx.input("T"), ctx.input("S")
    total = target.height * source.height
    if total > MAX_APPEND_ROWS:
        raise ValueError(
            f"O resultado teria {total:,} linhas ({target.height:,} × {source.height:,}); o limite é "
            f"{MAX_APPEND_ROWS:,}. A fonte [S] costuma ter poucas linhas.".replace(",", ".")
        )
    clashes = {c: f"{cfg.prefix}{c}" for c in source.columns if c in target.columns}
    return NodeOutput(tables={"out": target.join(source.rename(clashes), how="cross")})
