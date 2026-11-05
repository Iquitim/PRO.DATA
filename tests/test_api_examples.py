"""API pública no fluxo de exemplo e amostra da resposta no editor (spec 022). Nada aqui sai para a rede."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from prodata.config import Settings
from prodata.connectors import api as api_module
from prodata.connectors.api import read_api
from prodata.connectors.api_model import ApiDefinition, ApiError, ApiParam, SavedApi
from prodata.connectors.api_records import sample_document
from prodata.connectors.api_store import ApiStore
from prodata.connectors.secrets import MemorySecretStore
from prodata.desktop import web_link
from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner
from prodata.main import build_services
from prodata.samples.apis import (
    ESTADOS_ID,
    MUNICIPIOS_ID,
    editor_examples,
    refresh_example_docs,
    seed_example_apis,
)
from prodata.samples.workflows import DEMO_WORKFLOW_ID, add_api_section, demo_workflow

API_NODES = {"n_api_estados", "n_api_municipios", "n_api_contagem", "n_api_join", "n_api_chart"}


@pytest.fixture
def serve_notes(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    return calls_to(monkeypatch, lambda _r: httpx.Response(200, json=[]))


def calls_to(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(record))
    return seen


def test_opening_the_demo_calls_nothing(
    runner: WorkflowRunner, demo: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = calls_to(monkeypatch, lambda _r: httpx.Response(200, json=[]))
    report = runner.run(demo, hold_exports=True)
    assert seen == []
    assert report.node_results["n_api_estados"].status == "skipped"
    assert "Executar" in (report.node_results["n_api_estados"].error or "")
    assert report.node_results["n_api_chart"].status == "skipped"
    others = {k: v.status for k, v in report.node_results.items() if k not in API_NODES and k != "n_output"}
    assert set(others.values()) == {"executed"}, others


def test_running_the_demo_uses_the_api(runner: WorkflowRunner, demo: Workflow) -> None:
    report = runner.run(demo)
    bad = {k: (v.status, v.error) for k, v in report.node_results.items() if v.status != "executed"}
    assert not bad
    assert report.node_results["n_api_municipios"].extra["api_calls"] == 11
    counted = runner.cache.get(demo.id, "n_api_contagem").tables["out"]
    assert set(counted["municipios"].to_list()) == {3}
    chart = next(w for w in report.bi_widgets if w["node_id"] == "n_api_chart")
    assert {s["label"] for s in chart["series"]} >= {"Sudeste", "Sul"}


def test_without_network_only_the_api_step_fails(
    runner: WorkflowRunner, demo: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    calls_to(monkeypatch, offline)
    monkeypatch.setattr(api_module, "RETRY_BASE_SECONDS", 0)
    report = runner.run(demo)
    source = report.node_results["n_api_estados"]
    assert source.status == "error" and "Não foi possível conectar" in (source.error or "")
    for node in API_NODES - {"n_api_estados"}:
        assert report.node_results[node].status == "skipped"
    others = {k: v.status for k, v in report.node_results.items() if k not in API_NODES}
    assert set(others.values()) == {"executed"}, others


def test_dashboard_page_does_not_depend_on_the_api() -> None:
    dashboard = demo_workflow()["dashboard"]
    assert "n_api_chart" in dashboard["hidden"]
    assert not any(i.get("node_id") == "n_api_chart" for i in dashboard["items"])


def test_hold_is_an_option_of_any_api(tmp_path: Path, runner: WorkflowRunner) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf",
            "name": "x",
            "nodes": [{"id": "a", "type": "io.input_data", "label": "A", "config": {"dataset": "api:livre"}}],
            "edges": [],
        }
    )
    store = runner.apis
    assert store is not None
    store.save(SavedApi(id="livre", name="L", url="https://servicodados.ibge.gov.br/x/estados"))
    assert runner.run(flow, hold_exports=True).node_results["a"].status == "executed"
    store.save(
        SavedApi(id="livre", name="L", url="https://servicodados.ibge.gov.br/x/estados", hold_on_open=True)
    )
    assert runner.run(flow, hold_exports=True).node_results["a"].status == "skipped"
    assert runner.run(flow).node_results["a"].status == "executed"


def test_saved_demo_receives_the_step_and_keeps_changes(settings: Settings) -> None:
    services = build_services(settings)
    old = demo_workflow()
    old["nodes"] = [n for n in old["nodes"] if n["id"] not in API_NODES]
    old["edges"] = [e for e in old["edges"] if not e["id"].startswith("e_api")]
    old["containers"] = [c for c in old["containers"] if c["id"] != "c_api"]
    old["dashboard"]["hidden"] = []
    old["name"] = "Minha demonstração"
    next(n for n in old["nodes"] if n["id"] == "n_kpi")["y"] = 900
    services.workflows.save(Workflow.model_validate(old))

    again = build_services(settings)
    upgraded = again.workflows.get(DEMO_WORKFLOW_ID)
    ids = {n.id for n in upgraded.nodes}
    assert upgraded.name == "Minha demonstração" and ids >= API_NODES
    assert upgraded.node("n_kpi").y == 900
    assert upgraded.node("n_api_estados").y > 900  # não cobre o que o usuário moveu
    assert {a.id for a in again.apis.list()} >= {ESTADOS_ID, MUNICIPIOS_ID}

    assert build_services(settings).workflows.get(DEMO_WORKFLOW_ID).node("n_kpi").y == 900


def test_section_is_added_once_and_needs_the_join() -> None:
    complete = demo_workflow()
    assert add_api_section(complete) is False
    assert add_api_section({"nodes": [{"id": "x", "y": 0}], "edges": []}) is False


def test_seed_keeps_what_the_user_changed(tmp_path: Path) -> None:
    store = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    store.save(SavedApi(id=ESTADOS_ID, name="Meu nome", url="https://exemplo.com/x"))
    seed_example_apis(store)
    assert store.get(ESTADOS_ID).name == "Meu nome"
    assert store.get(MUNICIPIOS_ID).placeholders() == ["sigla"]


def test_examples_have_no_secret_and_are_valid() -> None:
    examples = editor_examples()
    assert len(examples) >= 4
    for example in examples:
        definition = ApiDefinition.model_validate(example["source"])
        definition.check()
        assert definition.url.startswith("https://")
        assert definition.secret_slots() == []
        assert set(definition.placeholders()) == set(example["values"])


def test_examples_route_calls_nothing(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = calls_to(monkeypatch, lambda _r: httpx.Response(200, json=[]))
    assert client.get("/api/apis/examples").status_code == 200
    assert seen == []


def test_fresh_install_has_the_example_apis(client: Any) -> None:
    listing = client.get("/api/apis").json()
    assert {a["id"] for a in listing} >= {ESTADOS_ID, MUNICIPIOS_ID}
    assert all(a["missing_secrets"] == [] for a in listing)
    demo = client.get("/api/workflows/demo").json()
    assert demo["dashboard"]["hidden"] == ["n_api_chart"]


# ------------------------------------------------------------------ amostra da resposta


def test_sample_describes_lists_with_their_paths() -> None:
    document = {"meta": {"total": 2}, "data": {"itens": [{"id": 1, "tags": ["a"]}, {"id": 2, "tags": []}]}}
    sample = sample_document(document)
    fields = dict(sample["fields"])
    itens = dict(fields["data"]["fields"])["itens"]
    assert itens["kind"] == "list" and itens["path"] == "data.itens" and itens["total"] == 2
    tags = dict(itens["items"][0]["fields"])["tags"]
    assert tags["path"] == "data.itens.*.tags"


def test_sample_is_cut_in_size() -> None:
    big = {"lista": [{"txt": "x" * 500, **{f"c{i}": i for i in range(50)}} for _ in range(1000)]}
    sample = sample_document(big)
    lista = dict(sample["fields"])["lista"]
    assert lista["total"] == 1000 and len(lista["items"]) == 3
    first = lista["items"][0]
    assert len(first["fields"]) == 30 and first["hidden"] == 21
    assert len(dict(first["fields"])["txt"]["value"]) <= 81


def test_sample_stops_at_a_depth() -> None:
    node: Any = {"v": 1}
    for _ in range(20):
        node = {"a": node}
    text = str(sample_document(node))
    assert "'kind': 'more'" in text


def test_preview_returns_the_sample_and_nothing_is_stored(
    client: Any, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls_to(
        monkeypatch, lambda _r: httpx.Response(200, json={"items": [{"cpf": "segredo-na-resposta"}], "n": 1})
    )
    body = {"definition": {"url": "https://exemplo.com/x"}}
    res = client.post("/api/apis/preview", json=body).json()
    assert res["sample"]["kind"] == "object" and res["rows"] == [{"cpf": "segredo-na-resposta"}]
    stored = [p for p in Path(settings.storage_dir).rglob("*") if p.is_file()]
    assert not any("segredo-na-resposta" in p.read_text(encoding="utf-8", errors="ignore") for p in stored)


def test_preview_of_csv_has_no_tree(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls_to(
        monkeypatch, lambda _r: httpx.Response(200, text="a,b\n1,2\n", headers={"content-type": "text/csv"})
    )
    res = client.post("/api/apis/preview", json={"definition": {"url": "https://exemplo.com/x"}}).json()
    assert res["sample"] is None and res["total"] == 1


# ------------------------------------------------------------------ documentação e anotações (spec 024)


def test_docs_and_notes_do_not_go_in_the_request(serve_notes: Any) -> None:
    definition = ApiDefinition(
        url="https://exemplo.com/x",
        docs_url="https://exemplo.com/docs",
        params=[ApiParam(name="a", value="1", note="anotação interna")],
    )
    read_api(definition, lambda _s: None)
    assert len(serve_notes) == 1
    assert "docs" not in str(serve_notes[0].url) and "anota" not in str(serve_notes[0].url)
    assert str(serve_notes[0].url).endswith("?a=1")


def test_docs_and_notes_do_not_invalidate_results() -> None:
    plain = SavedApi(id="a", name="A", url="https://x.com/y", params=[ApiParam(name="p", value="1")])
    noted = SavedApi(
        id="a",
        name="A",
        url="https://x.com/y",
        params=[ApiParam(name="p", value="1", note="serve para isso")],
        docs_url="https://x.com/docs",
    )
    assert plain.digest() == noted.digest()
    changed = SavedApi(id="a", name="A", url="https://x.com/y", params=[ApiParam(name="p", value="2")])
    assert plain.digest() != changed.digest()


@pytest.mark.parametrize(
    "bad", ["javascript:alert(1)", "file:///c:/x", "docs.exemplo.com", "https://u:s@exemplo.com/"]
)
def test_docs_link_must_be_a_web_page(bad: str) -> None:
    with pytest.raises(ApiError):
        ApiDefinition(url="https://exemplo.com/x", docs_url=bad).check()


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://exemplo.com/docs", True),
        ("http://exemplo.com/docs", True),
        ("javascript:alert(1)", False),
        ("file:///c:/windows/system32/calc.exe", False),
        ("C:\\Windows\\calc.exe", False),
        ("https://u:s@exemplo.com/", False),
        ("", False),
    ],
)
def test_only_web_pages_open_outside(url: str, ok: bool) -> None:
    assert bool(web_link(url)) is ok


def test_notes_are_saved_and_examples_have_docs(tmp_path: Path) -> None:
    store = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    seed_example_apis(store)
    saved = store.get(ESTADOS_ID)
    assert saved.docs_url.startswith("https://") and saved.params[0].note
    assert all(ApiDefinition.model_validate(e["source"]).docs_url for e in editor_examples())


def test_old_examples_receive_docs_and_keep_changes(tmp_path: Path) -> None:
    store = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    store.save(
        SavedApi(
            id=ESTADOS_ID,
            name="Meu nome",
            url="https://servicodados.ibge.gov.br/api/v1/localidades/estados",
            params=[ApiParam(name="orderBy", value="id", note="minha nota")],
        )
    )
    digest = store.get(ESTADOS_ID).digest()
    refresh_example_docs(store)
    updated = store.get(ESTADOS_ID)
    assert updated.docs_url and updated.name == "Meu nome"
    assert updated.params[0].value == "id" and updated.params[0].note == "minha nota"
    assert updated.digest() == digest


def test_refresh_does_not_bring_back_a_deleted_example(tmp_path: Path) -> None:
    store = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    refresh_example_docs(store)
    assert store.list() == []
