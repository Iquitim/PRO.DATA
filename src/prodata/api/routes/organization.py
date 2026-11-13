"""Organização da vista Dados (spec 034). Cada chamada devolve a organização inteira, já atualizada."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from prodata.api.deps import ServicesDep
from prodata.services.organization import Color, Organization, SourceChanges

router = APIRouter(prefix="/api/organization", tags=["dados"])
FolderId = Annotated[str, Path(pattern=r"^[a-z0-9]{6,16}$")]


class FolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: Color = "azul"


class MoveFolderRequest(BaseModel):
    position: int = Field(ge=0)


class SourcesRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=500)
    changes: SourceChanges


class ForgetRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=500)


@router.get("")
def get_organization(services: ServicesDep) -> Organization:
    return services.organization.get()


@router.post("/folders")
def add_folder(req: FolderRequest, services: ServicesDep) -> Organization:
    return services.organization.add_folder(req.name, req.color)


@router.put("/folders/{folder_id}")
def update_folder(folder_id: FolderId, req: FolderRequest, services: ServicesDep) -> Organization:
    return services.organization.update_folder(folder_id, req.name, req.color)


@router.post("/folders/{folder_id}/move")
def move_folder(folder_id: FolderId, req: MoveFolderRequest, services: ServicesDep) -> Organization:
    return services.organization.move_folder(folder_id, req.position)


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: FolderId, services: ServicesDep) -> Organization:
    return services.organization.delete_folder(folder_id)


@router.put("/sources")
def change_sources(req: SourcesRequest, services: ServicesDep) -> Organization:
    return services.organization.change_sources(req.keys, req.changes)


@router.post("/sources/forget")
def forget_sources(req: ForgetRequest, services: ServicesDep) -> Organization:
    return services.organization.forget(req.keys)
