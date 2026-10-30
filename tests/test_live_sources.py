"""Spec 017: fontes que se atualizam (arquivos vinculados, cache que percebe a mudança) e exportação segura."""

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from prodata.domain.workflow import Workflow
from prodata.engine import cache as cache_module
from prodata.engine.runner import WorkflowRunner
from prodata.errors import ConflictError, InvalidInputError, NotFoundError
from prodata.ingestion import DatasetStore


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    # Garante mtime diferente mesmo em sistemas de arquivos com resolução de 1 s.
    stamp = time.time() + 2 * (len(text) % 7 + 1)
    os.utime(path, (stamp, stamp))


def _flow(*, cache_point: bool = False, refresh: str = "changes") -> Workflow:
    return Workflow.model_validate(
        {
            "id": "vivo",
            "nodes": [
                {"id": "src", "type": "io.input_data", "config": {"dataset": "vendas_hoje.csv"}},
                {
                    "id": "soma",
                    "type": "transform.summarize",
                    "config": {
                        "group_by": [],
                        "aggregations": [{"column": "valor", "agg": "sum", "alias": "total"}],
                    },
                    "cache_point": cache_point,
                    "cache_refresh": refresh,
                },
                {
                    "id": "dobro",
                    "type": "prep.formula",
                    "config": {"formulas": [{"column": "x", "expression": "[total] * 2"}]},
                },
            ],
            "edges": [
                {"id": "e1", "source": "src", "target": "soma"},
                {"id": "e2", "source": "soma", "target": "dobro"},
            ],
        }
    )


@pytest.fixture
def shared(tmp_path: Path, store: DatasetStore) -> Path:
    """Planilha "da rede": fora da pasta de dados do PRO.DATA, vinculada."""
    folder = tmp_path / "rede"
    folder.mkdir()
    path = folder / "vendas_hoje.csv"
    _write(path, "valor\n10\n20\n")
    store.link(str(path))
    return path


def total(runner: WorkflowRunner, wf: Workflow) -> tuple[float, dict[str, Any]]:
    report = runner.run(wf)
    df = runner.cache.table(wf.id, "soma", "out")
    assert df is not None
    return float(df["total"][0]), report.node_results


def test_linked_file_is_read_where_it_is(runner: WorkflowRunner, shared: Path) -> None:
    value, results = total(runner, _flow())
    assert value == 30.0 and results["src"].extra["source_linked"] == str(shared.resolve())
    assert results["src"].extra["source_modified"]


def test_update_of_the_source_is_captured(runner: WorkflowRunner, shared: Path) -> None:
    total(runner, _flow())
    _, again = total(runner, _flow())
    assert again["src"].status == "cached"  # nada mudou: não relê
    _write(shared, "valor\n10\n20\n70\n")
    value, results = total(runner, _flow())
    assert value == 100.0 and results["src"].status == "executed" and results["dobro"].status == "executed"


def test_cache_point_notices_source_update(runner: WorkflowRunner, shared: Path) -> None:
    wf = _flow(cache_point=True)
    total(runner, wf)
    _, frozen = total(runner, wf)
    assert frozen["soma"].extra["cache_point"] == "frozen" and frozen["src"].extra.get("held")
    _write(shared, "valor\n1\n")
    value, results = total(runner, wf)
    assert value == 1.0 and results["src"].status == "executed"


def test_daily_cache_expires_next_day(
    runner: WorkflowRunner, shared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wf = _flow(cache_point=True, refresh="daily")
    total(runner, wf)
    snapshot = runner.cache.frozen(wf.id, "soma")
    assert snapshot is not None
    yesterday = cache_module.FrozenEntry(snapshot.signature, snapshot.entry, "2020-01-01T10:00:00+00:00")
    monkeypatch.setattr(runner.cache, "frozen", lambda *_: yesterday)
    _, results = total(runner, wf)
    assert results["src"].status != "skipped" and results["soma"].extra.get("cache_point") != "frozen"


def test_link_validations(store: DatasetStore, tmp_path: Path, shared: Path) -> None:
    with pytest.raises(InvalidInputError, match="caminho completo"):
        store.link("relativo/vendas.csv")
    bad = tmp_path / "x.exe"
    bad.write_text("x")
    with pytest.raises(InvalidInputError, match="Extensão"):
        store.link(str(bad))
    with pytest.raises(NotFoundError):
        store.link(str(tmp_path / "nao_existe.csv"))
    with pytest.raises(ConflictError):
        store.link(str(shared))  # mesmo nome de novo
    info = next(d for d in store.list() if d.name == "vendas_hoje.csv")
    assert info.linked_path and not info.missing


def test_unlink_keeps_the_file_and_missing_is_explained(store: DatasetStore, shared: Path) -> None:
    moved = shared.with_name("movida.csv")
    shared.rename(moved)
    info = next(d for d in store.list() if d.name == "vendas_hoje.csv")
    assert info.missing
    with pytest.raises(NotFoundError, match="movido ou renomeado"):
        store.resolve("vendas_hoje.csv")
    store.delete("vendas_hoje.csv")
    assert moved.is_file() and all(d.name != "vendas_hoje.csv" for d in store.list())


# ------------------------------------------------------------------ exportação (RF-1702..RF-1704)


def _export_flow(folder: Path, fmt: str, mode: str) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "exp",
            "nodes": [
                {"id": "t", "type": "io.text_input", "config": {}},
                {"id": "o", "type": "io.output_data",
                 "config": {"filename": "saida", "folder": str(folder), "format": fmt, "if_exists": mode}},
            ],
            "edges": [{"id": "e", "source": "t", "target": "o"}],
        }
    )  # fmt: skip


