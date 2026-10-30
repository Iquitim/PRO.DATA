from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from prodata.api.deps import ServicesDep
from prodata.errors import InvalidInputError
from prodata.ingestion import DatasetInfo, ReadOptions, inspect_file

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("")
def list_datasets(services: ServicesDep) -> list[DatasetInfo]:
    return services.datasets.list()


@router.post("", status_code=201)
async def upload_dataset(
    services: ServicesDep,
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
) -> DatasetInfo:
    if not file.filename:
        raise InvalidInputError("Arquivo sem nome.")
    return await run_in_threadpool(services.datasets.save, file.filename, file.file, overwrite=overwrite)


@router.post("/{name}/preview")
def preview_dataset(
    name: str,
    services: ServicesDep,
    options: ReadOptions | None = None,
    rows: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Lê as primeiras linhas com as opções informadas (``auto`` é resolvido e devolvido)."""
    path = services.datasets.resolve(name)
    preview = inspect_file(path, options or ReadOptions(), rows=rows)
    preview["info"] = services.datasets.info_of(name).model_dump(mode="json")
    return preview


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, services: ServicesDep) -> Response:
    services.datasets.delete(name)
    return Response(status_code=204)


class LinkRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)
    name: str | None = Field(None, max_length=200)


@router.post("/link", status_code=201)
def link_dataset(req: LinkRequest, services: ServicesDep) -> DatasetInfo:
    """Vincula um arquivo escolhido pelo usuário: lido onde está, sempre na versão atual (spec 017)."""
    return services.datasets.link(req.path, req.name)
