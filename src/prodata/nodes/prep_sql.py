"""Tradução para SQL das caixas de preparação (spec 020)."""

from __future__ import annotations

from typing import Any

from prodata.engine import formula, multirow
from prodata.engine.sql.fragment import (
    NUMERIC_KINDS,
    ROW_POSITION,
    Fragment,
    NoTranslationError,
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
from prodata.nodes.prep import (
    CleanseConfig,
    FilterConfig,
    FormulaConfig,
    MultiRowConfig,
    SampleConfig,
    SelectConfig,
    SelectField,
    SortConfig,
    UniqueConfig,
    _filter_annotation,
)


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


MAX_RECURSIVE_CHECK = 5000


def _multirow_refs(cfg: MultiRowConfig, source: Any, target: str) -> tuple[str, list[Any], list[Any]]:
    """Confere a caixa e separa as referências: outras colunas viram janelas; a própria, consulta recursiva."""
    if not target or not cfg.expression.strip():
        raise ValueError("Preencha a coluna e a expressão.")
    if cfg.target == "existing" and target not in source.columns:
        raise ValueError(f"A coluna [{target}] não existe para ser alterada.")
    if missing := [c for c in cfg.group_by if c not in source.columns]:
        raise ValueError(f"Coluna(s) de agrupamento inexistente(s): {', '.join(missing)}")
    if absent := [i.column for i in cfg.order_by if i.column and i.column not in source.columns]:
        raise ValueError(f"Coluna(s) de ordenação inexistente(s): {', '.join(absent)}")
    expression, refs = multirow.parse(cfg.expression)
    multirow.check_refs(refs, source.columns, target)
    chained = [r for r in refs if r.column == target]
    if len(chained) > 1 or (chained and chained[0].offset != -1):
        raise NoTranslationError(
            "Em SQL, a própria coluna só pode olhar para a linha imediatamente anterior ([Row-1:…])."
        )
    return expression, refs, chained


def _empty_start(cfg: MultiRowConfig, kind: str | None) -> str:
    """O valor da "linha anterior" na primeira linha de cada grupo."""
    if cfg.missing != "empty":
        return "NULL"
    if cfg.type in ("Float64", "Int64") or (cfg.type != "String" and kind in NUMERIC_KINDS):
        return "0"
    return "''" if cfg.type == "String" or kind == "String" else "NULL"


@sql_for("prep.multirow")
@sql_for("prep.multirow")
def multirow_sql(ctx: SqlContext, cfg: MultiRowConfig) -> dict[str, Fragment]:
    """Outras colunas viram janelas; a própria coluna, uma consulta recursiva (RF-2196)."""
    source = ctx.input()
    target = (cfg.existing if cfg.target == "existing" else cfg.column).strip()
    expression, refs, chained = _multirow_refs(cfg, source, target)
    fixed = [r for r in refs if r.column != target]
    partition = "PARTITION BY " + ", ".join(q(c) for c in cfg.group_by) + " " if cfg.group_by else ""
    order = [i for i in cfg.order_by if i.column]
    # Empates seguem a ordem de chegada, como no motor.
    sequence = ", ".join(
        [*(f"{q(i.column)} {'DESC' if i.descending else 'ASC'} NULLS LAST" for i in order), ROW_POSITION]
    )

    def neighbor(ref: multirow.RowRef) -> str:
        function = "lag" if ref.offset < 0 else "lead"
        kind = source.kinds[ref.column]
        default = ""
        if cfg.missing == "empty" and kind in (*NUMERIC_KINDS, "String"):
            default = ", 0" if kind in NUMERIC_KINDS else ", ''"
        return f"{function}({q(ref.column)}, {abs(ref.offset)}{default}) OVER ({partition}ORDER BY {sequence}) AS {ref.name}"

    formula.check_columns(expression, [*source.columns, *[r.name for r in refs]])
    sql = formula.transpile(expression)
    cast = formula.CASTS.get(cfg.type)
    value = cast.format(sql) if cast else sql
    helpers = [ROW_POSITION, *[r.name for r in refs]]
    existing = target in source.columns
    extras = [neighbor(r) for r in fixed]
    origin = f"SELECT *{''.join(', ' + e for e in extras)} FROM {numbered(source.block)}"
    notes = [ORDER_NOTE]
    explain = f"Calcula {target} olhando outras linhas"
    if not chained:
        exclude = ", ".join(helpers)
        if existing:
            head = f"SELECT * EXCLUDE ({exclude}) REPLACE ({value} AS {q(target)})"
        else:
            head = f"SELECT * EXCLUDE ({exclude}), {value} AS {q(target)}"
        tail = f"\nORDER BY {sequence}" if order else ""
        return {"out": Fragment(f"{head}\nFROM (\n{origin}\n){tail}", explain, notes)}

    # Própria coluna: a linha seguinte depende do valor já calculado na anterior.
    ref = chained[0]
    position = f"row_number() OVER ({partition}ORDER BY {sequence}) AS __pd_pos"
    same_group = "".join(f" AND b.{q(c)} IS NOT DISTINCT FROM c.{q(c)}" for c in cfg.group_by)
    start = _empty_start(cfg, source.kinds.get(target))
    sql_recursive = (
        "WITH RECURSIVE\n"
        f"pd_base AS (\nSELECT *, {position} FROM ({origin})\n),\n"
        "pd_calc AS (\n"
        f"SELECT *, {value} AS __pd_novo FROM (SELECT b.*, {start} AS {ref.name} FROM pd_base AS b WHERE b.__pd_pos = 1)\n"
        "UNION ALL\n"
        f"SELECT *, {value} AS __pd_novo FROM (\n"
        f"SELECT b.*, c.__pd_novo AS {ref.name} FROM pd_base AS b\n"
        f"JOIN pd_calc AS c ON b.__pd_pos = c.__pd_pos + 1{same_group}\n)\n"
        ")\n"
    )
    exclude = ", ".join([*helpers, "__pd_pos", "__pd_novo"])
    if existing:
        final = f"SELECT * EXCLUDE ({exclude}) REPLACE (__pd_novo AS {q(target)})\nFROM pd_calc\nORDER BY {sequence}"
    else:
        final = f"SELECT * EXCLUDE ({exclude}), __pd_novo AS {q(target)}\nFROM pd_calc\nORDER BY {sequence}"
    sample = ctx.sample("in")
    comparable = sample is None or sample.height <= MAX_RECURSIVE_CHECK
    if not comparable:
        notes = [
            *notes,
            f"Consulta recursiva: acima de {MAX_RECURSIVE_CHECK} linhas, esta etapa não é comparada na conferência.",
        ]
    return {"out": Fragment(sql_recursive + final, explain, notes, comparable=comparable)}
