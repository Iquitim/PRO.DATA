"""Os resultados dos fluxos não mudam de uma versão para outra sem querer.

``tests/data/regressao_0_4_1.json`` guarda a impressão digital de cada saída, gerada pelo código da tag v0.4.1. O fluxo
``regressao.prodata.json`` passa por todas as ferramentas de dados, e ``fluxo_0_3_8.prodata.json`` é a demonstração
daquela versão. As caixas de ML ficam de fora: o treino não é uma comparação exata entre máquinas.

Se um resultado mudar de propósito, a impressão digital é atualizada junto, com o motivo no commit.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner

DATA = Path(__file__).parent / "data"
BASELINE = json.loads((DATA / "regressao_0_4_1.json").read_text(encoding="utf-8"))
FLOWS = {"regressao": "regressao.prodata.json", "demo_0_3_8": "fluxo_0_3_8.prodata.json"}


def digest(df: pl.DataFrame) -> dict[str, Any]:
    exprs = [
        pl.col(c).cast(pl.Float64, strict=False).round(6).cast(pl.String)
        if t.is_numeric()
        else pl.col(c).cast(pl.String, strict=False)
        for c, t in df.schema.items()
    ]
    text = (
        df.select([e.fill_null("∅").alias(c) for e, c in zip(exprs, df.columns, strict=True)])
        .sort(pl.all())
        .write_csv()
    )
    return {
        "rows": df.height,
        "columns": df.columns,
        "types": [str(t) for t in df.dtypes],
        "sha": hashlib.sha256(text.encode()).hexdigest()[:16],
    }


@pytest.mark.parametrize("flow", FLOWS)
def test_results_match_version_041(flow: str, runner: WorkflowRunner) -> None:
    workflow = Workflow.model_validate(json.loads((DATA / FLOWS[flow]).read_text(encoding="utf-8")))
    report = runner.run(workflow)
    expected = BASELINE["flows"][flow]
    compared = 0
    for node in workflow.nodes:
        assert report.node_results[node.id].status == expected[node.id]["status"], node.id
        for port, fingerprint in expected[node.id]["ports"].items():
            assert digest(runner.cache.table(workflow.id, node.id, port)) == fingerprint, f"{node.id}[{port}]"
            compared += 1
    assert compared > 20


def test_regression_flow_covers_every_data_tool() -> None:
    raw = json.loads((DATA / "regressao.prodata.json").read_text(encoding="utf-8"))
    used = {n["type"] for n in raw["nodes"]}
    assert {
        "io.input_data", "io.text_input", "io.browse", "prep.select", "prep.filter", "prep.formula", "prep.cleanse",
        "prep.unique", "prep.sort", "prep.sample", "prep.text_to_columns", "prep.record_id", "prep.running_total",
        "transform.join", "transform.summarize", "transform.union", "transform.crosstab", "transform.transpose",
        "transform.append_fields", "transform.sql_query",
    } <= used  # fmt: skip


def test_fingerprint_notices_any_change() -> None:
    """O comparador precisa perceber valor, tipo, coluna e linha diferentes; a ordem das linhas não conta."""
    base = pl.DataFrame({"a": [1, 2], "b": ["x", None]})
    same = digest(base)
    assert digest(base.reverse()) == same
    assert digest(base.with_columns(pl.lit(9).alias("a"))) != same
    assert digest(base.with_columns(pl.lit("y").alias("b"))) != same
    assert digest(base.with_columns(pl.col("a").cast(pl.Float64))) != same
    assert digest(base.rename({"b": "c"})) != same
    assert digest(base.head(1)) != same
