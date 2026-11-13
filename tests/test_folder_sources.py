"""Spec 035: pasta de arquivos como fonte da aba Dados, lida pelo Input Data."""

from __future__ import annotations

import os
import time
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner
from prodata.errors import ConflictError, InvalidInputError, NotFoundError
from prodata.ingestion import DatasetStore
from prodata.ingestion.folders import FolderSource
from prodata.nodes import REGISTRY
from prodata.services.trust import summary


@pytest.fixture
def month(tmp_path: Path) -> Path:
    folder = tmp_path / "fechamento"
    folder.mkdir()
    pl.DataFrame({"uf": ["SP", "RJ"], "valor": [10.0, 20.0]}).write_csv(folder / "vendas_01.csv")
    pl.DataFrame({"uf": ["MG"], "valor": [5.0]}).write_csv(folder / "vendas_02.csv")
    pl.DataFrame({"x": [1]}).write_csv(folder / "outro.csv")
    (folder / "~$vendas_03.csv").write_text("temporário do Excel", encoding="utf-8")
    return folder


def source(month: Path, **extra: object) -> FolderSource:
    return FolderSource.model_validate(
        {"name": "Vendas do mês", "folder": str(month), "pattern": "vendas_*.csv", **extra}
    )


def flow(dataset: str) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "fechamento",
            "name": "Fechamento",
            "nodes": [
                {"id": "i", "type": "io.input_data", "config": {"dataset": dataset}},
                {"id": "s", "type": "prep.select", "config": {}},
            ],
            "edges": [{"id": "e", "source": "i", "target": "s"}],
        }
    )


def test_save_makes_an_id_and_refuses_duplicates(store: DatasetStore, month: Path) -> None:
    saved = store.folders.save(source(month))
    assert saved.id == "vendas_do_mes" and store.folders.get(saved.id).pattern == "vendas_*.csv"
    with pytest.raises(ConflictError):
        store.folders.save(source(month, name="vendas do mês"))
    other = store.folders.save(source(month, name="Outra", id="vendas_do_mes"))
    assert other.id == "vendas_do_mes_2"


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"folder": "relativa"}, InvalidInputError),
        ({"pattern": "../*.csv"}, InvalidInputError),
        ({"folder": "SUMIDA"}, NotFoundError),  # caminho completo nos dois sistemas: vira tmp/sumida
    ],
)
def test_save_checks_the_folder(store: DatasetStore, month: Path, changes: dict, error: type) -> None:
    if changes.get("folder") == "SUMIDA":
        changes = {"folder": str(month.parent / "sumida")}
    with pytest.raises(error):
        store.folders.save(source(month, **changes))


def test_delete_keeps_the_files(store: DatasetStore, month: Path) -> None:
    saved = store.folders.save(source(month))
    store.folders.delete(saved.id)
    assert (month / "vendas_01.csv").is_file() and store.folders.list() == []
    with pytest.raises(NotFoundError, match="Cadastre na vista Dados"):
        store.folders.get(saved.id)


def test_input_data_stacks_the_folder(runner: WorkflowRunner, month: Path) -> None:
    saved = runner.datasets.folders.save(source(month))
    result = runner.run(flow(f"folder:{saved.id}")).node_results["i"]
    assert result.status == "executed", result.error
    assert result.extra["folder_files"] == ["vendas_01.csv", "vendas_02.csv"]
    assert result.extra["source"] == "Vendas do mês"
    assert result.anchors["out"].row_count == 3
    assert [c.name for c in result.anchors["out"].columns] == ["uf", "valor", "arquivo"]


def test_new_or_changed_file_redoes_the_box(runner: WorkflowRunner, month: Path) -> None:
    saved = runner.datasets.folders.save(source(month))
    wf = flow(f"folder:{saved.id}")
    runner.run(wf)
    assert runner.run(wf).node_results["i"].status == "cached"
    pl.DataFrame({"uf": ["BA"], "valor": [1.0]}).write_csv(month / "vendas_03.csv")
    again = runner.run(wf).node_results["i"]
    assert again.status == "executed" and again.anchors["out"].row_count == 4
    later = time.time() + 5
    os.utime(month / "vendas_01.csv", (later, later))
    assert runner.run(wf).node_results["i"].status == "executed"
    runner.datasets.folders.save(source(month, pattern="vendas_0[12].csv"), previous=saved.id)
    assert runner.run(wf).node_results["i"].anchors["out"].row_count == 3


