"""Fontes de API (spec 021): cadastro, chamada, paginação e leitura da resposta como tabela.

A definição fica em ``storage/apis.json`` sem segredo algum: token, senha e cabeçalhos marcados
como sigilosos vão para o cofre do sistema. Mensagens de erro nunca levam esses valores.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import logging
import os
import re
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import polars as pl
from pydantic import BaseModel, Field, field_validator

from prodata.connectors.secrets import SecretStore
from prodata.domain.workflow import ID_PATTERN
from prodata.errors import InvalidInputError, NotFoundError

# A biblioteca registra cada URL no log em nível INFO, e a URL pode levar a chave da API.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Valor do campo ``dataset`` do Input Data que aponta para uma API: ``api:<id>``.
SOURCE_PREFIX = "api:"
MAX_REDIRECTS = 5
MAX_WAIT_SECONDS = 60.0
RETRY_BASE_SECONDS = 1.0
_PLACEHOLDER = re.compile(r"\{([^{}\"':\r\n]+)\}")
_LINK_NEXT = re.compile(r'<([^>]+)>\s*;[^,]*rel="?next"?', re.IGNORECASE)
_RETRY_ALWAYS = {429}
_RETRY_SAFE = {502, 503, 504}


def source_api_id(source: str) -> str | None:
    return source[len(SOURCE_PREFIX) :] if source.startswith(SOURCE_PREFIX) else None


class ApiError(InvalidInputError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


# ------------------------------------------------------------------ valores das colunas


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _fill_path(url: str, values: dict[str, Any]) -> str:
    """No endereço, o valor nunca muda o caminho: ``a/b`` vira ``a%2Fb``."""

    def replace(match: re.Match[str]) -> str:
        return quote(_text(values[match.group(1)]), safe="") if match.group(1) in values else match.group(0)

    return _PLACEHOLDER.sub(replace, url)


def _fill_text(text: str, values: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: _text(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def _fill_header(text: str, values: dict[str, Any]) -> str:
    filled = _fill_text(text, values)
    if "\r" in filled or "\n" in filled:
        raise ApiError("Um valor com quebra de linha não pode ir num cabeçalho.")
    return filled


def _fill_json(node: Any, values: dict[str, Any]) -> Any:
    """Um texto que é só ``{coluna}`` recebe o valor com o tipo original; o JSON é montado depois, com escape."""
    if isinstance(node, dict):
        return {k: _fill_json(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill_json(v, values) for v in node]
    if isinstance(node, str):
        whole = _PLACEHOLDER.fullmatch(node)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return _fill_text(node, values)
    return node


# ------------------------------------------------------------------ resposta vira tabela


def _dig(document: Any, path: str) -> Any:
    current = document
    for piece in [p for p in path.split(".") if p]:
        if isinstance(current, dict) and piece in current:
            current = current[piece]
        elif isinstance(current, list) and piece.isdigit() and int(piece) < len(current):
            current = current[int(piece)]
        else:
            return None
    return current


def _flatten(record: dict[str, Any], flatten: bool, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and flatten:
            out.update(_flatten(value, flatten, f"{name}."))
        elif isinstance(value, dict | list):
            out[name] = json.dumps(value, ensure_ascii=False)
        else:
            out[name] = value
    return out


def _explode(record: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Uma linha por item da lista em ``path``; os demais campos se repetem. Lista vazia mantém a linha."""
    keys = [p for p in path.split(".") if p]
    parent: Any = record
    for key in keys[:-1]:
        parent = parent.get(key) if isinstance(parent, dict) else None
    items = parent.get(keys[-1]) if isinstance(parent, dict) and keys else None
    if not isinstance(items, list) or not items:
        return [record]
    rows = []
    for item in items:
        copy = json.loads(json.dumps(record))
        target = copy
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = item if isinstance(item, dict) else {"valor": item}
        rows.append(copy)
    return rows


def _as_records(found: Any) -> list[dict[str, Any]]:
    items = found if isinstance(found, list) else [found]
    return [i if isinstance(i, dict) else {"valor": i} for i in items if i is not None or len(items) == 1]


