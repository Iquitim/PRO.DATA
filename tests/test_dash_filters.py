"""Filtros da página do dashboard e dados do HTML exportado (spec 021)."""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.dashboard.filters import (
    ExportTables,
    apply_filters,
    filter_options,
    json_values,
    used_columns,
)
from prodata.dashboard.viewer import MODULES, build_viewer, wrap_module
from prodata.desktop import generated_name, write_generated
from prodata.domain.dashboard import Dashboard, DashFilter
from prodata.domain.workflow import Workflow
from prodata.main import WEB_DIR
from prodata.nodes.bi import ChartConfig, KpiConfig, TableConfig, VennConfig

DF = pl.DataFrame(
    {
        "uf": ["SP", "RJ", None, "SP"],
        "valor": [10.0, 20.0, 30.0, None],
        "dia": [date(2026, 1, 1), date(2026, 2, 1), None, date(2026, 3, 1)],
    }
)


def f(column: str, **fields: Any) -> DashFilter:
    return DashFilter(id=f"f_{column}", column=column, **fields)


def test_list_filter_with_empty_value() -> None:
    out, missing = apply_filters(DF, [f("uf", selected=["SP"])])
    assert out.height == 2 and missing == []
    assert apply_filters(DF, [f("uf", selected=["(vazio)"])])[0]["valor"].to_list() == [30.0]


def test_inactive_filter_changes_nothing() -> None:
    assert apply_filters(DF, [f("uf"), f("valor", kind="number")])[0].height == 4


def test_number_range_is_inclusive_and_drops_empty() -> None:
    out, _ = apply_filters(DF, [f("valor", kind="number", min=10, max=20)])
    assert out["valor"].to_list() == [10.0, 20.0]
    assert apply_filters(DF, [f("valor", kind="number", min=25)])[0]["valor"].to_list() == [30.0]


def test_date_range() -> None:
    out, _ = apply_filters(DF, [f("dia", kind="date", min="2026-01-15", max="2026-02-15")])
    assert out["dia"].to_list() == [date(2026, 2, 1)]


def test_filters_add_up() -> None:
    out, _ = apply_filters(DF, [f("uf", selected=["SP"]), f("valor", kind="number", max=15)])
    assert out["valor"].to_list() == [10.0]


def test_column_absent_is_reported_and_keeps_data() -> None:
    out, missing = apply_filters(DF, [f("outra", selected=["x"])])
    assert out.height == 4 and missing == ["outra"]


def test_options_describe_each_kind() -> None:
    options = {o["column"]: o for o in filter_options([DF, DF.select("uf")])}
    assert options["uf"]["kind"] == "list" and options["uf"]["visuals"] == 2
    assert options["uf"]["values"] == ["(vazio)", "RJ", "SP"]
    assert (options["valor"]["min"], options["valor"]["max"]) == (10.0, 30.0)
    assert (options["dia"]["min"], options["dia"]["max"]) == ("2026-01-01", "2026-03-01")


def test_many_values_are_cut_and_say_so() -> None:
    many = pl.DataFrame({"c": [f"v{i:04}" for i in range(600)]})
    option = filter_options([many])[0]
    assert len(option["values"]) == 500 and option["truncated"]


def test_old_flows_open_without_filters() -> None:
    assert Dashboard.model_validate({"items": []}).filters == []


def test_only_needed_columns_go_to_the_file() -> None:
    table = DF.with_columns(pl.lit("segredo").alias("cpf"))
    filters = [f("uf", selected=["SP"])]
    assert used_columns("bi.chart", ChartConfig(x_column="dia", y_column="valor"), table, filters) == [
        "dia",
        "valor",
        "uf",
    ]
    assert used_columns("bi.kpi_card", KpiConfig(column="valor"), table, []) == ["valor"]
    assert used_columns("bi.venn", VennConfig(key_column="uf", group_column="dia"), table, []) == [
        "uf",
        "dia",
    ]
    assert used_columns("bi.table", TableConfig(columns=["uf"], sort_column="valor"), table, []) == [
        "uf",
        "valor",
    ]


def test_values_become_plain_json() -> None:
    assert json_values(pl.Series([date(2026, 1, 2), None])) == ["2026-01-02", None]
    assert json_values(pl.Series([1.5, float("nan"), float("inf"), None])) == [1.5, None, None, None]
    assert json_values(pl.Series([[1], [2]])) is not None


def test_equal_columns_are_stored_once() -> None:
    tables = ExportTables()
    assert tables.add(pl.Series("a", [1, 2])) == tables.add(pl.Series("b", [1, 2]))
    assert len(tables.columns) == 1 and tables.bytes == len("[1,2]")


# ------------------------------------------------------------------ rotas


def flow(client: Any, filters: list[dict], extra_items: list[dict] | None = None) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "wf-filtro",
            "name": "x",
            "nodes": [
                {
                    "id": "t",
                    "type": "io.text_input",
                    "label": "T",
                    "config": {
                        "table": {
                            "columns": ["uf", "v", "cpf"],
                            "rows": [["SP", "1", "a"], ["RJ", "2", "b"], ["SP", "3", "c"]],
                        }
                    },
                },
                {
                    "id": "o",
                    "type": "io.text_input",
                    "label": "O",
                    "config": {"table": {"columns": ["z", "v"], "rows": [["q", "5"]]}},
                },
                {
                    "id": "c",
                    "type": "bi.chart",
                    "label": "C",
                    "config": {"title": "G", "x_column": "uf", "y_column": "v"},
                },
                {"id": "k", "type": "bi.kpi_card", "label": "K", "config": {"title": "S", "column": "v"}},
                {
                    "id": "sem",
                    "type": "bi.kpi_card",
                    "label": "Sem",
                    "config": {"title": "S2", "column": "v"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "t", "sourceHandle": "out", "target": "c", "targetHandle": "in"},
                {"id": "e2", "source": "t", "sourceHandle": "out", "target": "k", "targetHandle": "in"},
                {"id": "e3", "source": "o", "sourceHandle": "out", "target": "sem", "targetHandle": "in"},
            ],
            "dashboard": {
                "filters": filters,
                "items": [
                    {"id": "i1", "kind": "visual", "node_id": "c"},
                    {"id": "i2", "kind": "visual", "node_id": "k"},
                    {"id": "i3", "kind": "visual", "node_id": "sem"},
                ],
            },
        }
    )


