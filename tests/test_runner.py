import pytest

from prodata.domain.workflow import Workflow
from prodata.engine.graph import GraphError
from prodata.engine.runner import WorkflowRunner


def test_demo_runs_cleanly(runner: WorkflowRunner, demo: Workflow) -> None:
    report = runner.run(demo)
    failures = {k: v.error for k, v in report.node_results.items() if v.status != "executed"}
    assert not failures
    join = report.node_results["n_join"].anchors
    assert {"L", "J", "R"} <= join.keys()
    assert join["J"].row_count > 0 and join["R"].row_count > 0
    assert {w["widget_type"] for w in report.bi_widgets} == {"chart", "kpi"}


def test_second_run_uses_cache(runner: WorkflowRunner, demo: Workflow) -> None:
    runner.run(demo)
    statuses = {k: v.status for k, v in runner.run(demo).node_results.items()}
    assert statuses.pop("n_output") == "executed"  # efeito colateral: nunca vem do cache
    assert set(statuses.values()) == {"cached"}


def test_config_change_invalidates_only_downstream(runner: WorkflowRunner, demo: Workflow) -> None:
    runner.run(demo)
    demo.node("n_filter").config["expression"] = "[mrr_mensal] >= 2000"
    statuses = {k: v.status for k, v in runner.run(demo).node_results.items()}
    assert statuses["n_clientes"] == statuses["n_formula"] == "cached"
    assert statuses["n_filter"] == statuses["n_join"] == "executed"


def test_failure_skips_descendants(runner: WorkflowRunner, demo: Workflow) -> None:
    demo.node("n_filter").config["expression"] = "[coluna_que_nao_existe] > 1"
    results = runner.run(demo).node_results
    assert results["n_filter"].status == "error"
    assert "coluna_que_nao_existe" in (results["n_filter"].error or "")
    assert results["n_join"].status == "skipped"
    assert results["n_output"].status == "skipped"
    assert results["n_sum_vendas"].status == "executed"


def test_invalid_config_reports_field(runner: WorkflowRunner, demo: Workflow) -> None:
    demo.node("n_filter").config["mode"] = "inexistente"
    result = runner.run(demo).node_results["n_filter"]
    assert result.status == "error" and result.error_field == "mode"


def test_missing_required_input(runner: WorkflowRunner, demo: Workflow) -> None:
    demo.edges = [e for e in demo.edges if e.id != "e6"]  # remove a entrada R do Join
    result = runner.run(demo).node_results["n_join"]
    assert result.status == "skipped" and "[R]" in (result.error or "")


def test_run_to_here_only_runs_ancestors(runner: WorkflowRunner, demo: Workflow) -> None:
    results = runner.run(demo, target_node_id="n_filter").node_results
    assert set(results) == {"n_clientes", "n_cleanse", "n_formula", "n_filter"}


def test_cycle_raises(runner: WorkflowRunner, demo: Workflow) -> None:
    data = demo.model_dump(by_alias=True)
    data["edges"].append(
        {"id": "loop", "source": "n_filter", "sourceHandle": "T", "target": "n_cleanse", "targetHandle": "in"}
    )
    with pytest.raises(GraphError):
        runner.run(Workflow.model_validate(data))


def test_model_metrics_use_holdout(runner: WorkflowRunner, demo: Workflow) -> None:
    metrics = runner.run(demo).node_results["n_trainer"].anchors["M"].metrics
    assert metrics["validation_rows"] > 0
    assert metrics["accuracy_pct"] < 100
