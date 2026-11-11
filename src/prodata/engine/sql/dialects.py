"""SQL para o Microsoft Fabric (spec 033): o código do DuckDB convertido para Spark SQL ou T-SQL.

A conversão é feita bloco a bloco pelo SQLGlot. Nada aqui é executado nem conferido com os resultados: o texto
sai marcado como não conferido, e o que a conversão não entende fica em DuckDB, com o motivo escrito.
"""

from __future__ import annotations

from typing import Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from prodata.engine.sql.macros import macros_used
from prodata.engine.sql.plan import SqlPlan
from prodata.engine.sql.render import DIALECT_NOTE, Part

Dialect = Literal["duckdb", "spark", "tsql"]
NAMES = {"duckdb": "DuckDB", "spark": "Spark SQL", "tsql": "T-SQL"}
WHERE = {"spark": "Lakehouse e notebooks do Fabric", "tsql": "Warehouse do Fabric"}
_READERS = ("read_csv", "read_parquet", "read_json", "read_xlsx", "read_ndjson")


def unverified_note(dialect: str) -> str:
    return (
        f"-- Dialeto: {NAMES[dialect]} ({WHERE[dialect]}), convertido do DuckDB. NÃO CONFERIDO: "
        "este texto não foi executado nem comparado com os resultados do PRO.DATA. Revise antes de usar."
    )


def _name(name: str, dialect: str) -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)


def _convert(sql: str, dialect: str) -> tuple[str, list[str]]:
    """O SQL convertido e os avisos do bloco. Erro de conversão sobe como ``SqlglotError``."""
    notes: list[str] = []
    if macros_used(sql):
        notes.append("usa funções do PRO.DATA (pd_…) que não existem neste dialeto: reescreva as chamadas")
    if any(f"{reader}(" in sql.lower() for reader in _READERS):
        notes.append("lê um arquivo: troque pela tabela do Fabric que tem esses dados")
    converted = sqlglot.transpile(sql.rstrip().rstrip(";"), read="duckdb", write=dialect, pretty=True)
    return ";\n".join(converted), notes


def _indent(text: str, spaces: int) -> str:
    return "\n".join(" " * spaces + line if line else line for line in text.split("\n"))


def _step(plan: SqlPlan, part: Part, dialect: str) -> Part:
    assert part.block is not None
    block = plan.blocks[part.block]
    cte = not part.text.lstrip().upper().startswith("CREATE")
    try:
        sql, notes = _convert(block.sql, dialect)
        name = _name(block.name, dialect)
    except SqlglotError as exc:
        reason = " ".join(str(exc).split())[:160]
        return Part(
            f"-- NÃO CONVERTIDO ({reason}). O bloco abaixo continua em DuckDB:\n{part.text}",
            part.block,
            part.kind,
        )
    lead = "".join(f"-- Atenção: {note}.\n" for note in notes)
    if cte:
        head = "WITH\n" if part.text.lstrip().upper().startswith("WITH") else ""
        tail = "," if part.text.rstrip().endswith(",") else ""
        return Part(
            f"{head}{_indent(lead, 2)}  {name} AS (\n{_indent(sql, 4)}\n  ){tail}", part.block, part.kind
        )
    if dialect == "tsql":
        # T-SQL não tem view temporária: cada etapa compartilhada vira uma tabela temporária.
        return Part(
            f"{lead}SELECT * INTO #{block.name} FROM (\n{_indent(sql, 2)}\n) AS _etapa;",
            part.block,
            part.kind,
        )
    return Part(f"{lead}CREATE OR REPLACE TEMP VIEW {name} AS\n{_indent(sql, 2)};", part.block, part.kind)


def _final(part: Part, dialect: str, temp_tables: set[str]) -> Part:
    lines = part.text.split("\n")
    comments = [line for line in lines if line.lstrip().startswith("--")]
    code = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    try:
        sql, notes = _convert(code, dialect)
    except SqlglotError as exc:
        reason = " ".join(str(exc).split())[:160]
        return Part(f"-- NÃO CONVERTIDO ({reason}). Continua em DuckDB:\n{part.text}", part.block, part.kind)
    for name in temp_tables:
        sql = sql.replace(_name(name, dialect), f"#{name}")
    lead = "\n".join([*comments, *(f"-- Atenção: {note}." for note in notes)])
    return Part(f"{lead}\n{sql};" if lead else f"{sql};", part.block, part.kind)


def convert_parts(plan: SqlPlan, parts: list[Part], dialect: str) -> list[Part]:
    """As mesmas partes, no dialeto pedido. Cabeçalho e seções são comentários e passam como estão."""
    if dialect == "duckdb":
        return parts
    temp_tables = (
        {
            plan.blocks[p.block].name
            for p in parts
            if p.kind == "step" and p.block and p.text.startswith("CREATE")
        }
        if dialect == "tsql"
        else set()
    )
    out: list[Part] = []
    for part in parts:
        if part.kind == "header":
            out.append(Part(part.text.replace(DIALECT_NOTE, unverified_note(dialect)), kind="header"))
        elif part.kind == "macros":
            out.append(
                Part(
                    f"-- O código do DuckDB define aqui funções do PRO.DATA (pd_…). Elas não existem em {NAMES[dialect]}:\n"
                    "-- os blocos que as usam estão marcados com Atenção e precisam ser reescritos.",
                    kind="macros",
                )
            )
        elif part.kind == "step" and part.block:
            converted = _step(plan, part, dialect)
            for name in temp_tables:
                converted.text = converted.text.replace(
                    f"FROM {_name(name, dialect)}", f"FROM #{name}"
                ).replace(f"JOIN {_name(name, dialect)}", f"JOIN #{name}")
            out.append(converted)
        elif part.kind == "final":
            out.append(_final(part, dialect, temp_tables))
        else:
            out.append(part)
    return out