def run_and_post(client: Any, route: str, workflow: Workflow) -> Any:
    body = workflow.model_dump(mode="json", by_alias=True)
    res = client.post("/api/execute", json={"workflow": body})
    assert res.status_code == 200, res.text
    answer = client.post(f"/api/dashboard/{route}", json={"workflow": body})
    assert answer.status_code == 200, answer.text
    return answer.json()


SP = {"id": "f1", "column": "uf", "kind": "list", "selected": ["SP"]}


def test_filtered_recalculates_without_running_the_flow(client: Any) -> None:
    out = run_and_post(client, "filtered", flow(client, [SP]))
    assert out["widgets"]["k"]["value"] == 4.0
    assert "c" not in out["widgets"]  # gráfico por uf: mantém as categorias e apaga as de fora, na tela
    assert out["no_column"] == {"sem": ["uf"]}
    assert "sem" not in out["widgets"]


def test_no_active_filter_recalculates_nothing(client: Any) -> None:
    out = run_and_post(client, "filtered", flow(client, [{**SP, "selected": []}]))
    assert out == {"widgets": {}, "no_column": {}}


def test_a_visual_that_cannot_be_calculated_explains(client: Any) -> None:
    workflow = flow(client, [SP])
    node = workflow.node("k")
    node.config = {"title": "S", "column": "v", "compare": "previous", "date_column": "uf"}
    body = workflow.model_dump(mode="json", by_alias=True)
    client.post("/api/execute", json={"workflow": body})
    out = client.post("/api/dashboard/filtered", json={"workflow": body}).json()
    assert out["widgets"].get("k", {"widget_type": "message"})["widget_type"] == "message"


def test_filter_options_route(client: Any) -> None:
    options = {o["column"]: o for o in run_and_post(client, "filter-options", flow(client, []))}
    assert options["v"]["visuals"] == 3 and options["uf"]["visuals"] == 2


def test_export_carries_only_what_filters_need(client: Any) -> None:
    out = run_and_post(client, "export-data", flow(client, [SP]))
    assert set(out["nodes"]) == {"c", "k"}  # "sem" não tem a coluna: vai só o número pronto
    assert out["column_names"] == ["uf", "v"]
    assert "cpf" not in str(out["nodes"])
    assert not any(
        "a" in v for v in out["columns"].values() if all(isinstance(x, str) and len(x) == 1 for x in v)
    )
    assert out["rows"] == 3


def test_export_beyond_the_limit_does_not_send_data(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("prodata.api.routes.dashboard.MAX_EXPORT_BYTES", 1)
    out = run_and_post(client, "export-data", flow(client, [SP]))
    assert out["too_large"] is True and "columns" not in out


def test_stale_results_are_not_used(client: Any) -> None:
    workflow = flow(client, [SP])
    body = workflow.model_dump(mode="json", by_alias=True)
    client.post("/api/execute", json={"workflow": body})
    workflow.node("k").config = {"title": "Outro", "column": "v", "metric": "mean"}
    changed = workflow.model_dump(mode="json", by_alias=True)
    out = client.post("/api/dashboard/filtered", json={"workflow": changed}).json()
    assert "k" not in out["widgets"]


# ------------------------------------------------------------------ o script do HTML


def test_viewer_has_no_imports_left() -> None:
    script = build_viewer(WEB_DIR / "js")
    assert "import {" not in script
    assert "from './" not in script
    assert "\nexport " not in script
    assert "fetch(" not in script  # o arquivo não busca nada na rede
    for name in MODULES:
        assert f"__m['{name}']" in script


def test_viewer_module_shape() -> None:
    out = wrap_module(
        "x.js", "import { a, b as c } from './y.js';\nexport function f() {}\nexport const g = 1;\n"
    )
    assert "const { a, b: c } = __m['y.js'];" in out
    assert "function f()" in out and "export" not in out
    assert "__m['x.js'] = { f, g };" in out


@pytest.mark.parametrize(
    "source", ["import x from './y.js';\n", "export default 1;\n", "const m = import('./y.js');\n"]
)
def test_viewer_refuses_what_it_cannot_join(source: str) -> None:
    with pytest.raises(ValueError):
        wrap_module("x.js", source)


# ------------------------------------------------------------------ salvar


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Painel.html", "Painel.html"),
        ("a/b.HTML", "b.html"),
        ("x.sql", "x.sql"),
        ("y.zip", "y.zip"),
        ("z", "z.sql"),
        ("a*b.html", "a b.html"),
    ],
)
def test_generated_names(given: str, expected: str) -> None:
    assert generated_name(given) == expected


def test_html_is_written_where_asked(tmp_path: Path) -> None:
    path = write_generated(str(tmp_path / "painel"), "painel.html", "data:text/html;base64,PGh0bWw+")
    assert path.name == "painel.html" and path.read_text() == "<html>"
