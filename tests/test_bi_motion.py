"""Corrida de barras, bolhas e Sankey (spec 030) e a linha do tempo no modelo do dashboard."""

from typing import Any

import polars as pl
import pytest

from prodata.dashboard.filters import filter_options
from prodata.domain.dashboard import Dashboard, DashItem, DashScene, DashTimeline
from prodata.nodes.base import NodeContext
from prodata.nodes.bi import ChartConfig, chart

TICKETS = pl.DataFrame({
    "projeto": ["A", "A", "B", "B", "C"],
    "horas": [10.0, 20.0, 5.0, 5.0, 1.0],
    "pontos": [1.0, 3.0, 2.0, 2.0, 9.0],
    "custo": [100.0, 100.0, 50.0, 50.0, 10.0],
    "de": ["Novo", "Novo", "Fazendo", "Fazendo", None],
    "para": ["Fazendo", "Fazendo", "Feito", "Novo", "Feito"],
})  # fmt: skip


def widget(frame: pl.DataFrame = TICKETS, **kw: Any) -> dict[str, Any]:
    ctx = NodeContext({"in": frame}, {}, None, None)  # type: ignore[arg-type]
    return chart(ctx, ChartConfig(**kw)).extra["bi_widget"]


def test_race_is_always_ranked_and_never_folds_the_rest() -> None:
    w = widget(chart_type="race", x_column="projeto", y_column="horas", sort="label", max_items=2)
    assert [s["label"] for s in w["series"]] == ["A", "B"]


def test_bubble_has_one_point_per_category() -> None:
    w = widget(chart_type="bubble", x_column="projeto", y_column="horas", x_value_column="pontos", size_column="custo", agg="sum")
    assert w["points"][0] == {"label": "A", "x": 4.0, "y": 30.0, "size": 200.0}
    assert [p["label"] for p in w["points"]] == ["A", "B", "C"]


def test_bubble_without_size_uses_the_row_count() -> None:
    w = widget(chart_type="bubble", x_column="projeto", y_column="horas", x_value_column="pontos", agg="mean")
    assert [p["size"] for p in w["points"]] == [2.0, 2.0, 1.0]


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"agg": "count", "y_column": "horas", "x_value_column": "pontos"}, "agregação"),
        ({"y_column": "horas"}, "eixo X da bolha"),
        ({"y_column": "horas", "x_value_column": "pontos", "size_column": "nada"}, "tamanho"),
    ],
)
def test_bubble_errors_are_explained(kw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        widget(chart_type="bubble", x_column="projeto", **kw)


def test_sankey_sums_each_transition() -> None:
    w = widget(chart_type="sankey", x_column="de", series_column="para", agg="count")
    assert w["links"][0] == {"source": "Novo", "target": "Fazendo", "value": 2.0}
    assert {"source": "(vazio)", "target": "Feito", "value": 1.0} in w["links"]


def test_sankey_needs_a_target() -> None:
    with pytest.raises(ValueError, match="destino"):
        widget(chart_type="sankey", x_column="de", agg="count")


def test_text_dates_can_drive_the_timeline() -> None:
    frame = pl.DataFrame({"competencia": ["2026-05", "2026-06"], "nome": ["Ana", "Bia"], "br": ["29/10/2026", "30/10/2026"]})
    options = {o["column"]: o for o in filter_options([frame])}
    assert options["competencia"]["date_like"] and options["br"]["date_like"]
    assert not options["nome"]["date_like"]


def test_old_dashboards_have_no_timeline() -> None:
    d = Dashboard.model_validate({"items": []})
    assert d.timeline == DashTimeline() and d.scenes == []


def test_a_scene_loses_the_highlight_when_the_visual_is_gone() -> None:
    d = Dashboard(items=[DashItem(id="a", node_id="n1")], scenes=[DashScene(id="c", item_id="a")])
    d.prune({"outro"})
    assert d.scenes[0].item_id is None
