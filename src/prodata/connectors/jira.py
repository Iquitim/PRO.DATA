"""Cliente do Jira Cloud (spec 030): só lê, e toda chamada passa por um único lugar.

O token comum funciona no endereço do site; o token com escopo só funciona em api.atlassian.com, com o ``cloudId``.
A conexão tenta os dois e guarda qual serviu. Limites de chamada respeitam o ``Retry-After``.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from prodata.connectors.api import _system_tls
from prodata.errors import InvalidInputError, ProdataError

log = logging.getLogger(__name__)

GATEWAY = "https://api.atlassian.com/ex/jira"
PAGE = 100
HISTORY_BATCH = 1000
MAX_ATTEMPTS = 6
MAX_WAIT = 90.0
TEST_BASE_ENV = "PRODATA_JIRA_TEST_BASE"  # só fora do executável: aponta para o Jira simulado dos testes

# As únicas rotas que o conector pode chamar. POST aqui é consulta: o Jira usa POST para perguntas longas.
READ_ONLY = (
    ("GET", re.compile(r"^/rest/api/3/myself$")),
    ("GET", re.compile(r"^/rest/api/3/project/search$")),
    ("GET", re.compile(r"^/rest/api/3/project/[^/]+/statuses$")),
    ("GET", re.compile(r"^/rest/api/3/field$")),
    ("GET", re.compile(r"^/rest/api/3/status$")),
    ("GET", re.compile(r"^/rest/api/3/issuetype$")),
    ("GET", re.compile(r"^/rest/api/3/search/jql$")),
    ("GET", re.compile(r"^/rest/api/3/issue/[^/]+/changelog$")),
    ("GET", re.compile(r"^/rest/api/3/issue/[^/]+/comment$")),
    ("POST", re.compile(r"^/rest/api/3/search/approximate-count$")),
    ("POST", re.compile(r"^/rest/api/3/changelog/bulkfetch$")),
)

# Trocado nos testes por um transporte simulado.
_transport: httpx.BaseTransport | None = None


class JiraError(ProdataError):
    """Erro já em português, pronto para a tela."""


class JiraAuthError(JiraError):
    """Token vencido, revogado ou e-mail errado."""


def assert_read_only(method: str, path: str) -> None:
    if not any(m == method and p.match(path) for m, p in READ_ONLY):
        raise JiraError(f"O conector do Jira só lê: {method} {path} não é permitido.")


@dataclass
class Identity:
    display_name: str
    account_id: str
    token_kind: str  # "comum" ou "com escopo"


def _test_base() -> str | None:
    return None if getattr(sys, "frozen", False) else os.environ.get(TEST_BASE_ENV)


class JiraClient:
    def __init__(
        self,
        site: str,
        email: str,
        token: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        report: Callable[[str], None] = lambda _t: None,
    ) -> None:
        if not email or not token:
            raise JiraAuthError("Falta o e-mail ou o token desta conexão: cadastre de novo na vista Dados.")
        self.site = site
        self._sleep = sleep
        self.report = report
        self.calls = 0
        credential = base64.b64encode(f"{email}:{token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {credential}", "Accept": "application/json"}
        self._client = httpx.Client(
            timeout=60, verify=_system_tls(), transport=_transport, follow_redirects=False
        )
        self._base: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JiraClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _site_base(self) -> str:
        return _test_base() or f"https://{self.site}"

    def _gateway_base(self, cloud_id: str) -> str:
        test = _test_base()
        return f"{test}/ex/jira/{cloud_id}" if test else f"{GATEWAY}/{cloud_id}"

    def _send(self, method: str, url: str, **kw: Any) -> httpx.Response:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.calls += 1
            try:
                res = self._client.request(method, url, headers=self._headers, **kw)
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise JiraError(
                        "Não foi possível falar com o Jira. Confira a internet e tente de novo."
                    ) from exc
                self._sleep(min(2.0**attempt, MAX_WAIT))
                continue
            if res.status_code != 429 and res.status_code < 500:
                return res
            if attempt == MAX_ATTEMPTS:
                break
            wait = self._retry_after(res, attempt)
            self.report(f"O Jira pediu para aguardar {wait:.0f} s")
            self._sleep(wait)
        raise JiraError("O Jira não respondeu depois de várias tentativas. Tente de novo em alguns minutos.")

    @staticmethod
    def _retry_after(res: httpx.Response, attempt: int) -> float:
        try:
            told = float(res.headers.get("Retry-After", ""))
        except ValueError:
            told = 0.0
        return min(max(told, 2.0**attempt), MAX_WAIT)

    def connect(self) -> Identity:
        """Testa o token nos dois endereços e fixa o que serviu."""
        path = "/rest/api/3/myself"
        res = self._send("GET", self._site_base() + path)
        kind = "comum"
        base = self._site_base()
        if res.status_code in (401, 403, 404):
            info = self._send("GET", self._site_base() + "/_edge/tenant_info")
            cloud = info.json().get("cloudId") if info.status_code == 200 else None
            if cloud:
                base = self._gateway_base(cloud)
                res = self._send("GET", base + path)
                kind = "com escopo"
        if res.status_code in (401, 403):
            raise JiraAuthError(
                "O Jira não aceitou o e-mail e o token. O token pode ter vencido: crie outro."
            )
        if res.status_code != 200:
            raise JiraError(f"O Jira respondeu {res.status_code} ao conectar. Confira o endereço.")
        self._base = base
        data = res.json()
        return Identity(str(data.get("displayName") or ""), str(data.get("accountId") or ""), kind)

    def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        assert_read_only(method, path)
        if self._base is None:
            self.connect()
        return self._send(method, f"{self._base}{path}", **kw)

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        res = self._call(method, path, **kw)
        if res.status_code in (401, 403):
            raise JiraAuthError(
                "O Jira recusou o acesso. O token pode ter vencido ou não ter permissão de leitura."
            )
        if res.status_code == 400:
            messages = "; ".join(res.json().get("errorMessages", [])) if res.content else ""
            raise InvalidInputError(f"O Jira recusou a consulta: {messages or 'JQL inválido.'}")
        if res.status_code != 200:
            raise JiraError(f"O Jira respondeu {res.status_code} em {path}.")
        return res.json()

    # ------------------------------------------------------------------ catálogo

    def projects(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self._json(
                "GET", "/rest/api/3/project/search", params={"startAt": start, "maxResults": 50}
            )
            found += page.get("values", [])
            if page.get("isLast", True) or not page.get("values"):
                return found
            start += len(page["values"])

    def fields(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/rest/api/3/field"))

    def statuses(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/rest/api/3/status"))

    def project_statuses(self, key: str) -> list[dict[str, Any]]:
        """Um item por tipo de demanda do projeto, cada um com os seus status."""
        return list(self._json("GET", f"/rest/api/3/project/{quote(key, safe='')}/statuses"))

    def issue_types(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/rest/api/3/issuetype"))

    # ------------------------------------------------------------------ busca

    def count(self, jql: str) -> int:
        return int(
            self._json("POST", "/rest/api/3/search/approximate-count", json={"jql": jql}).get("count", 0)
        )

    def search_pages(
        self, jql: str, fields: list[str], *, token: str | None = None, size: int = PAGE
    ) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
        """Uma página por vez, com o token da próxima (None na última)."""
        while True:
            params: dict[str, Any] = {"jql": jql, "maxResults": size, "fields": ",".join(fields)}
            if token:
                params["nextPageToken"] = token
            page = self._json("GET", "/rest/api/3/search/jql", params=params)
            token = page.get("nextPageToken")
            yield page.get("issues", []), token if not page.get("isLast", not token) else None
            if page.get("isLast", not token) or not token:
                return

    # ------------------------------------------------------------------ histórico e comentários

    def changelogs(self, issue_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Histórico de cada demanda, em lote. Se o endpoint em lote sair do ar, vai demanda por demanda."""
        found: dict[str, list[dict[str, Any]]] = {i: [] for i in issue_ids}
        token: str | None = None
        while True:
            body: dict[str, Any] = {"issueIdsOrKeys": issue_ids, "maxResults": HISTORY_BATCH}
            if token:
                body["nextPageToken"] = token
            res = self._call("POST", "/rest/api/3/changelog/bulkfetch", json=body)
            if res.status_code in (404, 405, 410):
                log.info("Histórico em lote indisponível (%s): lendo uma demanda por vez", res.status_code)
                return {i: self.changelog_of(i) for i in issue_ids}
            if res.status_code in (401, 403):
                raise JiraAuthError(
                    "O Jira recusou o histórico. O token precisa da permissão de leitura de demandas."
                )
            if res.status_code != 200:
                raise JiraError(f"O Jira respondeu {res.status_code} ao buscar o histórico.")
            page = res.json()
            for item in page.get("issueChangeLogs", []):
                found.setdefault(str(item.get("issueId")), []).extend(item.get("changeHistories", []))
            token = page.get("nextPageToken")
            if not token:
                return found

    def changelog_of(self, issue: str) -> list[dict[str, Any]]:
        return self._paged(f"/rest/api/3/issue/{issue}/changelog", "values")

    def comments_of(self, issue: str) -> list[dict[str, Any]]:
        return self._paged(f"/rest/api/3/issue/{issue}/comment", "comments")

    def _paged(self, path: str, key: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        while True:
            page = self._json("GET", path, params={"startAt": len(found), "maxResults": PAGE})
            items = page.get(key, [])
            found += items
            if not items or len(found) >= int(page.get("total", len(found))):
                return found
