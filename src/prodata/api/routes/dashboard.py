"""Organização do dashboard (spec 014): layouts prontos e posição de visuais novos."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from prodata.dashboard.layouts import Arrangement, LayoutItem, Rect, Template, arrange_all, place
from prodata.domain.dashboard import DashPage

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class ArrangeRequest(BaseModel):
    page: DashPage = Field(default_factory=DashPage)
    items: list[LayoutItem] = Field(max_length=200)
    obstacles: list[Rect] = Field(default_factory=list, max_length=500)


@router.post("/arrange")
def arrange_dashboard(req: ArrangeRequest) -> dict[Template, Arrangement]:
    """Resultado de todos os layouts de uma vez: a galeria desenha as miniaturas e aplica o escolhido."""
    return arrange_all(req.items, req.page, req.obstacles)


class PlaceRequest(BaseModel):
    page: DashPage = Field(default_factory=DashPage)
    items: list[LayoutItem] = Field(max_length=200)
    occupied: list[Rect] = Field(default_factory=list, max_length=500)


@router.post("/place")
def place_visuals(req: PlaceRequest) -> dict[str, Rect]:
    return place(req.items, req.occupied)
