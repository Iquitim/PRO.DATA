"""Spec 033: conexão ODBC, SQL convertido para o Fabric e índice do guia."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prodata.connectors import odbc, sql
from prodata.connectors.models import Connection
from prodata.errors import InvalidInputError

ROOT = Path(__file__).parents[1]

# ------------------------------------------------------------------ ODBC


class FakeCursor:
    description = (("id", int), ("valor", Decimal), ("dia", date), ("id", int))

    def __init__(self, log: list[Any]) -> None:
        self.log = log
        self.rows = [
            (1, Decimal("10.50"), date(2026, 1, 2), 7),
            (2, None, None, 8),
            (3, Decimal("1"), None, 9),
        ]

    def execute(self, query: str) -> None:
        self.log.append(query)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
        return self.rows[:n]

    def tables(self) -> list[tuple[Any, ...]]:
        return [
            ("db", "vendas", "pedidos", "TABLE", None),
            ("db", "vendas", "v_resumo", "VIEW", None),
            ("db", "sys", "interno", "TABLE", None),
            ("db", None, "solta", "TABLE", None),
            ("db", "vendas", "tmp", "GLOBAL TEMPORARY", None),
        ]

    def close(self) -> None:
        self.log.append("cursor fechado")


class FakeConnection:
    def __init__(self, log: list[Any]) -> None:
        self.log = log

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.log)

    def close(self) -> None:
        self.log.append("conexão fechada")


@pytest.fixture
def erp(monkeypatch: pytest.MonkeyPatch) -> tuple[Connection, list[Any]]:
    log: list[Any] = []

    def connect(conn: Connection, password: str) -> FakeConnection:
        log.append(odbc.connection_string(conn, password))
        return FakeConnection(log)

    monkeypatch.setattr(odbc, "connect", connect)
    return Connection(id="erp", name="ERP", kind="odbc", odbc_dsn="ERP_PROD", user="leitor"), log


def test_odbc_reads_and_types_the_rows(erp: tuple[Connection, list[Any]]) -> None:
    conn, log = erp
    table = sql.read_sql(conn, "s3;gr=e}do", "SELECT * FROM pedidos")
    assert table.columns == ["id", "valor", "dia", "id_2"]
    assert table["valor"].to_list() == [10.5, None, 1.0] and table["dia"][0] == date(2026, 1, 2)
    assert log[0] == "DSN=ERP_PROD;UID={leitor};PWD={s3;gr=e}}do}"
    assert log[-2:] == ["cursor fechado", "conexão fechada"]


def test_odbc_limit_fetches_only_what_was_asked(erp: tuple[Connection, list[Any]]) -> None:
    conn, log = erp
    assert sql.read_sql(conn, "", "SELECT * FROM pedidos", limit=2).height == 2
    assert log[1] == "SELECT * FROM pedidos"  # o SQL não é reescrito: cada banco limita de um jeito


def test_odbc_is_read_only(erp: tuple[Connection, list[Any]]) -> None:
    conn, log = erp
    for query in ("DELETE FROM pedidos", "SELECT 1; DROP TABLE pedidos", "SELECT * INTO copia FROM pedidos"):
        with pytest.raises(InvalidInputError):
            sql.read_sql(conn, "", query)
    assert log == []


def test_odbc_lists_tables_without_system_ones(erp: tuple[Connection, list[Any]]) -> None:
    conn, _ = erp
    tables = sql.list_tables(conn, "")
    assert [t["qualified"] for t in tables] == ["solta", "vendas.pedidos", "vendas.v_resumo"]
    assert tables[2]["type"] == "view"
    assert sql.table_query(conn, "vendas.pedidos") == "SELECT * FROM vendas.pedidos"
    assert sql.table_query(conn, "vendas.nota fiscal") == 'SELECT * FROM vendas."nota fiscal"'


def test_odbc_error_never_shows_the_password(
    erp: tuple[Connection, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _ = erp

    def broken(_conn: Connection, password: str) -> Any:
        raise RuntimeError(f"[28000] login failed PWD={password}")

    monkeypatch.setattr(odbc, "connect", broken)
    with pytest.raises(sql.DatabaseError) as exc:
        sql.read_sql(conn, "segredo123", "SELECT 1")
    assert "segredo123" not in exc.value.message and "login failed" in exc.value.message


@pytest.mark.parametrize("dsn", ["", "ERP;PWD=abc", "Driver={SQL Server}", "a=b"])
def test_odbc_accepts_only_a_data_source_name(dsn: str) -> None:
    with pytest.raises(ValidationError, match="nome da fonte de dados"):
        Connection(id="x", name="X", kind="odbc", odbc_dsn=dsn)


def test_other_connections_still_need_server_and_user() -> None:
    with pytest.raises(ValidationError, match="Informe o servidor"):
        Connection(id="x", name="X", kind="postgres", database="d", user="u")
    assert Connection(id="x", name="X", kind="mssql", host="h", database="d", user="u").effective_port == 1433


def test_odbc_connection_through_the_api(client: TestClient, erp: tuple[Connection, list[Any]]) -> None:
    body = {
        "connection": {"id": "erp", "name": "ERP", "kind": "odbc", "odbc_dsn": "ERP_PROD"},
        "password": "p",
    }
    saved = client.put("/api/connections/erp", json=body).json()
    assert saved["has_password"] is True and "password" not in saved
    assert client.post("/api/connections/erp/test").json() == {
        "ok": True,
        "message": "Conectado à fonte ODBC ERP_PROD.",
    }
    preview = client.post(
        "/api/connections/erp/preview?rows=1", json={"mode": "table", "table": "vendas.pedidos"}
    )
    assert len(preview.json()["rows"]) == 1
    bad = client.put(
        "/api/connections/x",
        json={"connection": {"id": "x", "name": "X", "kind": "odbc", "odbc_dsn": "a;PWD=1"}},
    )
    assert bad.status_code == 422


# ------------------------------------------------------------------ SQL para o Fabric


def generate(client: TestClient, dialect: str, selection: list[str] | None = None) -> dict[str, Any]:
    flow_id = client.get("/api/workflows").json()[0]["id"]
    flow = client.get(f"/api/workflows/{flow_id}").json()
    body = {"workflow": flow, "selection": selection or [], "dialect": dialect}
    result: dict[str, Any] = client.post("/api/sql/generate", json=body).json()
    return result


def test_duckdb_code_is_unchanged_and_verified(client: TestClient) -> None:
    data = generate(client, "duckdb")
    assert data["dialect"] == "duckdb" and data["unverified"] is False
    assert "Dialeto: DuckDB" in data["text"] and "NÃO CONFERIDO" not in data["text"]


@pytest.mark.parametrize(("dialect", "name"), [("spark", "Spark SQL"), ("tsql", "T-SQL")])
def test_converted_code_is_marked_as_unverified(client: TestClient, dialect: str, name: str) -> None:
    data = generate(client, dialect)
    text = data["text"]
    assert data["unverified"] is True
    assert f"Dialeto: {name}" in text and "NÃO CONFERIDO" in text
    assert "lê um arquivo: troque pela tabela do Fabric" in text
    # As etapas continuam ligadas aos mesmos blocos da trilha.
    plain = generate(client, "duckdb")
    assert [p["block"] for p in data["parts"]] == [p["block"] for p in plain["parts"]]


def test_tsql_uses_its_own_syntax(client: TestClient) -> None:
    text = generate(client, "tsql")["text"]
    assert "[limpeza] AS (" in text
    assert "TRY_CAST(" in text and "::" not in text


def test_download_names_the_converted_file(client: TestClient) -> None:
    flow_id = client.get("/api/workflows").json()[0]["id"]
    flow = client.get(f"/api/workflows/{flow_id}").json()
    body = {"workflow": flow, "selection": [], "dialect": "spark", "mode": "selection"}
    res = client.post("/api/sql/download", json=body)
    assert "__spark_nao_conferido.sql" in res.headers["content-disposition"]
    assert "NÃO CONFERIDO" in res.text


def test_block_that_cannot_be_converted_stays_and_says_why() -> None:
    from prodata.engine.sql import dialects
    from prodata.engine.sql.render import Part

    class Block:
        name = "ruim"
        sql = "SELECT FROM WHERE ((("

    class Plan:
        blocks: ClassVar[dict[str, Any]] = {"b": Block()}

    part = Part("WITH\n  ruim AS (\n    SELECT FROM WHERE (((\n  )", "b")
    out = dialects.convert_parts(Plan(), [part], "spark")[0]  # type: ignore[arg-type]
    assert out.text.startswith("-- NÃO CONVERTIDO") and "SELECT FROM WHERE (((" in out.text


# ------------------------------------------------------------------ índice do guia


def test_guide_index_lists_every_chapter_in_order() -> None:
    html = (ROOT / "docs/guia/guia.html").read_text(encoding="utf-8")
    start = html.index('<div class="toc">')
    index = html[start : html.index("</section>", start)]
    listed = [int(n) for n in re.findall(r"<div><span>(\d+)</span>", index)]
    chapters = [int(n) for n in re.findall(r'<div class="eyebrow">(\d+) ·', html)]
    assert chapters == list(range(1, len(chapters) + 1)) and len(chapters) >= 18
    assert listed == chapters


# ------------------------------------------------------------------ abertura protegida, uso e catálogo


def test_trust_summary_shows_what_the_new_boxes_touch() -> None:
    from prodata.domain.workflow import Workflow
    from prodata.services.trust import summary

    flow = Workflow.model_validate(
        {
            "id": "recebido",
            "nodes": [
                {
                    "id": "a",
                    "type": "io.input_folder",
                    "config": {"folder": "C:/Users/ana", "pattern": "*.xlsx"},
                },
                {"id": "b", "type": "flow.subflow", "config": {"workflow": "padroniza"}},
                {"id": "c", "type": "flow.subflow", "config": {"workflow": "nao_tem"}},
                {"id": "d", "type": "io.output_data", "config": {"filename": "r", "template": "D:/m.xlsx"}},
                {"id": "e", "type": "prep.regex", "config": {"pattern": "([0-9]+)"}},
                {"id": "f", "type": "prep.multi_field", "config": {"expression": "Trim([_Atual_])"}},
            ],
        }
    )
    items = {i["node_id"]: i for i in summary(flow, {"flow:padroniza": "fluxo Padroniza"})}
    assert items["a"]["kind"] == "folder" and items["a"]["detail"] == "*.xlsx em C:/Users/ana"
    assert items["b"] == {**items["b"], "kind": "subflow", "detail": "fluxo Padroniza", "missing": False}
    assert items["c"]["missing"] is True
    assert "lê o modelo D:/m.xlsx" in items["d"]["detail"]
    assert items["e"]["kind"] == items["f"]["kind"] == "formula"


def test_usage_index_knows_who_uses_a_subflow() -> None:
    from prodata.services.usage import source_keys

    assert source_keys("flow.subflow", {"workflow": "padroniza"}) == ["flow:padroniza"]
    assert source_keys("flow.subflow", {}) == []


def test_catalog_says_how_to_call_the_command_line(client: TestClient) -> None:
    catalog = client.get("/api/catalog").json()
    assert catalog["cli_command"] == "uv run prodata"
    assert {"id": "control", "label": "Conferência e reúso"} in catalog["categories"]


def test_guide_and_readme_state_the_real_number_of_tools() -> None:
    """Toda vez que o guia ou o README dizem quantas ferramentas existem, o número é o do programa."""
    from prodata.nodes import REGISTRY

    real = sum(1 for spec in REGISTRY.values() if not spec.hidden)
    guide = (ROOT / "docs/guia/guia.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # "6 ferramentas novas" é o histórico de uma spec no README, não a contagem do produto.
    stated = [int(n) for n in re.findall(r"(\d+) ferramentas(?! novas)", guide + readme)]
    stated += [int(n) for n in re.findall(r"<b>(\d+)</b><span>ferramentas", guide)]
    assert len(stated) >= 4 and set(stated) == {real}, (stated, real)
