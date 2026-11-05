"""Definição de uma API: modelos, erros e checagem do endereço (spec 021)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from prodata.domain.workflow import ID_PATTERN
from prodata.errors import InvalidInputError

SOURCE_PREFIX = "api:"
_PLACEHOLDER = re.compile(r"\{([^{}\"':\r\n]+)\}")


def source_api_id(source: str) -> str | None:
    return source[len(SOURCE_PREFIX) :] if source.startswith(SOURCE_PREFIX) else None


class ApiError(InvalidInputError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RequestLimitError(ApiError):
    """Chegou ao limite de pedidos reais do API Loop."""


class ApiParam(BaseModel):
    name: str = ""
    value: str = ""
    # Sigiloso: o valor vai para o cofre e ``value`` fica vazio.
    secret: bool = False
    # Para que serve: anotação de quem cadastrou, não vai no pedido.
    note: str = Field("", max_length=300)


class ApiAuth(BaseModel):
    type: Literal["none", "bearer", "api_key", "basic", "oauth2"] = "none"
    key_name: str = "X-API-Key"
    key_in: Literal["header", "query"] = "header"
    username: str = ""
    token_url: str = ""
    client_id: str = ""
    scope: str = ""


class ApiPagination(BaseModel):
    type: Literal["none", "page", "offset", "cursor", "next_link"] = "none"
    page_param: str = "page"
    start_page: int = Field(1, ge=0)
    size_param: str = ""
    page_size: int = Field(100, ge=1, le=100_000)
    offset_param: str = "offset"
    limit_param: str = "limit"
    cursor_param: str = "cursor"
    cursor_path: str = "next_cursor"
    # Vazio: lê o cabeçalho ``Link`` da resposta.
    next_path: str = ""
    max_pages: int = Field(100, ge=1, le=100_000)


class ApiDefinition(BaseModel):
    url: str = ""
    method: Literal["GET", "POST"] = "GET"
    params: list[ApiParam] = Field(default_factory=list)
    headers: list[ApiParam] = Field(default_factory=list)
    body: str = ""
    body_type: Literal["json", "text"] = "json"
    auth: ApiAuth = Field(default_factory=ApiAuth)
    format: Literal["auto", "json", "csv", "xml"] = "auto"
    records_path: str = ""
    explode_path: str = ""
    flatten: bool = True
    pagination: ApiPagination = Field(default_factory=ApiPagination)
    timeout_s: float = Field(30, gt=0, le=600)
    max_mb: int = Field(200, ge=1, le=4096)
    retries: int = Field(3, ge=0, le=10)
    # Onde estão os parâmetros que a API aceita: só para consulta, nunca é chamado pelo programa.
    docs_url: str = ""

    @field_validator("url")
    @classmethod
    def _clean_url(cls, value: str) -> str:
        return value.strip()

    def check(self) -> None:
        check_url(self.url)
        if self.docs_url.strip():
            check_url(self.docs_url.strip(), "da documentação")
        if self.auth.type == "oauth2":
            check_url(self.auth.token_url, "do token")
        if self.method == "POST" and self.body_type == "json" and self.body.strip():
            try:
                json.loads(self.body)
            except json.JSONDecodeError as exc:
                raise ApiError(
                    f"O corpo não é um JSON válido (linha {exc.lineno}). Coloque cada {{coluna}} entre aspas: "
                    'o valor entra com o tipo certo, como em {"id": "{id}"}.'
                ) from None

    def placeholders(self) -> list[str]:
        """Colunas que a definição pede, como ``{id}``: sem elas, a chamada precisa do API Loop."""
        texts = [self.url, self.body if self.method == "POST" else ""]
        texts += [p.value for p in [*self.params, *self.headers] if not p.secret]
        return list(dict.fromkeys(m for t in texts for m in _PLACEHOLDER.findall(t)))

    def secret_slots(self) -> list[str]:
        slots = {
            "bearer": ["token"],
            "api_key": ["token"],
            "basic": ["password"],
            "oauth2": ["client_secret"],
        }
        own = slots.get(self.auth.type, [])
        own = [*own, *[f"param:{p.name}" for p in self.params if p.secret and p.name]]
        return [*own, *[f"header:{p.name}" for p in self.headers if p.secret and p.name]]


class SavedApi(ApiDefinition):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    cache_results: bool = False
    # Não chama ao abrir um fluxo: espera o clique em Executar (spec 022).
    hold_on_open: bool = False

    def digest(self) -> str:
        """Muda quando a definição muda; entra no fingerprint de quem lê a fonte."""
        # Link e anotações não mudam a chamada: editá-los não pode refazer nem invalidar nada.
        data = self.model_dump(mode="json", exclude={"docs_url"})
        for group in ("params", "headers"):
            for item in data[group]:
                item.pop("note", None)
        raw = json.dumps(data, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]


class ApiInfo(SavedApi):
    missing_secrets: list[str] = Field(default_factory=list)
    set_secrets: list[str] = Field(default_factory=list)


def check_url(url: str, what: str = "da API") -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ApiError(f"O endereço {what} precisa começar com https:// (ou http://).")
    if parts.username or parts.password:
        raise ApiError("Não coloque usuário e senha no endereço: use a Autenticação, que guarda no cofre.")


def is_insecure(url: str) -> bool:
    """http:// fora da própria máquina: credenciais e dados viajam sem criptografia."""
    parts = urlsplit(url)
    return parts.scheme == "http" and (parts.hostname or "") not in ("localhost", "127.0.0.1", "::1")


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()
