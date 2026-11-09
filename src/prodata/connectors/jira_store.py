"""Cadastro de conexões e consultas do Jira (spec 030). Token e e-mail vão só para o cofre do sistema."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from prodata.connectors.jira import JiraClient
from prodata.connectors.jira_model import JiraConnection, JiraInfo, JiraQuery
from prodata.connectors.secrets import SecretStore
from prodata.errors import InvalidInputError, NotFoundError


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class JiraStore:
    def __init__(self, folder: Path, secrets: SecretStore) -> None:
        self.folder = folder
        self.secrets = secrets
        self.local_dir = folder / "local"
        self._lock = threading.Lock()
        self._connections_file = folder / "conexoes.json"
        self._queries_file = folder / "consultas.json"

    def _ensure(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ conexões

    def _connections(self) -> dict[str, JiraConnection]:
        if not self._connections_file.is_file():
            return {}
        raw = json.loads(self._connections_file.read_text(encoding="utf-8"))
        return {c["id"]: JiraConnection.model_validate(c) for c in raw}

    def _info(self, conn: JiraConnection) -> JiraInfo:
        return JiraInfo(
            **conn.model_dump(),
            has_token=bool(self.secrets.get(f"jira:{conn.id}:token")),
            email=self.secrets.get(f"jira:{conn.id}:email") or "",
        )

    def connections(self) -> list[JiraInfo]:
        return [self._info(c) for c in sorted(self._connections().values(), key=lambda c: c.name.lower())]

    def connection(self, conn_id: str) -> JiraConnection:
        conn = self._connections().get(conn_id)
        if conn is None:
            raise NotFoundError(f"Conexão do Jira não encontrada: {conn_id}. Ela foi excluída da vista Dados?")
        return conn

    def save_connection(self, conn: JiraConnection, email: str | None, token: str | None) -> JiraInfo:
        """E-mail ou token ausente fica como está."""
        self._ensure()
        with self._lock:
            items = self._connections()
            items[conn.id] = conn
            _write_json(self._connections_file, [c.model_dump(mode="json") for c in items.values()])
        if email:
            self.secrets.set(f"jira:{conn.id}:email", email.strip())
        if token:
            self.secrets.set(f"jira:{conn.id}:token", token.strip())
        return self._info(conn)

    def delete_connection(self, conn_id: str) -> None:
        if any(q.connection == conn_id for q in self.queries()):
            raise InvalidInputError("Há consultas usando esta conexão: exclua-as antes.")
        with self._lock:
            items = self._connections()
            if items.pop(conn_id, None) is None:
                raise NotFoundError(f"Conexão do Jira não encontrada: {conn_id}")
            _write_json(self._connections_file, [c.model_dump(mode="json") for c in items.values()])
        self.secrets.delete(f"jira:{conn_id}:email")
        self.secrets.delete(f"jira:{conn_id}:token")

    def client(self, conn_id: str, **kw: Any) -> JiraClient:
        conn = self.connection(conn_id)
        return JiraClient(
            conn.site,
            self.secrets.get(f"jira:{conn_id}:email") or "",
            self.secrets.get(f"jira:{conn_id}:token") or "",
            **kw,
        )

    # ------------------------------------------------------------------ consultas

    def queries(self) -> list[JiraQuery]:
        if not self._queries_file.is_file():
            return []
        raw = json.loads(self._queries_file.read_text(encoding="utf-8"))
        return sorted((JiraQuery.model_validate(q) for q in raw), key=lambda q: q.name.lower())

    def query(self, query_id: str) -> JiraQuery:
        for q in self.queries():
            if q.id == query_id:
                return q
        raise NotFoundError(f"Consulta do Jira não encontrada: {query_id}. Ela foi excluída da vista Dados?")

    def save_query(self, query: JiraQuery) -> JiraQuery:
        self.connection(query.connection)
        query.to_jql()
        self._ensure()
        with self._lock:
            items = {q.id: q for q in self.queries()}
            items[query.id] = query
            _write_json(self._queries_file, [q.model_dump(mode="json") for q in items.values()])
        return query

    def delete_query(self, query_id: str) -> None:
        with self._lock:
            items = {q.id: q for q in self.queries()}
            if items.pop(query_id, None) is None:
                raise NotFoundError(f"Consulta do Jira não encontrada: {query_id}")
            _write_json(self._queries_file, [q.model_dump(mode="json") for q in items.values()])
        self.forget(query_id)

    # ------------------------------------------------------------------ guardado local

    def local_path(self, query_id: str, what: str) -> Path:
        self._ensure()
        return self.local_dir / f"{query_id}.{what}"

    def forget(self, query_id: str) -> None:
        for path in self.local_dir.glob(f"{query_id}.*") if self.local_dir.is_dir() else []:
            path.unlink(missing_ok=True)

    def remove_all_local(self) -> None:
        shutil.rmtree(self.local_dir, ignore_errors=True)