def test_ask_without_anyone_never_overwrites(runner: WorkflowRunner, tmp_path: Path) -> None:
    original = tmp_path / "saida.csv"
    original.write_text("antigo", encoding="utf-8")
    report = runner.run(_export_flow(tmp_path, "csv", "ask"))
    created = report.node_results["o"].extra
    assert original.read_text(encoding="utf-8") == "antigo"
    assert created["export_action"] == "novo arquivo" and created["exported_file"].startswith("saida 20")
    assert (tmp_path / created["exported_file"]).is_file()


def test_replace_and_add_sheet_rules(runner: WorkflowRunner, tmp_path: Path) -> None:
    (tmp_path / "saida.csv").write_text("antigo", encoding="utf-8")
    report = runner.run(_export_flow(tmp_path, "csv", "replace"))
    assert report.node_results["o"].extra["export_action"] == "substituído"
    assert (tmp_path / "saida.csv").read_text(encoding="utf-8") != "antigo"
    report = runner.run(_export_flow(tmp_path, "csv", "add_sheet"))
    assert (
        report.node_results["o"].status == "error" and "só vale para Excel" in report.node_results["o"].error
    )


def test_pending_exports_lists_files_that_would_be_asked(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "saida.xlsx").write_bytes(b"x")
    wf = _export_flow(tmp_path, "excel", "ask").model_dump(mode="json", by_alias=True)
    pending = client.post("/api/exports/pending", json={"workflow": wf}).json()
    assert [(p["node_id"], p["file"]) for p in pending] == [("o", "saida.xlsx")]
    wf["nodes"][1]["config"]["if_exists"] = "replace"
    assert client.post("/api/exports/pending", json={"workflow": wf}).json() == []


def test_link_route(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "planilha.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    res = client.post("/api/datasets/link", json={"path": str(path)})
    assert res.status_code == 201 and res.json()["linked_path"] == str(path.resolve())
    names = {d["name"]: d for d in client.get("/api/datasets").json()}
    assert names["planilha.csv"]["linked_path"]
    assert client.post("/api/datasets/link", json={"path": "planilha.csv"}).status_code == 400


def test_value_search_on_the_server(client: TestClient) -> None:
    from prodata.samples.workflows import DEMO_WORKFLOW_ID

    wf = client.get(f"/api/workflows/{DEMO_WORKFLOW_ID}").json()
    client.post("/api/execute", json={"workflow": wf})
    data = client.get(
        f"/api/results/{wf['id']}/n_vendas/out/values",
        params={"column": "id_cliente", "search": "cli-14", "limit": 15},
    ).json()
    assert data["distinct"] > 400 and data["matches"] >= 1
    assert all("CLI-14" in v["value"] for v in data["values"]) and len(data["values"]) <= 15


def test_automatic_runs_hold_exports_that_would_ask(runner: WorkflowRunner, tmp_path: Path) -> None:
    (tmp_path / "saida.csv").write_text("antigo", encoding="utf-8")
    report = runner.run(_export_flow(tmp_path, "csv", "ask"), hold_exports=True)
    result = report.node_results["o"]
    assert result.status == "skipped" and result.extra["export_waiting"] == "saida.csv"
    assert sorted(p.name for p in tmp_path.glob("saida*")) == ["saida.csv"]  # nada gravado
    # Arquivo ainda não existe: a execução automática grava normalmente.
    fresh = runner.run(
        _export_flow(tmp_path / "vazia" if (tmp_path / "vazia").mkdir() is None else tmp_path, "csv", "ask"),
        hold_exports=True,
    )
    assert fresh.node_results["o"].status == "executed"
