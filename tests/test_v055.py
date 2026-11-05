"""Versão 0.5.5 (spec 021): Excel com várias tabelas e Multi-Row Formula."""

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import fastexcel
import polars as pl
import pytest

from prodata.domain.workflow import Workflow
from prodata.engine.runner import WorkflowRunner
from prodata.engine.sql.fragment import SQL_REGISTRY, SqlContext, SqlInput, kind_of
from prodata.engine.sql.macros import install_all
from prodata.engine.sql.verify import SAME, compare
from prodata.errors import InvalidInputError
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext


def run(tool: str, inputs: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: object):
    spec = REGISTRY[tool]
    return spec.run(NodeContext(inputs, {}, store, tmp_path), spec.config.model_validate(config))


# ------------------------------------------------------------------ Excel: várias tabelas na mesma caixa


A = pl.DataFrame({"a": [1, 2]})
B = pl.DataFrame({"b": ["x", "y", "z"]})
C = pl.DataFrame({"c": [1.5]})


def test_each_table_becomes_a_sheet(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "io.output_data",
        {"in": A, "in2": B, "in3": C},
        store,
        tmp_path,
        filename="pasta",
        format="excel",
        sheet_name="Primeira",
        sheet_names={"in2": "Segunda"},
        if_exists="replace",
    )
    book = fastexcel.read_excel(tmp_path / "pasta.xlsx")
    assert book.sheet_names == ["Primeira", "Segunda", "Planilha 3"]
    assert book.load_sheet("Segunda").to_polars().equals(B)
    assert out.extra["exported_sheets"] == ["Primeira", "Segunda", "Planilha 3"]
    assert out.tables["out"].equals(A)


def test_order_follows_the_ports_not_the_connection(store: DatasetStore, tmp_path: Path) -> None:
    run(
        "io.output_data",
        {"in": A, "in3": C, "in2": B},
        store,
        tmp_path,
        filename="o",
        format="excel",
        if_exists="replace",
    )
    assert fastexcel.read_excel(tmp_path / "o.xlsx").sheet_names == ["Dados", "Planilha 2", "Planilha 3"]


def test_add_sheet_keeps_what_is_there(store: DatasetStore, tmp_path: Path) -> None:
    run(
        "io.output_data",
        {"in": A},
        store,
        tmp_path,
        filename="p",
        format="excel",
        sheet_name="Antiga",
        if_exists="replace",
    )
    run(
        "io.output_data",
        {"in": B, "in2": C},
        store,
        tmp_path,
        filename="p",
        format="excel",
        sheet_name="N1",
        sheet_names={"in2": "N2"},
        if_exists="add_sheet",
    )
    assert fastexcel.read_excel(tmp_path / "p.xlsx").sheet_names == ["Antiga", "N1", "N2"]


@pytest.mark.parametrize(
    ("names", "message"),
    [
        ({"in2": "dados"}, "Duas planilhas"),
        ({"in2": "a/b"}, "não pode ter"),
        ({"in2": "x" * 32}, "31 caracteres"),
    ],
)
def test_bad_sheet_names_stop_before_writing(
    names: dict, message: str, store: DatasetStore, tmp_path: Path
) -> None:
    with pytest.raises(InvalidInputError, match=message):
        run(
            "io.output_data",
            {"in": A, "in2": B},
            store,
            tmp_path,
            filename="ruim",
            format="excel",
            sheet_names=names,
            if_exists="replace",
        )
    assert not (tmp_path / "ruim.xlsx").exists()


def test_other_formats_refuse_many_tables(store: DatasetStore, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="Excel"):
        run(
            "io.output_data",
            {"in": A, "in2": B},
            store,
            tmp_path,
            filename="c",
            format="csv",
            if_exists="replace",
        )


def test_single_table_is_unchanged(store: DatasetStore, tmp_path: Path) -> None:
    out = run("io.output_data", {"in": A}, store, tmp_path, filename="u", format="excel", if_exists="replace")
    assert fastexcel.read_excel(tmp_path / "u.xlsx").sheet_names == ["Dados"]
    assert "exported_sheets" not in out.extra


