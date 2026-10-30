"""Correções da versão 0.4 (spec 018)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from prodata.engine import formula
from prodata.engine.convert import convert
from prodata.engine.profiling import profile_column
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore, ReadOptions, inspect_file, read_table
from prodata.ingestion.detect import detect_format
from prodata.nodes import REGISTRY, NodeContext

XLSB = Path(__file__).parent / "data" / "amostra.xlsb"


def run(tool: str, inputs: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: object):
    spec = REGISTRY[tool]
    ctx = NodeContext(inputs, {}, store, tmp_path)
    return spec.run(ctx, spec.config.model_validate(config))


# ------------------------------------------------------------------ RF-1802: xlsb


def test_xlsb_is_read_like_excel() -> None:
    assert detect_format(XLSB) == "excel"
    info = inspect_file(XLSB, ReadOptions())
    assert "issue2" in info["sheets"] and len(info["sheets"]) > 1
    df = read_table(XLSB, ReadOptions(sheet="issue2"))
    assert df.shape == (2, 2)


# ------------------------------------------------------------------ RF-1804: conversões do Select


@pytest.mark.parametrize(
    ("values", "target", "expected"),
    [
        ([" 12 ", "7", None], pl.Int64, [12, 7, None]),
        (["1.234,56", "12,5", "R$ 1.500,00", "3.5"], pl.Float64, [1234.56, 12.5, 1500.0, 3.5]),
        (["sim", "NÃO", "1", "false"], pl.Boolean, [True, False, True, False]),
        (["29/10/2026", "2026-10-30"], pl.Date, [date(2026, 10, 29), date(2026, 10, 30)]),
        ([45229, None], pl.Date, [date(2023, 10, 30), None]),  # número de série do Excel
    ],
)
def test_convert_is_tolerant(values: list[object], target: pl.DataType, expected: list[object]) -> None:
    result = convert(pl.Series("c", values), target)
    assert result.series.to_list() == expected
    assert result.failed == 0


def test_convert_reports_failures() -> None:
    result = convert(pl.Series("c", ["10", "abc", "", None]), pl.Int64)
    assert result.series.to_list() == [10, None, None, None]
    assert result.failed == 1 and result.examples == ["abc"]


def test_select_orders_columns_and_warns(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"a": ["1", "x"], "b": ["01/02/2026", "02/02/2026"], "c": [1, 2]})
    out = run(
        "prep.select",
        {"in": df},
        store,
        tmp_path,
        fields=[{"name": "a", "cast": "Int64"}, {"name": "b", "cast": "Date", "rename": "data"}],
        order=["c", "b"],
    )
    table = out.tables["out"]
    assert table.columns == ["c", "data", "a"]  # "a" não estava na ordem: vai para o fim
    assert table["data"].to_list() == [date(2026, 2, 1), date(2026, 2, 2)]
    assert table["a"].to_list() == [1, None]
    [warning] = out.extra["warnings"]
    assert "a" in warning and "1 valor" in warning and "x" in warning


# ------------------------------------------------------------------ RF-1806: média e soma entre colunas


def test_row_functions_across_columns() -> None:
    df = pl.DataFrame({"a": [1.0, None, 10.0], "b": [3.0, 4.0, None], "c": [5.0, 5.0, None]})
    out = formula.evaluate_columns(
        df,
        [
            {"column": "media", "type": "Float64", "expression": "Average([a], [b], [c])"},
            {"column": "soma", "type": "Float64", "expression": "Sum([a], [b], [c])"},
            {"column": "mediana", "type": "Float64", "expression": "Median([a], [b], [c])"},
            {"column": "maior", "type": "Float64", "expression": "Max([a], [b], [c])"},
            {"column": "menor", "type": "Float64", "expression": "Min([a], Round([b], 0))"},
        ],
    )
    assert out["media"].to_list() == [3.0, 4.5, 10.0]
    assert out["soma"].to_list() == [9.0, 9.0, 10.0]
    assert out["mediana"].to_list() == [3.0, 4.5, 10.0]
    assert out["maior"].to_list() == [5.0, 5.0, 10.0]
    assert out["menor"].to_list() == [1.0, 4.0, 10.0]


# ------------------------------------------------------------------ RF-1807: chaves do Join


def test_join_keeps_calculated_key_from_both_sides(store: DatasetStore, tmp_path: Path) -> None:
    """Coluna criada por Formula e usada como chave não pode sumir do J."""
    left = pl.DataFrame({"id": [1, 2], "x": ["a", "b"]})
    right = pl.DataFrame({"chave": [2, 3], "y": ["B", "C"]})
    out = run(
        "transform.join", {"L": left, "R": right}, store, tmp_path, keys=[{"left": "id", "right": "chave"}]
    )
    assert out.tables["J"].columns == ["id", "x", "chave", "y"]
    assert out.tables["J"].row(0) == (2, "b", 2, "B")


def test_join_after_formula_keeps_new_column(tmp_path: Path, runner: WorkflowRunner) -> None:
    from prodata.domain.workflow import Workflow

    pl.DataFrame({"id": [1, 2], "v": [10, 20]}).write_csv(tmp_path / "datasets" / "a.csv")
    pl.DataFrame({"k": ["1-x", "2-x"], "w": [1, 2]}).write_csv(tmp_path / "datasets" / "b.csv")
    wf = Workflow.model_validate(
        {
            "id": "wf-join",
            "name": "join",
            "nodes": [
                {"id": "a", "type": "io.input_data", "config": {"dataset": "a.csv"}},
                {"id": "b", "type": "io.input_data", "config": {"dataset": "b.csv"}},
                {
                    "id": "f",
                    "type": "prep.formula",
                    "config": {
                        "formulas": [
                            {"column": "k", "type": "String", "expression": "Concat(ToString([id]), '-x')"}
                        ]
                    },
                },
                {"id": "j", "type": "transform.join", "config": {"keys": [{"left": "k", "right": "k"}]}},
            ],
            "edges": [
                {"id": "e1", "source": "a", "source_handle": "out", "target": "f", "target_handle": "in"},
                {"id": "e2", "source": "f", "source_handle": "out", "target": "j", "target_handle": "L"},
                {"id": "e3", "source": "b", "source_handle": "out", "target": "j", "target_handle": "R"},
            ],
        }
    )
    report = runner.run(wf)
    assert report.node_results["j"].status == "executed", {k: r.error for k, r in report.node_results.items()}
    columns = [c.name for c in report.node_results["j"].anchors["J"].columns]
    assert "k" in columns and "r_k" in columns


# ------------------------------------------------------------------ RF-1808: espaços em branco


def test_profile_counts_blank_and_padded_text() -> None:
    profile = profile_column(pl.Series("uf", ["SP", "SP ", "  ", "", " RJ", None]))
    assert profile["empty_count"] == 2
    assert profile["padded_count"] == 2
    assert profile["null_count"] == 1


# ------------------------------------------------------------------ RF-1809: andamento da execução


def test_progress_is_empty_when_idle(runner: WorkflowRunner) -> None:
    assert runner.progress("nada") == {"running": None, "done": {}, "order": [], "active": False}
