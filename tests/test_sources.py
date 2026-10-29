"""Spec 009: consultas da aba Dados no Input Data, pasta de destino e fluxos em qualquer pasta."""

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.connectors import Connection, ConnectionStore, MemorySecretStore, sql
from prodata.connectors.queries import QueryStore, SavedQuery
from prodata.domain.workflow import Workflow
from prodata.errors import InvalidInputError, NotFoundError
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

PG = Connection(id="dw", name="DW", kind="postgres", host="db.local", database="vendas", user="ana")
VENDAS = SavedQuery(
    id="vendas", name="Vendas 2026", connection="dw", mode="query", query="SELECT * FROM vendas"
)


@pytest.fixture
def connections(tmp_path: Path) -> ConnectionStore:
    store = ConnectionStore(tmp_path / "connections.json", MemorySecretStore())
    store.save(PG, "s3gr3d0")
    return store


@pytest.fixture
def queries(tmp_path: Path) -> QueryStore:
    store = QueryStore(tmp_path / "queries.json")
    store.save(VENDAS)
    return store


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    executed: list[str] = []
    monkeypatch.setattr(sql, "ensure_reachable", lambda *a, **k: None)

    def fake(uri: str, query: str, pre: list[str] | None) -> pl.DataFrame:
        executed.append(query)
        return pl.DataFrame({"id": [1, 2, 3]})

    monkeypatch.setattr(sql, "_execute", fake)
    return executed


def _ctx(
    tmp_path: Path, connections: ConnectionStore | None = None, queries: QueryStore | None = None
) -> NodeContext:
    return NodeContext({}, {}, DatasetStore(tmp_path / "d", 10), tmp_path, connections, queries)


# ------------------------------------------------------------------ consultas salvas


def test_query_file_has_no_secret(queries: QueryStore, connections: ConnectionStore) -> None:
    text = queries.path.read_text(encoding="utf-8")
    assert "s3gr3d0" not in text and "password" not in text


def test_input_data_reads_saved_query(
    tmp_path: Path, connections: ConnectionStore, queries: QueryStore, fake_db: list[str]
) -> None:
    spec = REGISTRY["io.input_data"]
    cfg = spec.config.model_validate({"dataset": "sql:vendas", "limit": 2})
    out = spec.run(_ctx(tmp_path, connections, queries), cfg)
    assert out.tables["out"].height == 3
    assert fake_db == ["SELECT * FROM (SELECT * FROM vendas) AS _q LIMIT 2"]
    assert spec.annotation(cfg) == "Consulta de banco"


def test_saved_query_is_read_only(
    tmp_path: Path, connections: ConnectionStore, queries: QueryStore, fake_db: list[str]
) -> None:
    queries.save(VENDAS.model_copy(update={"query": "DELETE FROM vendas"}))
    spec = REGISTRY["io.input_data"]
    with pytest.raises(InvalidInputError, match="SELECT"):
        spec.run(_ctx(tmp_path, connections, queries), spec.config.model_validate({"dataset": "sql:vendas"}))
    assert fake_db == []


def test_query_fingerprint_follows_definition_and_cache_flag(tmp_path: Path, queries: QueryStore) -> None:
    spec = REGISTRY["io.input_data"]
    assert spec.fingerprint is not None
    ctx = _ctx(tmp_path, queries=queries)
    cfg = spec.config.model_validate({"dataset": "sql:vendas"})
    assert spec.fingerprint(ctx, cfg) != spec.fingerprint(ctx, cfg)  # sem cache: sempre reconsulta

    queries.save(VENDAS.model_copy(update={"cache_results": True}))
    cached = spec.fingerprint(ctx, cfg)
    assert cached == spec.fingerprint(ctx, cfg)
    queries.save(VENDAS.model_copy(update={"cache_results": True, "query": "SELECT 1"}))
    assert spec.fingerprint(ctx, cfg) != cached  # editar a consulta invalida o cache


def test_missing_query_is_explicit(tmp_path: Path, connections: ConnectionStore, queries: QueryStore) -> None:
    spec = REGISTRY["io.input_data"]
    with pytest.raises(NotFoundError, match="aba Dados"):
        spec.run(_ctx(tmp_path, connections, queries), spec.config.model_validate({"dataset": "sql:nada"}))


def test_database_input_hidden_but_registered() -> None:
    assert REGISTRY["io.database_input"].hidden
    assert not REGISTRY["io.input_data"].hidden


# ------------------------------------------------------------------ pasta de destino


def test_output_data_writes_to_chosen_folder(tmp_path: Path) -> None:
    target = tmp_path / "Relatorios"
    target.mkdir()
    spec = REGISTRY["io.output_data"]
    ctx = NodeContext(
        {"in": pl.DataFrame({"a": [1]})}, {}, DatasetStore(tmp_path / "d", 10), tmp_path / "exports"
    )
    cfg = spec.config.model_validate({"filename": "../fora", "format": "csv", "folder": str(target)})
    out = spec.run(ctx, cfg)
    assert (target / "fora.csv").is_file()  # nome saneado: não escapa da pasta
    assert out.extra["exported_path"] == str((target / "fora.csv").resolve())


@pytest.mark.parametrize("folder", ["relativa/pasta", "Z:/nao/existe/mesmo"])
def test_output_data_rejects_bad_folder(tmp_path: Path, folder: str) -> None:
    spec = REGISTRY["io.output_data"]
    ctx = NodeContext({"in": pl.DataFrame({"a": [1]})}, {}, DatasetStore(tmp_path / "d", 10), tmp_path)
    with pytest.raises(InvalidInputError):
        spec.run(ctx, spec.config.model_validate({"folder": folder}))


# ------------------------------------------------------------------ API


def test_queries_api_roundtrip(client: TestClient) -> None:
    client.put("/api/connections/dw", json={"connection": PG.model_dump(), "password": "x"})
    body = VENDAS.model_dump()
    assert client.put("/api/queries/vendas", json=body).status_code == 200
    assert [q["name"] for q in client.get("/api/queries").json()] == ["Vendas 2026"]
    bad = client.put("/api/queries/vendas", json={**body, "query": "DROP TABLE vendas"})
    assert bad.status_code == 400
    assert client.delete("/api/queries/vendas").status_code == 204
    assert client.get("/api/queries").json() == []


def test_workflow_file_save_and_open(client: TestClient, demo: Workflow, tmp_path: Path) -> None:
    folder = tmp_path / "Fluxos"
    folder.mkdir()
    res = client.post(
        "/api/files/workflow/save", json={"path": str(folder / "vendas"), "workflow": demo.model_dump()}
    )
    assert res.status_code == 200
    saved = Path(res.json()["path"])
    assert saved.name == "vendas.prodata.json" and saved.is_file()

    opened = client.post("/api/files/workflow/open", json={"path": str(saved)}).json()
    assert opened["workflow"]["id"] == demo.id and len(opened["workflow"]["nodes"]) == len(demo.nodes)


def test_workflow_file_rejects_relative_or_missing_folder(
    client: TestClient, demo: Workflow, tmp_path: Path
) -> None:
    for path in ["fluxo.prodata.json", str(tmp_path / "nao" / "existe.prodata.json")]:
        res = client.post("/api/files/workflow/save", json={"path": path, "workflow": demo.model_dump()})
        assert res.status_code == 400
    garbage = tmp_path / "lixo.prodata.json"
    garbage.write_text("{}", encoding="utf-8")
    assert client.post("/api/files/workflow/open", json={"path": str(garbage)}).status_code == 400
