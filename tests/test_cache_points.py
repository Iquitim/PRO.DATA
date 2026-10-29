"""Spec 012: ponto de cache — congela um resultado e dispensa as caixas anteriores."""

from pathlib import Path

from fastapi.testclient import TestClient

from prodata.domain.workflow import Workflow
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore

UPSTREAM = {"n_clientes", "n_cleanse", "n_formula", "n_filter", "n_vendas", "n_sum_vendas"}


def _point(demo: Workflow, node_id: str = "n_join") -> Workflow:
    demo.node(node_id).cache_point = True
    return demo


def test_cache_point_skips_everything_before_it(runner: WorkflowRunner, demo: Workflow) -> None:
    wf = _point(demo)
    first = runner.run(wf).node_results
    assert first["n_join"].extra["cache_point"] == "saved"
    second = runner.run(wf).node_results
    assert second["n_join"].status == "cached" and second["n_join"].extra["cache_point"] == "frozen"
    held = {k for k, r in second.items() if r.extra.get("held")}
    assert held >= UPSTREAM
    # O que vem depois continua funcionando com o resultado congelado.
    assert second["n_kpi"].status in ("executed", "cached")
    assert second["n_join"].anchors["J"].row_count == first["n_join"].anchors["J"].row_count


def test_cache_point_survives_restart(tmp_path: Path, store: DatasetStore, demo: Workflow) -> None:
    wf = _point(demo)
    exports = tmp_path / "exports"
    exports.mkdir()
    WorkflowRunner(ResultCache(tmp_path / "cache"), store, exports).run(wf)
    # Programa reaberto: memória vazia, só o disco.
    results = WorkflowRunner(ResultCache(tmp_path / "cache"), store, exports).run(wf).node_results
    assert results["n_join"].extra["cache_point"] == "frozen"
    assert results["n_clientes"].status == "skipped" and results["n_clientes"].extra["held"]
    assert results["n_kpi"].status == "executed"


def test_change_before_point_invalidates(runner: WorkflowRunner, demo: Workflow) -> None:
    wf = _point(demo)
    runner.run(wf)
    wf.node("n_filter").config["expression"] = "[mrr_mensal] >= 2000"
    results = runner.run(wf).node_results
    assert results["n_filter"].status == "executed"
    assert results["n_join"].extra["cache_point"] == "saved"
    assert not any(r.extra.get("held") for r in results.values())


def test_change_after_point_keeps_cache(runner: WorkflowRunner, demo: Workflow) -> None:
    wf = _point(demo)
    runner.run(wf)
    kpi = wf.node("n_kpi")
    kpi.label = "Outro nome"
    results = runner.run(wf).node_results
    assert results["n_join"].extra["cache_point"] == "frozen"


def test_branch_outside_point_still_runs(runner: WorkflowRunner, demo: Workflow) -> None:
    """Uma entrada que alimenta outro ramo (fora do ponto) continua executando."""
    wf = _point(demo, "n_filter")
    runner.run(wf)
    results = runner.run(wf).node_results
    assert results["n_clientes"].extra.get("held")
    assert not results["n_vendas"].extra.get("held")  # alimenta o Join pela direita


def test_removing_point_and_refresh_route(client: TestClient, demo: Workflow) -> None:
    wf = _point(demo).model_dump(mode="json", by_alias=True)
    client.post("/api/execute", json={"workflow": wf})
    second = client.post("/api/execute", json={"workflow": wf}).json()["node_results"]
    assert second["n_join"]["extra"]["cache_point"] == "frozen"
    assert client.delete(f"/api/cache/{demo.id}/n_join").status_code == 204
    third = client.post("/api/execute", json={"workflow": wf}).json()["node_results"]
    assert third["n_join"]["extra"]["cache_point"] == "saved"
    wf["nodes"] = [{**n, "cache_point": False} for n in wf["nodes"]]
    fourth = client.post("/api/execute", json={"workflow": wf}).json()["node_results"]
    assert "cache_point" not in fourth["n_join"]["extra"]
