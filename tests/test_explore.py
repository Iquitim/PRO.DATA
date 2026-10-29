import json

import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.domain.workflow import Container
from prodata.engine.results import ExploreFilter, apply_filters
from prodata.errors import InvalidInputError
from prodata.samples.workflows import DEMO_WORKFLOW_ID

DF = pl.DataFrame(
    {
        "uf": ["SP", "RJ", "SP", None],
        "mrr": [1000.0, 5000.0, 3500.0, 200.0],
        "nome": ["Alfa Ltda", "Beta SA", "alfa labs", "Gama"],
        "dia": ["2026-01-05", "2026-02-10", "2026-03-15", "2026-04-20"],
    }
)


def run(*filters: dict) -> list:
    return apply_filters(DF, [ExploreFilter.model_validate(f) for f in filters])["mrr"].to_list()


def test_combined_conditions_are_and() -> None:
    assert run(
        {"column": "uf", "op": "eq", "value": "SP"}, {"column": "mrr", "op": "ge", "value": "3000"}
    ) == [3500.0]


def test_numeric_accepts_comma_decimal_and_between() -> None:
    assert run({"column": "mrr", "op": "between", "value": "1000", "value2": "3500,0"}) == [1000.0, 3500.0]


def test_text_operators_are_case_insensitive() -> None:
    assert run({"column": "nome", "op": "starts_with", "value": "ALFA"}) == [1000.0, 3500.0]
    assert run({"column": "nome", "op": "not_contains", "value": "alfa"}) == [5000.0, 200.0]


def test_in_list_and_nulls() -> None:
    assert run({"column": "uf", "op": "in", "value": "SP, RJ"}) == [1000.0, 5000.0, 3500.0]
    assert run({"column": "uf", "op": "is_null"}) == [200.0]
    assert run({"column": "uf", "op": "ne", "value": "SP"}) == [5000.0]  # nulo não entra


def test_dates_compare_as_iso_text() -> None:
    assert run({"column": "dia", "op": "lt", "value": "2026-03-01"}) == [1000.0, 5000.0]


def test_invalid_filters() -> None:
    with pytest.raises(InvalidInputError, match="inexistente"):
        run({"column": "xx", "op": "eq", "value": "1"})
    with pytest.raises(InvalidInputError, match="número"):
        run({"column": "mrr", "op": "gt", "value": "abc"})


def test_container_backwards_compatible() -> None:
    old = Container.model_validate({"id": "c", "title": "Etapa", "color": "#fff", "x": 0, "y": 0})
    assert old.description == "" and old.opacity == pytest.approx(0.05)
    assert old.disabled is False


def test_api_filters_count_and_profile(client: TestClient) -> None:
    wf = client.get(f"/api/workflows/{DEMO_WORKFLOW_ID}").json()
    client.post("/api/execute", json={"workflow": wf})
    url = f"/api/results/{wf['id']}/n_clientes/out"
    full = client.get(url).json()
    filters = json.dumps([{"column": "uf", "op": "eq", "value": "SP"}])
    page = client.get(url, params={"filters": filters}).json()
    assert 0 < page["filtered_count"] < full["filtered_count"]
    assert page["profile_scope"] == "filtered"
    uf = next(c for c in page["profile"]["columns"] if c["name"] == "uf")
    assert uf["unique_count"] == 1
    bad = client.get(url, params={"filters": '[{"column": "uf", "op": "magic"}]'})
    assert bad.status_code == 400
