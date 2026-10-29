"""Spec 013: Cross Tab, Transpose, Text To Columns, Record ID, Running Total e Append Fields."""

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

VENDAS = pl.DataFrame(
    {
        "uf": ["SP", "SP", "RJ", "RJ", "SP"],
        "mes": ["jan", "fev", "jan", "fev", "jan"],
        "valor": [10.0, 20.0, 5.0, 7.0, 1.0],
    }
)


def run(tool: str, tables: dict[str, pl.DataFrame], tmp_path: Path, **config: Any) -> pl.DataFrame:
    spec = REGISTRY[tool]
    ctx = NodeContext(tables, {}, DatasetStore(tmp_path / "d", 10), tmp_path)
    return spec.run(ctx, spec.config.model_validate(config)).tables["out"]


def test_crosstab_turns_rows_into_columns(tmp_path: Path) -> None:
    out = run("transform.crosstab", {"in": VENDAS}, tmp_path, group_by=["uf"], header="mes", value="valor")
    rows = {r["uf"]: r for r in out.to_dicts()}
    assert out.columns == ["uf", "jan", "fev"]
    assert rows["SP"]["jan"] == 11.0 and rows["RJ"]["fev"] == 7.0


def test_crosstab_count_and_concat(tmp_path: Path) -> None:
    count = run(
        "transform.crosstab",
        {"in": VENDAS},
        tmp_path,
        group_by=["uf"],
        header="mes",
        value="valor",
        agg="count",
    )
    assert {r["uf"]: r["jan"] for r in count.to_dicts()} == {"SP": 2, "RJ": 1}
    text = run("transform.crosstab", {"in": VENDAS}, tmp_path, header="uf", value="mes", agg="concat")
    assert text.height == 1 and text["SP"][0] == "jan, fev, jan"


def test_transpose_turns_columns_into_rows(tmp_path: Path) -> None:
    wide = pl.DataFrame({"uf": ["SP", "RJ"], "jan": [1, 2], "fev": [3, 4]})
    out = run("transform.transpose", {"in": wide}, tmp_path, keys=["uf"])
    assert out.columns == ["uf", "nome", "valor"] and out.height == 4
    assert set(out.filter(pl.col("uf") == "SP")["valor"].to_list()) == {1, 3}


def test_transpose_mixed_types_become_text(tmp_path: Path) -> None:
    wide = pl.DataFrame({"id": [1], "nome": ["Ana"], "idade": [30]})
    out = run("transform.transpose", {"in": wide}, tmp_path, keys=["id"], name_column="campo")
    assert out.schema["valor"] == pl.String and set(out["valor"]) == {"Ana", "30"}


def test_text_to_columns_in_place_and_rows(tmp_path: Path) -> None:
    df = pl.DataFrame({"id": [1, 2], "local": ["SP - São Paulo", "RJ - Rio - Centro"], "x": [0, 0]})
    out = run("prep.text_to_columns", {"in": df}, tmp_path, column="local", delimiter="-")
    assert out.columns == ["id", "local_1", "local_2", "local_3", "x"]
    assert out.row(1) == (2, "RJ", "Rio", "Centro", 0) and out["local_3"][0] is None
    rows = run("prep.text_to_columns", {"in": df}, tmp_path, column="local", delimiter="-", mode="rows")
    assert rows.height == 5 and rows["local"].to_list()[:2] == ["SP", "São Paulo"]


def test_record_id(tmp_path: Path) -> None:
    out = run("prep.record_id", {"in": VENDAS}, tmp_path)
    assert out.columns[0] == "record_id" and out["record_id"].to_list() == [1, 2, 3, 4, 5]
    last = run("prep.record_id", {"in": VENDAS}, tmp_path, column="n", start=100, position="last")
    assert last.columns[-1] == "n" and last["n"][0] == 100


def test_running_total_by_group(tmp_path: Path) -> None:
    out = run("prep.running_total", {"in": VENDAS}, tmp_path, columns=["valor"], group_by=["uf"])
    assert out["acumulado_valor"].to_list() == [10.0, 30.0, 5.0, 12.0, 31.0]
    with pytest.raises(ValueError, match="numéricas"):
        run("prep.running_total", {"in": VENDAS}, tmp_path, columns=["uf"])


def test_append_fields_cross_join(tmp_path: Path) -> None:
    params = pl.DataFrame({"taxa": [0.07], "uf": ["XX"]})
    out = run("transform.append_fields", {"T": VENDAS, "S": params}, tmp_path)
    assert out.height == VENDAS.height and out["taxa"].unique().to_list() == [0.07]
    assert "s_uf" in out.columns  # coluna repetida ganha prefixo
