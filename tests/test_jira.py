"""Conector do Jira (spec 030), contra o Jira simulado."""

from __future__ import annotations

import base64
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from jira_fake import CLASSIC, EMAIL, SCOPED, FakeJira
from prodata.connectors import jira as jira_module
from prodata.connectors import jira_read
from prodata.connectors.jira import JiraAuthError, JiraClient, JiraError, assert_read_only
from prodata.connectors.jira_model import (
    JiraConnection,
    JiraQuery,
    normalize_site,
)
from prodata.connectors.jira_read import adf_text, to_local
from prodata.connectors.jira_store import JiraStore
from prodata.connectors.secrets import MemorySecretStore
from prodata.errors import InvalidInputError


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeJira]:
    jira = FakeJira(12)
    monkeypatch.setattr(jira_module, "_transport", httpx.MockTransport(jira.handle))
    yield jira


@pytest.fixture
def store(tmp_path: Path, fake: FakeJira) -> JiraStore:
    s = JiraStore(tmp_path / "jira", MemorySecretStore())
    s.save_connection(JiraConnection(id="c", name="Empresa", site="empresa.atlassian.net"), EMAIL, CLASSIC)
    return s


def query(table: str = "issues", **kw: Any) -> JiraQuery:
    return JiraQuery(id="q", name="Consulta", connection="c", table=table, projects=["DEMO"], **kw)  # type: ignore[arg-type]


def no_sleep(_s: float) -> None:
    pass


@pytest.mark.parametrize("text", ["empresa.atlassian.net", "https://empresa.atlassian.net/jira/software/projects/X/boards/1", "EMPRESA", " empresa.atlassian.net/ "])
def test_site_accepts_how_people_paste_it(text: str) -> None:
    assert normalize_site(text) == "empresa.atlassian.net"


@pytest.mark.parametrize("text", ["https://evil.com", "169.254.169.254", "empresa.atlassian.net.evil.com", ""])
def test_site_refuses_anything_that_is_not_jira_cloud(text: str) -> None:
    with pytest.raises(InvalidInputError):
        normalize_site(text)


def test_filters_become_jql() -> None:
    q = query(issue_types=["Bug"], statuses=['Em "teste"'], period_field="updated", period_days=90)
    assert q.to_jql() == 'project in ("DEMO") AND issuetype in ("Bug") AND status in ("Em \\"teste\\"") AND updated >= -90d ORDER BY created ASC'


def test_query_without_limit_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="ao menos um projeto"):
        JiraQuery(id="q", name="x", connection="c").to_jql()


def test_changed_since_keeps_the_filter_and_drops_the_order() -> None:
    jql = JiraQuery(id="q", name="x", connection="c", advanced=True, jql="project = X OR project = Y ORDER BY rank").changed_since("2026-01-02 10:00")
    assert jql == '(project = X OR project = Y) AND updated >= "2026-01-02 10:00" ORDER BY updated ASC'


def test_classic_token_connects_on_the_site(fake: FakeJira) -> None:
    with JiraClient("empresa.atlassian.net", EMAIL, CLASSIC) as c:
        who = c.connect()
    assert (who.display_name, who.token_kind) == ("Ana Souza", "comum")


def test_scoped_token_finds_the_gateway_alone(fake: FakeJira) -> None:
    with JiraClient("empresa.atlassian.net", EMAIL, SCOPED) as c:
        assert c.connect().token_kind == "com escopo"
        assert len(c.projects()) == 2


def test_wrong_token_is_explained(fake: FakeJira) -> None:
    with JiraClient("empresa.atlassian.net", EMAIL, "errado") as c, pytest.raises(JiraAuthError, match="vencido"):
        c.connect()


@pytest.mark.parametrize(("method", "path"), [("POST", "/rest/api/3/issue"), ("PUT", "/rest/api/3/issue/X-1"), ("DELETE", "/rest/api/3/issue/X-1"), ("POST", "/rest/api/3/issue/X-1/comment"), ("POST", "/rest/api/3/issue/X-1/transitions"), ("POST", "/rest/api/3/search/jql")])
def test_only_read_routes_can_be_called(method: str, path: str) -> None:
    with pytest.raises(JiraError, match="só lê"):
        assert_read_only(method, path)


def test_a_full_load_never_writes(store: JiraStore, fake: FakeJira) -> None:
    for table in ("issues", "history", "comments"):
        jira_read.load(query(table), store)
    assert fake.writes == []


