"""Onde cada fonte é usada (spec 028, RF-2811..2815)."""

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from prodata.config import Settings


def flow(fid: str, name: str, dataset: str, extra: int = 0) -> dict[str, Any]:
    nodes = [
        {"id": "a", "type": "io.input_data", "label": "Entrada", "config": {"dataset": dataset}},
        {"id": "b", "type": "prep.sort", "label": "Ordena", "config": {}},
        {"id": "c", "type": "bi.chart", "label": "Gráfico", "config": {}},
    ]
    edges = [{"id": "e1", "source": "a", "target": "b"}, {"id": "e2", "source": "b", "target": "c"}]
    for i in range(extra):
        nodes.append({"id": f"x{i}", "type": "prep.sort", "config": {}})
    return {"id": fid, "name": name, "nodes": nodes, "edges": edges}


def test_lists_flows_readers_and_what_comes_after(client: TestClient) -> None:
    client.put("/api/workflows/f1", json=flow("f1", "Vendas", "clientes.csv"))
    client.put("/api/workflows/f2", json=flow("f2", "Relatório", "api:ibge"))
    usage = client.get("/api/usage").json()
    entry = usage["clientes.csv"][0]
    assert entry["workflow"] == "Vendas"
    assert [r["id"] for r in entry["readers"]] == ["a"]
    assert [d["id"] for d in entry["downstream"]] == ["b", "c"]
    assert usage["api:ibge"][0]["workflow_id"] == "f2"


def test_api_loop_counts_as_using_the_api(client: TestClient) -> None:
    loop = {
        "id": "f3",
        "name": "Loop",
        "nodes": [{"id": "l", "type": "io.api_loop", "config": {"source": "municipios"}}],
        "edges": [],
    }
    client.put("/api/workflows/f3", json=loop)
    assert client.get("/api/usage").json()["api:municipios"][0]["readers"][0]["type"] == "io.api_loop"


def test_index_follows_changes_in_the_library(client: TestClient) -> None:
    client.put("/api/workflows/f1", json=flow("f1", "Vendas", "clientes.csv"))
    assert "clientes.csv" in client.get("/api/usage").json()
    client.put("/api/workflows/f1", json=flow("f1", "Vendas", "outro.csv"))
    usage = client.get("/api/usage").json()
    assert "clientes.csv" not in usage and "outro.csv" in usage


def test_fast_with_500_flows(client: TestClient, settings: Settings) -> None:
    folder = settings.workflows_dir
    for i in range(500):
        (folder / f"w{i}.prodata.json").write_text(
            json.dumps(flow(f"w{i}", f"Fluxo {i}", f"arquivo{i % 20}.csv", extra=10)), encoding="utf-8"
        )
    # A primeira abertura de um arquivo recém-gravado custa de 0,4 a 2 s no Windows (varia com a máquina e o antivírus).
    # Uma biblioteca de verdade já está no disco: o que este teste mede é o índice.
    for path in folder.glob("*.prodata.json"):
        path.read_bytes()
    start = time.perf_counter()
    usage = client.get("/api/usage").json()
    first = time.perf_counter() - start
    start = time.perf_counter()
    client.get("/api/usage")
    again = time.perf_counter() - start
    assert len(usage["arquivo0.csv"]) == 25
    assert first < 1.0, first
    assert again < 0.2, again


def test_broken_file_is_skipped(client: TestClient, settings: Settings) -> None:
    (Path(settings.workflows_dir) / "quebrado.prodata.json").write_text("{", encoding="utf-8")
    client.put("/api/workflows/f1", json=flow("f1", "Vendas", "clientes.csv"))
    assert "clientes.csv" in client.get("/api/usage").json()
