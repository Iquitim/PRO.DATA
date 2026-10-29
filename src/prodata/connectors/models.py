"""Modelo de conexão. Não existe campo de senha: ela vive só no ``SecretStore``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from prodata.domain.workflow import ID_PATTERN

Dialect = Literal["postgres", "mssql"]
DEFAULT_PORTS: dict[str, int] = {"postgres": 5432, "mssql": 1433}


class Connection(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    kind: Dialect = "postgres"
    host: str = Field(min_length=1)
    port: int = Field(0, ge=0, le=65535, description="0 = porta padrão do banco.")
    database: str = Field(min_length=1)
    user: str = Field(min_length=1)
    # PostgreSQL
    ssl_mode: Literal["disable", "prefer", "require"] = "prefer"
    # SQL Server
    encrypt: bool = True
    trust_server_certificate: bool = False

    @property
    def effective_port(self) -> int:
        return self.port or DEFAULT_PORTS[self.kind]


class ConnectionInfo(Connection):
    has_password: bool = False