def test_rate_limit_waits_as_told(fake: FakeJira) -> None:
    waits: list[float] = []
    fake.rate_limit_next = 2
    with JiraClient("empresa.atlassian.net", EMAIL, CLASSIC, sleep=waits.append) as c:
        c.connect()
    assert len(waits) == 2 and all(w >= 1 for w in waits)


def test_gives_up_with_a_clear_message(fake: FakeJira) -> None:
    fake.rate_limit_next = 99
    with JiraClient("empresa.atlassian.net", EMAIL, CLASSIC, sleep=no_sleep) as c, pytest.raises(JiraError, match="várias tentativas"):
        c.connect()


def test_issues_become_columns(store: JiraStore) -> None:
    frame, info = jira_read.load(query(fields=["customfield_10001", "customfield_10002"]), store)
    assert frame.height == 12 and not info["incremental"]
    row = frame.filter(pl.col("chave") == "DEMO-1").row(0, named=True)
    assert row["status"] == "Em andamento" and row["responsavel"] == "Dados" and row["rotulos"] == "a, b" and row["componentes"] == "Web"
    assert row["descricao"] == "Linha um\nLinha dois"
    assert isinstance(row["criado_em"], datetime)
    assert row["Story Points"] == "4" and row["Equipe"] == "Dados"


def test_pages_are_followed(store: JiraStore, fake: FakeJira) -> None:
    fake.issues = [fake._issue(i) for i in range(1, 251)]
    frame, _ = jira_read.load(query(), store)
    assert frame.height == 250 and frame["chave"].n_unique() == 250
    assert sum(1 for m, p in fake.calls if p.endswith("/search/jql")) == 3


def test_history_has_one_row_per_change(store: JiraStore) -> None:
    frame, _ = jira_read.load(query("history"), store)
    assert frame.columns == ["chave", "mudanca_id", "quando", "autor", "campo", "de", "para"]
    three = frame.filter(pl.col("chave") == "DEMO-3").sort("quando")
    assert three["para"].to_list() == ["Em andamento", "Em revisão", "Concluído"]
    assert frame.filter(pl.col("chave") == "DEMO-4").is_empty()


def test_history_falls_back_one_issue_at_a_time(store: JiraStore, fake: FakeJira) -> None:
    bulk, _ = jira_read.load(query("history"), store)
    store.forget("q")
    fake.bulk = False
    single, _ = jira_read.load(query("history"), store)
    assert bulk.sort("mudanca_id")["para"].to_list() == single.sort("mudanca_id")["para"].to_list()
    assert any("/changelog" in p and "bulk" not in p for _, p in fake.calls)


def test_comments_are_plain_text(store: JiraStore) -> None:
    frame, _ = jira_read.load(query("comments"), store)
    assert frame.filter(pl.col("chave") == "DEMO-2")["texto"].to_list() == ["Comentário 2"]


def test_second_load_only_asks_what_changed(store: JiraStore, fake: FakeJira) -> None:
    first, _ = jira_read.load(query(), store)
    fake.calls.clear()
    second, info = jira_read.load(query(), store)
    assert info["incremental"] and second.height == first.height
    assert sum(1 for _, p in fake.calls if p.endswith("/search/jql")) == 1


def test_incremental_replaces_what_changed(store: JiraStore, fake: FakeJira) -> None:
    jira_read.load(query(), store)
    fake.touch("DEMO-2")
    frame, _ = jira_read.load(query(), store)
    assert frame.height == 12 and frame.filter(pl.col("chave") == "DEMO-2")["resumo"].item().endswith("(editada)")


def test_incremental_history_adds_the_new_change(store: JiraStore, fake: FakeJira) -> None:
    before, _ = jira_read.load(query("history"), store)
    fake.touch("DEMO-3")
    after, _ = jira_read.load(query("history"), store)
    assert after.height == before.height + 1 and after.filter(pl.col("chave") == "DEMO-3").height == 4


def test_deleted_issue_goes_away_only_on_full_reload(store: JiraStore, fake: FakeJira) -> None:
    jira_read.load(query(), store)
    fake.issues = [i for i in fake.issues if i["key"] != "DEMO-5"]
    assert jira_read.load(query(), store)[0].height == 12
    assert jira_read.load(query(), store, full=True)[0].height == 11


def test_changing_the_query_invalidates_the_local_copy(store: JiraStore) -> None:
    jira_read.load(query(), store)
    _, info = jira_read.load(query(statuses=["Concluído"]), store)
    assert not info["incremental"]


