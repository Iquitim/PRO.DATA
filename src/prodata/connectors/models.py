"""Modelo de conexão. Não existe campo de senha: ela vive só no ``SecretStore``."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from prodata.domain.workflow import ID_PATTERN

Dialect = Literal["postgres", "mssql", "odbc"]
DEFAULT_PORTS: dict[str, int] = {"postgres": 5432, "mssql": 1433, "odbc": 0}
# Só o nome da fonte de dados: nada de ``;`` ou ``=``, para ninguém embutir senha ou outro atributo no texto.
_DSN = re.compile(r"^[^;={}\[\]\n\r]{1,120}$")


class Connection(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    kind: Dialect = "postgres"
    host: str = ""
    port: int = Field(0, ge=0, le=65535, description="0 = porta padrão do banco.")
    database: str = ""
    user: str = ""
    # ODBC (spec 033): nome da fonte de dados (DSN) configurada no Windows. Usuário e senha são opcionais.
    odbc_dsn: str = ""
    # PostgreSQL
    ssl_mode: Literal["disable", "prefer", "require"] = "prefer"
    # SQL Server
    encrypt: bool = True
    trust_server_certificate: bool = False

    @model_validator(mode="after")
    def _check_kind(self) -> Connection:
        if self.kind == "odbc":
            if not _DSN.match(self.odbc_dsn.strip()):
                raise ValueError(
                    "Informe só o nome da fonte de dados ODBC (DSN), sem ';' nem '='. "
                    "Usuário e senha têm campos próprios, e a senha fica no cofre."
                )
            self.odbc_dsn = self.odbc_dsn.strip()
            return self
        for value, label in (
            (self.host, "o servidor"),
            (self.database, "o database"),
            (self.user, "o usuário"),
        ):
            if not value.strip():
                raise ValueError(f"Informe {label}.")
        return self

    @property
    def effective_port(self) -> int:
        return self.port or DEFAULT_PORTS[self.kind]


class ConnectionInfo(Connection):
    has_password: bool = False
