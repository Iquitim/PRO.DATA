from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from prodata.api.deps import ServicesDep
from prodata.domain.execution import ExecutionReport
from prodata.domain.workflow import ID_PATTERN, Workflow
from prodata.engine import graph, results
from prodata.errors import InvalidInputError, NotFoundError
from prodata.ingestion.datasets import resolve_inside
from prodata.nodes.io import OutputDataConfig, export_path

router = APIRouter(prefix="/api", tags=["execução"])


class ExecuteRequest(BaseModel):
    workflow: Workflow
    target_node_id: str | None = None
    # Execução automática (ao abrir o fluxo): exportações em "Perguntar" com arquivo existente esperam.
    hold_exports: bool = False


@router.post("/execute")
def execute(req: ExecuteRequest, services: ServicesDep) -> ExecutionReport:
    """Executa o fluxo inteiro ou apenas até ``target_node_id`` (o nó e seus ancestrais)."""
    return services.runner.run(req.workflow, req.target_node_id, hold_exports=req.hold_exports)


@router.get("/execute/{workflow_id}/progress")
def execution_progress(
    workflow_id: Annotated[str, Path(pattern=ID_PATTERN)], services: ServicesDep
) -> dict[str, Any]:
    """Andamento da execução em curso (spec 018): caixa da vez e caixas concluídas."""
    return services.runner.progress(workflow_id)


@router.get("/results/{workflow_id}/{node_id}/{anchor}")
def get_results(
    workflow_id: Annotated[str, Path(pattern=ID_PATTERN)],
    node_id: str,
    anchor: str,
    services: ServicesDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: str = "",
    sort_col: str | None = None,
    sort_desc: bool = False,
    filters: str = Query("", description="JSON: [{column, op, value, value2}] (filtros exploratórios)"),
) -> dict[str, Any]:
    return results.page(
        services.cache,
        workflow_id,
        node_id,
        anchor,
        offset=offset,
        limit=min(limit, services.settings.results_page_max),
        search=search,
        sort_col=sort_col,
        sort_desc=sort_desc,
        filters=_parse_filters(filters),
    )


@router.post("/exports/pending")
def pending_exports(req: ExecuteRequest, services: ServicesDep) -> list[dict[str, Any]]:
    """Output Data em "Perguntar" que vão encontrar o arquivo já existente (spec 017, RF-1703).

    A interface pergunta o que fazer com cada um antes de executar.
    """
    wf = req.workflow
    scope = None
    if req.target_node_id:
        scope = graph.ancestors(wf, req.target_node_id) | {req.target_node_id}
    pending = []
    for node in wf.nodes:
        if node.type != "io.output_data" or node.disabled or (scope is not None and node.id not in scope):
            continue
        try:
            cfg = OutputDataConfig.model_validate(node.config)
            path = export_path(services.settings.exports_dir, cfg)
        except ValidationError, InvalidInputError:
            continue  # configuração inválida: o erro aparece na execução
        if cfg.if_exists == "ask" and path.exists():
            pending.append(
                {
                    "node_id": node.id,
                    "label": node.label,
                    "file": path.name,
                    "path": str(path),
                    "format": cfg.format,
                }
            )
    return pending


@router.get("/results/{workflow_id}/{node_id}/{anchor}/values")
def get_distinct_values(
    workflow_id: Annotated[str, Path(pattern=ID_PATTERN)],
    node_id: str,
    anchor: str,
    services: ServicesDep,
    column: str = Query(..., min_length=1),
    limit: int = Query(500, ge=1, le=5000),
    search: str = Query("", max_length=200),
) -> dict[str, Any]:
    """Valores distintos de uma coluna com a contagem de linhas (ex.: grupos do Venn)."""
    return results.distinct_values(services.cache, workflow_id, node_id, anchor, column, limit, search)


@router.delete("/cache/{workflow_id}/{node_id}", status_code=204)
def refresh_cache_point(workflow_id: str, node_id: str, services: ServicesDep) -> Response:
    """Descarta o resultado congelado de um ponto de cache: a próxima execução relê tudo (spec 012)."""
    services.cache.unfreeze(workflow_id, node_id)
    return Response(status_code=204)


@router.get("/exports/{name}")
def download_export(name: str, services: ServicesDep) -> FileResponse:
    path = resolve_inside(services.settings.exports_dir, name)
    if not path.is_file():
        raise NotFoundError(f"Arquivo exportado não encontrado: {name}")
    return FileResponse(path, filename=path.name)


def _parse_filters(raw: str) -> list[results.ExploreFilter]:
    if not raw.strip():
        return []
    try:
        return TypeAdapter(list[results.ExploreFilter]).validate_json(raw)
    except ValidationError as exc:
        raise InvalidInputError(f"Filtros inválidos: {exc.errors()[0]['msg']}") from exc