def test_interrupted_load_resumes_and_matches_a_full_one(store: JiraStore, fake: FakeJira, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.issues = [fake._issue(i) for i in range(1, 451)]
    monkeypatch.setattr(jira_module.time, "sleep", no_sleep)
    fake.fail_after = 1  # primeiro lote passa, o segundo cai
    with pytest.raises(JiraError):
        jira_read.load(query("history"), store)
    assert jira_read.status(query("history"), store)["interrupted"]
    fake.fail_after = None
    fake.calls.clear()
    resumed, _ = jira_read.load(query("history"), store)
    assert sum(1 for _, p in fake.calls if p.endswith("bulkfetch")) == 2  # só o que faltava: 450 demandas em lotes de 200
    store.forget("q")
    whole, _ = jira_read.load(query("history"), store)
    assert resumed.sort("mudanca_id").equals(whole.sort("mudanca_id"))


def test_token_never_reaches_a_file(store: JiraStore, tmp_path: Path) -> None:
    jira_read.load(query("history"), store)
    token = base64.b64encode(f"{EMAIL}:{CLASSIC}".encode())
    for path in (tmp_path / "jira").rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert CLASSIC.encode() not in data and EMAIL.encode() not in data and token not in data, path


def test_dates_keep_the_moment() -> None:
    a = to_local("2026-01-01T12:00:00.000+0000")
    b = to_local("2026-01-01T09:00:00.000-0300")
    c = to_local(int(datetime.fromisoformat("2026-01-01T12:00:00+00:00").timestamp() * 1000))
    assert a == b == c
    assert to_local(None) is None


def test_document_format_becomes_text() -> None:
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Oi "}, {"type": "mention", "attrs": {"text": "@Ana"}}]}, {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item"}]}]}]}]}
    assert adf_text(doc).split() == ["Oi", "@Ana", "item"]


# ---------------------------------------------------------------- rotas e fluxo


@pytest.fixture
def api(client: TestClient, fake: FakeJira) -> TestClient:
    save = client.put("/api/jira/connections/c", json={"connection": {"id": "c", "name": "Empresa", "site": "empresa.atlassian.net"}, "email": EMAIL, "token": CLASSIC})
    assert save.status_code == 200, save.text
    return client


def test_routes_never_return_the_token(api: TestClient) -> None:
    listed = api.get("/api/jira/connections").json()
    assert listed[0]["has_token"] and CLASSIC not in str(listed)


def test_connection_test_says_who_and_how_many(api: TestClient) -> None:
    res = api.post("/api/jira/test", json={"site": "https://empresa.atlassian.net/x", "id": "c"}).json()
    assert res == {"display_name": "Ana Souza", "token_kind": "comum", "projects": 2, "site": "empresa.atlassian.net"}


def test_preview_shows_lines_total_and_jql(api: TestClient) -> None:
    res = api.post("/api/jira/queries/preview", json={"connection": "c", "projects": ["DEMO"]}).json()
    assert res["total"] == 12 and len(res["rows"]) == 12 and res["jql"].startswith("project in")


def test_invalid_jql_is_explained(api: TestClient) -> None:
    res = api.post("/api/jira/queries/preview", json={"connection": "c", "advanced": True, "jql": "ERRO ="})
    assert res.status_code == 400 and "sintaxe" in res.text


def test_input_data_reads_a_jira_query(api: TestClient) -> None:
    body = {"id": "q", "name": "Demandas", "connection": "c", "projects": ["DEMO"]}
    assert api.put("/api/jira/queries/q", json=body).status_code == 200
    flow = {"id": "j", "name": "Jira", "nodes": [{"id": "i", "type": "io.input_data", "config": {"dataset": "jira:q"}}], "edges": []}
    result = api.post("/api/execute", json={"workflow": flow}).json()["node_results"]["i"]
    assert result["status"] == "executed", result.get("error")
    assert result["anchors"]["out"]["row_count"] == 12 and result["extra"]["source"] == "Demandas"


def test_opening_a_flow_does_not_call_jira(api: TestClient, fake: FakeJira) -> None:
    api.put("/api/jira/queries/q", json={"id": "q", "name": "D", "connection": "c", "projects": ["DEMO"]})
    fake.calls.clear()
    flow = {"id": "j2", "name": "Jira", "nodes": [{"id": "i", "type": "io.input_data", "config": {"dataset": "jira:q"}}], "edges": []}
    report = api.post("/api/execute", json={"workflow": flow, "hold_exports": True}).json()
    assert report["node_results"]["i"]["status"] != "executed"
    assert not any(p.endswith("/search/jql") for _, p in fake.calls)
