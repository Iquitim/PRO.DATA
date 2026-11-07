"""Constantes (spec 028, RF-2841..2850): um valor com nome, trocado num lugar só e refeito só onde é usado."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prodata.domain.constants import Constant
from prodata.domain.workflow import Workflow
from prodata.engine import constants as ce
from prodata.engine.runner import WorkflowRunner
from prodata.errors import InvalidInputError
from prodata.services.constants import ConstantStore


def flow(expression: str = "[v] * [#fator]", **extra: Any) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "const",
            "name": "Constantes",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "config": {"table": {"columns": ["v"], "rows": [[1], [2], [3]]}},
                },
                {
                    "id": "f",
                    "type": "prep.formula",
                    "config": {
                        "formulas": [
                            {"target": "new", "column": "x", "type": "Auto", "expression": expression}
                        ]
                    },
                },
                {"id": "s", "type": "prep.select", "config": {}},
            ],
            "edges": [{"id": "e1", "source": "t", "target": "f"}, {"id": "e2", "source": "f", "target": "s"}],
            **extra,
        }
    )


def const(name: str, value: str, type_: str = "number") -> dict[str, str]:
    return {"name": name, "type": type_, "value": value}


@pytest.fixture
def shared(tmp_path: Path, runner: WorkflowRunner) -> ConstantStore:
    runner.constants = ConstantStore(tmp_path / "constantes.json")
    return runner.constants


def column(runner: WorkflowRunner, wf: Workflow, node: str = "f") -> list[Any]:
    table = runner.cache.table(wf.id, node, "out")
    assert table is not None
    return table["x"].to_list()


# ---------------------------------------------------------------- modelo


def test_name_and_value_are_checked() -> None:
    with pytest.raises(ValidationError):
        Constant(name="1mes", value="x")
    with pytest.raises(ValidationError):
        Constant(name="taxa", type="number", value="abc")
    with pytest.raises(ValidationError):
        Constant(name="dia", type="date", value="31/02/2026")
    assert Constant(name="taxa", type="number", value="1,5").value == "1,5"


def test_flow_rejects_two_constants_with_the_same_name() -> None:
    with pytest.raises(ValidationError, match="mesmo nome"):
        flow(constants=[const("a", "1"), const("a", "2")])


# ---------------------------------------------------------------- troca do valor


def test_formula_literal_writes_each_type_in_formula_language() -> None:
    assert ce.formula_literal(Constant(name="n", type="number", value="1,5")) == "1.5"
    assert ce.formula_literal(Constant(name="d", type="date", value="2026-03-01")) == "ToDate('2026-03-01')"
    assert ce.formula_literal(Constant(name="t", type="text", value="d'água")) == "'d''água'"


def test_reference_inside_quotes_stays_as_text() -> None:
    values = {"a": Constant(name="a", type="number", value="2")}
    assert ce.fill_expression("[#a] + '[#a]'", values) == "2 + '[#a]'"
    assert ce.node_refs("prep.formula", {"expression": "'[#b]' & [#a]"}) == {"a"}


def test_flow_constant_runs_in_the_formula(runner: WorkflowRunner) -> None:
    wf = flow(constants=[const("fator", "10")])
    report = runner.run(wf)
    assert report.node_results["f"].status == "executed", report.node_results["f"].error
    assert column(runner, wf) == [10, 20, 30]


def test_shared_constant_runs_and_text_constant_is_quoted(
    runner: WorkflowRunner, shared: ConstantStore
) -> None:
    shared.save(Constant(name="uf", type="text", value="SP"))
    wf = flow("Concat([#uf], '-', ToString([v]))")
    assert runner.run(wf).node_results["f"].status == "executed"
    runner.run(wf)
    assert column(runner, wf) == ["SP-1", "SP-2", "SP-3"]


def test_missing_constant_is_an_error_of_the_box_that_uses_it(runner: WorkflowRunner) -> None:
    result = runner.run(flow()).node_results
    assert result["t"].status == "executed"
    assert result["f"].status == "error" and "[#fator] não existe" in (result["f"].error or "")


def test_same_name_in_flow_and_shared_is_an_error(runner: WorkflowRunner, shared: ConstantStore) -> None:
    shared.save(Constant(name="fator", value="3", type="number"))
    result = runner.run(flow(constants=[const("fator", "10")])).node_results["f"]
    assert result.status == "error" and "renomeie" in (result.error or "")


def test_changing_a_constant_redoes_only_what_uses_it(runner: WorkflowRunner, shared: ConstantStore) -> None:
    shared.save(Constant(name="fator", type="number", value="2"))
    wf = flow()
    runner.run(wf)
    assert runner.is_fresh(wf, "f")
    shared.save(Constant(name="fator", type="number", value="5"), previous="fator")
    assert runner.is_fresh(wf, "t") and not runner.is_fresh(wf, "f")
    statuses = {k: v.status for k, v in runner.run(wf).node_results.items()}
    assert statuses["t"] == "cached" and statuses["f"] == "executed"
    assert column(runner, wf) == [5, 10, 15]


def test_snapshot_keeps_the_value_for_a_computer_without_the_constant(
    runner: WorkflowRunner, shared: ConstantStore, tmp_path: Path
) -> None:
    shared.save(Constant(name="fator", type="number", value="7"))
    shared.save(Constant(name="sobra", type="number", value="1"))
    saved = runner.snapshot(flow())
    assert set(saved.shared_constants) == {"fator"}
    shared.delete("fator")
    report = runner.run(saved).node_results["f"]
    assert report.status == "executed"
    assert any("não cadastrada neste computador" in w for w in report.extra.get("warnings", []))
    assert column(runner, saved) == [7, 14, 21]


def test_filter_value_and_output_name_accept_constants(runner: WorkflowRunner, tmp_path: Path) -> None:
    wf = Workflow.model_validate(
        {
            "id": "raw",
            "name": "raw",
            "constants": [const("minimo", "2"), const("mes", "2026-03", "text")],
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "config": {"table": {"columns": ["v"], "rows": [[1], [2], [3]]}},
                },
                {
                    "id": "fl",
                    "type": "prep.filter",
                    "config": {"mode": "simple", "column": "v", "operator": ">=", "value": "[#minimo]"},
                },
                {
                    "id": "o",
                    "type": "io.output_data",
                    "config": {"filename": "saida_[#mes]", "format": "csv"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "t", "target": "fl"},
                {"id": "e2", "source": "fl", "target": "o", "sourceHandle": "T"},
            ],
        }
    )
    results = runner.run(wf).node_results
    assert results["o"].status == "executed", results["o"].error
    assert (runner.exports_dir / "saida_2026-03.csv").is_file()


# ---------------------------------------------------------------- cadastro e rotas


def test_store_rejects_duplicates_and_renames(tmp_path: Path) -> None:
    store = ConstantStore(tmp_path / "c.json")
    store.save(Constant(name="a", value="1"))
    with pytest.raises(InvalidInputError):
        store.save(Constant(name="a", value="2"))
    store.save(Constant(name="b", value="2"), previous="a")
    assert [c.name for c in store.list()] == ["b"]


def test_routes_save_list_and_where_used(client: TestClient) -> None:
    body = {"constant": {"name": "fator", "type": "number", "value": "3", "description": "Multiplicador"}}
    assert client.post("/api/constants", json=body).status_code == 200
    assert [c["name"] for c in client.get("/api/constants").json()] == ["fator"]
    wf = flow().model_dump(mode="json")
    saved = client.put(f"/api/workflows/{wf['id']}", json=wf).json()
    assert saved["shared_constants"] == {"fator": {"type": "number", "value": "3"}}
    usage = client.get("/api/usage").json()
    assert any(k == "const:fator" for k in usage)


def test_validate_formula_knows_constants(client: TestClient) -> None:
    cols = [{"name": "v", "type": "Int64"}]
    bad = client.post("/api/formula/validate", json={"expression": "[v] * [#fator]", "columns": cols}).json()
    assert not bad["valid"] and "[#fator]" in bad["error"]
    ok = client.post(
        "/api/formula/validate",
        json={"expression": "[v] * [#fator]", "columns": cols, "constants": [const("fator", "2")]},
    ).json()
    assert ok["valid"], ok


def test_sql_lists_the_constants_it_used(client: TestClient) -> None:
    wf = flow(constants=[const("fator", "4")]).model_dump(mode="json")
    response = client.post("/api/sql/generate", json={"workflow": wf})
    assert response.status_code == 200, response.text
    text = str(response.json())
    assert "Constantes usadas" in text and "fator = 4" in text and "[#fator]" not in text


def test_api_address_takes_the_constant(runner: WorkflowRunner) -> None:
    from prodata.connectors.api_model import SavedApi
    from prodata.samples.apis import IBGE

    assert runner.apis is not None
    runner.apis.save(
        SavedApi(id="ibge_uf", name="Municípios da UF", url=f"{IBGE}/v1/localidades/estados/[#uf]/municipios")
    )
    wf = Workflow.model_validate(
        {
            "id": "api_const",
            "name": "API",
            "constants": [const("uf", "SP", "text")],
            "nodes": [{"id": "i", "type": "io.input_data", "config": {"dataset": "api:ibge_uf"}}],
            "edges": [],
        }
    )
    result = runner.run(wf).node_results["i"]
    assert result.status == "executed", result.error
    table = runner.cache.table(wf.id, "i", "out")
    assert table is not None and table["municipio-id"].to_list()[0].startswith("SP")
    other = runner.run(wf.model_copy(update={"constants": [Constant(name="uf", type="text", value="RJ")]}))
    assert other.node_results["i"].status == "executed"
    table = runner.cache.table(wf.id, "i", "out")
    assert table is not None and table["municipio-id"].to_list()[0].startswith("RJ")