def _json_records(document: Any, d: ApiDefinition) -> list[dict[str, Any]]:
    if d.records_path:
        found = _dig(document, d.records_path)
        if found is None:
            keys = ", ".join(document) if isinstance(document, dict) else "uma lista"
            raise ApiError(f'O caminho "{d.records_path}" não existe na resposta. Ela traz: {keys[:200]}.')
    elif isinstance(document, dict):
        lists = [v for v in document.values() if isinstance(v, list)]
        found = lists[0] if len(lists) == 1 else document
    else:
        found = document
    rows = _as_records(found)
    if d.explode_path:
        rows = [r for row in rows for r in _explode(row, d.explode_path)]
    return [_flatten(r, d.flatten) for r in rows]


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element(el: ET.Element) -> Any:
    data: dict[str, Any] = {f"@{_strip_ns(k)}": v for k, v in el.attrib.items()}
    for child in el:
        name = _strip_ns(child.tag)
        value = _element(child)
        if name in data:
            data[name] = [*data[name], value] if isinstance(data[name], list) else [data[name], value]
        else:
            data[name] = value
    text = (el.text or "").strip()
    if not data:
        return text or None
    if text:
        data["valor"] = text
    return data


def _xml_records(body: bytes, d: ApiDefinition) -> list[dict[str, Any]]:
    if b"<!DOCTYPE" in body[:4096] or b"<!ENTITY" in body[:65536]:
        raise ApiError("A resposta XML traz um DOCTYPE, que não é aceito por segurança.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ApiError(f"A resposta não é um XML válido: {exc}.") from None
    node = root
    pieces = [p for p in d.records_path.split(".") if p]
    if pieces and pieces[0] == _strip_ns(root.tag):
        pieces = pieces[1:]
    for depth, piece in enumerate(pieces):
        matches = [c for c in node if _strip_ns(c.tag) == piece]
        if not matches:
            raise ApiError(f'O caminho "{d.records_path}" não existe na resposta.')
        if depth == len(pieces) - 1:
            return [_flatten(r, d.flatten) for r in _as_records([_element(m) for m in matches])]
        node = matches[0]
    # Sem caminho: desce até achar um elemento que se repete.
    while len(node) == 1:
        node = node[0]
    tags = Counter(_strip_ns(c.tag) for c in node)
    if not tags:
        return [_flatten(r, d.flatten) for r in _as_records(_element(node))]
    common = tags.most_common(1)[0][0]
    return [
        _flatten(r, d.flatten) for r in _as_records([_element(c) for c in node if _strip_ns(c.tag) == common])
    ]


def _csv_records(body: bytes) -> list[dict[str, Any]]:
    head = body[:4096].decode("utf-8", "replace").split("\n", 1)[0]
    separator = max(",;\t|", key=head.count)
    frame = pl.read_csv(
        io.BytesIO(body),
        separator=separator,
        infer_schema_length=10_000,
        truncate_ragged_lines=True,
        encoding="utf8-lossy",
        quote_char='"',
    )
    return frame.to_dicts()


def _detect_format(body: bytes, content_type: str, wanted: str) -> str:
    if wanted != "auto":
        return wanted
    kind = content_type.lower()
    if "json" in kind:
        return "json"
    if "xml" in kind:
        return "xml"
    if "csv" in kind:
        return "csv"
    if "html" in kind:
        raise ApiError(
            "A API devolveu uma página HTML, e não dados. Costuma ser uma tela de login: confira o endereço e a autenticação."
        )
    start = body.lstrip()[:1]
    return "json" if start in (b"{", b"[") else "xml" if start == b"<" else "csv"


def parse_records(body: bytes, content_type: str, d: ApiDefinition) -> tuple[list[dict[str, Any]], Any]:
    """Linhas da resposta e o documento JSON (para achar o próximo cursor)."""
    if not body.strip():
        return [], None
    kind = _detect_format(body, content_type, d.format)
    if kind == "json":
        try:
            document = json.loads(body)
        except ValueError:
            raise ApiError("A resposta não é um JSON válido.") from None
        return _json_records(document, d), document
    if kind == "xml":
        return _xml_records(body, d), None
    return _csv_records(body), None


def _column(name: str, values: list[Any]) -> pl.Series:
    kinds = {type(v) for v in values if v is not None}
    if kinds == {bool}:
        return pl.Series(name, values, dtype=pl.Boolean)
    if kinds == {int}:
        try:
            return pl.Series(name, values, dtype=pl.Int64)
        except (
            OverflowError,
            TypeError,
            pl.exceptions.PolarsError,
        ):  # número grande demais vira texto, sem arredondar
            return pl.Series(name, [None if v is None else str(v) for v in values], dtype=pl.String)
    if kinds and kinds <= {int, float}:
        return pl.Series(name, [None if v is None else float(v) for v in values], dtype=pl.Float64)
    return pl.Series(name, [None if v is None else _as_str(v) for v in values], dtype=pl.String)


SAMPLE_ITEMS = 3
SAMPLE_FIELDS = 30
SAMPLE_DEPTH = 6
SAMPLE_TEXT = 80


def sample_document(node: Any, path: str = "", depth: int = 0) -> dict[str, Any]:
    """Amostra da resposta para a tela (RF-2225): poucos itens por lista, textos curtos, profundidade limitada."""
    if isinstance(node, dict):
        fields = list(node.items())
        if depth >= SAMPLE_DEPTH:
            return {"kind": "more", "text": f"{len(fields)} campos"}
        shown = [
            [str(k), sample_document(v, f"{path}.{k}" if path else str(k), depth + 1)]
            for k, v in fields[:SAMPLE_FIELDS]
        ]
        return {"kind": "object", "fields": shown, "hidden": max(0, len(fields) - SAMPLE_FIELDS)}
    if isinstance(node, list):
        inner = f"{path}.*" if path else "*"
        items = (
            []
            if depth >= SAMPLE_DEPTH
            else [sample_document(v, inner, depth + 1) for v in node[:SAMPLE_ITEMS]]
        )
        return {"kind": "list", "path": path, "total": len(node), "items": items}
    if isinstance(node, str) and len(node) > SAMPLE_TEXT:
        return {"kind": "value", "value": node[:SAMPLE_TEXT] + "…", "path": path}
    return {"kind": "value", "value": node, "path": path}


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def rows_to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Colunas na ordem em que aparecem; tipos misturados viram texto, para nada se perder."""
    names = list(dict.fromkeys(k for r in rows for k in r))
    return pl.DataFrame([_column(n, [r.get(n) for r in rows]) for n in names])


# ------------------------------------------------------------------ chamada


@dataclass
class ApiResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    # Parou no limite de páginas com mais dados para trazer.
    truncated: bool = False
    # Documento JSON da primeira página: só o editor usa, para mostrar a resposta.
    document: Any = None


@dataclass
class _Response:
    status: int
    headers: httpx.Headers
    body: bytes
    url: str


def _system_tls() -> ssl.SSLContext:
    # Usa os certificados do Windows: em rede corporativa, a autoridade da empresa é reconhecida.
    return ssl.create_default_context()


# Trocado nos testes por um transporte simulado.
_transport: httpx.BaseTransport | None = None


class ApiClient:
    def __init__(
        self,
        definition: ApiDefinition,
        secret: Callable[[str], str | None],
        *,
        pace: Callable[[], None] | None = None,
    ) -> None:
        self.d = definition
        self.secret = secret
        self.pace = pace or (lambda: None)
        self._secrets_seen = [v for s in definition.secret_slots() if (v := secret(s))]
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()
        options: dict[str, Any] = {"timeout": definition.timeout_s, "follow_redirects": False}
        if _transport is not None:
            options["transport"] = _transport
        else:
            options["verify"] = _system_tls()
        self.client = httpx.Client(**options)
        self.origin = ("", "")
        self._budget = definition.max_mb * 1024 * 1024
        self._budget_lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- texto seguro

    def _clean(self, text: str) -> str:
        """Mensagem sem nenhum segredo, venha de onde vier (a API pode devolver o token no erro)."""
        tokens = [*self._secrets_seen, self._token[0] if self._token else ""]
        for value in tokens:
            if value:
                text = text.replace(value, "***")
        return text

    def _shown(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"

    # ---------------------------------------------------------------- autenticação

    def _oauth_token(self, *, renew: bool = False) -> str:
        with self._lock:
            if not renew and self._token and self._token[1] > time.monotonic():
                return self._token[0]
            auth = self.d.auth
            form = {"grant_type": "client_credentials", "client_id": auth.client_id}
            if auth.scope:
                form["scope"] = auth.scope
            form["client_secret"] = self.secret("client_secret") or ""
            try:
                response = self.client.post(auth.token_url, data=form)
            except httpx.HTTPError as exc:
                raise ApiError(self._network_message(exc, auth.token_url)) from None
            if response.status_code >= 400:
                raise ApiError(
                    f"O servidor de autenticação recusou as credenciais (HTTP {response.status_code}). "
                    "Confira o endereço do token, o ID e o segredo do cliente.",
                    response.status_code,
                )
            try:
                data = response.json()
                token = str(data["access_token"])
            except ValueError, KeyError, TypeError:
                raise ApiError("O servidor de autenticação não devolveu um access_token.") from None
            lifetime = data.get("expires_in")
            seconds = float(lifetime) if isinstance(lifetime, int | float) else 3000.0
            self._token = (token, time.monotonic() + max(seconds - 30, 0))
            return token

    def _auth_headers(self, *, renew: bool = False) -> dict[str, str]:
        auth = self.d.auth
        match auth.type:
            case "bearer":
                return {"Authorization": f"Bearer {self.secret('token') or ''}"}
            case "api_key" if auth.key_in == "header":
                return {auth.key_name: self.secret("token") or ""}
            case "basic":
                raw = f"{auth.username}:{self.secret('password') or ''}".encode()
                return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
            case "oauth2":
                return {"Authorization": f"Bearer {self._oauth_token(renew=renew)}"}
        return {}

    def _auth_query(self) -> list[tuple[str, str]]:
        auth = self.d.auth
        if auth.type == "api_key" and auth.key_in == "query":
            return [(auth.key_name, self.secret("token") or "")]
        return []

    # ---------------------------------------------------------------- envio

    def _network_message(self, exc: Exception, url: str) -> str:
        shown = self._shown(url)
        if isinstance(exc, httpx.TimeoutException):
            return f"A API não respondeu em {self.d.timeout_s:g} s ({shown}). Aumente o tempo limite ou tente de novo."
        text = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate" in text.lower():
            return f"O certificado de {urlsplit(url).netloc} não é confiável neste computador. Fale com a TI da empresa."
        if isinstance(exc, httpx.ConnectError):
            return f"Não foi possível conectar em {urlsplit(url).netloc}. Confira o endereço e a rede."
        return f"Falha de rede ao chamar {shown}: {self._clean(text)[:200]}"

    def _read(self, method: str, url: str, headers: dict[str, str], content: bytes | None) -> _Response:
        request = self.client.build_request(method, url, headers=headers, content=content)
        response = self.client.send(request, stream=True)
        try:
            chunks = []
            for chunk in response.iter_bytes():
                with self._budget_lock:
                    self._budget -= len(chunk)
                    over = self._budget < 0
                if over:
                    raise ApiError(
                        f"A resposta passou do limite de {self.d.max_mb} MB desta fonte. Aumente o limite ou filtre a consulta."
                    )
                chunks.append(chunk)
        finally:
            response.close()
        return _Response(response.status_code, response.headers, b"".join(chunks), url)

    def _follow(self, method: str, url: str, headers: dict[str, str], content: bytes | None) -> _Response:
        """Segue redirecionamentos. Fora da origem, cabeçalhos e corpo ficam para trás."""
        first = _origin(url)
        for _ in range(MAX_REDIRECTS + 1):
            answer = self._read(method, url, headers, content)
            location = answer.headers.get("location")
            if answer.status not in (301, 302, 303, 307, 308) or not location:
                return answer
            target = urljoin(url, location)
            if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
                raise ApiError(
                    f"A API redirecionou de https para um endereço sem criptografia ({self._shown(target)})."
                )
            if answer.status in (301, 302, 303) and method != "GET":
                method, content = "GET", None
            if _origin(target) != first:
                headers, content = {}, None
                if method != "GET":
                    raise ApiError(
                        f"A API redirecionou um envio de dados para outro servidor ({urlsplit(target).netloc})."
                    )
            url = target
        raise ApiError("A API redirecionou vezes demais.")

    def _wait(self, attempt: int, headers: httpx.Headers | None) -> None:
        delay = RETRY_BASE_SECONDS * 2**attempt
        after = headers.get("retry-after") if headers else None
        if after:
            try:
                delay = float(after)
            except ValueError:
                with contextlib.suppress(TypeError, ValueError):
                    delay = parsedate_to_datetime(after).timestamp() - time.time()
        time.sleep(min(max(delay, 0), MAX_WAIT_SECONDS))

    def _send(self, url: str, values: dict[str, Any], query: list[tuple[str, str]]) -> _Response:
        d = self.d
        headers = {p.name: self._header_value(p, values) for p in d.headers if p.name}
        content: bytes | None = None
        if d.method == "POST" and d.body.strip():
            if d.body_type == "json":
                try:
                    payload = _fill_json(json.loads(d.body), values)
                except json.JSONDecodeError:
                    raise ApiError("O corpo não é um JSON válido.") from None
                content = json.dumps(payload, ensure_ascii=False, default=str).encode()
                headers.setdefault("Content-Type", "application/json")
            else:
                content = _fill_text(d.body, values).encode()
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        full = _with_query(url, query)
        retry = _RETRY_ALWAYS | (_RETRY_SAFE if d.method == "GET" else set())
        renewed = False
        attempt = 0
        while True:
            self.pace()
            try:
                answer = self._follow(d.method, full, {**headers, **self._auth_headers()}, content)
            except httpx.HTTPError as exc:
                # Num POST, a chamada pode ter chegado: repetir poderia gravar duas vezes.
                if d.method == "GET" and attempt < d.retries and isinstance(exc, httpx.TransportError):
                    self._wait(attempt, None)
                    attempt += 1
                    continue
                raise ApiError(self._network_message(exc, url)) from None
            if answer.status == 401 and d.auth.type == "oauth2" and not renewed:
                renewed = True
                self._oauth_token(renew=True)
                continue
            if answer.status in retry and attempt < d.retries:
                self._wait(attempt, answer.headers)
                attempt += 1
                continue
            if answer.status >= 400:
                raise self._status_error(answer, url)
            return answer

    def _header_value(self, param: ApiParam, values: dict[str, Any]) -> str:
        if param.secret:
            return self.secret(f"header:{param.name}") or ""
        return _fill_header(param.value, values)

    def _status_error(self, answer: _Response, url: str) -> ApiError:
        shown = self._shown(url)
        status = answer.status
        reasons = {
            400: "A API não entendeu o pedido",
            401: "A API recusou as credenciais",
            403: "A API negou o acesso: as credenciais não têm permissão",
            404: "A API não encontrou este endereço",
            429: "A API pediu para diminuir o ritmo e as novas tentativas acabaram",
        }
        reason = reasons.get(status) or (
            "A API falhou do lado dela" if status >= 500 else "A API recusou o pedido"
        )
        detail = self._clean(answer.body[:300].decode("utf-8", "replace")).strip()
        detail = f" Resposta: {detail[:200]}" if detail and not detail.lstrip().startswith("<") else ""
        return ApiError(f"{reason} (HTTP {status}, {shown}).{detail}", status)

    # ---------------------------------------------------------------- páginas

    def _base(self, values: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
        url = _fill_path(self.d.url, values)
        check_url(url)
        query = []
        for p in self.d.params:
            if not p.name:
                continue
            query.append(
                (p.name, self.secret(f"param:{p.name}") or "" if p.secret else _fill_text(p.value, values))
            )
        return url, query + self._auth_query()

    def fetch(self, values: dict[str, Any] | None = None, *, max_pages: int | None = None) -> ApiResult:
        values = values or {}
        d = self.d
        pager = d.pagination
        limit = max_pages or pager.max_pages
        url, query = self._base(values)
        result = ApiResult()
        origin = _origin(url)
        page, offset = pager.start_page, 0
        extra: list[tuple[str, str]] = _first_page(pager)
        seen_cursor: set[str] = set()
        last_digest = ""
        while True:
            answer = self._send(url, values, query + extra)
            digest = hashlib.sha256(answer.body).hexdigest()
            if digest == last_digest:  # o servidor ignora a página pedida e repete a mesma resposta
                return result
            last_digest = digest
            records, document = parse_records(answer.body, answer.headers.get("content-type", ""), d)
            result.rows.extend(records)
            result.pages += 1
            if result.pages == 1:
                result.document = document
            following: str | None = None
            if pager.type == "none":
                return result
            if pager.type in ("page", "offset"):
                if not records:
                    return result
                if (pager.type == "offset" or pager.size_param) and len(records) < pager.page_size:
                    return result
                page += 1
                offset += len(records)
                extra = _next_numbered(pager, page, offset)
            elif pager.type == "cursor":
                cursor = _dig(document, pager.cursor_path)
                if cursor in (None, "", False) or str(cursor) in seen_cursor:
                    return result
                seen_cursor.add(str(cursor))
                extra = [(pager.cursor_param, str(cursor))]
            else:
                following = _next_link(answer, document, pager)
                if not following:
                    return result
                target = urljoin(answer.url, following)
                if _origin(target) != origin:
                    raise ApiError(
                        f"O próximo link da paginação aponta para outro servidor ({urlsplit(target).netloc}): "
                        "as credenciais não são enviadas para lá."
                    )
                url, query, extra = target, self._auth_query_if_missing(target), []
            if result.pages >= limit:
                result.truncated = True
                return result

    def _auth_query_if_missing(self, url: str) -> list[tuple[str, str]]:
        present = {k for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
        return [(k, v) for k, v in self._auth_query() if k not in present]


def _first_page(p: ApiPagination) -> list[tuple[str, str]]:
    return _next_numbered(p, p.start_page, 0)


def _next_numbered(p: ApiPagination, page: int, offset: int) -> list[tuple[str, str]]:
    if p.type == "page":
        size = [(p.size_param, str(p.page_size))] if p.size_param else []
        return [(p.page_param, str(page)), *size]
    if p.type == "offset":
        return [(p.offset_param, str(offset)), (p.limit_param, str(p.page_size))]
    return []


def _next_link(answer: _Response, document: Any, p: ApiPagination) -> str | None:
    if p.next_path:
        found = _dig(document, p.next_path)
        return found if isinstance(found, str) and found else None
    match = _LINK_NEXT.search(answer.headers.get("link", ""))
    return match.group(1) if match else None


def _with_query(url: str, extra: Iterable[tuple[str, str]]) -> str:
    """Soma parâmetros aos que já estão no endereço; o da paginação substitui um igual."""
    parts = urlsplit(url)
    extra = list(extra)
    names = {k for k, _ in extra}
    current = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in names]
    if not extra:
        return url
    return urlunsplit(parts._replace(query=urlencode([*current, *extra])))


def read_api(
    definition: ApiDefinition, secret: Callable[[str], str | None], *, max_pages: int | None = None
) -> tuple[pl.DataFrame, ApiResult]:
    definition.check()
    if needed := definition.placeholders():
        names = ", ".join("{" + n + "}" for n in needed)
        raise ApiError(
            f"Esta API pede {names}: use a ferramenta API Loop, que chama uma vez para cada linha da tabela."
        )
    with ApiClient(definition, secret) as client:
        result = client.fetch(max_pages=max_pages)
    return rows_to_frame(result.rows), result


# ------------------------------------------------------------------ uma chamada por linha


class _Pace:
    """Distribui as chamadas no tempo, somando todas as threads."""

    def __init__(self, per_second: float) -> None:
        self.gap = 1 / per_second if per_second > 0 else 0.0
        self.next = 0.0
        self.lock = threading.Lock()

    def __call__(self) -> None:
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.gap
        if start > now:
            time.sleep(start - now)


LOOP_CALL = "__pd_chamada"


@dataclass
class LoopResult:
    table: pl.DataFrame
    errors: pl.DataFrame
    calls: int
    failed: int
    truncated: int


def run_loop(
    df: pl.DataFrame,
    source: ApiDefinition,
    secret: Callable[[str], str | None],
    *,
    concurrency: int = 4,
    per_second: float = 5,
    max_calls: int = 1000,
    stop_on_error: bool = False,
    keep_columns: bool = True,
    progress: Callable[[int, int], None] | None = None,
    columns: dict[str, str] | None = None,
) -> LoopResult:
    """Chama a API uma vez para cada combinação de valores e junta as respostas às linhas de entrada.

    ``columns`` diz de qual coluna vem cada variável; sem escolha, vale a coluna de mesmo nome.
    """
    source.check()
    wanted = source.placeholders()
    if not wanted:
        raise ApiError(
            "Esta API não pede nenhuma variável: use o Input Data. "
            "Para o endereço mudar a cada chamada, escreva o nome entre chaves nele, como {sigla}."
        )
    origin = {p: (columns or {}).get(p) or p for p in wanted}
    if missing := [p for p in wanted if origin[p] not in df.columns]:
        names = ", ".join("{" + p + "}" for p in missing)
        raise ApiError(
            f"A API pede {names}, mas a tabela de entrada não tem essa coluna. Escolha a coluna no API Loop. "
            f"A tabela traz: {', '.join(df.columns)[:200]}."
        )
    used = list(dict.fromkeys(origin.values()))
    calls = df.select(used).unique(maintain_order=True).with_row_index(LOOP_CALL)
    if calls.height > max_calls:
        raise ApiError(
            f"A tabela pede {calls.height:,} chamadas e o limite desta caixa está em {max_calls:,}. "
            "Filtre a tabela ou aumente o limite, se a API aguentar.".replace(",", ".")
        )
    rows: dict[int, list[dict[str, Any]]] = {}
    errors: dict[int, tuple[str, int | None]] = {}
    truncated = 0
    done = 0
    stop = threading.Event()
    lock = threading.Lock()

    with ApiClient(source, secret, pace=_Pace(per_second)) as client:

        def call(item: dict[str, Any]) -> None:
            nonlocal done, truncated
            index = int(item[LOOP_CALL])
            values = {p: item[origin[p]] for p in wanted}
            try:
                if stop.is_set():
                    return
                if empty := [p for p, v in values.items() if v is None]:
                    raise ApiError(f"Valor vazio em [{origin[empty[0]]}]: a chamada não foi feita.")
                result = client.fetch(values)
                rows[index] = result.rows
                if result.truncated:
                    with lock:
                        truncated += 1
            except ApiError as exc:
                errors[index] = (exc.message, exc.status)
                if stop_on_error:
                    stop.set()
            finally:
                with lock:
                    done += 1
                    if progress:
                        progress(done, calls.height)

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            list(pool.map(call, calls.to_dicts()))
    if stop_on_error and errors:
        first = errors[min(errors)][0]
        raise ApiError(f"O loop parou no primeiro erro: {first}")
    return _loop_tables(df, calls, used, rows, errors, keep_columns, truncated)


def _loop_tables(
    df: pl.DataFrame,
    calls: pl.DataFrame,
    used: list[str],
    rows: dict[int, list[dict[str, Any]]],
    errors: dict[int, tuple[str, int | None]],
    keep_columns: bool,
    truncated: int,
) -> LoopResult:
    position = "__pd_ordem"
    ok_rows = [{LOOP_CALL: i, **r} for i in sorted(rows) for r in rows[i]]
    answered = rows_to_frame(ok_rows) if ok_rows else pl.DataFrame({LOOP_CALL: pl.Series([], dtype=pl.Int64)})
    answered = answered.with_columns(pl.col(LOOP_CALL).cast(pl.UInt32))
    linked = df.join(calls, on=used, how="left", nulls_equal=True, maintain_order="left")
    failed = pl.DataFrame(
        {
            LOOP_CALL: pl.Series(list(errors), dtype=pl.UInt32),
            "erro": pl.Series([e[0] for e in errors.values()], dtype=pl.String),
            "status_http": pl.Series([e[1] for e in errors.values()], dtype=pl.Int64),
        }
    )
    bad = linked.join(failed, on=LOOP_CALL, how="inner", maintain_order="left").drop(LOOP_CALL)
    good = linked.filter(pl.col(LOOP_CALL).is_in(list(rows)))
    if keep_columns:
        clash = {c: f"{c}_api" for c in answered.columns if c in df.columns}
        answered = answered.rename(clash)
    else:
        good = good.select(LOOP_CALL)
    table = (
        good.with_row_index(position)
        .join(answered, on=LOOP_CALL, how="left", maintain_order="left")
        .sort(position, maintain_order=True)
        .drop(position, LOOP_CALL)
    )
    return LoopResult(table, bad, calls.height, len(errors), truncated)


# ------------------------------------------------------------------ cadastro


def secret_key(api_id: str, slot: str) -> str:
    return f"api:{api_id}:{slot}"


class ApiStore:
    def __init__(self, path: Path, secrets: SecretStore) -> None:
        self.path = path
        self.secrets = secrets
        self._lock = threading.Lock()

    def _read(self) -> dict[str, SavedApi]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["id"]: SavedApi.model_validate(item) for item in raw}

    def _write(self, items: dict[str, SavedApi]) -> None:
        tmp = self.path.with_suffix(".tmp")
        data = [a.model_dump(mode="json") for a in sorted(items.values(), key=lambda a: a.name.lower())]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _info(self, api: SavedApi) -> ApiInfo:
        slots = api.secret_slots()
        has = {s for s in slots if self.secrets.get(secret_key(api.id, s))}
        return ApiInfo(
            **api.model_dump(), set_secrets=sorted(has), missing_secrets=[s for s in slots if s not in has]
        )

    def list(self) -> list[ApiInfo]:
        return [self._info(a) for a in self._read().values()]

    def get(self, api_id: str) -> SavedApi:
        api = self._read().get(api_id)
        if api is None:
            raise NotFoundError(f"API não encontrada: {api_id}. Ela foi excluída da aba Dados?")
        return api

    def secret_reader(self, api_id: str, typed: dict[str, str] | None = None) -> Callable[[str], str | None]:
        """Lê o segredo do cofre. ``typed``: digitado agora no editor, ainda não salvo."""

        def read(slot: str) -> str | None:
            if typed and typed.get(slot):
                return typed[slot]
            return self.secrets.get(secret_key(api_id, slot)) if api_id else None

        return read

    def save(self, api: SavedApi, secrets: dict[str, str] | None = None) -> ApiInfo:
        """Salva a definição. Segredo ausente fica como está; vazio remove."""
        api = api.model_copy(
            update={
                "params": [p.model_copy(update={"value": ""}) if p.secret else p for p in api.params],
                "headers": [p.model_copy(update={"value": ""}) if p.secret else p for p in api.headers],
            }
        )
        with self._lock:
            items = self._read()
            before = items.get(api.id)
            items[api.id] = api
            self._write(items)
        slots = api.secret_slots()
        for slot, value in (secrets or {}).items():
            if slot not in slots:
                continue
            if value:
                self.secrets.set(secret_key(api.id, slot), value)
            else:
                self.secrets.delete(secret_key(api.id, slot))
        if before:
            for slot in set(before.secret_slots()) - set(slots):
                self.secrets.delete(secret_key(api.id, slot))
        return self._info(api)

    def delete(self, api_id: str) -> None:
        with self._lock:
            items = self._read()
            api = items.pop(api_id, None)
            if api is None:
                raise NotFoundError(f"API não encontrada: {api_id}")
            self._write(items)
        for slot in api.secret_slots():
            self.secrets.delete(secret_key(api_id, slot))
