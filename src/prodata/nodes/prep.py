"""Ferramentas de preparação: Select, Filter, Formula, Cleansing, Unique, Sort, Sample."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.engine import formula
from prodata.engine.convert import convert
from prodata.engine.sql.fragment import (
    NUMERIC_KINDS,
    ROW_POSITION,
    Fragment,
    SqlContext,
    SqlInput,
    join_list,
    lit,
    numbered,
    q,
    sql_for,
    text_cast,
    text_of,
)
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
    out, warnings = apply_select(ctx.input(), cfg.fields, cfg.order)
    return NodeOutput(tables={"out": out}, extra={"warnings": warnings} if warnings else {})


def apply_select(
    df: pl.DataFrame, fields: list[SelectField], order: list[str]
) -> tuple[pl.DataFrame, list[str]]:
    """Manter, renomear, converter e ordenar colunas. Usado pelo Select e pelo Join (spec 019)."""
    if not fields and not order:
        return df, []
    by_name = {f.name: f for f in fields}
    rank = {name: i for i, name in enumerate(order)}
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
    return (pl.DataFrame(out) if out else df.clear().select([])), warnings


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


# ------------------------------------------------------------------ tradução para SQL (spec 020)


def cast_sql(expr: str, source: str, target: str) -> str:
    """Mesmas conversões de ``engine/convert.py``, em SQL."""
    if target == "String":
        return text_cast(expr, source)
    if source == "String":
        macro = {
            "Float64": "pd_para_decimal",
            "Int64": "pd_para_inteiro",
            "Boolean": "pd_para_booleano",
            "Date": "pd_para_data",
        }
        return f"{macro[target]}({expr})"
    if target == "Date":
        if source in NUMERIC_KINDS:
            return f"pd_data_excel({expr})"
        return f"CAST({expr} AS DATE)"
    if target == "Int64":
        return f"TRY_CAST(trunc({expr}) AS BIGINT)" if source == "Float" else f"TRY_CAST({expr} AS BIGINT)"
    return f"TRY_CAST({expr} AS {'DOUBLE' if target == 'Float64' else 'BOOLEAN'})"


def select_items(
    columns: list[tuple[str, str, str]], fields: list[SelectField], order: list[str]
) -> tuple[list[str], list[str]]:
    """Itens do SELECT para (nome de entrada, expressão, família do tipo). Devolve os itens e o que foi feito."""
    by_name = {f.name: f for f in fields}
    rank = {name: i for i, name in enumerate(order)}
    names = [c[0] for c in columns]
    items: list[str] = []
    dropped = renamed = casted = 0
    for name, expr, kind in sorted(columns, key=lambda c: (rank.get(c[0], len(rank)), names.index(c[0]))):
        rule = by_name.get(name)
        if rule is not None and not rule.keep:
            dropped += 1
            continue
        out = (rule.rename.strip() if rule else "") or name
        value = expr
        if rule is not None and rule.cast:
            value = cast_sql(expr, kind, rule.cast)
            casted += 1
        renamed += out != name
        # "l.id AS id" diz o mesmo que "l.id": o nome só aparece quando muda algo.
        same = value == q(out) or value.endswith(f".{q(out)}")
        items.append(value if same else f"{value} AS {q(out)}")
    what = [
        text
        for count, text in (
            (dropped, f"descarta {dropped} coluna(s)"),
            (renamed, f"renomeia {renamed}"),
            (casted, f"converte o tipo de {casted}"),
            (len(order) > 0, "muda a ordem"),
        )
        if count
    ]
    return items, what


def _select_from(items: list[str], source: str) -> str:
    if not items:
        raise ValueError("Todas as colunas foram descartadas: sobrou uma tabela sem colunas.")
    return f"SELECT\n  {join_list(items)}\nFROM {source}"


@sql_for("prep.select")
def select_sql(ctx: SqlContext, cfg: SelectConfig) -> dict[str, Fragment]:
    source = ctx.input()
    columns = [(c, q(c), source.kinds[c]) for c in source.columns]
    items, what = select_items(columns, cfg.fields, cfg.order)
    explain = ", ".join(what).capitalize() if what else "Mantém todas as colunas"
    return {"out": Fragment(_select_from(items, q(source.block)), explain)}


def _simple_condition(source: SqlInput, cfg: FilterConfig) -> str:
    if cfg.column not in source.columns:
        raise ValueError(
            f"Coluna '{cfg.column}' não existe na entrada." if cfg.column else "Escolha a coluna."
        )
    column = q(cfg.column)
    kind = source.kinds[cfg.column]
    if cfg.operator == "is_null":
        return f"{column} IS NULL"
    if cfg.operator == "is_not_null":
        return f"{column} IS NOT NULL"
    if cfg.operator == "contains":
        return f"contains(lower({text_cast(column, kind)}), {lit(cfg.value.lower())})"
    if cfg.operator == "starts_with":
        return f"starts_with(lower({text_cast(column, kind)}), {lit(cfg.value.lower())})"
    operator = {"==": "="}.get(cfg.operator, cfg.operator)
    if kind in NUMERIC_KINDS:
        try:
            return f"{column} {operator} {float(cfg.value.replace(',', '.'))!r}"
        except ValueError as exc:
            raise ValueError(f"'{cfg.value}' não é um número válido para a coluna '{cfg.column}'.") from exc
    if kind == "Boolean":
        return f"{column} {operator} {lit(cfg.value.strip().lower() in ('true', '1', 'sim', 'verdadeiro'))}"
    return (
        f"{text_cast(column, kind)} {operator} {lit(cfg.value)}"
        if kind != "String"
        else f"{column} {operator} {lit(cfg.value)}"
    )


@sql_for("prep.filter")
def filter_sql(ctx: SqlContext, cfg: FilterConfig) -> dict[str, Fragment]:
    source = ctx.input()
    if cfg.mode == "expression":
        if not cfg.expression.strip():
            raise ValueError("Escreva a expressão do filtro.")
        formula.check_columns(cfg.expression, source.columns)
        condition = formula.transpile(cfg.expression)
        readable = cfg.expression.strip()
    else:
        condition = _simple_condition(source, cfg)
        readable = _filter_annotation(cfg)
    block = q(source.block)
    return {
        "T": Fragment(
            f"SELECT *\nFROM {block}\nWHERE COALESCE(CAST(({condition}) AS BOOLEAN), FALSE)",
            f"Mantém as linhas em que {readable}",
        ),
        "F": Fragment(
            f"SELECT *\nFROM {block}\nWHERE NOT COALESCE(CAST(({condition}) AS BOOLEAN), FALSE)",
            f"Linhas que não atendem a {readable}",
        ),
    }


@sql_for("prep.formula")
def formula_sql(ctx: SqlContext, cfg: FormulaConfig) -> dict[str, Fragment]:
    """Fórmulas em sequência: uma nova camada só quando a fórmula usa coluna criada na camada atual."""
    source = ctx.input()
    columns = list(source.columns)
    layers: list[tuple[list[str], list[str]]] = [([], [])]  # (novas, substituídas)
    created: set[str] = set()
    names: list[str] = []
    for rule in cfg.formulas:
        replace = rule.target == "existing"
        column = (rule.existing if replace else rule.column).strip()
        expression = rule.expression.strip()
        if not column or not expression:
            continue
        if replace and column not in columns:
            raise ValueError(f"A coluna [{column}] não existe para ser alterada.")
        formula.check_columns(expression, columns)
        sql = formula.transpile(expression)
        cast = formula.CASTS.get(rule.type)
        item = f"{cast.format(sql) if cast else sql} AS {q(column)}"
        if created & set(formula.referenced_columns(expression)) or column in created:
            layers.append(([], []))
            created = set()
        if column in columns:
            layers[-1][1].append(item)
        else:
            layers[-1][0].append(item)
            columns.append(column)
        created.add(column)
        names.append(column)
    origin = q(source.block)
    query = f"SELECT * FROM {origin}"
    for new, replaced in layers:
        if not new and not replaced:
            continue
        star = "*" + (f" REPLACE (\n    {join_list(replaced, 4)}\n  )" if replaced else "")
        query = f"SELECT\n  {join_list([star, *new])}\nFROM {origin}"
        origin = f"(\n{query}\n)"
    return {"out": Fragment(query, "Calcula " + ", ".join(dict.fromkeys(names)) if names else "Sem fórmulas")}


def _cleanse_expr(name: str, kind: str, cfg: CleanseConfig) -> str | None:
    expr = q(name)
    if kind == "String":
        if cfg.trim_whitespace:
            expr = text_of(expr)
        if cfg.collapse_whitespace:
            expr = f"regexp_replace({expr}, '\\s+', ' ', 'g')"
        if cfg.case_mode != "none":
            expr = f"{ {'upper': 'upper', 'lower': 'lower', 'title': 'pd_titulo'}[cfg.case_mode] }({expr})"
        if cfg.empty_as_null:
            expr = f"NULLIF({expr}, '')"
        if cfg.replace_null_string:
            expr = f"COALESCE({expr}, {lit(cfg.string_default)})"
        return expr
    if kind in NUMERIC_KINDS and cfg.replace_null_numeric:
        return f"COALESCE({expr}, {lit(int(cfg.numeric_default) if kind == 'Int' else cfg.numeric_default)})"
    return None


@sql_for("prep.cleanse")
def cleanse_sql(ctx: SqlContext, cfg: CleanseConfig) -> dict[str, Fragment]:
    source = ctx.input()
    targets = [c for c in (cfg.columns or source.columns) if c in source.columns]
    items = [
        f"{expr} AS {q(c)}" for c in targets if (expr := _cleanse_expr(c, source.kinds[c], cfg)) is not None
    ]
    notes = (
        ['"Primeira Maiúscula" pode diferir do motor em palavras separadas por hífen ou pontuação.']
        if cfg.case_mode == "title"
        else []
    )
    what = []
    if cfg.replace_null_string:
        what.append(f'preenche texto vazio com "{cfg.string_default}"')
    if cfg.trim_whitespace:
        what.append("tira espaços das pontas")
    if cfg.replace_null_numeric:
        what.append(f"preenche números vazios com {cfg.numeric_default:g}")
    explain = (
        ("Limpa " + ", ".join(targets[:3]) + (": " + ", ".join(what) if what else ""))
        if targets
        else "Sem colunas para limpar"
    )
    if not items:
        return {"out": Fragment(f"SELECT * FROM {q(source.block)}", explain, notes)}
    return {
        "out": Fragment(
            f"SELECT * REPLACE (\n  {join_list(items)}\n)\nFROM {q(source.block)}", explain, notes
        )
    }


ORDER_NOTE = "Depende da ordem das linhas, que o SQL só garante com um ORDER BY: confirme a ordem desejada."


@sql_for("prep.unique")
def unique_sql(ctx: SqlContext, cfg: UniqueConfig) -> dict[str, Fragment]:
    source = ctx.input()
    if missing := [k for k in cfg.keys if k not in source.columns]:
        raise ValueError(f"Coluna(s)-chave inexistente(s): {', '.join(missing)}")
    keys = ", ".join(q(k) for k in (cfg.keys or source.columns))
    rank = f"row_number() OVER (PARTITION BY {keys} ORDER BY {ROW_POSITION})"
    base = numbered(source.block)
    label = ", ".join(cfg.keys) or "a linha inteira"
    return {
        "U": Fragment(
            f"SELECT * EXCLUDE ({ROW_POSITION})\nFROM {base}\nQUALIFY {rank} = 1",
            f"Fica com a primeira linha de cada {label}",
            [ORDER_NOTE],
        ),
        "D": Fragment(
            f"SELECT * EXCLUDE ({ROW_POSITION})\nFROM {base}\nQUALIFY {rank} > 1",
            f"Linhas repetidas de {label}",
            [ORDER_NOTE],
        ),
    }


@sql_for("prep.sort")
def sort_sql(ctx: SqlContext, cfg: SortConfig) -> dict[str, Fragment]:
    source = ctx.input()
    items = [s for s in cfg.sorts if s.column]
    if missing := [s.column for s in items if s.column not in source.columns]:
        raise ValueError(f"Coluna(s) inexistente(s): {', '.join(missing)}")
    if not items:
        return {"out": Fragment(f"SELECT * FROM {q(source.block)}", "Sem ordenação")}
    order = ", ".join(f"{q(s.column)} {'DESC' if s.descending else 'ASC'} NULLS LAST" for s in items)
    return {
        "out": Fragment(
            f"SELECT *\nFROM {q(source.block)}\nORDER BY {order}",
            "Ordena por " + ", ".join(s.column for s in items),
            ["A ordem vale para esta etapa: num banco, etapas seguintes podem não mantê-la."],
            ordered_by=[s.column for s in items],
        )
    }


@sql_for("prep.sample")
def sample_sql(ctx: SqlContext, cfg: SampleConfig) -> dict[str, Fragment]:
    source = ctx.input()
    block = q(source.block)
    if cfg.mode == "first":
        return {
            "out": Fragment(
                f"SELECT *\nFROM {block}\nLIMIT {cfg.n}", f"Primeiras {cfg.n} linhas", [ORDER_NOTE]
            )
        }
    if cfg.mode == "last":
        return {
            "out": Fragment(
                f"SELECT * EXCLUDE ({ROW_POSITION})\nFROM {numbered(source.block)}\nQUALIFY {ROW_POSITION} > count(*) OVER () - {cfg.n}",
                f"Últimas {cfg.n} linhas",
                [ORDER_NOTE],
            )
        }
    note = "Amostra aleatória: as linhas sorteadas no SQL não são as mesmas do fluxo, então esta etapa não é comparada."
    if cfg.mode == "random":
        return {
            "out": Fragment(
                f"SELECT *\nFROM {block}\nUSING SAMPLE {cfg.n} ROWS (reservoir, {cfg.seed})",
                f"{cfg.n} linhas sorteadas",
                [note],
                comparable=False,
            )
        }
    return {
        "out": Fragment(
            f"SELECT *\nFROM {block}\nUSING SAMPLE {cfg.percent:g} PERCENT (bernoulli, {cfg.seed})",
            f"{cfg.percent:g}% das linhas, por sorteio",
            [note],
            comparable=False,
        )
    }