def test_runner_feeds_extra_ports(runner: WorkflowRunner, tmp_path: Path) -> None:
    flow = Workflow.model_validate(
        {
            "id": "wf-x",
            "name": "x",
            "nodes": [
                {
                    "id": "a",
                    "type": "io.text_input",
                    "label": "A",
                    "config": {"table": {"columns": ["a"], "rows": [["1"]]}},
                },
                {
                    "id": "b",
                    "type": "io.text_input",
                    "label": "B",
                    "config": {"table": {"columns": ["b"], "rows": [["2"]]}},
                },
                {
                    "id": "o",
                    "type": "io.output_data",
                    "label": "O",
                    "config": {"filename": "fluxo", "format": "excel", "if_exists": "replace"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "a", "sourceHandle": "out", "target": "o", "targetHandle": "in"},
                {"id": "e2", "source": "b", "sourceHandle": "out", "target": "o", "targetHandle": "in2"},
            ],
        }
    )
    report = runner.run(flow)
    assert report.node_results["o"].status == "executed", report.node_results["o"].error
    assert fastexcel.read_excel(tmp_path / "exports" / "fluxo.xlsx").sheet_names == ["Dados", "Planilha 2"]


# ------------------------------------------------------------------ Multi-Row Formula

DF = pl.DataFrame(
    {
        "g": ["a", "a", "a", "b", "b", None],
        "v": [10, 20, None, 5, 7, 1],
        "s": ["x", None, None, "y", None, None],
        "d": [date(2026, 1, 1), None, date(2026, 1, 3), None, date(2026, 2, 1), None],
    }
)


def multi(store: DatasetStore, tmp_path: Path, table: pl.DataFrame = DF, **config: Any) -> pl.DataFrame:
    return run("prep.multirow", {"in": table}, store, tmp_path, **config).tables["out"]


def test_previous_and_next_row(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="p", expression="[Row-1:v]")
    assert out["p"].to_list() == [None, 10, 20, None, 5, 7]
    out = multi(store, tmp_path, column="n", expression="[Row+1:v]")
    assert out["n"].to_list() == [20, None, 5, 7, 1, None]
    out = multi(store, tmp_path, column="d2", expression="[Row-2:v]")
    assert out["d2"].to_list() == [None, None, 10, 20, None, 5]


def test_difference_to_previous_row(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="dif", type="Int64", expression="[v] - [Row-1:v]")
    assert out["dif"].to_list() == [None, 10, None, None, 2, -6]


def test_references_do_not_cross_groups(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="p", expression="[Row-1:v]", group_by=["g"])
    assert out["p"].to_list() == [None, 10, 20, None, 5, None]


def test_missing_row_can_be_zero_or_empty(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="p", expression="[Row-1:v]", missing="empty")
    assert out["p"].to_list()[0] == 0
    out = multi(store, tmp_path, column="t", expression="[Row-1:s]", missing="empty")
    assert out["t"].to_list()[0] == ""


def test_fill_down_uses_the_value_just_calculated(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(
        store,
        tmp_path,
        target="existing",
        existing="s",
        expression="IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF",
    )
    assert out["s"].to_list() == ["x", "x", "x", "y", "y", "y"]
    assert out.columns == DF.columns  # alterar uma coluna mantém a posição


def test_fill_down_respects_groups(store: DatasetStore, tmp_path: Path) -> None:
    table = pl.DataFrame({"g": ["a", "a", "b", "b"], "s": ["x", None, None, "y"]})
    out = multi(
        store,
        tmp_path,
        table,
        target="existing",
        existing="s",
        expression="IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF",
        group_by=["g"],
    )
    assert out["s"].to_list() == ["x", "x", None, "y"]


def test_chain_builds_on_itself(store: DatasetStore, tmp_path: Path) -> None:
    table = pl.DataFrame({"v": [1, 2, 3, 4]})
    out = multi(store, tmp_path, table, column="ac", type="Int64", expression="COALESCE([Row-1:ac], 0) + [v]")
    assert out["ac"].to_list() == [1, 3, 6, 10]


def test_chain_can_look_two_rows_back(store: DatasetStore, tmp_path: Path) -> None:
    table = pl.DataFrame({"v": [1, 1, 1, 1, 1, 1]})
    out = multi(
        store,
        tmp_path,
        table,
        column="f",
        type="Int64",
        expression="COALESCE([Row-1:f], 0) + COALESCE([Row-2:f], 1)",
    )
    assert out["f"].to_list() == [1, 2, 3, 5, 8, 13]


def test_empty_table_keeps_the_column(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, DF.clear(), column="p", expression="[Row-1:v]")
    assert out.height == 0 and "p" in out.columns


def test_text_with_the_reference_is_not_touched(store: DatasetStore, tmp_path: Path) -> None:
    out = multi(store, tmp_path, column="t", expression="'[Row-1:v]'")
    assert set(out["t"].to_list()) == {"[Row-1:v]"}


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("[Row+1:nova]", "ainda não foi calculado"),
        ("[Row-1:nao_existe]", "inexistente"),
        ("[Row-101:v]", "entre 1 e 100"),
        ("[Row-0:v]", "entre 1 e 100"),
    ],
)
def test_invalid_references_explain_themselves(
    expression: str, message: str, store: DatasetStore, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=message):
        multi(store, tmp_path, column="nova", expression=expression)


