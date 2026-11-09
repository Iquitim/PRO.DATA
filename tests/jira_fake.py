"""Jira Cloud simulado (spec 030), no formato das respostas reais da API v3.

Serve aos testes pelo transporte do httpx (`FakeJira.handle`) e ao navegador como servidor local (`python tests/jira_fake.py`).
Reproduz paginação por token, limite com Retry-After, token vencido, token com escopo e histórico em lote.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

CLOUD = "11111111-0000-4000-8000-000000000000"
EMAIL = "ana@exemplo.com"
CLASSIC = "token-comum"
SCOPED = "token-com-escopo"
READ_METHODS = {"GET"}
READ_POSTS = {"/rest/api/3/search/approximate-count", "/rest/api/3/changelog/bulkfetch"}
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
STATUSES = ["A fazer", "Em andamento", "Em revisão", "Concluído"]
TEAMS = ["Plataforma", "Dados", "Atendimento"]


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


class FakeJira:
    def __init__(self, issues: int = 12, *, bulk: bool = True) -> None:
        self.bulk = bulk
        self.rate_limit_next = 0
        self.fail_after: int | None = None  # corta a conexão depois de N chamadas de histórico
        self.valid = True
        self.writes: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.issues = [self._issue(i) for i in range(1, issues + 1)]

    def _issue(self, n: int) -> dict[str, Any]:
        created = START + timedelta(days=n)
        moves = n % 4  # quantas vezes andou no quadro
        history = [
            {
                "id": str(n * 100 + m), "created": stamp(created + timedelta(days=2 * (m + 1))), "author": {"displayName": "Time"},
                "items": [{"field": "status", "fromString": STATUSES[m], "toString": STATUSES[m + 1]}],
            }
            for m in range(moves)
        ]  # fmt: skip
        status = STATUSES[moves]
        return {
            "id": str(10000 + n), "key": f"DEMO-{n}", "changes": history,
            "comments": [{"id": str(n), "author": {"displayName": "Ana"}, "created": stamp(created), "updated": stamp(created), "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"Comentário {n}"}]}]}}],
            "fields": {
                "project": {"key": "DEMO", "name": "Demonstração"}, "issuetype": {"name": "História" if n % 2 else "Bug"},
                "status": {"name": status, "statusCategory": {"name": "Concluído" if status == "Concluído" else "Em andamento"}},
                "priority": {"name": "Alta" if n % 3 == 0 else "Média"}, "summary": f"Demanda {n}", "assignee": {"displayName": TEAMS[n % 3]}, "reporter": {"displayName": "Ana"},
                "created": stamp(created), "updated": stamp(created + timedelta(days=2 * moves)), "resolutiondate": None, "duedate": "2026-12-31",
                "labels": ["a", "b"], "components": [{"name": "Web"}], "parent": None,
                "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Linha um"}, {"type": "hardBreak"}, {"type": "text", "text": "Linha dois"}]}]},
                "customfield_10001": 3 + n, "customfield_10002": {"value": TEAMS[n % 3]},
            },
        }  # fmt: skip

    def touch(self, key: str) -> None:
        """A demanda mudou agora: anda no quadro e entra na busca por alteração."""
        issue = next(i for i in self.issues if i["key"] == key)
        now = datetime.now(UTC)
        issue["fields"]["updated"] = stamp(now)
        issue["fields"]["summary"] = f"{issue['fields']['summary']} (editada)"
        issue["changes"].append({"id": f"{issue['id']}99", "created": stamp(now), "author": {"displayName": "Time"}, "items": [{"field": "status", "fromString": "A fazer", "toString": "Concluído"}]})

    def _authorized(self, auth: str, gateway: bool) -> bool:
        if not self.valid or not auth.startswith("Basic "):
            return False
        email, _, token = base64.b64decode(auth[6:]).decode().partition(":")
        return (email == EMAIL and token == (SCOPED if gateway else CLASSIC)) or (gateway and email == EMAIL and token == CLASSIC)

    def _matching(self, jql: str) -> list[dict[str, Any]]:
        found = self.issues
        since = re.search(r'updated >= "(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"', jql)
        if since:
            limit = datetime.strptime(since.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            found = [i for i in found if datetime.strptime(i["fields"]["updated"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC) >= limit]
        status = re.search(r'status in \(([^)]*)\)', jql)
        if status:
            wanted = re.findall(r'"([^"]+)"', status.group(1))
            found = [i for i in found if i["fields"]["status"]["name"] in wanted]
        return found

    def _search(self, query: dict[str, list[str]]) -> dict[str, Any]:
        jql = query["jql"][0]
        if "ERRO" in jql:
            raise ValueError("JQL")
        found = self._matching(jql)
        size = int(query.get("maxResults", ["50"])[0])
        start = int(query.get("nextPageToken", ["0"])[0])
        page = found[start : start + size]
        wanted = set(query.get("fields", [""])[0].split(","))
        issues = [{"id": i["id"], "key": i["key"], "fields": {k: v for k, v in i["fields"].items() if k in wanted}} for i in page]
        last = start + size >= len(found)
        return {"issues": issues, "isLast": last, **({} if last else {"nextPageToken": str(start + size)})}

    def _bulk(self, body: dict[str, Any]) -> dict[str, Any]:
        wanted = [str(i) for i in body["issueIdsOrKeys"]]
        items = []
        for issue in self.issues:
            if issue["id"] in wanted:
                items.append({"issueId": issue["id"], "changeHistories": [{**c, "created": int(datetime.strptime(c["created"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000)} for c in issue["changes"]]})
        return {"issueChangeLogs": items}

    def answer(self, method: str, url: str, auth: str, body: bytes) -> tuple[int, dict[str, str], Any]:
        parts = urlsplit(url)
        path = parts.path
        query = parse_qs(parts.query)
        self.calls.append((method, path))
        if method not in READ_METHODS and path.split(f"/ex/jira/{CLOUD}")[-1] not in READ_POSTS:
            self.writes.append(f"{method} {path}")
            return 405, {}, {}
        if self.rate_limit_next:
            self.rate_limit_next -= 1
            return 429, {"Retry-After": "1"}, {}
        if path == "/_edge/tenant_info":
            return 200, {}, {"cloudId": CLOUD}
        gateway = path.startswith(f"/ex/jira/{CLOUD}")
        path = path.split(f"/ex/jira/{CLOUD}")[-1]
        if not self._authorized(auth, gateway):
            return 401, {}, {"message": "Client must be authenticated"}
        return self._route(method, path, query, body)

    def _route(self, method: str, path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, dict[str, str], Any]:
        if path == "/rest/api/3/myself":
            return 200, {}, {"displayName": "Ana Souza", "accountId": "abc"}
        if path == "/rest/api/3/project/search":
            return 200, {}, {"values": [{"key": "DEMO", "name": "Demonstração"}, {"key": "OPS", "name": "Operações"}], "isLast": True}
        if path == "/rest/api/3/field":
            return 200, {}, [{"id": "summary", "name": "Resumo", "custom": False}, {"id": "customfield_10001", "name": "Story Points", "custom": True}, {"id": "customfield_10002", "name": "Equipe", "custom": True}]
        if path == "/rest/api/3/status":
            return 200, {}, [{"name": s} for s in STATUSES]
        if path == "/rest/api/3/issuetype":
            return 200, {}, [{"name": "História"}, {"name": "Bug"}]
        if path == "/rest/api/3/search/jql":
            try:
                return 200, {}, self._search(query)
            except ValueError:
                return 400, {}, {"errorMessages": ["Erro de sintaxe no JQL."]}
        if path == "/rest/api/3/search/approximate-count":
            return 200, {}, {"count": len(self._matching(json.loads(body)["jql"]))}
        if path == "/rest/api/3/changelog/bulkfetch":
            if not self.bulk:
                return 404, {}, {}
            if self.fail_after is not None:
                if self.fail_after <= 0:
                    return 503, {}, {}
                self.fail_after -= 1
            return 200, {}, self._bulk(json.loads(body))
        for tail, key in (("changelog", "values"), ("comment", "comments")):
            m = re.fullmatch(rf"/rest/api/3/issue/([^/]+)/{tail}", path)
            if m:
                issue = next(i for i in self.issues if m.group(1) in (i["key"], i["id"]))
                items = issue["changes"] if tail == "changelog" else issue["comments"]
                return 200, {}, {key: items, "total": len(items), "startAt": 0}
        return 404, {}, {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        status, headers, data = self.answer(request.method, str(request.url), request.headers.get("authorization", ""), request.content)
        return httpx.Response(status, headers=headers, json=data)


def serve(port: int, issues: int) -> None:
    """Para as baterias no navegador: PRODATA_JIRA_TEST_BASE=http://127.0.0.1:<port>"""
    fake = FakeJira(issues)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a: Any) -> None:
            pass

        def _reply(self, method: str) -> None:
            size = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(size) if size else b""
            status, headers, data = fake.answer(method, f"http://x{self.path}", self.headers.get("Authorization", ""), body)
            raw = json.dumps(data).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._reply("GET")

        def do_POST(self) -> None:
            self._reply("POST")

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8795, int(sys.argv[2]) if len(sys.argv) > 2 else 120)
