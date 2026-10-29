import json
import time
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.connectors import Connection, ConnectionStore, MemorySecretStore, sql
from prodata.errors import InvalidInputError
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

PG = Connection(id="dw", name="DW", kind="postgres", host="db.local", database="vendas", user="ana")
MSSQL = Connection(id="erp", name="ERP", kind="mssql", host="erp.local", database="ERP", user="sa")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testes com driver simulado não devem depender de rede (checagem TCP desligada)."""
    monkeypatch.setattr(sql, "ensure_reachable", lambda *a, **k: None)


@pytest.fixture
def store(tmp_path: Path) -> ConnectionStore:
    return ConnectionStore(tmp_path / "connections.json", MemorySecretStore())


# ------------------------------------------------------------------ armazenamento


def test_password_never_written_to_disk(store: ConnectionStore) -> None:
    info = store.save(PG, "s3gr3d0!")
    assert info.has_password
    assert "s3gr3d0!" not in store.path.read_text(encoding="utf-8")
    assert "password" not in json.loads(store.path.read_text(encoding="utf-8"))[0]
    assert store.password("dw") == "s3gr3d0!"


def test_save_without_password_keeps_existing(store: ConnectionStore) -> None:
    store.save(PG, "abc")
    store.save(PG.model_copy(update={"host": "outro"}))
    assert store.password("dw") == "abc"
    store.save(PG, "")
    assert store.password("dw") == ""


def test_delete_removes_secret(store: ConnectionStore) -> None:
    store.save(PG, "abc")
    store.delete("dw")
    assert store.list() == []
    assert store.secrets.get("connection:dw") is None


# ------------------------------------------------------------------ SQL


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM vendas",
        "  with t as (select 1 as x) select * from t;",
        "SELECT 'DELETE FROM x' AS texto",
        'SELECT "update" FROM t',
        "SELECT 1 -- DROP TABLE x",
    ],
)
def test_read_only_accepts(query: str) -> None:
    assert sql.ensure_read_only(query)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("DELETE FROM vendas", "SELECT ou WITH"),
        ("SELECT 1; DROP TABLE vendas", "única instrução"),
        ("WITH x AS (SELECT 1) DELETE FROM vendas", "DELETE"),
        ("SELECT * INTO copia FROM vendas", "INTO"),
        ("/* oi */ UPDATE vendas SET a = 1", "SELECT ou WITH"),
        ("", "Escreva"),
    ],
)
def test_read_only_rejects(query: str, reason: str) -> None:
    with pytest.raises(InvalidInputError, match=reason):
        sql.ensure_read_only(query)


def test_uri_encodes_credentials() -> None:
    uri = sql.build_uri(PG, "p@ss:/w#rd")
    assert uri.startswith("postgresql://ana:p%40ss%3A%2Fw%23rd@db.local:5432/vendas?")
    assert "sslmode=prefer" in uri
    assert sql.build_uri(MSSQL, "x").startswith("mssql://sa:x@erp.local:1433/ERP?encrypt=true")


def test_limit_and_quoting_by_dialect() -> None:
    assert sql.limited(PG, "SELECT 1", 10).endswith("LIMIT 10")
    assert sql.limited(MSSQL, "SELECT 1", 10).startswith("SELECT TOP 10 *")
    assert sql.table_query(PG, "public.vendas") == 'SELECT * FROM "public"."vendas"'
    assert sql.table_query(MSSQL, "dbo.Pedidos") == "SELECT * FROM [dbo].[Pedidos]"


@pytest.mark.usefixtures("no_network")
def test_postgres_session_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(uri: str, query: str, pre: list[str] | None) -> pl.DataFrame:
        seen.update(uri=uri, query=query, pre=pre)
        return pl.DataFrame({"ok": [1]})

    monkeypatch.setattr(sql, "_execute", fake)
    sql.read_sql(PG, "x", "SELECT 1")
    assert seen["pre"] == ["SET default_transaction_read_only = on"]


@pytest.mark.usefixtures("no_network")
def test_driver_errors_do_not_leak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(uri: str, query: str, pre: list[str] | None) -> pl.DataFrame:
        raise RuntimeError(f"connection to {uri} failed: password authentication failed (senha=Sup3r)")

    monkeypatch.setattr(sql, "_execute", boom)
    with pytest.raises(sql.DatabaseError) as info:
        sql.read_sql(PG, "Sup3r", "SELECT 1")
    assert "Sup3r" not in info.value.message


def test_unreachable_host_fails_fast() -> None:
    conn = PG.model_copy(update={"host": "127.0.0.1", "port": 1})
    started = time.perf_counter()
    with pytest.raises(sql.DatabaseError, match="inacessível"):
        sql.check_connection(conn, "x")
    assert time.perf_counter() - started < 8  # antes: ~30 s esperando o pool do driver


# ------------------------------------------------------------------ ferramenta


@pytest.mark.usefixtures("no_network")
def test_database_input_reads_table(
    monkeypatch: pytest.MonkeyPatch, store: ConnectionStore, tmp_path: Path
) -> None:
    store.save(PG, "x")
    queries = []

    def fake(uri: str, query: str, pre: list[str] | None) -> pl.DataFrame:
        queries.append(query)
        return pl.DataFrame({"id": [1, 2]})

    monkeypatch.setattr(sql, "_execute", fake)
    spec = REGISTRY["io.database_input"]
    ctx = NodeContext({}, {}, DatasetStore(tmp_path / "d", 10), tmp_path, store)
    out = spec.run(
        ctx, spec.config.model_validate({"connection": "dw", "table": "public.vendas", "limit": 5})
    )
    assert out.tables["out"].height == 2
    assert queries == ['SELECT * FROM (SELECT * FROM "public"."vendas") AS _q LIMIT 5']


def test_database_input_reruns_unless_cached(tmp_path: Path) -> None:
    spec = REGISTRY["io.database_input"]
    assert spec.fingerprint is not None
    fresh = spec.config.model_validate({"connection": "dw"})
    cached = spec.config.model_validate({"connection": "dw", "cache_results": True})
    ctx = NodeContext({}, {}, DatasetStore(tmp_path / "d", 10), tmp_path)
    assert spec.fingerprint(ctx, fresh) != spec.fingerprint(ctx, fresh)
    assert spec.fingerprint(ctx, cached) == spec.fingerprint(ctx, cached)


# ------------------------------------------------------------------ API


def test_api_never_returns_password(client: TestClient) -> None:
    body = {"connection": PG.model_dump(), "password": "s3gr3d0"}
    res = client.put("/api/connections/dw", json=body)
    assert res.status_code == 200 and res.json()["has_password"] is True
    listed = client.get("/api/connections").text
    assert "s3gr3d0" not in listed and '"has_password":true' in listed
    assert client.delete("/api/connections/dw").status_code == 204
    assert client.get("/api/connections").json() == []


def test_api_test_reports_failure(client: TestClient) -> None:
    conn = PG.model_copy(update={"host": "127.0.0.1", "port": 1}).model_dump()
    client.put("/api/connections/dw", json={"connection": conn, "password": "x"})
    result = client.post("/api/connections/dw/test").json()
    assert result["ok"] is False and result["message"]


def test_api_preview_rejects_writes(client: TestClient) -> None:
    client.put("/api/connections/dw", json={"connection": PG.model_dump()})
    res = client.post("/api/connections/dw/preview", json={"mode": "query", "query": "DROP TABLE x"})
    assert res.status_code == 400
