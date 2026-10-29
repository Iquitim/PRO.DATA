"""Repositório de conexões: metadados em JSON, senha no ``SecretStore``."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from prodata.connectors.models import Connection, ConnectionInfo
from prodata.connectors.secrets import SecretStore
from prodata.errors import NotFoundError


def secret_key(connection_id: str) -> str:
    return f"connection:{connection_id}"


class ConnectionStore:
    def __init__(self, path: Path, secrets: SecretStore) -> None:
        self.path = path
        self.secrets = secrets
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Connection]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["id"]: Connection.model_validate(item) for item in raw}

    def _write(self, items: dict[str, Connection]) -> None:
        tmp = self.path.with_suffix(".tmp")
        data = [c.model_dump(mode="json") for c in sorted(items.values(), key=lambda c: c.name.lower())]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _info(self, conn: Connection) -> ConnectionInfo:
        return ConnectionInfo(
            **conn.model_dump(), has_password=self.secrets.get(secret_key(conn.id)) is not None
        )

    def list(self) -> list[ConnectionInfo]:
        return [self._info(c) for c in self._read().values()]

    def get(self, connection_id: str) -> Connection:
        conn = self._read().get(connection_id)
        if conn is None:
            raise NotFoundError(f"Conexão não encontrada: {connection_id}")
        return conn

    def password(self, connection_id: str) -> str:
        return self.secrets.get(secret_key(connection_id)) or ""

    def save(self, conn: Connection, password: str | None = None) -> ConnectionInfo:
        """Salva os metadados. ``password=None`` mantém a senha atual; ``""`` remove."""
        with self._lock:
            items = self._read()
            items[conn.id] = conn
            self._write(items)
        if password is not None:
            if password:
                self.secrets.set(secret_key(conn.id), password)
            else:
                self.secrets.delete(secret_key(conn.id))
        return self._info(conn)

    def delete(self, connection_id: str) -> None:
        with self._lock:
            items = self._read()
            if connection_id not in items:
                raise NotFoundError(f"Conexão não encontrada: {connection_id}")
            del items[connection_id]
            self._write(items)
        self.secrets.delete(secret_key(connection_id))
