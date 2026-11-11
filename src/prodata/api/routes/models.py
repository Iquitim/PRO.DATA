"""Biblioteca de modelos (spec 033): listar, importar e exportar o arquivo ``.modelo``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from fastapi import Path as PathParam

from prodata.api.deps import Services, ServicesDep
from prodata.domain.workflow import ID_PATTERN
from prodata.errors import InvalidInputError
from prodata.nodes import ml_library, ml_store

router = APIRouter(prefix="/api/models", tags=["modelos"])


def _folder(services: Services) -> Path:
    return ml_library.folder_of(services.settings.storage_dir / "estado")


@router.get("")
def list_models(services: ServicesDep) -> list[dict[str, Any]]:
    return ml_library.cards(_folder(services))


@router.post("/import")
async def import_model(
    services: ServicesDep, file: Annotated[UploadFile, File()], name: Annotated[str, Form()] = ""
) -> dict[str, Any]:
    """Recebe um ``.modelo``. O conteúdo é conferido antes de qualquer coisa ser gravada."""
    filename = file.filename or ""
    if not filename.lower().endswith(ml_library.SUFFIX):
        raise InvalidInputError(f"Escolha um arquivo {ml_library.SUFFIX}, exportado pelo PRO.DATA.")
    data = await file.read(ml_library.MAX_BYTES + 1)
    return ml_library.store(_folder(services), name.strip() or Path(filename).stem, data)


@router.get("/{name}/export")
def export_model(name: str, services: ServicesDep) -> Response:
    key = ml_library.slug(name)
    data = ml_library.file_bytes(_folder(services), key)
    headers = {"Content-Disposition": f'attachment; filename="{key}{ml_library.SUFFIX}"'}
    return Response(data, media_type="application/octet-stream", headers=headers)


@router.delete("/{name}", status_code=204)
def delete_model(name: str, services: ServicesDep) -> Response:
    ml_library.delete(_folder(services), name)
    return Response(status_code=204)


# ------------------------------------------------------------------ versões guardadas por um Model Trainer

FlowId = Annotated[str, PathParam(pattern=ID_PATTERN)]
NodeId = Annotated[str, PathParam(pattern=ID_PATTERN)]


def _versions_folder(services: Services, workflow_id: str, node_id: str) -> Path:
    return ml_store.node_folder(services.settings.storage_dir / "estado", workflow_id, node_id)


@router.get("/versions/{workflow_id}/{node_id}")
def list_versions(workflow_id: FlowId, node_id: NodeId, services: ServicesDep) -> list[dict[str, Any]]:
    return ml_store.listing(_versions_folder(services, workflow_id, node_id))


@router.delete("/versions/{workflow_id}/{node_id}/{version}", status_code=204)
def delete_version(
    workflow_id: FlowId,
    node_id: NodeId,
    version: int,
    services: ServicesDep,
    in_use: Annotated[int | None, Query()] = None,
) -> Response:
    """Apaga uma versão guardada. A que a caixa usa (``in_use``) nunca é apagada."""
    ml_store.delete(_versions_folder(services, workflow_id, node_id), version, in_use)
    return Response(status_code=204)
