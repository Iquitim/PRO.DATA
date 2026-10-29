"""Consultas de banco da aba Dados (spec 009). Nada aqui envolve senha."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response

from prodata.api.deps import ServicesDep
from prodata.connectors.queries import QueryDefinition, SavedQuery, read_definition
from prodata.domain.workflow import ID_PATTERN
from prodata.engine.profiling import schema_of
from prodata.engine.serialize import json_rows

router = APIRouter(prefix="/api/queries", tags=["consultas"])
QueryId = Annotated[str, Path(pattern=ID_PATTERN)]


@router.get("")
def list_queries(services: ServicesDep) -> list[SavedQuery]:
    return services.queries.list()


@router.put("/{query_id}")
def save_query(query_id: QueryId, query: SavedQuery, services: ServicesDep) -> SavedQuery:
    query = query.model_copy(update={"id": query_id})
    query.to_sql(services.connections)  # valida conexão, tabela e somente-leitura antes de salvar
    return services.queries.save(query)


@router.delete("/{query_id}", status_code=204)
def delete_query(query_id: QueryId, services: ServicesDep) -> Response:
    services.queries.delete(query_id)
    return Response(status_code=204)


@router.post("/preview")
def preview_query(
    definition: QueryDefinition, services: ServicesDep, rows: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    """Prévia de uma definição ainda não salva (editor da aba Dados)."""
    df = read_definition(definition, services.connections, limit=rows)
    return {"columns": schema_of(df), "rows": json_rows(df)}
