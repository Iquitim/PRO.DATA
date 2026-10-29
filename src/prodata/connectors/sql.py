"""Leitura de bancos via connectorx (PostgreSQL e SQL Server), sempre somente leitura."""

from __future__ import annotations

import re
import socket
from typing import Any
from urllib.parse import quote, urlencode

import polars as pl

from prodata.connectors.models import Connection
from prodata.errors import InvalidInputError

_STRINGS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]")
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|"
    r"INTO|COPY|VACUUM|REINDEX|LOCK|SET|DECLARE|BACKUP|RESTORE|SHUTDOWN)\b",
    re.IGNORECASE,
)

SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "sys", "INFORMATION_SCHEMA")


class DatabaseError(InvalidInputError):
    """Falha ao falar com o banco (mensagem já sem a senha)."""


def ensure_read_only(query: str) -> str:
    """Devolve a consulta normalizada ou lança ``InvalidInputError`` se não for leitura pura."""
    masked = _COMMENTS.sub(" ", _STRINGS.sub("''", query or ""))
    stripped = masked.strip().rstrip(";").strip()
    if not stripped:
        raise InvalidInputError("Escreva uma consulta SQL.")
    if ";" in stripped:
        raise InvalidInputError("Use uma única instrução SQL (sem ';' no meio).")
    if not re.match(r"(?is)^(SELECT|WITH)\b", stripped):
        raise InvalidInputError(
            "Somente consultas SELECT ou WITH são permitidas (conexões são somente leitura)."
        )
    if match := _FORBIDDEN.search(stripped):
        raise InvalidInputError(f"Comando não permitido em conexão somente leitura: {match.group(1).upper()}")
    return query.strip().rstrip(";").strip()


def build_uri(conn: Connection, password: str) -> str:
    auth = quote(conn.user, safe="") + (f":{quote(password, safe='')}" if password else "")
    base = f"{auth}@{conn.host}:{conn.effective_port}/{quote(conn.database, safe='')}"
    if conn.kind == "postgres":
        params: dict[str, Any] = {"sslmode": conn.ssl_mode, "connect_timeout": 10}
        return f"postgresql://{base}?{urlencode(params)}"
    params = {
        "encrypt": str(conn.encrypt).lower(),
        "trust_server_certificate": str(conn.trust_server_certificate).lower(),
    }
    return f"mssql://{base}?{urlencode(params)}"


def quote_table(conn: Connection, schema: str, table: str) -> str:
    if conn.kind == "mssql":
        return f"[{schema.replace(']', ']]')}].[{table.replace(']', ']]')}]"
    return '"{}"."{}"'.format(schema.replace('"', '""'), table.replace('"', '""'))


def limited(conn: Connection, query: str, limit: int | None) -> str:
    if not limit:
        return query
    if conn.kind == "mssql":
        return f"SELECT TOP {int(limit)} * FROM ({query}) AS _q"
    return f"SELECT * FROM ({query}) AS _q LIMIT {int(limit)}"


def _execute(uri: str, query: str, pre_execution: list[str] | None) -> pl.DataFrame:
    """Único ponto que toca o driver (substituído nos testes). Importado sob demanda: só quem
    usa bancos paga o custo de carregar o connectorx."""
    import connectorx

    table = connectorx.read_sql(uri, query, return_type="arrow", pre_execution_query=pre_execution)
    df = pl.from_arrow(table)
    if not isinstance(df, pl.DataFrame):
        raise TypeError("O driver não devolveu uma tabela.")
    return df


def _sanitize(message: str, password: str, uri: str) -> str:
    for secret in {password, quote(password, safe=""), uri} - {""}:
        message = message.replace(secret, "***")
    return re.sub(r"://[^@\s/]+@", "://***@", message).strip()


def ensure_reachable(conn: Connection, timeout: float = 5.0) -> None:
    """Checagem rápida de rede antes do driver: o pool do connectorx insiste por ~30 s
    antes de desistir de um servidor inacessível; aqui a resposta vem em segundos."""
    try:
        socket.create_connection((conn.host, conn.effective_port), timeout=timeout).close()
    except OSError as exc:
        reason = "tempo esgotado" if isinstance(exc, TimeoutError) else (exc.strerror or str(exc))
        raise DatabaseError(
            f"{conn.name}: servidor {conn.host}:{conn.effective_port} inacessível ({reason}). "
            "Confira host, porta, VPN e firewall."
        ) from exc


def read_sql(conn: Connection, password: str, query: str, limit: int | None = None) -> pl.DataFrame:
    sql = limited(conn, ensure_read_only(query), limit)
    ensure_reachable(conn)
    uri = build_uri(conn, password)
    pre = ["SET default_transaction_read_only = on"] if conn.kind == "postgres" else None
    try:
        return _execute(uri, sql, pre)
    except Exception as exc:  # o driver lança RuntimeError/ValueError genéricos com a mensagem do banco
        raise DatabaseError(f"{conn.name}: {_sanitize(str(exc), password, uri)}") from exc


def table_query(conn: Connection, qualified: str) -> str:
    schema, _, table = qualified.rpartition(".")
    return f"SELECT * FROM {quote_table(conn, schema or default_schema(conn), table)}"


def default_schema(conn: Connection) -> str:
    return "dbo" if conn.kind == "mssql" else "public"


def list_tables(conn: Connection, password: str) -> list[dict[str, str]]:
    excluded = ", ".join(f"'{s}'" for s in SYSTEM_SCHEMAS)
    query = (
        "SELECT table_schema, table_name, table_type FROM information_schema.tables "
        f"WHERE table_schema NOT IN ({excluded}) AND table_schema NOT LIKE 'pg_%' "
        "ORDER BY table_schema, table_name"
    )
    df = read_sql(conn, password, query)
    return [
        {
            "schema": s,
            "name": n,
            "type": "view" if "VIEW" in str(t).upper() else "table",
            "qualified": f"{s}.{n}",
        }
        for s, n, t in df.rows()
    ]


def check_connection(conn: Connection, password: str) -> None:
    read_sql(conn, password, "SELECT 1 AS ok")
