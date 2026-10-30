"""Versão 0.4.1 (spec 019): Join com chaves e colunas escolhidas, moda e desvio padrão, fluxos da 0.3.8."""

import json
from pathlib import Path

import polars as pl
import pytest

from prodata.domain.workflow import Workflow
from prodata.engine import formula
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

DATA = Path(__file__).parent / "data"
LEFT = pl.DataFrame({"id": [1, 2, 3], "x": ["a", "b", "c"], "valor": ["10", "20", "x"]})
RIGHT = pl.DataFrame({"id": [2, 3, 4], "x": ["B", "C", "D"]})


def run(tool: str, inputs: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: object):
    spec = REGISTRY[tool]
    ctx = NodeContext(inputs, {}, store, tmp_path)
    return spec.run(ctx, spec.config.model_validate(config))


def join(store: DatasetStore, tmp_path: Path, **config: object):
    keys = [{"left": "id", "right": "id"}]
    return run("transform.join", {"L": LEFT, "R": RIGHT}, store, tmp_path, keys=keys, **config)


# ------------------------------------------------------------------ RF-1901: chaves no J


@pytest.mark.parametrize(
    ("mode", "columns"),
    [
        ("both", ["id", "x", "valor", "r_id", "r_x"]),
        ("left", ["id", "x", "valor", "r_x"]),  # como até a 0.3.8
        ("right", ["x", "valor", "id", "r_x"]),  # a chave da direita volta ao nome original
    ],
)
def test_join_key_side(store: DatasetStore, tmp_path: Path, mode: str, columns: list[str]) -> None:
    out = join(store, tmp_path, keys_mode=mode)
    assert out.tables["J"].columns == columns
    assert out.tables["J"]["id"].to_list() == [2, 3]


def test_join_key_side_with_different_names(store: DatasetStore, tmp_path: Path) -> None:
    right = pl.DataFrame({"codigo": [2, 3], "y": ["B", "C"]})
    keys = [{"left": "id", "right": "codigo"}]
    left_only = run("transform.join", {"L": LEFT, "R": right}, store, tmp_path, keys=keys, keys_mode="left")
    right_only = run("transform.join", {"L": LEFT, "R": right}, store, tmp_path, keys=keys, keys_mode="right")
    assert left_only.tables["J"].columns == ["id", "x", "valor", "y"]
    assert right_only.tables["J"].columns == ["x", "valor", "codigo", "y"]


# ------------------------------------------------------------------ RF-1902: Select embutido


def test_join_select_keeps_renames_casts_and_orders(store: DatasetStore, tmp_path: Path) -> None:
    out = join(
        store,
        tmp_path,
        keys_mode="left",
        fields=[
            {"name": "x", "keep": False},
            {"name": "r_x", "rename": "nome_direita"},
            {"name": "valor", "cast": "Int64"},
        ],
        order=["r_x", "id"],  # a ordem usa o nome de entrada, como no Select
    )
    table = out.tables["J"]
    assert table.columns == ["nome_direita", "id", "valor"]
    assert table["valor"].to_list() == [20, None]
    assert "não converteram" in out.extra["warnings"][0]
    # As saídas L e R não passam pelo Select do J.
    assert out.tables["L"].columns == LEFT.columns
    assert out.tables["R"].columns == RIGHT.columns


# ------------------------------------------------------------------ RF-1904 e RF-1905: moda e desvio padrão


def test_summarize_mode_and_std(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"uf": ["SP", "SP", "SP", "RJ", "RJ"], "v": [2, 1, 2, 5, 3]})
    out = run(
        "transform.summarize",
        {"in": df},
        store,
        tmp_path,
        group_by=["uf"],
        aggregations=[{"column": "v", "agg": "mode"}, {"column": "v", "agg": "std", "alias": "desvio"}],
    )
    table = out.tables["out"]
    assert table["mode_v"].to_list() == [2, 3]  # RJ empata (5 e 3): fica o menor
    assert table["desvio"].round(4).to_list() == [0.5774, 1.4142]


def test_row_mode_and_stddev() -> None:
    df = pl.DataFrame({"a": [1.0, 2.0], "b": [1.0, None], "c": [3.0, 4.0]})
    out = formula.evaluate_columns(
        df,
        [
            {"column": "moda", "type": "Float64", "expression": "Mode([a], [b], [c])"},
            {"column": "dp", "type": "Float64", "expression": "StdDev([a], [b], [c])"},
        ],
    )
    assert out["moda"].to_list()[0] == 1.0
    assert out["dp"].round(4).to_list() == [1.1547, 1.4142]


# ------------------------------------------------------------------ RF-1906: fluxos salvos na 0.3.8


def test_workflow_saved_in_038_still_runs(runner: WorkflowRunner) -> None:
    raw = json.loads((DATA / "fluxo_0_3_8.prodata.json").read_text(encoding="utf-8"))
    wf = Workflow.model_validate(raw)
    report = runner.run(wf)
    errors = {k: r.error for k, r in report.node_results.items() if r.status == "error"}
    assert not errors
    assert all(r.status == "executed" for r in report.node_results.values())
