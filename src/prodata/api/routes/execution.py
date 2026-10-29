from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from prodata.api.deps import ServicesDep
from prodata.domain.execution import ExecutionReport
from prodata.domain.workflow import ID_PATTERN, Workflow
from prodata.engine import results
from prodata.errors import InvalidInputError, NotFoundError
from prodata.ingestion.datasets import resolve_inside

router = APIRouter(prefix="/api", tags=["execução"])


class ExecuteRequest(BaseModel):
    workflow: Workflow
    target_node_id: str | None = None


@router.post("/execute")
def execute(req: ExecuteRequest, services: ServicesDep) -> ExecutionReport:
    """Executa o fluxo inteiro ou apenas até ``target_node_id`` (o nó e seus ancestrais)."""
    return services.runner.run(req.workflow, req.target_node_id)


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
