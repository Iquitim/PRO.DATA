"""Fontes de API (spec 021): cadastro, chamada, paginação e leitura da resposta como tabela.

A definição fica em ``storage/apis.json`` sem segredo algum: token, senha e cabeçalhos marcados
como sigilosos vão para o cofre do sistema. Mensagens de erro nunca levam esses valores.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import re
import ssl
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import polars as pl

from prodata.connectors import api_policy
from prodata.connectors.api_model import (
    _PLACEHOLDER,
    ApiDefinition,
    ApiError,
    ApiPagination,
    ApiParam,
    RequestLimitError,
    _origin,
    check_url,
)
from prodata.connectors.api_records import _dig, parse_records, rows_to_frame

# A biblioteca registra cada URL no log em nível INFO, e a URL pode levar a chave da API.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


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


MAX_REDIRECTS = 5
MAX_WAIT_SECONDS = 60.0
RETRY_BASE_SECONDS = 1.0
_LINK_NEXT = re.compile(r'<([^>]+)>\s*;[^,]*rel="?next"?', re.IGNORECASE)
_RETRY_ALWAYS = {429}
_RETRY_SAFE = {502, 503, 504}


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
        request_limit: int | None = None,
    ) -> None:
        self.d = definition
        self.secret = secret
        self.pace = pace or (lambda: None)
        self.request_limit = request_limit
        self.requests = 0
        self._policy = api_policy.load_policy()
        self._destinations: dict[str, api_policy.Destination] = {}
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
        forms: list[str] = []
        for value in filter(None, tokens):
            forms += [value, quote(value, safe=""), base64.b64encode(value.encode()).decode()]
            if self.d.auth.username:
                forms.append(base64.b64encode(f"{self.d.auth.username}:{value}".encode()).decode())
        for form in sorted(set(forms), key=len, reverse=True):
            text = text.replace(form, "***")
        return text

    # ---------------------------------------------------------------- destino

    def _destination(self, url: str) -> api_policy.Destination:
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._destinations:
            self._destinations[host] = api_policy.classify(url, self._policy)
        return self._destinations[host]

    def _check_destination(self, url: str) -> None:
        """Vale para o endereço, para cada redirecionamento, para o token e para a paginação."""
        where = self._destination(url)
        if where.metadata:
            raise ApiError(
                f"{where.host} é um endereço de metadados de nuvem, que pode revelar credenciais da máquina. "
                "O PRO.DATA não chama esse endereço."
            )
        if where.internal and not where.listed:
            raise ApiError(
                f"{where.host} é um endereço da rede interna. APIs internas precisam estar na lista autorizada "
                f"pela TI, em {api_policy.policy_path()}. APIs públicas não precisam de lista."
            )

    def _has_credentials(self) -> bool:
        return self.d.auth.type != "none" or any(p.secret for p in [*self.d.params, *self.d.headers])

    def _check_credentials(self, url: str, what: str = "A credencial") -> None:
        if urlsplit(url).scheme != "http" or not self._has_credentials():
            return
        where = self._destination(url)
        if not (where.loopback or where.listed):
            raise ApiError(
                f"{what} não pode ir por http, sem criptografia: ela viajaria aberta na rede. "
                f"Use https em {where.host}."
            )

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
            self._check_destination(auth.token_url)
            self._check_credentials(auth.token_url, "O segredo do OAuth")
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
        with self._budget_lock:
            if self.request_limit is not None and self.requests >= self.request_limit:
                raise RequestLimitError(
                    f"Chegou ao limite de {self.request_limit} pedidos à API desta caixa. "
                    "Páginas e novas tentativas também contam."
                )
            self.requests += 1
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
            self._check_destination(url)
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
        self._check_credentials(full)
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


# ------------------------------------------------------------------ cadastro