def test_unregistered_folder_explains_what_to_do(runner: WorkflowRunner) -> None:
    result = runner.run(flow("folder:sumiu")).node_results["i"]
    assert result.status == "error" and "Cadastre na vista Dados" in (result.error or "")


def test_old_box_is_hidden_but_still_runs() -> None:
    assert REGISTRY["io.input_folder"].hidden
    assert "(Antiga)" in REGISTRY["io.input_folder"].description


def test_trust_lists_the_folder() -> None:
    items = summary(flow("folder:vendas"), {"folder:vendas": "vendas_*.csv em D:\\Fechamento"})
    assert items[0]["kind"] == "folder" and "D:\\Fechamento" in items[0]["detail"] and not items[0]["missing"]
    assert summary(flow("folder:outra"), {})[0]["missing"]


def test_routes(client: TestClient, month: Path) -> None:
    body = {"name": "Vendas do mês", "folder": str(month), "pattern": "vendas_*.csv"}
    preview = client.post("/api/folders/preview", json={"source": body}).json()
    assert [f["name"] for f in preview["files"]] == ["vendas_01.csv", "vendas_02.csv"]
    assert [c["name"] for c in preview["columns"]] == ["uf", "valor", "arquivo"] and len(preview["rows"]) == 3
    odd = client.post("/api/folders/preview", json={"source": {**body, "pattern": "*.csv"}}).json()
    assert [f["name"] for f in odd["files"] if f["odd"]] == ["vendas_01.csv", "vendas_02.csv"]
    gone = client.post("/api/folders/preview", json={"source": {**body, "folder": str(month / "x")}}).json()
    assert gone["missing"] and gone["files"] == []

    saved = client.post("/api/folders", json=body).json()
    assert saved["status"]["files"] == 2 and saved["id"] == "vendas_do_mes"
    changed = client.put(f"/api/folders/{saved['id']}", json={**body, "pattern": "nada_*.csv"}).json()
    assert changed["status"]["files"] == 0
    listed = client.get("/api/folders").json()
    assert [f["id"] for f in listed] == ["vendas_do_mes"]
    assert client.delete(f"/api/folders/{saved['id']}").status_code == 204
    assert client.delete(f"/api/folders/{saved['id']}").status_code == 404
    org = client.put(
        "/api/organization/sources", json={"keys": ["folder:vendas"], "changes": {"pinned": True}}
    )
    assert org.status_code == 200


def test_link_each_links_every_file_once(store: DatasetStore, month: Path) -> None:
    files = sorted(month.glob("vendas_*.csv"))
    linked, skipped = store.link_many(files)
    assert [d.name for d in linked] == ["vendas_01.csv", "vendas_02.csv"] and skipped == []
    assert all(d.linked_path for d in linked)
    again, skipped = store.link_many(files)
    assert again == [] and skipped == ["vendas_01.csv", "vendas_02.csv"]
    other = month / "copia"
    other.mkdir()
    (other / "vendas_01.csv").write_text("uf,valor\nPE,1\n", encoding="utf-8")
    renamed, _ = store.link_many([other / "vendas_01.csv"])
    assert renamed[0].name == "vendas_01_2.csv"


def test_link_each_route(client: TestClient, month: Path) -> None:
    out = client.post("/api/folders/link-each", json={"folder": str(month), "pattern": "vendas_*.csv"}).json()
    assert [d["name"] for d in out["linked"]] == ["vendas_01.csv", "vendas_02.csv"]
    names = [d["name"] for d in client.get("/api/datasets").json()]
    assert "vendas_01.csv" in names and "vendas_02.csv" in names
    none = client.post("/api/folders/link-each", json={"folder": str(month), "pattern": "nada_*"})
    assert none.status_code == 400
