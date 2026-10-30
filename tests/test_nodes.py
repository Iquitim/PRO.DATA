from pathlib import Path

import polars as pl

from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext, catalog


def run(tool: str, inputs: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: object):
    spec = REGISTRY[tool]
    ctx = NodeContext(inputs, {}, store, tmp_path)
    return spec.run(ctx, spec.config.model_validate(config))


def test_catalog_describes_every_field() -> None:
    tools = {t["type"]: t for t in catalog()}
    assert len(tools) >= 21
    join_keys = next(f for f in tools["transform.join"]["config_fields"] if f["name"] == "keys")
    assert join_keys["widget"] == "list"
    assert [f["port"] for f in join_keys["item_fields"]] == ["L", "R"]
    op = next(f for f in tools["prep.filter"]["config_fields"] if f["name"] == "operator")
    assert op["widget"] == "select" and {"value": ">=", "label": "maior ou igual a"} in op["options"]
    for tool in tools.values():
        for field in tool["config_fields"]:
            assert field["widget"], (tool["type"], field["name"])


def test_join_emits_l_j_r(store: DatasetStore, tmp_path: Path) -> None:
    left = pl.DataFrame({"id": [1, 2, 3], "x": ["a", "b", "c"]})
    right = pl.DataFrame({"id": [2, 3, 4], "x": ["B", "C", "D"]})
    out = run(
        "transform.join", {"L": left, "R": right}, store, tmp_path, keys=[{"left": "id", "right": "id"}]
    )
    assert out.tables["L"]["id"].to_list() == [1]
    assert out.tables["R"]["id"].to_list() == [4]
    # As duas chaves ficam no J (spec 018): a da direita com prefixo quando o nome coincide.
    assert out.tables["J"].columns == ["id", "x", "r_id", "r_x"]


def test_unique_splits_first_and_duplicates(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"k": [1, 1, 2, 1], "v": [1, 2, 3, 4]})
    out = run("prep.unique", {"in": df}, store, tmp_path, keys=["k"])
    assert out.tables["U"]["v"].to_list() == [1, 3]
    assert out.tables["D"]["v"].to_list() == [2, 4]


def test_select_drops_renames_casts(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"a": ["1", "2"], "b": [1, 2], "c": [0, 0]})
    out = run(
        "prep.select",
        {"in": df},
        store,
        tmp_path,
        fields=[
            {"name": "a", "rename": "a_num", "cast": "Int64"},
            {"name": "c", "keep": False},
        ],
    )
    assert out.tables["out"].schema == pl.Schema({"a_num": pl.Int64, "b": pl.Int64})


def test_simple_filter_on_numeric_with_comma_decimal(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"v": [1.0, 2.5, 3.0]})
    out = run(
        "prep.filter", {"in": df}, store, tmp_path, mode="simple", column="v", operator=">=", value="2,5"
    )
    assert out.tables["T"]["v"].to_list() == [2.5, 3.0]
    assert out.tables["F"].height == 1


def test_text_input_infers_types(store: DatasetStore, tmp_path: Path) -> None:
    out = run(
        "io.text_input",
        {},
        store,
        tmp_path,
        table={
            "columns": ["n", "x", "ok", "t"],
            "rows": [["1", "1,5", "sim", "a"], ["2", "", "não", "b"]],
        },
    )
    df = out.tables["out"]
    assert df.schema == pl.Schema({"n": pl.Int64, "x": pl.Float64, "ok": pl.Boolean, "t": pl.String})
    assert df["x"].to_list() == [1.5, None]


def test_summarize_and_count_all(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"g": ["a", "a", "b"], "v": [1, None, 3]})
    out = run(
        "transform.summarize",
        {"in": df},
        store,
        tmp_path,
        group_by=["g"],
        aggregations=[
            {"column": "v", "agg": "sum", "alias": "s"},
            {"column": "v", "agg": "count", "alias": "c"},
            {"agg": "count_all", "alias": "n"},
        ],
    )
    assert out.tables["out"].rows() == [("a", 1, 1, 2), ("b", 3, 1, 1)]


def test_union_by_position(store: DatasetStore, tmp_path: Path) -> None:
    a = pl.DataFrame({"x": [1]})
    b = pl.DataFrame({"y": [2]})
    out = run("transform.union", {"in1": a, "in2": b}, store, tmp_path, mode="by_position")
    assert out.tables["out"]["x"].to_list() == [1, 2]


def test_output_data_cannot_escape_exports(store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({"a": [1]})
    out = run("io.output_data", {"in": df}, store, tmp_path, filename="../../fora", format="csv")
    assert out.extra["exported_file"] == "fora.csv"
    assert (tmp_path / "fora.csv").exists()
