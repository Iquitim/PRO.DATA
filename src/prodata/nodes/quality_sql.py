"""Tradução para SQL do Data Quality (spec 028, RF-2836).

Cada regra vira uma coluna de falha; P fica com as linhas sem falha, F com as demais e os motivos. CPF, CNPJ e
datas em texto dependem de contas que o SQL de cada banco faz de um jeito: essas regras dizem que não têm
tradução, em vez de gerar um código que daria outro resultado.
"""

from __future__ import annotations

from prodata.engine import formula
from prodata.engine.sql.fragment import (
    NUMERIC_KINDS,
    ROW_POSITION,
    Fragment,
    NoTranslationError,
    SqlContext,
    SqlInput,
    lit,
    numbered,
    q,
    sql_for,
)
from prodata.nodes.quality import EMAIL, RULE_NAMES, QualityConfig, QualityRule, _number

NO_SQL = {"cpf": "CPF válido", "cnpj": "CNPJ válido", "date": "Data válida"}


def _text(column: str) -> str:
    return f"CAST({q(column)} AS VARCHAR)"


def _filled(column: str) -> str:
    return f"({q(column)} IS NOT NULL AND trim({_text(column)}) <> '')"


def _failure(rule: QualityRule, source: SqlInput, lists: SqlInput | None = None) -> tuple[str, str]:
    """Condição SQL de falha e o motivo, iguais aos do motor."""
    col = rule.column
    if rule.kind in NO_SQL:
        raise NoTranslationError(f'A regra "{NO_SQL[rule.kind]}" ainda não tem tradução para SQL.')
    if rule.kind == "formula":
        formula.check_columns(rule.expression, source.columns)
        reason = rule.message.strip() or f"Não atende a: {rule.expression.strip()}"
        return f"NOT COALESCE(CAST(({formula.transpile(rule.expression)}) AS BOOLEAN), FALSE)", reason
    if col not in source.columns:
        raise ValueError(f"A coluna [{col}] da regra {RULE_NAMES[rule.kind]} não existe na entrada.")
    if rule.kind == "not_empty":
        return f"NOT {_filled(col)}", f"Vazio em [{col}]"
    if rule.kind == "unique":
        keys = [col, *[c for c in rule.also if c and c != col]]
        names = "], [".join(keys)
        return f"count(*) OVER (PARTITION BY {', '.join(q(k) for k in keys)}) > 1", f"Repetido em [{names}]"
    if rule.kind == "email":
        return (
            f"({_filled(col)} AND NOT regexp_matches(trim({_text(col)}), {lit(EMAIL)}))",
            f"E-mail inválido em [{col}]",
        )
    if rule.kind == "number_range":
        if source.kinds.get(col) not in NUMERIC_KINDS:
            raise ValueError(f"A regra Número na faixa vale para colunas de número: [{col}] não é.")
        parts = [
            f"{q(col)} < {rule.min!r}" if rule.min is not None else "",
            f"{q(col)} > {rule.max!r}" if rule.max is not None else "",
        ]
        lo = _number(rule.min) if rule.min is not None else "…"
        hi = _number(rule.max) if rule.max is not None else "…"
        test = " OR ".join(p for p in parts if p) or "FALSE"
        return f"COALESCE({test}, FALSE)", f"Fora da faixa de {lo} a {hi} em [{col}]"
    return _allowed(rule, lists)


def _allowed(rule: QualityRule, lists: SqlInput | None) -> tuple[str, str]:
    """Valor permitido: a lista digitada vira IN (...); a da entrada L, uma subconsulta sem os vazios (RF-2840)."""
    col = rule.column
    norm = (lambda sql: f"lower({sql})") if rule.ignore_case else (lambda sql: sql)
    value = norm(f"trim({_text(col)})")
    reason = f"Valor fora da lista em [{col}]"
    if rule.values_from == "table":
        if lists is None:
            raise ValueError(f"Conecte na entrada [L] a tabela com os valores permitidos de [{col}].")
        other = rule.list_column
        if not other:
            raise ValueError(f"Escolha a coluna de [L] com os valores permitidos de [{col}].")
        if other not in lists.columns:
            raise ValueError(f"A coluna [{other}] não existe na entrada [L].")
        sub = f"SELECT {norm(f'trim({_text(other)})')} FROM {q(lists.block)} WHERE {_filled(other)}"
        return f"({_filled(col)} AND {value} NOT IN ({sub}))", reason
    allowed = [v.strip() for v in rule.values if v.strip()]
    if not allowed:
        raise ValueError(f"Informe os valores permitidos da regra em [{col}].")
    if rule.ignore_case:
        allowed = [v.lower() for v in allowed]
    return f"({_filled(col)} AND {value} NOT IN ({', '.join(lit(v) for v in allowed)}))", reason


def _free(columns: list[str], name: str) -> str:
    while name in columns:
        name = f"{name}_dq"
    return name


@sql_for("prep.data_quality")
def data_quality_sql(ctx: SqlContext, cfg: QualityConfig) -> dict[str, Fragment]:
    if not cfg.rules:
        raise ValueError("Escolha ao menos uma regra.")
    source = ctx.input()
    lists = ctx.inputs.get("L")
    failures = [_failure(rule, source, lists) for rule in cfg.rules]
    flags = [f"__pd_falha{i}" for i in range(len(failures))]
    checked = ",\n  ".join(
        f"COALESCE({cond}, FALSE) AS {flag}" for (cond, _), flag in zip(failures, flags, strict=True)
    )
    base = f"WITH pd_regras AS (\nSELECT *,\n  {checked}\nFROM {numbered(source.block)}\n)\n"
    hidden = ", ".join([*flags, ROW_POSITION])
    failed_any = " OR ".join(flags)
    rule_col = _free(source.columns, "regra")
    reason_col = _free(source.columns, "motivo")
    names = ", ".join(
        f"CASE WHEN {flag} THEN {lit(RULE_NAMES[r.kind])} END"
        for flag, r in zip(flags, cfg.rules, strict=True)
    )
    reasons = ", ".join(
        f"CASE WHEN {flag} THEN {lit(reason)} END" for flag, (_, reason) in zip(flags, failures, strict=True)
    )
    explain = f"Confere {len(cfg.rules)} regra(s)"
    return {
        "P": Fragment(
            f"{base}SELECT * EXCLUDE ({hidden})\nFROM pd_regras\nWHERE NOT ({failed_any})\nORDER BY {ROW_POSITION}",
            f"{explain}: linhas que passaram em todas",
        ),
        "F": Fragment(
            f"{base}SELECT * EXCLUDE ({hidden}),\n  concat_ws(' · ', {names}) AS {q(rule_col)},\n"
            f"  concat_ws(' · ', {reasons}) AS {q(reason_col)}\nFROM pd_regras\nWHERE {failed_any}\nORDER BY {ROW_POSITION}",
            f"{explain}: linhas que falharam, com o motivo",
        ),
    }
