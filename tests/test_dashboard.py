"""Spec 014: layout do dashboard no fluxo, organização automática e layouts prontos."""

import base64
import itertools
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prodata.dashboard.layouts import (
    GRID,
    TEMPLATES,
    LayoutItem,
    Rect,
    VisualHint,
    arrange,
    place,
)
from prodata.domain.dashboard import DashPage, check_image
from prodata.domain.workflow import Workflow


def _wf(dashboard: dict[str, Any]) -> Workflow:
    return Workflow.model_validate(
        {
            "id": "wf",
            "nodes": [{"id": "k1", "type": "bi.kpi_card"}, {"id": "c1", "type": "bi.chart"}],
            "dashboard": dashboard,
        }
    )


def test_old_workflows_have_no_dashboard() -> None:
    assert Workflow.model_validate({"id": "wf"}).dashboard is None


def test_visuals_of_deleted_nodes_are_pruned() -> None:
    wf = _wf(
        {
            "items": [
                {"id": "a", "node_id": "k1"},
                {"id": "b", "node_id": "sumiu"},
                {"id": "t", "kind": "text", "content": "Título"},
            ],
            "hidden": ["c1", "sumiu", "c1"],
        }
    )
    assert wf.dashboard is not None
    assert [i.id for i in wf.dashboard.items] == ["a", "t"]
    assert wf.dashboard.hidden == ["c1"]


def test_duplicate_item_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicados"):
        _wf({"items": [{"id": "a", "node_id": "k1"}, {"id": "a", "node_id": "c1"}]})


