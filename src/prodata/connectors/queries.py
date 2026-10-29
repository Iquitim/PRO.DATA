"""Consultas de banco salvas na aba Dados (spec 009): fontes que o Input Data lê como um arquivo.

Ficam em ``storage/queries.json`` sem segredo algum: a senha é resolvida pela
conexão, no cofre do sistema, no momento da leitura.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.connectors import sql
from prodata.connectors.store import ConnectionStore
from prodata.domain.workflow import ID_PATTERN
from prodata.errors import InvalidInputError, NotFoundError

# Valor do campo ``dataset`` do Input Data que aponta para uma consulta: ``sql:<id>``.
SOURCE_PREFIX = "sql:"


class QueryDefinition(BaseModel):
    connection: str = Field(min_length=1)
    mode: Literal["table", "query"] = "table"
    table: str = ""
    query: str = ""

    def to_sql(self, connections: ConnectionStore) -> str:
        conn = connections.get(self.connection)
        if self.mode == "table":
            if not self.table:
                raise InvalidInputError("Escolha uma tabela.")
            return sql.table_query(conn, self.table)
        return sql.ensure_read_only(self.query)


class SavedQuery(QueryDefinition):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    cache_results: bool = False

    def digest(self) -> str:
        """Muda quando a definição muda; entra no fingerprint do Input Data."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]


def source_query_id(source: str) -> str | None:
    return source[len(SOURCE_PREFIX) :] if source.startswith(SOURCE_PREFIX) else None


def read_definition(
    definition: QueryDefinition, connections: ConnectionStore, limit: int | None = None
) -> pl.DataFrame:
    conn = connections.get(definition.connection)
    return sql.read_sql(conn, connections.password(conn.id), definition.to_sql(connections), limit=limit)


class QueryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, SavedQuery]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["id"]: SavedQuery.model_validate(item) for item in raw}

    def _write(self, items: dict[str, SavedQuery]) -> None:
        tmp = self.path.with_suffix(".tmp")
        data = [q.model_dump(mode="json") for q in sorted(items.values(), key=lambda q: q.name.lower())]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[SavedQuery]:
        return list(self._read().values())

    def get(self, query_id: str) -> SavedQuery:
        query = self._read().get(query_id)
        if query is None:
            raise NotFoundError(f"Consulta não encontrada: {query_id}. Ela foi excluída da aba Dados?")
        return query

    def save(self, query: SavedQuery) -> SavedQuery:
        with self._lock:
            items = self._read()
            items[query.id] = query
            self._write(items)
        return query

    def delete(self, query_id: str) -> None:
        with self._lock:
            items = self._read()
            if query_id not in items:
                raise NotFoundError(f"Consulta não encontrada: {query_id}")
            del items[query_id]
            self._write(items)
