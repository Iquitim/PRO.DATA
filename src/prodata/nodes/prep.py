"""Ferramentas de preparação: Select, Filter, Formula, Cleansing, Unique, Sort, Sample."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.engine import formula
from prodata.engine.convert import convert
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

CastType = Literal["", "Int64", "Float64", "String", "Boolean", "Date"]
_POLARS_TYPES: dict[str, type[pl.DataType]] = {
    "Int64": pl.Int64,
    "Float64": pl.Float64,
    "String": pl.String,
    "Boolean": pl.Boolean,
    "Date": pl.Date,
}
_TYPE_LABELS = {
    "": "Manter",
    "Int64": "Inteiro",
    "Float64": "Decimal",
    "String": "Texto",
    "Boolean": "Booleano",
    "Date": "Data",
}

# ------------------------------------------------------------------ Select


class SelectField(BaseModel):
    name: str = ""
    keep: bool = True
    rename: str = ""
    cast: CastType = ""


class SelectConfig(ToolConfig):
    fields: list[SelectField] = Field(
        default_factory=list,
        title="Colunas",
        description="Colunas não listadas são mantidas como estão.",
        json_schema_extra=ui(widget="select_columns"),
    )
    # Ordem das colunas na saída (spec 018), editada arrastando as linhas da tabela acima.
    # Vazio = ordem de entrada; colunas que não estão na lista vão para o fim, na ordem de entrada.
    order: list[str] = Field(default_factory=list, title="Ordem", json_schema_extra=ui(widget="hidden"))


@tool(
    type="prep.select",
    name="Select",
    category="prep",
    icon="columns",
    description="Escolhe, renomeia e converte o tipo das colunas.",
    config=SelectConfig,
    annotate=lambda c: f"{sum(not f.keep for f in c.fields)} removida(s)" if c.fields else "Todas as colunas",
)
def select(ctx: NodeContext, cfg: SelectConfig) -> NodeOutput:
    df = ctx.input()
    by_name = {f.name: f for f in cfg.fields}
    rank = {name: i for i, name in enumerate(cfg.order)}
    columns = sorted(df.columns, key=lambda c: (rank.get(c, len(rank)), df.columns.index(c)))
    out: list[pl.Series] = []
    warnings: list[str] = []
    for col in columns:
        rule = by_name.get(col)
        if rule is not None and not rule.keep:
            continue
        series = df[col]
        if rule is not None and rule.cast:
            # Conversão tolerante (spec 018): entende padrão brasileiro, datas em texto e do Excel,
            # e avisa o que não converteu em vez de perder em silêncio.
            result = convert(series, _POLARS_TYPES[rule.cast])
            series = result.series
            if result.failed:
                warnings.append(
                    f"[{col}] → {_TYPE_LABELS[rule.cast]}: {result.failed} valor(es) não converteram e ficaram vazios "
                    f"(ex.: {', '.join(repr(v) for v in result.examples)})."
                )
        out.append(series.alias((rule.rename.strip() if rule else "") or col))
    return NodeOutput(
        tables={"out": pl.DataFrame(out) if out else df.clear().select([])},
        extra={"warnings": warnings} if warnings else {},
    )


# ------------------------------------------------------------------ Filter

Operator = Literal["==", "!=", ">", ">=", "<", "<=", "contains", "starts_with", "is_null", "is_not_null"]


class FilterConfig(ToolConfig):
    mode: Literal["simple", "expression"] = Field(
        "simple", title="Modo", json_schema_extra=ui(labels={"simple": "Básico", "expression": "Expressão"})
    )
    column: str = Field(
        "", title="Coluna", json_schema_extra=ui(widget="column", show_if={"mode": ["simple"]})
    )
    operator: Operator = Field(
        "==",
        title="Operador",
        json_schema_extra=ui(
            show_if={"mode": ["simple"]},
            labels={
                "==": "igual a",
                "!=": "diferente de",
                ">": "maior que",
                ">=": "maior ou igual a",
                "<": "menor que",
                "<=": "menor ou igual a",
                "contains": "contém",
                "starts_with": "começa com",
                "is_null": "é nulo",
                "is_not_null": "não é nulo",
            },
        ),
    )
    value: str = Field(
        "",
        title="Valor",
        json_schema_extra=ui(
            show_if={
                "mode": ["simple"],
                "operator": ["==", "!=", ">", ">=", "<", "<=", "contains", "starts_with"],
            }
        ),
    )
    expression: str = Field(
        "",
        title="Expressão",
        description="Linhas que satisfazem a expressão saem em [T]; as demais em [F].",
        json_schema_extra=ui(
            widget="expression",
            show_if={"mode": ["expression"]},
            placeholder="[status] == 'ATIVO' AND [mrr_mensal] >= 1000",
        ),
    )


def _simple_mask(df: pl.DataFrame, cfg: FilterConfig) -> pl.Series:
    if cfg.column not in df.columns:
        raise ValueError(
            f"Coluna '{cfg.column}' não existe na entrada." if cfg.column else "Escolha a coluna."
        )
    s = df[cfg.column]
    if cfg.operator == "is_null":
        return s.is_null()
    if cfg.operator == "is_not_null":
        return s.is_not_null()
    if cfg.operator in ("contains", "starts_with"):
        text = s.cast(pl.String).str.to_lowercase()
        needle = cfg.value.lower()
        mask = (
            text.str.contains(needle, literal=True)
            if cfg.operator == "contains"
            else text.str.starts_with(needle)
        )
        return mask.fill_null(False)

    value: object = cfg.value
    if s.dtype.is_numeric():
        try:
            value = float(cfg.value.replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"'{cfg.value}' não é um número válido para a coluna '{cfg.column}'.") from exc
    elif s.dtype == pl.Boolean:
        value = cfg.value.strip().lower() in ("true", "1", "sim", "verdadeiro")
    else:
        s = s.cast(pl.String)
    ops = {
        "==": s.__eq__,
        "!=": s.__ne__,
        ">": s.__gt__,
        ">=": s.__ge__,
        "<": s.__lt__,
        "<=": s.__le__,
    }
    return ops[cfg.operator](value).fill_null(False)


def _filter_annotation(c: FilterConfig) -> str:
    if c.mode == "expression":
        return c.expression
    if c.operator in ("is_null", "is_not_null"):
        return f"[{c.column}] {c.operator.replace('_', ' ')}"
    return f"[{c.column}] {c.operator} {c.value}"


@tool(
    type="prep.filter",
    name="Filter",
    category="prep",
    icon="filter",
    description="Divide os registros: os que atendem à condição saem em [T], os demais em [F].",
    config=FilterConfig,
    outputs=[Port("T", "T", "Verdadeiro"), Port("F", "F", "Falso")],
    annotate=_filter_annotation,
)
def filter_rows(ctx: NodeContext, cfg: FilterConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.mode == "expression":
        if not cfg.expression.strip():
            raise ValueError("Escreva a expressão do filtro.")
        mask = formula.evaluate_mask(df, cfg.expression)
    else:
        mask = _simple_mask(df, cfg)
    return NodeOutput(tables={"T": df.filter(mask), "F": df.filter(~mask)})


# ------------------------------------------------------------------ Formula


class FormulaItem(BaseModel):
    target: Literal["new", "existing"] = Field(
        "new",
        title="Resultado em",
        json_schema_extra=ui(
            labels={"new": "Uma coluna nova", "existing": "Uma coluna existente (troca os valores)"}
        ),
    )
    column: str = Field(
        "nova_coluna", title="Nome da coluna nova", json_schema_extra=ui(show_if={"target": ["new"]})
    )
    existing: str = Field(
        "", title="Coluna a alterar", json_schema_extra=ui(widget="column", show_if={"target": ["existing"]})
    )
    type: Literal["Auto", "Float64", "Int64", "String", "Boolean", "Date"] = Field(
        "Auto",
        title="Tipo",
        json_schema_extra=ui(labels={"Auto": "Automático", **{k: v for k, v in _TYPE_LABELS.items() if k}}),
    )
    expression: str = Field("", title="Expressão", json_schema_extra=ui(widget="expression"))


class FormulaConfig(ToolConfig):
    formulas: list[FormulaItem] = Field(
        default_factory=lambda: [FormulaItem()],
        title="Fórmulas",
        description="Aplicadas em ordem; uma fórmula pode usar colunas criadas pelas anteriores.",
    )


@tool(
    type="prep.formula",
    name="Formula",
    category="prep",
    icon="function",
    description="Cria ou atualiza colunas com expressões (IF/THEN/ELSE, IIF, funções de texto e matemática).",
    config=FormulaConfig,
    annotate=lambda c: ", ".join(f.existing if f.target == "existing" else f.column for f in c.formulas),
)
def formula_columns(ctx: NodeContext, cfg: FormulaConfig) -> NodeOutput:
    rules = [f.model_dump() for f in cfg.formulas]
    return NodeOutput(tables={"out": formula.evaluate_columns(ctx.input(), rules)})


# ------------------------------------------------------------------ Data Cleansing


class CleanseConfig(ToolConfig):
    columns: list[str] = Field(
        default_factory=list,
        title="Colunas",
        description="Vazio = todas as colunas.",
        json_schema_extra=ui(widget="columns"),
    )
    trim_whitespace: bool = Field(True, title="Remover espaços nas pontas")
    collapse_whitespace: bool = Field(False, title="Reduzir espaços repetidos")
    empty_as_null: bool = Field(True, title="Texto vazio vira nulo")
    case_mode: Literal["none", "upper", "lower", "title"] = Field(
        "none",
        title="Maiúsculas/minúsculas",
        json_schema_extra=ui(
            labels={
                "none": "Manter",
                "upper": "MAIÚSCULAS",
                "lower": "minúsculas",
                "title": "Primeira Maiúscula",
            }
        ),
    )
    replace_null_string: bool = Field(False, title="Substituir nulos em texto")
    string_default: str = Field(
        "Não informado", title="Texto padrão", json_schema_extra=ui(show_if={"replace_null_string": [True]})
    )
    replace_null_numeric: bool = Field(False, title="Substituir nulos numéricos")
    numeric_default: float = Field(
        0, title="Número padrão", json_schema_extra=ui(show_if={"replace_null_numeric": [True]})
    )


@tool(
    type="prep.cleanse",
    name="Data Cleansing",
    category="prep",
    icon="sparkles",
    description="Limpeza comum em um passo: espaços, texto vazio, caixa e substituição de nulos.",
    config=CleanseConfig,
    annotate=lambda c: ", ".join(c.columns) if c.columns else "Todas as colunas",
)
def cleanse(ctx: NodeContext, cfg: CleanseConfig) -> NodeOutput:
    df = ctx.input()
    targets = [c for c in (cfg.columns or df.columns) if c in df.columns]
    exprs: list[pl.Expr] = []
    for name in targets:
        dtype = df.schema[name]
        expr = pl.col(name)
        if dtype == pl.String:
            if cfg.trim_whitespace:
                expr = expr.str.strip_chars()
            if cfg.collapse_whitespace:
                expr = expr.str.replace_all(r"\s+", " ")
            if cfg.case_mode == "upper":
                expr = expr.str.to_uppercase()
            elif cfg.case_mode == "lower":
                expr = expr.str.to_lowercase()
            elif cfg.case_mode == "title":
                expr = expr.str.to_titlecase()
            if cfg.empty_as_null:
                expr = pl.when(expr == "").then(None).otherwise(expr)
            if cfg.replace_null_string:
                expr = expr.fill_null(cfg.string_default)
        elif dtype.is_numeric() and cfg.replace_null_numeric:
            fill = int(cfg.numeric_default) if dtype.is_integer() else cfg.numeric_default
            expr = expr.fill_null(fill)
        else:
            continue
        exprs.append(expr.alias(name))
    return NodeOutput(tables={"out": df.with_columns(exprs) if exprs else df})


# ------------------------------------------------------------------ Unique


class UniqueConfig(ToolConfig):
    keys: list[str] = Field(
        default_factory=list,
        title="Colunas-chave",
        description="Vazio = a linha inteira.",
        json_schema_extra=ui(widget="columns"),
    )


@tool(
    type="prep.unique",
    name="Unique",
    category="prep",
    icon="fingerprint",
    description="Primeira ocorrência de cada chave sai em [U]; as repetições saem em [D].",
    config=UniqueConfig,
    outputs=[Port("U", "U", "Únicos"), Port("D", "D", "Duplicados")],
    annotate=lambda c: "Chave: " + (", ".join(c.keys) or "linha inteira"),
)
def unique(ctx: NodeContext, cfg: UniqueConfig) -> NodeOutput:
    df = ctx.input()
    missing = [k for k in cfg.keys if k not in df.columns]
    if missing:
        raise ValueError(f"Coluna(s)-chave inexistente(s): {', '.join(missing)}")
    keys = cfg.keys or df.columns
    first = df.select(pl.struct(keys).is_first_distinct()).to_series()
    return NodeOutput(tables={"U": df.filter(first), "D": df.filter(~first)})


# ------------------------------------------------------------------ Sort


class SortItem(BaseModel):
    column: str = Field("", title="Coluna", json_schema_extra=ui(widget="column"))
    descending: bool = Field(False, title="Decrescente")


class SortConfig(ToolConfig):
    sorts: list[SortItem] = Field(default_factory=lambda: [SortItem()], title="Ordenar por")


@tool(
    type="prep.sort",
    name="Sort",
    category="prep",
    icon="sort",
    description="Ordena por uma ou mais colunas, crescente ou decrescente.",
    config=SortConfig,
    annotate=lambda c: ", ".join(f"{s.column} {'↓' if s.descending else '↑'}" for s in c.sorts if s.column),
)
def sort(ctx: NodeContext, cfg: SortConfig) -> NodeOutput:
    df = ctx.input()
    items = [s for s in cfg.sorts if s.column]
    missing = [s.column for s in items if s.column not in df.columns]
    if missing:
        raise ValueError(f"Coluna(s) inexistente(s): {', '.join(missing)}")
    if not items:
        return NodeOutput(tables={"out": df})
    out = df.sort([s.column for s in items], descending=[s.descending for s in items], nulls_last=True)
    return NodeOutput(tables={"out": out})


# ------------------------------------------------------------------ Sample


class SampleConfig(ToolConfig):
    mode: Literal["first", "last", "random", "percent"] = Field(
        "first",
        title="Modo",
        json_schema_extra=ui(
            labels={
                "first": "Primeiras N linhas",
                "last": "Últimas N linhas",
                "random": "N linhas aleatórias",
                "percent": "Percentual aleatório",
            }
        ),
    )
    n: int = Field(100, ge=0, title="N", json_schema_extra=ui(show_if={"mode": ["first", "last", "random"]}))
    percent: float = Field(
        10, gt=0, le=100, title="Percentual", json_schema_extra=ui(show_if={"mode": ["percent"]})
    )
    seed: int = Field(42, title="Semente", json_schema_extra=ui(show_if={"mode": ["random", "percent"]}))


@tool(
    type="prep.sample",
    name="Sample",
    category="prep",
    icon="dice",
    description="Amostra de linhas: primeiras, últimas, aleatórias ou um percentual.",
    config=SampleConfig,
    annotate=lambda c: f"{c.percent:g}%" if c.mode == "percent" else f"{c.mode} {c.n}",
)
def sample(ctx: NodeContext, cfg: SampleConfig) -> NodeOutput:
    df = ctx.input()
    match cfg.mode:
        case "last":
            out = df.tail(cfg.n)
        case "random":
            out = df.sample(n=min(cfg.n, df.height), seed=cfg.seed)
        case "percent":
            out = df.sample(fraction=cfg.percent / 100, seed=cfg.seed)
        case _:
            out = df.head(cfg.n)
    return NodeOutput(tables={"out": out})
