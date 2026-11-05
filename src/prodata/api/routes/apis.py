"""Fontes de API da aba Dados (spec 021). Segredos entram por aqui e nunca voltam."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, Field

from prodata.api.deps import ServicesDep
from prodata.connectors.api import (
    ApiClient,
    ApiDefinition,
    ApiInfo,
    SavedApi,
    is_insecure,
    rows_to_frame,
    sample_document,
)
from prodata.domain.workflow import ID_PATTERN
from prodata.engine.profiling import schema_of
from prodata.engine.serialize import json_rows
from prodata.samples.apis import editor_examples

router = APIRouter(prefix="/api/apis", tags=["apis"])
ApiId = Annotated[str, Path(pattern=ID_PATTERN)]


class SaveRequest(BaseModel):
    source: SavedApi
    # Ausente = mantém o que está no cofre; vazio = remove.
    secrets: dict[str, str] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    definition: ApiDefinition
    # Fonte já salva: os segredos vêm do cofre.
    id: str = ""
    secrets: dict[str, str] = Field(default_factory=dict)
    # Valores de exemplo para {coluna}.
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_apis(services: ServicesDep) -> list[ApiInfo]:
    return services.apis.list()


@router.get("/examples")
def api_examples() -> list[dict[str, Any]]:
    """Pontos de partida do cadastro: nada é chamado até o usuário clicar em Testar."""
    return editor_examples()


@router.put("/{api_id}")
def save_api(api_id: ApiId, req: SaveRequest, services: ServicesDep) -> ApiInfo:
    source = req.source.model_copy(update={"id": api_id})
    source.check()
    return services.apis.save(source, req.secrets)


@router.delete("/{api_id}", status_code=204)
def delete_api(api_id: ApiId, services: ServicesDep) -> Response:
    services.apis.delete(api_id)
    return Response(status_code=204)


@router.post("/preview")
def preview_api(
    req: PreviewRequest, services: ServicesDep, rows: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    """Chamada de teste, só a primeira página. Num POST, a chamada é real: o editor avisa antes."""
    definition = req.definition
    definition.check()
    needed = definition.placeholders()
    if missing := [c for c in needed if c not in req.values or req.values[c] in (None, "")]:
        return {"needs_values": missing, "columns": [], "rows": []}
    with ApiClient(definition, services.apis.secret_reader(req.id, req.secrets)) as client:
        result = client.fetch(req.values, max_pages=1)
    df = rows_to_frame(result.rows)
    return {
        "columns": schema_of(df),
        "rows": json_rows(df.head(rows)),
        "total": df.height,
        "more_pages": result.truncated,
        "insecure": is_insecure(definition.url),
        "sample": None if result.document is None else sample_document(result.document),
    }
