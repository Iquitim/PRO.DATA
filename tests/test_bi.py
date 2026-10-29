"""Spec 014 fase 3: KPI com comparação e tendência, gráficos com 2ª dimensão, Pareto, dispersão, Venn e Table."""

import math
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext
from prodata.nodes.bi import as_date, lens_area, venn2_geometry

VENDAS = pl.DataFrame(
    {
        "uf": ["SP", "SP", "RJ", "RJ", "SP", "MG", "SP", "RJ"],
        "produto": ["A", "B", "A", "B", "A", "A", "C", "C"],
        "mes": ["2026-08", "2026-08", "2026-09", "2026-09", "2026-10", "2026-10", "2026-10", "2026-10"],
        "valor": [10.0, 20.0, 5.0, 7.0, 30.0, 3.0, 2.0, 1.0],
        "cliente": ["c1", "c1", "c2", "c3", "c4", "c2", "c1", "c5"],
    }
)


def widget(tool: str, df: pl.DataFrame, tmp_path: Path, **config: Any) -> dict[str, Any]:
    spec = REGISTRY[tool]
    ctx = NodeContext({"in": df}, {}, DatasetStore(tmp_path / "d", 10), tmp_path)
    out = spec.run(ctx, spec.config.model_validate(config))
    assert out.tables["out"] is df  # ferramentas de BI repassam a entrada
    return out.extra["bi_widget"]


# ------------------------------------------------------------------ KPI


def test_kpi_against_previous_period(tmp_path: Path) -> None:
    w = widget(
        "bi.kpi_card", VENDAS, tmp_path, column="valor", compare="previous", date_column="mes", sparkline=True
    )
    assert w["value"] == 36.0  # outubro: 30 + 3 + 2 + 1
    assert w["period_label"] == "out/2026"
    c = w["compare"]
    assert c["reference"] == 12.0 and c["delta"] == 24.0 and c["delta_pct"] == 200.0 and c["good"] is True
    assert c["label"] == "vs set/2026"
    assert [t["value"] for t in w["trend"]] == [30.0, 12.0, 36.0]


def test_kpi_lower_is_better_and_target(tmp_path: Path) -> None:
    w = widget(
        "bi.kpi_card", VENDAS, tmp_path, column="valor", compare="target", target=100, higher_is_better=False
    )
    assert w["value"] == 78.0 and w["compare"]["delta"] == -22.0 and w["compare"]["good"] is True
    g = widget("bi.kpi_card", VENDAS, tmp_path, column="valor", display="gauge", compare="target", target=100)
    assert g["gauge_max"] >= 100 and g["target"] == 100


def test_kpi_previous_needs_two_periods(tmp_path: Path) -> None:
    one = VENDAS.filter(pl.col("mes") == "2026-10")
    with pytest.raises(ValueError, match="dois períodos"):
        widget("bi.kpi_card", one, tmp_path, column="valor", compare="previous", date_column="mes")


@pytest.mark.parametrize(
    "raw", [["2026-10-29", None], ["29/10/2026", None], ["2026-10", None], ["2026-10-29 13:45:00", None]]
)
def test_dates_in_common_text_formats(raw: list[str | None]) -> None:
    parsed = as_date(pl.Series(raw))
    assert parsed.dtype == pl.Date and parsed[0].year == 2026 and parsed[0].month == 10 and parsed[1] is None


def test_bad_dates_are_explained() -> None:
    with pytest.raises(ValueError, match="não são datas"):
        as_date(pl.Series(["outubro", "2026-10"]))


# ------------------------------------------------------------------ gráficos


def test_stacked_matches_summarize(tmp_path: Path) -> None:
    w = widget(
        "bi.chart",
        VENDAS,
        tmp_path,
        chart_type="stacked",
        x_column="uf",
        y_column="valor",
        series_column="produto",
    )
    by_uf = {s["label"]: s for s in w["series"]}
    expected = VENDAS.group_by("uf", "produto").agg(pl.col("valor").sum())
    for uf, produto, valor in expected.rows():
        assert by_uf[uf]["values"][produto] == valor
    assert by_uf["SP"]["value"] == 62.0
    assert w["series_names"][0] == "A"  # séries em ordem do maior total, cor fixa por posição


