"""Vocabulário da tradução: o que cada ferramenta recebe e devolve ao virar SQL (spec 020).

Uma ferramenta declara a tradução com ``@sql_for("tipo")``, ao lado do ``run``. Sem isso, ela aparece como
"sem tradução", sem nenhum tratamento especial.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from prodata.connectors.api_store import ApiStore
from prodata.connectors.queries import QueryStore
from prodata.ingestion.datasets import DatasetStore


class NoTranslationError(Exception):
    """Não há equivalente em SQL. A mensagem explica o motivo ao usuário."""


class NotReadyError(Exception):
    """A tradução depende dos dados (ex.: colunas do Cross Tab), e o fluxo ainda não executou até aqui."""


@dataclass
class SqlInput:
    """Uma entrada da caixa: o nome do bloco anterior e as colunas que chegam."""

    block: str
    columns: list[str]
    kinds: dict[str, str]


@dataclass
class SqlContext:
    inputs: dict[str, SqlInput]
    datasets: DatasetStore | None = None
    queries: QueryStore | None = None
    # Tabela que chegou pela porta na última execução, se ainda vale para o fluxo atual.
    sample: Callable[[str], pl.DataFrame | None] = lambda _port: None
    apis: ApiStore | None = None

    def input(self, port: str = "in") -> SqlInput:
        if port not in self.inputs:
            raise ValueError(f"Conecte a entrada [{port}].")
        return self.inputs[port]


@dataclass
class SourceInfo:
    """Fonte de dados: o SQL mostra só o nome; o caminho real nunca entra no código (RF-2030)."""

    display: str
    path: Path | None = None
    schema: pl.Schema | None = None
    file_check: bool = True  # False: a leitura não pode ser conferida a partir do arquivo


@dataclass
class Fragment:
    sql: str
    explain: str = ""
    notes: list[str] = field(default_factory=list)
    comparable: bool = True  # False: o motor e o SQL não têm como dar as mesmas linhas (amostra aleatória)
    ordered_by: list[str] = field(default_factory=list)  # a ordem destas colunas faz parte do resultado
    source: SourceInfo | None = None
    visual_sql: str | None = None
    data_warning: str = ""
    export_file: str = ""


SqlFn = Callable[[SqlContext, Any], dict[str, Fragment]]
SQL_REGISTRY: dict[str, SqlFn] = {}


def sql_for(tool_type: str) -> Callable[[SqlFn], SqlFn]:
    def register(fn: SqlFn) -> SqlFn:
        SQL_REGISTRY[tool_type] = fn
        return fn

    return register


# ---------------------------------------------------------------- texto SQL


def _reserved_words() -> frozenset[str]:
    """As palavras que o próprio DuckDB não aceita como nome sem aspas."""
    with duckdb.connect(":memory:") as con:
        rows = con.execute(
            "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category IN ('reserved', 'type_function')"
        ).fetchall()
    return frozenset(str(r[0]) for r in rows)


_RESERVED = _reserved_words()
_PLAIN = re.compile(r"^[a-z_][a-z0-9_]*$")


def q(name: str) -> str:
    """Identificador: sem aspas quando dá, para o código ficar legível; aspas escapadas nos demais casos."""
    if _PLAIN.match(name) and name not in _RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


def lit(value: Any) -> str:
    """Valor literal, sempre escapado (RF-2032)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def comment(text: str) -> str:
    """Texto de comentário em uma linha só: uma quebra de linha num nome viraria comando no código (RF-2032)."""
    return " ".join(str(text).split())


def single_select(con: duckdb.DuckDBPyConnection, sql: str) -> bool:
    """O texto é uma única consulta? Fórmula ou consulta com "; COPY ..." nunca entra no código nem é executada."""
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error:
        return True  # erro de sintaxe: quem executa dá a mensagem certa
    return len(statements) == 1 and statements[0].type == duckdb.StatementType.SELECT


def arrow_safe(df: pl.DataFrame) -> pl.DataFrame:
    """O DuckDB não lê inteiros de 128 bits vindos do Polars; decimal sem casas guarda o mesmo número."""
    wide = [c for c, t in df.schema.items() if t in (pl.Int128, pl.UInt128)]
    return df.with_columns(pl.col(wide).cast(pl.Decimal(38, 0), strict=False)) if wide else df


def text_cast(expr: str, kind: str) -> str:
    """Valor como texto, escrito como o motor escreve: data e hora com microssegundos, "NaN" em decimal."""
    if kind == "Datetime":
        return f"strftime({expr}, '%Y-%m-%d %H:%M:%S.%f')"
    if kind == "Float":
        return f"pd_texto_decimal({expr})"
    return f"CAST({expr} AS VARCHAR)"


def slug(text: str) -> str:
    """Nome de bloco legível: sem acento, minúsculas e sublinhado."""
    plain = unicodedata.normalize("NFKD", text.replace("×", "x"))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    name = re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "etapa"
    if name[0].isdigit():
        name = f"etapa_{name}"
    return f"{name}_" if name in _RESERVED else name


def kind_of(sql_type: str) -> str:
    """Família do tipo do DuckDB, usada para escolher conversões."""
    t = sql_type.upper()
    if t == "VARCHAR" or t.startswith("VARCHAR"):
        return "String"
    if t == "BOOLEAN":
        return "Boolean"
    if t == "DATE":
        return "Date"
    if t.startswith("TIMESTAMP"):
        return "Datetime"
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return "Float"
    if t.endswith("INT") or t in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "UHUGEINT"):
        return "Int"
    return "Other"


def text_of(column: str) -> str:
    """Texto sem espaços nas pontas, do mesmo jeito que o motor (espaço, tabulação e quebra de linha)."""
    return f"regexp_replace({column}, '^\\s+|\\s+$', '', 'g')"


NUMERIC_KINDS = ("Int", "Float")
OWN_RESULT = "__proprio__"  # ``SqlContext.sample``: o resultado da própria caixa, para fontes
ROW_POSITION = "__linha"


def numbered(block: str) -> str:
    """Subconsulta com a posição de cada linha: o SQL não garante ordem; o motor preserva a de chegada."""
    return f"(SELECT *, row_number() OVER () AS {ROW_POSITION} FROM {q(block)})"


def join_list(items: list[str], indent: int = 2) -> str:
    return (",\n" + " " * indent).join(items)
