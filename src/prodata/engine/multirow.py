"""Fórmula que olha outras linhas (spec 021): ``[Row-1:valor]`` e ``[Row+1:valor]``.

Uma referência à linha anterior da própria coluna usa o valor já calculado, o que permite preencher para baixo.
Nesse caso o cálculo é por rodadas: cada rodada só refaz as linhas cuja linha anterior mudou.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import polars as pl

from prodata.engine import formula

MAX_OFFSET = 100
MAX_PASSES = 5000
MAX_RECALCULATED = 50_000_000  # linhas refeitas, somando todas as rodadas
_REF = re.compile(r"\[Row([+-])(\d+):([^\]]+)\]", re.IGNORECASE)
_ROW_INDEX = "__pd_linha"


@dataclass(frozen=True)
class RowRef:
    offset: int  # negativo: linhas anteriores
    column: str
    name: str  # coluna auxiliar que guarda o valor da outra linha


def parse(expression: str) -> tuple[str, list[RowRef]]:
    """Troca ``[Row-1:x]`` por uma coluna auxiliar e devolve a lista de referências. Textos ficam como estão."""
    refs: dict[tuple[int, str], RowRef] = {}

    def replace(match: re.Match[str]) -> str:
        sign, amount, column = match.groups()
        size = int(amount)
        if size == 0 or size > MAX_OFFSET:
            raise ValueError(
                f"A referência {match.group(0)} precisa estar entre 1 e {MAX_OFFSET} linhas de distância."
            )
        key = (-size if sign == "-" else size, column.strip())
        if key not in refs:
            refs[key] = RowRef(key[0], key[1], f"__pd_ref{len(refs)}")
        return f"[{refs[key].name}]"

    pieces = []
    last = 0
    for literal in formula._STRING_LITERAL.finditer(expression):
        pieces.append(_REF.sub(replace, expression[last : literal.start()]))
        pieces.append(literal.group(0))
        last = literal.end()
    pieces.append(_REF.sub(replace, expression[last:]))
    return "".join(pieces), list(refs.values())


def for_validation(expression: str) -> str:
    """A mesma expressão com ``[Row-1:x]`` no lugar de ``[x]``: serve para conferir colunas e sintaxe."""
    return _REF.sub(lambda m: f"[{m.group(3).strip()}]", expression)


def check_refs(refs: list[RowRef], columns: list[str], target: str) -> None:
    for ref in refs:
        if ref.column == target and ref.offset > 0:
            raise ValueError(
                f"[Row+{ref.offset}:{target}] pediria um valor que ainda não foi calculado: "
                "a própria coluna só pode olhar para as linhas anteriores."
            )
        if ref.column != target and ref.column not in columns:
            raise ValueError(f"Coluna inexistente na referência: [{ref.column}].")


def empty_value(dtype: pl.DataType | None) -> Any:
    """O valor de "0 ou texto vazio" para o tipo da coluna; datas e outros tipos ficam vazios."""
    if dtype is None:
        return None
    if dtype.is_numeric():
        return 0
    return "" if dtype == pl.String else None


def _neighbors(df: pl.DataFrame, offsets: set[int], group_by: list[str]) -> dict[int, pl.Series]:
    """Para cada distância, a posição da outra linha no mesmo grupo (vazio se não existir)."""
    frame = (
        df.select(group_by).with_row_index(_ROW_INDEX)
        if group_by
        else pl.DataFrame({_ROW_INDEX: range(df.height)})
    )
    index = pl.col(_ROW_INDEX).cast(pl.Int64)
    exprs = [(index.shift(-k).over(group_by) if group_by else index.shift(-k)).alias(str(k)) for k in offsets]
    positions = frame.select(exprs) if exprs else frame.clear()
    return {k: positions[str(k)] for k in offsets}


def _value_at(values: pl.Series, positions: pl.Series, missing: str, name: str) -> pl.Series:
    out = pl.select(
        pl.when(pl.lit(positions).is_null())
        .then(pl.lit(empty_value(values.dtype) if missing == "empty" else None, dtype=values.dtype))
        .otherwise(pl.lit(values).gather(pl.lit(positions).fill_null(0)))
        .alias(name)
    ).to_series()
    return out


def _evaluate(frame: pl.DataFrame, rule: dict[str, Any], target: str, kept: str) -> pl.Series:
    """Roda a expressão sobre o quadro e devolve a coluna calculada."""
    result = formula.evaluate_columns(frame, [{**rule, "target": "new", "column": kept}])
    return result[kept].alias(target)


def evaluate(df: pl.DataFrame, rule: dict[str, Any], group_by: list[str], missing: str) -> pl.DataFrame:
    """Aplica a fórmula. ``rule`` tem ``target``, ``column``, ``existing``, ``type`` e ``expression``."""
    replace = rule.get("target") == "existing"
    target = (rule.get("existing") if replace else rule.get("column")) or ""
    target = target.strip()
    if not target or not (rule.get("expression") or "").strip():
        return df
    if replace and target not in df.columns:
        raise ValueError(f"A coluna [{target}] não existe para ser alterada.")
    if missing_groups := [c for c in group_by if c not in df.columns]:
        raise ValueError(f"Coluna(s) de agrupamento inexistente(s): {', '.join(missing_groups)}")
    expression, refs = parse(rule["expression"])
    check_refs(refs, df.columns, target)
    fixed = [r for r in refs if r.column != target]
    chained = [r for r in refs if r.column == target]
    neighbors = _neighbors(df, {r.offset for r in refs}, group_by)
    base = df.with_columns([_value_at(df[r.column], neighbors[r.offset], missing, r.name) for r in fixed])
    calculation = {**rule, "expression": expression}
    kept = "__pd_resultado"
    if not chained:
        column = _evaluate(base, calculation, target, kept)
    else:
        column = _evaluate_chained(base, df, target, calculation, chained, neighbors, missing, kept)
    return df.with_columns(column)


def _evaluate_chained(
    base: pl.DataFrame,
    df: pl.DataFrame,
    target: str,
    rule: dict[str, Any],
    chained: list[RowRef],
    neighbors: dict[int, pl.Series],
    missing: str,
    kept: str,
) -> pl.Series:
    """Rodadas até estabilizar. Depois da rodada N, as N primeiras linhas de cada grupo já estão certas."""
    current = df[target] if target in df.columns else pl.Series(target, [None] * df.height, dtype=pl.Null)

    def with_chain(values: pl.Series) -> pl.DataFrame:
        return base.with_columns([_value_at(values, neighbors[r.offset], missing, r.name) for r in chained])

    current = _evaluate(with_chain(current), rule, target, kept)
    dirty = pl.Series([True] * df.height, dtype=pl.Boolean)  # o tipo só existe agora: refaz tudo uma vez
    recalculated = 0
    for _ in range(MAX_PASSES):
        if not dirty.any():
            return current
        recalculated += int(dirty.sum())
        if recalculated > MAX_RECALCULATED:
            break
        fresh = _evaluate(with_chain(current).filter(dirty), rule, target, kept)
        if current.dtype == pl.Null:
            current = pl.Series(target, [None] * df.height, dtype=fresh.dtype)
        # ``scatter`` altera a própria série: a comparação precisa da versão anterior.
        updated = current.clone().scatter(dirty.arg_true(), fresh.cast(current.dtype, strict=False))
        changed = ~updated.eq_missing(current)
        current = updated
        dirty = pl.Series([False] * df.height, dtype=pl.Boolean)
        for ref in chained:
            positions = neighbors[ref.offset]
            dirty = dirty | (changed.gather(positions.fill_null(0)) & positions.is_not_null())
    raise ValueError(
        "A fórmula depende de cada linha anterior numa cadeia longa demais para esta tabela. "
        "Para somas acumuladas, use o Running Total; para o resto, reduza a tabela antes."
    )
