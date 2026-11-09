"""Organização do dashboard (spec 014): layouts prontos e posição de visuais novos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, ValidationError

from prodata.api.deps import Services, ServicesDep
from prodata.dashboard.filters import (
    MAX_EXPORT_BYTES,
    ExportTables,
    apply_filters,
    column_type,
    filter_options,
    filters_for,
    used_columns,
)
from prodata.dashboard.formats import describe_formats
from prodata.dashboard.layouts import Arrangement, LayoutItem, Rect, Template, arrange_all, place
from prodata.dashboard.viewer import build_viewer
from prodata.domain.dashboard import DashFilter, DashPage
from prodata.domain.labels import LABEL_NAMES, Confidentiality
from prodata.domain.workflow import Node, Workflow
from prodata.nodes import REGISTRY, NodeContext
from prodata.services.audit import log_export

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


@router.get("/formats")
def dashboard_formats() -> dict[str, list[dict[str, Any]]]:
    """Campos do painel Formato por tipo de item, no mesmo formato dos formulários das ferramentas."""
    return describe_formats()


# ------------------------------------------------------------------ filtros e HTML (spec 021)

WEB_JS = Path(__file__).resolve().parents[2] / "web" / "js"
_VISUAL_TOOLS = ("bi.chart", "bi.kpi_card", "bi.venn", "bi.table")


class WorkflowRequest(BaseModel):
    workflow: Workflow


def _visual_nodes(services: Services, workflow: Workflow) -> list[tuple[Node, pl.DataFrame]]:
    """Visuais na página com tabela guardada que ainda vale para o fluxo atual. Nada é executado."""
    on_page = (
        {i.node_id for i in workflow.dashboard.items if i.kind == "visual"} if workflow.dashboard else set()
    )
    found = []
    for node in workflow.nodes:
        if node.type not in _VISUAL_TOOLS or node.id not in on_page or node.disabled:
            continue
        entry = services.cache.get(workflow.id, node.id)
        if entry is not None and "out" in entry.tables and services.runner.is_fresh(workflow, node.id):
            found.append((node, entry.tables["out"]))
    return found


def _filters(workflow: Workflow) -> list[DashFilter]:
    return workflow.dashboard.filters if workflow.dashboard else []


def _config_of(node: Node) -> Any:
    # Se a configuração estiver inválida, quem avisa é o próprio visual, em ``_widget``.
    try:
        return REGISTRY[node.type].config.model_validate(node.config)
    except ValidationError:
        return None


def _widget(services: Services, node: Node, table: pl.DataFrame) -> dict[str, Any]:
    spec = REGISTRY[node.type]
    label = node.label or spec.name
    try:
        cfg = spec.config.model_validate(node.config)
        ctx = NodeContext({"in": table}, {}, services.datasets, services.settings.exports_dir)
        widget: dict[str, Any] = spec.run(ctx, cfg).extra["bi_widget"]
    except (ValueError, ValidationError, pl.exceptions.PolarsError) as exc:
        # Ex.: comparar com o período anterior quando o filtro deixou um período só.
        return {"widget_type": "message", "title": label, "message": str(exc), "node_id": node.id}
    return {**widget, "node_id": node.id, "node_label": label}


@router.post("/filter-options")
def dashboard_filter_options(req: WorkflowRequest, services: ServicesDep) -> list[dict[str, Any]]:
    visuals = _visual_nodes(services, req.workflow)
    options = filter_options([t for _, t in visuals])
    for option in options:
        option["node_ids"] = [n.id for n, t in visuals if option["column"] in t.columns]
    return options


@router.post("/filtered")
def dashboard_filtered(req: WorkflowRequest, services: ServicesDep) -> dict[str, Any]:
    """Visuais recalculados com os filtros da página, a partir das tabelas guardadas."""
    filters = _filters(req.workflow)
    widgets: dict[str, Any] = {}
    no_column: dict[str, list[str]] = {}
    for node, table in _visual_nodes(services, req.workflow):
        current, missing = apply_filters(table, filters_for(_config_of(node), filters))
        if missing:
            no_column[node.id] = missing
        if current.height != table.height:
            widgets[node.id] = _widget(services, node, current)
    return {"widgets": widgets, "no_column": no_column}


@router.post("/export-data")
def dashboard_export_data(req: WorkflowRequest, services: ServicesDep) -> dict[str, Any]:
    """O que o HTML precisa para os filtros funcionarem sozinhos: só as colunas usadas e só dos visuais filtráveis."""
    filters = _filters(req.workflow)
    # A coluna da linha do tempo também vai: é ela que escolhe as linhas de cada momento.
    dashboard = req.workflow.dashboard
    if dashboard is not None and dashboard.timeline.column:
        filters = [*filters, DashFilter(id="linha_do_tempo", column=dashboard.timeline.column, kind="date")]
    wanted = {f.column for f in filters}
    visuals = _visual_nodes(services, req.workflow)
    tables = ExportTables()
    nodes: dict[str, Any] = {}
    names: set[str] = set()
    rows = 0
    for node, table in visuals:
        if not wanted.intersection(table.columns):
            continue
        spec = REGISTRY[node.type]
        cfg = spec.config.model_validate(node.config)
        columns = used_columns(node.type, cfg, table, filters)
        nodes[node.id] = {
            "tool": node.type,
            "title": node.label or spec.name,
            "config": cfg.model_dump(mode="json"),
            "rows": table.height,
            "columns": {c: tables.add(table[c]) for c in columns},
            "types": {c: column_type(table.schema[c]) for c in columns},
        }
        names.update(columns)
        rows = max(rows, table.height)
    info: dict[str, Any] = {"bytes": tables.bytes, "rows": rows, "column_names": sorted(names)}
    if tables.bytes > MAX_EXPORT_BYTES:
        return {**info, "too_large": True}
    options = filter_options([t for _, t in visuals])
    return {
        **info,
        "nodes": nodes,
        "columns": tables.columns,
        "options": [o for o in options if o["column"] in wanted],
    }


@router.get("/viewer.js")
def dashboard_viewer() -> Response:
    return Response(build_viewer(WEB_JS), media_type="text/javascript; charset=utf-8")


class ExportLog(BaseModel):
    kind: str = Field(pattern=r"^(PNG|GIF|HTML)$")
    file: str = Field(max_length=300)
    label: Confidentiality
    rows: int | None = None
    columns: int | None = None
    password: bool = False


@router.post("/export-log", status_code=204)
def dashboard_export_log(req: ExportLog) -> Response:
    """Registra a exportação feita na tela (a imagem e o HTML são montados no navegador). Nunca os dados."""
    log_export(
        f"Dashboard ({req.kind})", req.file, LABEL_NAMES[req.label], req.rows, req.columns, senha=req.password
    )
    return Response(status_code=204)
