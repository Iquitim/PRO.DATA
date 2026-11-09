"""Spec 032: valores vazios em fórmulas e filtros, cores por categoria e correções de tela."""

from pathlib import Path

import polars as pl
import pytest

from prodata.dashboard.formats import FORMATS, clean_format, describe_formats
from prodata.engine import formula
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

WEB = Path(__file__).parents[1] / "src/prodata/web"
DF = pl.DataFrame({"t": ["a", "", "   ", None], "n": [1.0, None, 3.0, None]})


def mask(expression: str) -> list[bool]:
    return formula.evaluate_mask(DF, expression).to_list()


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("IsNotNull([t])", [True, True, True, False]),
        ("IsNotEmpty([t])", [True, False, False, False]),
        ("IsNotNull([n])", [True, False, True, False]),
        ("IsNotEmpty([n])", [True, False, True, False]),
        ("[t] != Null", [True, True, True, False]),
        ("[t] <> null", [True, True, True, False]),
        ("[t] == Null", [False, False, False, True]),
        ("[t] = NULL", [False, False, False, True]),
        ("[n] != Null AND [n] > 2", [False, False, True, False]),
    ],
)
def test_empty_values_in_formulas(expression: str, expected: list[bool]) -> None:
    assert mask(expression) == expected


def test_null_inside_text_is_not_a_comparison() -> None:
    frame = pl.DataFrame({"t": ["= Null", "x"]})
    assert formula.evaluate_mask(frame, "[t] == '= Null'").to_list() == [True, False]


def test_comparison_with_greater_or_equal_null_is_untouched() -> None:
    assert ">= NULL" in formula.transpile("[n] >= NULL")


@pytest.mark.parametrize(
    ("operator", "kept"),
    [("is_empty", ["", "   ", None]), ("is_not_empty", ["a"])],
)
def test_filter_empty_operators(
    store: DatasetStore, tmp_path: Path, operator: str, kept: list[str | None]
) -> None:
    spec = REGISTRY["prep.filter"]
    cfg = spec.config.model_validate({"mode": "simple", "column": "t", "operator": operator})
    out = spec.run(NodeContext({"in": DF}, {}, store, tmp_path), cfg)
    assert out.tables["T"]["t"].to_list() == kept
    assert out.tables["T"].height + out.tables["F"].height == DF.height


def test_empty_operators_do_not_ask_for_a_value() -> None:
    fields = {f["name"]: f for f in REGISTRY["prep.filter"].describe()["config_fields"]}
    operators = {o["value"]: o["label"] for o in fields["operator"]["options"]}
    assert operators["is_not_empty"] == "está preenchido"
    assert "is_not_empty" not in fields["value"]["show_if"]["operator"]


def test_category_colors_are_always_offered() -> None:
    fields = {f["name"]: f for f in describe_formats()["chart"]}
    assert not fields["category_colors"].get("show_if")
    assert fields["other_palette"]["show_if"] == {"palette": ["custom"]}


def test_other_palette_is_kept_in_the_saved_format() -> None:
    saved = clean_format(
        "visual", {"palette": "custom", "other_palette": "single", "category_colors": {"SP": "#112233"}}
    )
    assert saved == {"palette": "custom", "other_palette": "single", "category_colors": {"SP": "#112233"}}
    assert "other_palette" in FORMATS["chart"].model_fields


def test_switch_input_scrolls_with_its_panel() -> None:
    css = (WEB / "css/app.css").read_text(encoding="utf-8")
    rule = next(line for line in css.splitlines() if line.startswith(".switch {"))
    assert "position: relative" in rule


def test_scrollbar_does_not_change_the_dashboard_width() -> None:
    css = (WEB / "css/dashboard.css").read_text(encoding="utf-8")
    rule = next(line for line in css.splitlines() if line.startswith(".dashboard {"))
    assert "scrollbar-gutter: stable" in rule