def test_runaway_chain_stops_with_a_clear_message(
    store: DatasetStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prodata.engine import multirow

    monkeypatch.setattr(multirow, "MAX_PASSES", 3)
    table = pl.DataFrame({"v": list(range(50))})
    with pytest.raises(ValueError, match="Running Total"):
        multi(store, tmp_path, table, column="ac", type="Int64", expression="COALESCE([Row-1:ac], 0) + [v]")


def test_validation_accepts_row_references(client) -> None:
    columns = [{"name": "v", "type": "Int64"}]
    ok = client.post(
        "/api/formula/validate", json={"expression": "[v] - [Row-1:v]", "columns": columns, "multirow": True}
    ).json()
    assert ok["valid"], ok
    plain = client.post(
        "/api/formula/validate", json={"expression": "[v] - [Row-1:v]", "columns": columns}
    ).json()
    assert not plain["valid"]


SQL_CASES: list[dict[str, Any]] = [
    {"column": "p", "expression": "[Row-1:v]"},
    {"column": "p", "expression": "[Row-1:v]", "missing": "empty"},
    {"column": "n", "expression": "[Row+1:s]", "missing": "empty"},
    {"column": "d", "type": "Int64", "expression": "[v] - [Row-1:v]", "group_by": ["g"]},
    {"column": "p", "expression": "[Row-2:v]", "group_by": ["g"]},
    {"target": "existing", "existing": "v", "type": "Int64", "expression": "[v] + COALESCE([Row-1:v], 0)"},
]
SQL_ORDERED: list[dict[str, Any]] = [
    # Receitas da Multi-Row (spec 026): as mesmas fórmulas que os cartões escrevem.
    {"column": "r", "expression": "[v] - [Row-1:v]", "order_by": [{"column": "v"}]},
    {
        "column": "r",
        "expression": "IF IsNull([Row-1:v]) OR [Row-1:v] = 0 THEN Null ELSE ([v] - [Row-1:v]) / [Row-1:v] * 100 ENDIF",
        "order_by": [{"column": "v"}],
    },
    {"column": "r", "expression": "[Row+2:v]", "order_by": [{"column": "v"}]},
    {
        "column": "r",
        "expression": "IF IsNull([Row-1:v]) THEN 'Início' ELSEIF [v] == [Row-1:v] THEN 'Igual' ELSE 'Mudou' ENDIF",
        "order_by": [{"column": "v"}],
    },
    {
        "column": "r",
        "expression": "IF IsNull([v]) THEN [Row-1:r] ELSE [v] ENDIF",
        "order_by": [{"column": "d"}],
    },
    {"column": "p", "expression": "[Row-1:v]", "order_by": [{"column": "v"}]},
    {
        "column": "p",
        "expression": "[Row+1:v]",
        "order_by": [{"column": "d", "descending": True}, {"column": "v"}],
    },
    {
        "column": "p",
        "expression": "[Row-1:v]",
        "group_by": ["g"],
        "order_by": [{"column": "v", "descending": True}],
    },
    {
        "target": "existing",
        "existing": "s",
        "expression": "IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF",
        "order_by": [{"column": "v"}],
    },
    {
        "column": "ac",
        "type": "Int64",
        "expression": "COALESCE([Row-1:ac], 0) + COALESCE([v], 0)",
        "group_by": ["g"],
        "order_by": [{"column": "v", "descending": True}],
    },
]
SQL_CHAINS: list[dict[str, Any]] = [
    {"target": "existing", "existing": "s", "expression": "IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF"},
    {
        "target": "existing",
        "existing": "s",
        "expression": "IF IsNull([s]) THEN [Row-1:s] ELSE [s] ENDIF",
        "group_by": ["g"],
    },
    {"column": "ac", "type": "Int64", "expression": "COALESCE([Row-1:ac], 0) + COALESCE([v], 0)"},
    {
        "column": "ac",
        "type": "Int64",
        "expression": "COALESCE([Row-1:ac], 0) + COALESCE([v], 0)",
        "group_by": ["g"],
    },
    {"column": "ac", "type": "Int64", "expression": "[Row-1:ac] + COALESCE([v], 0)", "missing": "empty"},
]


@pytest.mark.parametrize("config", SQL_CASES + SQL_CHAINS + SQL_ORDERED, ids=str)
def test_sql_matches_engine(config: dict[str, Any], store: DatasetStore, tmp_path: Path) -> None:
    spec = REGISTRY["prep.multirow"]
    cfg = spec.config.model_validate(config)
    engine = spec.run(NodeContext({"in": DF}, {}, store, tmp_path), cfg).tables["out"]
    con = duckdb.connect(":memory:")
    install_all(con)
    con.register("entrada", DF)
    rows = con.execute('DESCRIBE "entrada"').fetchall()
    source = SqlInput("entrada", [str(r[0]) for r in rows], {str(r[0]): kind_of(str(r[1])) for r in rows})
    fragment = SQL_REGISTRY["prep.multirow"](SqlContext({"in": source}, sample=lambda _p: DF), cfg)["out"]
    check = compare(con.sql(fragment.sql).pl(), engine)
    con.close()
    assert check.state == SAME, (check.detail, check.examples, fragment.sql)


def test_chain_beyond_one_row_has_no_sql(store: DatasetStore, tmp_path: Path) -> None:
    from prodata.engine.sql.fragment import NoTranslationError

    spec = REGISTRY["prep.multirow"]
    cfg = spec.config.model_validate({"column": "f", "expression": "[Row-2:f]"})
    source = SqlInput("entrada", ["v"], {"v": "Int"})
    with pytest.raises(NoTranslationError):
        SQL_REGISTRY["prep.multirow"](SqlContext({"in": source}), cfg)
