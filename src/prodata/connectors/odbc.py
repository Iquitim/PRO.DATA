"""Conexão ODBC genérica (spec 033): qualquer banco com driver instalado, por uma fonte de dados (DSN) do Windows.

Somente leitura, como as outras conexões: a consulta passa pela mesma conferência de SELECT/WITH e a conexão é
aberta em modo de leitura. A senha vem do cofre e só existe no texto de conexão montado aqui, em memória.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import polars as pl

from prodata.connectors.models import Connection
from prodata.errors import InvalidInputError

SYSTEM_SCHEMAS = {"sys", "information_schema", "pg_catalog", "system", "mysql", "performance_schema"}
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


def _braced(value: str) -> str:
    """Valor do texto de conexão entre chaves: ``;`` e ``=`` dentro dele não viram outro atributo."""
    return "{" + value.replace("}", "}}") + "}"


def connection_string(conn: Connection, password: str) -> str:
    parts = [f"DSN={conn.odbc_dsn}"]
    if conn.user:
        parts.append(f"UID={_braced(conn.user)}")
    if password:
        parts.append(f"PWD={_braced(password)}")
    return ";".join(parts)


def connect(conn: Connection, password: str) -> Any:
    """Único ponto que abre o driver (substituído nos testes). Importado sob demanda."""
    try:
        import pyodbc
    except ImportError as exc:
        raise InvalidInputError("O suporte a ODBC não está instalado neste ambiente.") from exc
    return pyodbc.connect(connection_string(conn, password), readonly=True, autocommit=True, timeout=15)


def _unique(names: Sequence[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for raw in names:
        name = raw or "coluna"
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def to_frame(names: Sequence[str], rows: Sequence[Sequence[Any]]) -> pl.DataFrame:
    """Linhas do driver em tabela. Decimal vira número, e o que o Polars não conhece vira texto."""
    columns = _unique(names)
    if not rows:
        return pl.DataFrame(schema=dict.fromkeys(columns, pl.String))
    data: dict[str, pl.Series] = {}
    for i, name in enumerate(columns):
        values = [row[i] for row in rows]
        if any(isinstance(v, Decimal) for v in values):
            values = [float(v) if isinstance(v, Decimal) else v for v in values]
        try:
            data[name] = pl.Series(name, values, strict=False)
        except TypeError, ValueError, pl.exceptions.PolarsError:
            data[name] = pl.Series(name, [None if v is None else str(v) for v in values], dtype=pl.String)
    return pl.DataFrame(data)


def read_with(connection: Any, query: str, limit: int | None = None) -> pl.DataFrame:
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        names = [str(d[0]) for d in cursor.description or []]
        rows = cursor.fetchmany(int(limit)) if limit else cursor.fetchall()
        return to_frame(names, rows)
    finally:
        cursor.close()


def read(conn: Connection, password: str, query: str, limit: int | None = None) -> pl.DataFrame:
    connection = connect(conn, password)
    try:
        return read_with(connection, query, limit)
    finally:
        connection.close()


def tables_with(connection: Any) -> list[dict[str, str]]:
    cursor = connection.cursor()
    try:
        found = []
        for row in cursor.tables():
            schema, name, kind = str(row[1] or ""), str(row[2] or ""), str(row[3] or "").upper()
            if kind not in ("TABLE", "VIEW") or schema.lower() in SYSTEM_SCHEMAS or not name:
                continue
            found.append(
                {
                    "schema": schema,
                    "name": name,
                    "type": "view" if kind == "VIEW" else "table",
                    "qualified": f"{schema}.{name}" if schema else name,
                }
            )
        return sorted(found, key=lambda t: (t["schema"].lower(), t["name"].lower()))
    finally:
        cursor.close()


def list_tables(conn: Connection, password: str) -> list[dict[str, str]]:
    connection = connect(conn, password)
    try:
        return tables_with(connection)
    finally:
        connection.close()


def quote_name(part: str) -> str:
    """Nome simples vai como está: as aspas mudam de banco para banco, e o padrão (") nem sempre vale."""
    return part if _PLAIN_NAME.match(part) else '"' + part.replace('"', '""') + '"'


def table_query(qualified: str) -> str:
    return "SELECT * FROM " + ".".join(quote_name(p) for p in qualified.split(".") if p)
