"""Organização automática e layouts prontos do dashboard (spec 014, RF-1406, RF-1460..RF-1463).

Funções puras sobre retângulos: não conhecem HTTP nem DOM. Tudo fica alinhado à grade de 8 px,
numa grade de 12 colunas de 112 px com espaçamento de 16 px e margem de 40 px (largura 1600).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from prodata.domain.dashboard import PAGE_WIDTH, DashPage

GRID = 8
GAP = 16
MARGIN = 40
COLUMNS = 12
COL = (PAGE_WIDTH - 2 * MARGIN - (COLUMNS - 1) * GAP) // COLUMNS  # 112
KPI_H = 136
CHART_H = 360
CHART_H_MIN = 240
CHART_H_MAX = 720
REPORT_H = 400

SizeClass = Literal["small", "square", "wide", "xwide", "full"]
Template = Literal["auto", "kpis-top-2", "kpis-top-3", "highlight", "kpis-side", "report"]
TEMPLATES: tuple[Template, ...] = ("auto", "kpis-top-2", "kpis-top-3", "highlight", "kpis-side", "report")
SPANS: dict[SizeClass, int] = {"small": 3, "square": 4, "wide": 6, "xwide": 8, "full": 12}
SQUARE_CHARTS = {"donut", "gauge", "venn"}
WIDE_CHARTS = {"line", "area", "area_stacked"}


class Rect(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlaps(self, other: Rect, gap: int = 0) -> bool:
        return (
            self.x < other.x + other.w + gap
            and other.x < self.x + self.w + gap
            and self.y < other.y + other.h + gap
            and other.y < self.y + self.h + gap
        )


class VisualHint(BaseModel):
    kind: Literal["kpi", "chart", "table"] = "chart"
    chart_type: str = ""
    categories: int = Field(0, ge=0)


class LayoutItem(BaseModel):
    id: str
    hint: VisualHint = Field(default_factory=VisualHint)
    rect: Rect = Field(default_factory=Rect)  # posição atual: define a ordem de leitura


class Arrangement(BaseModel):
    positions: dict[str, Rect]
    page: DashPage
    grew: bool = False  # não coube na página fixa: a altura virou livre (RF-1463)


def size_class(hint: VisualHint) -> SizeClass:
    if hint.kind == "kpi":
        return "small"
    if hint.kind == "table":
        return "full"
    if hint.chart_type in SQUARE_CHARTS:
        return "square"
    if hint.chart_type in WIDE_CHARTS or hint.categories > 12:
        return "xwide"
    return "wide"


def span_width(span: int) -> int:
    return span * COL + (span - 1) * GAP


def _ceil(v: float) -> int:
    return math.ceil(v / GRID) * GRID


def reading_order(items: Sequence[LayoutItem]) -> list[LayoutItem]:
    return sorted(items, key=lambda i: (i.rect.y, i.rect.x))


# ------------------------------------------------------------------ montagem por faixas


class _Board:
    """Coloca linhas de itens de cima para baixo dentro de uma região, desviando dos obstáculos."""

    def __init__(self, obstacles: Sequence[Rect]) -> None:
        self.obstacles = list(obstacles)
        self.positions: dict[str, Rect] = {}

    def free_y(self, y: int, h: int, x0: int, x1: int) -> int:
        band = Rect(x=x0, y=y, w=x1 - x0, h=h)
        while hits := [o for o in self.obstacles if band.overlaps(o, GAP - 1)]:
            band.y = _ceil(max(o.bottom for o in hits) + GAP)
        return band.y

    def row(self, ids: Sequence[str], weights: Sequence[int], y: int, h: int, x0: int, x1: int) -> int:
        """Divide [x0, x1] entre os itens na proporção dos pesos, sem sobra. Devolve o y seguinte."""
        if not ids:
            return y
        y = self.free_y(y, h, x0, x1)
        room = x1 - x0 - GAP * (len(ids) - 1)
        total = sum(weights)
        x = x0
        for k, (item_id, weight) in enumerate(zip(ids, weights, strict=True)):
            last = k == len(ids) - 1
            w = x1 - x if last else max(GRID, math.floor(room * weight / total / GRID) * GRID)
            self.positions[item_id] = Rect(x=x, y=y, w=w, h=h)
            x += w + GAP
        return y + h + GAP


def _chunks(seq: Sequence[LayoutItem], per_row: int) -> list[list[LayoutItem]]:
    """Linhas equilibradas: 5 em linhas de até 4 vira 3 + 2, não 4 + 1."""
    if not seq:
        return []
    rows = math.ceil(len(seq) / per_row)
    size = math.ceil(len(seq) / rows)
    return [list(seq[i : i + size]) for i in range(0, len(seq), size)]


def _split(items: Sequence[LayoutItem]) -> tuple[list[LayoutItem], list[LayoutItem]]:
    ordered = reading_order(items)
    kpis = [i for i in ordered if size_class(i.hint) == "small"]
    return kpis, [i for i in ordered if size_class(i.hint) != "small"]


def _kpi_rows(board: _Board, kpis: Sequence[LayoutItem], y: int, x0: int, x1: int, per_row: int = 4) -> int:
    for row in _chunks(kpis, per_row):
        y = board.row([i.id for i in row], [1] * len(row), y, KPI_H, x0, x1)
    return y


def _column_rows(
    board: _Board, items: Sequence[LayoutItem], per_row: int, y: int, h: int, x0: int, x1: int
) -> int:
    """Visuais em colunas iguais; tabelas ocupam a linha inteira; a última linha estica (sem buracos)."""
    pending: list[LayoutItem] = []

    def flush(y: int) -> int:
        for row in _chunks(pending, per_row):
            y = board.row([i.id for i in row], [1] * len(row), y, h, x0, x1)
        pending.clear()
        return y

    for item in items:
        if size_class(item.hint) == "full":
            y = flush(y)
            y = board.row([item.id], [1], y, h, x0, x1)
        else:
            pending.append(item)
            if len(pending) == per_row:
                y = flush(y)
    return flush(y)


Builder = Callable[[_Board, Sequence[LayoutItem], int], int]
LEFT, RIGHT = MARGIN, PAGE_WIDTH - MARGIN


def _grid(per_row: int) -> Builder:
    def build(board: _Board, items: Sequence[LayoutItem], h: int) -> int:
        kpis, others = _split(items)
        y = _kpi_rows(board, kpis, MARGIN, LEFT, RIGHT)
        return _column_rows(board, others, per_row, y, h, LEFT, RIGHT)

    return build


def _highlight(board: _Board, items: Sequence[LayoutItem], h: int) -> int:
    kpis, others = _split(items)
    y = _kpi_rows(board, kpis, MARGIN, LEFT, RIGHT)
    if not others:
        return y
    hero, side, rest = others[0], others[1:3], others[3:]
    split = LEFT + span_width(8)
    tall = 2 * h + GAP if side else h
    y = board.free_y(y, tall, LEFT, RIGHT)
    board.row([hero.id], [1], y, tall, LEFT, split if side else RIGHT)
    side_h = (tall - GAP * (len(side) - 1)) // len(side) if side else 0
    side_h -= side_h % GRID
    sy = y
    for k, item in enumerate(side):
        hh = tall - (side_h + GAP) * (len(side) - 1) if k == len(side) - 1 else side_h
        board.positions[item.id] = Rect(x=split + GAP, y=sy, w=RIGHT - split - GAP, h=hh)
        sy += hh + GAP
    return _column_rows(board, rest, 3, y + tall + GAP, h, LEFT, RIGHT)


def _kpis_side(board: _Board, items: Sequence[LayoutItem], h: int) -> int:
    kpis, others = _split(items)
    if not kpis or not others:
        return _grid(2)(board, items, h)
    split = LEFT + span_width(3)
    y_left = MARGIN
    for item in kpis:
        y_left = board.row([item.id], [1], y_left, KPI_H, LEFT, split)
    y_right = _column_rows(board, others, 2, MARGIN, h, split + GAP, RIGHT)
    return max(y_left, y_right)


def _auto(board: _Board, items: Sequence[LayoutItem], h: int) -> int:
    """Ordem de leitura atual; cada linha junta visuais da mesma altura e estica para fechar a largura."""
    y = MARGIN
    row: list[LayoutItem] = []

    def flush() -> int:
        if not row:
            return y
        small = size_class(row[0].hint) == "small"
        weights = [SPANS[size_class(i.hint)] for i in row]
        return board.row([i.id for i in row], weights, y, KPI_H if small else h, LEFT, RIGHT)

    for item in reading_order(items):
        cls = size_class(item.hint)
        same_height = not row or (cls == "small") == (size_class(row[0].hint) == "small")
        if row and (not same_height or sum(SPANS[size_class(i.hint)] for i in row) + SPANS[cls] > COLUMNS):
            y = flush()
            row = []
        row.append(item)
    return flush()


BUILDERS: dict[Template, Builder] = {
    "auto": _auto,
    "kpis-top-2": _grid(2),
    "kpis-top-3": _grid(3),
    "highlight": _highlight,
    "kpis-side": _kpis_side,
}


def arrange(
    items: Sequence[LayoutItem],
    page: DashPage,
    template: Template = "auto",
    obstacles: Sequence[Rect] = (),
) -> Arrangement:
    """Novas posições para `items`. Obstáculos (textos, imagens, visuais não selecionados) ficam onde estão."""
    if template == "report":
        board = _Board(obstacles)
        kpis, others = _split(items)
        y = _kpi_rows(board, kpis, MARGIN, LEFT, RIGHT)
        for item in others:
            y = board.row([item.id], [1], y, REPORT_H, LEFT, RIGHT)
        height = max(y - GAP + MARGIN, *(o.bottom + MARGIN for o in obstacles), 400)
        return Arrangement(
            positions=board.positions, page=DashPage(size="free", height=height, background=page.background)
        )

    build = BUILDERS[template]

    def attempt(h: int) -> tuple[_Board, int]:
        board = _Board(obstacles)
        bottom = build(board, items, h) - GAP + MARGIN
        return board, bottom

    limit = page.pixel_height
    if page.size == "free":
        board, bottom = attempt(CHART_H)
        return Arrangement(
            positions=board.positions, page=page.model_copy(update={"height": max(bottom, 400)})
        )
    # Página fixa: a maior altura de gráfico que ainda cabe, para preencher a página sem sobra.
    best: tuple[_Board, int] | None = None
    for h in range(CHART_H_MAX, CHART_H_MIN - 1, -GRID):
        board, bottom = attempt(h)
        if bottom <= limit:
            best = (board, bottom)
            break
    if best is not None:
        positions, bottom = best[0].positions, best[1]
        _stretch_last_row(positions, limit - bottom, obstacles)
        return Arrangement(positions=positions, page=page)
    board, bottom = attempt(CHART_H)
    grown = DashPage(size="free", height=bottom, background=page.background)
    return Arrangement(positions=board.positions, page=grown, grew=True)


def _stretch_last_row(positions: dict[str, Rect], slack: int, obstacles: Sequence[Rect]) -> None:
    """A altura dos gráficos anda de 8 em 8 px: a sobra (menor que uma linha) vai para a última linha."""
    slack -= slack % GRID  # a página (ex.: 900 px) nem sempre é múltipla de 8
    if slack <= 0 or not positions:
        return
    bottom = max(r.bottom for r in positions.values())
    for r in positions.values():
        if r.bottom == bottom:
            grown = r.model_copy(update={"h": r.h + slack})
            if not any(grown.overlaps(o, GAP - 1) for o in obstacles):
                r.h = grown.h


def arrange_all(
    items: Sequence[LayoutItem], page: DashPage, obstacles: Sequence[Rect] = ()
) -> dict[Template, Arrangement]:
    return {t: arrange(items, page, t, obstacles) for t in TEMPLATES}


def place(items: Sequence[LayoutItem], occupied: Sequence[Rect]) -> dict[str, Rect]:
    """Visuais novos no primeiro espaço livre da grade, de cima para baixo (RF-1406)."""
    taken = list(occupied)
    out: dict[str, Rect] = {}
    for item in items:
        cls = size_class(item.hint)
        span = SPANS[cls]
        rect = Rect(w=span_width(span), h=KPI_H if cls == "small" else CHART_H)
        y = MARGIN
        while item.id not in out:
            for col in range(COLUMNS - span + 1):
                rect.x, rect.y = MARGIN + col * (COL + GAP), y
                if not any(rect.overlaps(o, GAP - 1) for o in taken):
                    out[item.id] = rect.model_copy()
                    taken.append(out[item.id])
                    break
            y += GRID
    return out