def _data_uri(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def test_images_are_checked() -> None:
    check_image(_data_uri("image/png", b"\x89PNG..."))
    check_image(_data_uri("image/svg+xml", b'<svg><use href="#a"/><circle r="2"/></svg>'))
    for bad, msg in [
        (_data_uri("image/svg+xml", b"<svg><script>alert(1)</script></svg>"), "scripts"),
        (_data_uri("image/svg+xml", b'<svg onload="x()"></svg>'), "scripts"),
        (_data_uri("image/svg+xml", b'<svg><image href="https://evil/x.png"/></svg>'), "externos"),
        (_data_uri("image/gif", b"GIF89a"), "PNG, JPG ou SVG"),
        (_data_uri("image/png", b"0" * (1024 * 1024 + 1)), "1 MB"),
        ("https://exemplo.com/logo.png", "PNG, JPG ou SVG"),
    ]:
        with pytest.raises(ValueError, match=msg):
            check_image(bad)


# ------------------------------------------------------------------ organização


def _items(spec: str) -> list[LayoutItem]:
    """'kkcd' → 2 KPIs, um gráfico de colunas, uma rosca... na ordem de leitura."""
    kinds = {
        "k": VisualHint(kind="kpi"),
        "c": VisualHint(chart_type="bar"),
        "d": VisualHint(chart_type="donut"),
        "l": VisualHint(chart_type="line"),
        "t": VisualHint(kind="table"),
    }
    return [
        LayoutItem(id=f"v{n}", hint=kinds[ch], rect=Rect(x=(n % 3) * 500, y=(n // 3) * 400, w=300, h=200))
        for n, ch in enumerate(spec)
    ]


def _check(positions: dict[str, Rect], page_h: int, obstacles: list[Rect] = ()) -> None:  # type: ignore[assignment]
    rects = list(positions.values())
    for r in rects:
        assert r.x % GRID == r.y % GRID == r.w % GRID == r.h % GRID == 0, r
        assert r.x >= 0 and r.x + r.w <= 1600 and r.y >= 0 and r.bottom <= page_h, r
    for a, b in itertools.combinations(rects, 2):
        assert not a.overlaps(b), (a, b)
    for r, o in itertools.product(rects, obstacles):
        assert not r.overlaps(o), (r, o)


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("spec", ["kkkcccd", "c", "kkkkk", "kccdltc", "cdl"])
def test_every_template_fits_without_overlap(template: str, spec: str) -> None:
    items = _items(spec)
    result = arrange(items, DashPage(), template)  # type: ignore[arg-type]
    assert set(result.positions) == {i.id for i in items}
    _check(result.positions, result.page.pixel_height)


def test_fixed_page_is_filled_and_rows_have_no_holes() -> None:
    result = arrange(_items("kkkcccc"), DashPage(), "kpis-top-2")
    assert not result.grew
    bottom = max(r.bottom for r in result.positions.values())
    assert 900 - 40 - GRID < bottom <= 900 - 40  # preenche a página até a margem
    rows: dict[int, list[Rect]] = {}
    for r in result.positions.values():
        rows.setdefault(r.y, []).append(r)
    for row in rows.values():  # cada linha vai de margem a margem
        assert min(r.x for r in row) == 40 and max(r.x + r.w for r in row) == 1560


def test_kpis_go_first_in_kpi_templates() -> None:
    items = _items("cckk")
    result = arrange(items, DashPage(), "kpis-top-2")
    kpi_y = {result.positions[i.id].y for i in items if i.hint.kind == "kpi"}
    chart_y = {result.positions[i.id].y for i in items if i.hint.kind == "chart"}
    assert max(kpi_y) < min(chart_y)


def test_auto_keeps_reading_order() -> None:
    items = _items("cdcl")
    result = arrange(items, DashPage(size="free", height=2000), "auto")
    order = sorted(result.positions, key=lambda k: (result.positions[k].y, result.positions[k].x))
    assert order == [i.id for i in items]


def test_too_many_visuals_grow_the_page() -> None:
    result = arrange(_items("c" * 14), DashPage(), "kpis-top-2")
    assert result.grew and result.page.size == "free" and result.page.height > 900
    _check(result.positions, result.page.height)


def test_report_is_one_visual_per_row() -> None:
    result = arrange(_items("kkccd"), DashPage(), "report")
    assert result.page.size == "free"
    charts = [result.positions[f"v{n}"] for n in (2, 3, 4)]
    assert all(r.x == 40 and r.w == 1520 for r in charts)


def test_obstacles_stay_free() -> None:
    title = Rect(x=40, y=40, w=800, h=80)
    logo = Rect(x=1400, y=500, w=160, h=160)
    for template in TEMPLATES:
        result = arrange(_items("kkccd"), DashPage(), template, [title, logo])
        _check(result.positions, result.page.pixel_height, [title, logo])


def test_place_new_visual_in_first_free_spot() -> None:
    occupied = [Rect(x=40, y=40, w=752, h=360)]
    pos = place(_items("c"), occupied)["v0"]
    assert (pos.x, pos.y) == (808, 40)  # ao lado do que já existe, no topo
    _check({"a": occupied[0], "b": pos}, 900)


def test_arrange_route_returns_all_templates(client: TestClient) -> None:
    body = {
        "items": [i.model_dump() for i in _items("kcd")],
        "obstacles": [{"x": 0, "y": 0, "w": 10, "h": 10}],
    }
    res = client.post("/api/dashboard/arrange", json=body)
    assert res.status_code == 200
    assert set(res.json()) == set(TEMPLATES)
    res = client.post("/api/dashboard/place", json={"items": body["items"][:1]})
    assert res.status_code == 200 and set(res.json()) == {"v0"}


# ------------------------------------------------------------------ formato (fase 2)


def test_formats_are_described_for_every_kind(client: TestClient) -> None:
    res = client.get("/api/dashboard/formats")
    assert res.status_code == 200
    data = res.json()
    assert set(data) == {"chart", "kpi", "text", "image", "shape"}
    widgets = {f["name"]: f["widget"] for f in data["chart"]}
    assert widgets["color"] == "color" and widgets["category_colors"] == "category_colors"
    labels = {o["value"] for f in data["chart"] if f["name"] == "data_labels" for o in f["options"]}
    assert labels == {"none", "max", "max_min"}  # nunca um número em cada ponto


def test_format_keeps_only_what_differs_from_default() -> None:
    wf = _wf(
        {
            "items": [
                {
                    "id": "a",
                    "node_id": "c1",
                    "format": {"palette": "single", "color": "#AABBCC", "title_size": 14},
                },
                {"id": "t", "kind": "text", "content": "x" * 6000, "format": {"size": 16, "bold": True}},
            ]
        }
    )
    assert wf.dashboard is not None
    chart, text = wf.dashboard.items
    assert chart.format == {"palette": "single", "color": "#aabbcc"}
    assert text.format == {"bold": True} and len(text.content) == 5000


@pytest.mark.parametrize("bad", ["red", "#12345", "#zzzzzz", "#fff;background:url(x)"])
def test_colors_only_accept_hex(bad: str) -> None:
    with pytest.raises(ValidationError, match="Cor inválida"):
        _wf({"items": [{"id": "t", "kind": "text", "format": {"color": bad}}]})


def test_category_colors_drop_invalid_entries() -> None:
    wf = _wf(
        {"items": [{"id": "a", "node_id": "c1", "format": {"category_colors": {"SP": "#112233", "RJ": ""}}}]}
    )
    assert wf.dashboard is not None
    assert wf.dashboard.items[0].format == {"category_colors": {"SP": "#112233"}}