def test_extra_series_fold_into_outras(tmp_path: Path) -> None:
    df = pl.DataFrame({"x": ["a"] * 10, "s": [f"s{i}" for i in range(10)], "v": list(range(1, 11))})
    w = widget("bi.chart", df, tmp_path, chart_type="stacked", x_column="x", y_column="v", series_column="s")
    assert len(w["series_names"]) == 8 and w["series_names"][-1] == "Outras"
    assert sum(w["series"][0]["values"].values()) == 55


def test_pareto_cumulative_and_highlight(tmp_path: Path) -> None:
    df = pl.DataFrame({"cliente": list("abcdef"), "v": [50.0, 25.0, 10.0, 8.0, 5.0, 2.0]})
    w = widget("bi.chart", df, tmp_path, chart_type="pareto", x_column="cliente", y_column="v", sort="label")
    assert [s["label"] for s in w["series"]] == list("abcdef")  # sempre do maior para o menor
    assert w["series"][-1]["cum_pct"] == 100.0
    # a, b (75%) e c, que cruza os 80%: as categorias que somam até a linha de corte
    assert [s["highlight"] for s in w["series"]] == [True, True, True, False, False, False]


def test_scatter_samples_with_fixed_seed(tmp_path: Path) -> None:
    df = pl.DataFrame({"x": list(range(5000)), "y": [i * 2 for i in range(5000)]})
    a = widget("bi.chart", df, tmp_path, chart_type="scatter", x_column="x", y_column="y")
    b = widget("bi.chart", df, tmp_path, chart_type="scatter", x_column="x", y_column="y")
    assert a["sampled"] and a["point_count"] == 5000 and len(a["points"]) == 2000
    assert a["points"] == b["points"]


# ------------------------------------------------------------------ Venn


def test_venn_key_group_counts_distinct_keys(tmp_path: Path) -> None:
    w = widget("bi.venn", VENDAS, tmp_path, key_column="cliente", group_column="produto", groups=["A", "B"])
    regions = {tuple(r["sets"]): r["count"] for r in w["regions"]}
    # A: c1 c2 c4; B: c1 c3 → só A: c2 c4; A e B: c1; só B: c3
    assert regions == {(0,): 2, (1,): 1, (0, 1): 1}
    assert w["union"] == 4 and w["outside"] == 1  # c5 só comprou C
    assert [s["size"] for s in w["sets"]] == [3, 2] and w["proportional"]


def test_venn_three_flags(tmp_path: Path) -> None:
    df = pl.DataFrame({"a": [1, 1, 0, 1], "b": ["sim", "não", "sim", "SIM"], "c": [True, False, False, True]})
    w = widget("bi.venn", df, tmp_path, mode="flags", flag_columns=["a", "b", "c"])
    regions = {tuple(r["sets"]): r["count"] for r in w["regions"]}
    assert regions[(0, 1, 2)] == 2 and regions[(0,)] == 1 and regions[(1,)] == 1
    assert not w["proportional"] and "geometry" not in w
    assert sum(r["count"] for r in w["regions"]) == w["union"] == 4


def test_venn_rejects_missing_group(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sem nenhuma linha"):
        widget("bi.venn", VENDAS, tmp_path, key_column="cliente", group_column="produto", groups=["A", "Z"])


def test_venn_two_sets_area_is_proportional() -> None:
    g = venn2_geometry(300, 120, 50)
    assert math.isclose(math.pi * g["r1"] ** 2, 300) and math.isclose(math.pi * g["r2"] ** 2, 120)
    assert abs(lens_area(g["r1"], g["r2"], g["d"]) - 50) / 50 < 0.01


# ------------------------------------------------------------------ Table


def test_table_sorts_limits_and_totals(tmp_path: Path) -> None:
    w = widget("bi.table", VENDAS, tmp_path, columns=["uf", "valor"], sort_column="valor", max_rows=3)
    assert [r[1] for r in w["rows"]] == [30.0, 20.0, 10.0]
    assert w["truncated"] and w["totals"] == {"valor": 78.0}
    assert w["columns"] == [{"name": "uf", "numeric": False}, {"name": "valor", "numeric": True}]
