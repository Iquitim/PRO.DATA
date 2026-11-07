"""Fluxos salvos e abertos em qualquer pasta escolhida pelo usuário (spec 009, RF-907)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from prodata.api.deps import ServicesDep
from prodata.domain.workflow import Workflow
from prodata.engine import graph
from prodata.services.workflows import load_from_file, save_to_file

router = APIRouter(prefix="/api/files", tags=["arquivos"])


class SaveFileRequest(BaseModel):
    path: str
    workflow: Workflow


class OpenFileRequest(BaseModel):
    path: str


class FileResponse(BaseModel):
    path: str
    workflow: Workflow


@router.post("/workflow/save")
def save_workflow_file(req: SaveFileRequest, services: ServicesDep) -> FileResponse:
    graph.topological_order(req.workflow)  # recusa ciclos antes de salvar
    workflow = services.runner.snapshot(req.workflow)
    path = save_to_file(workflow, req.path)
    services.trust.saved(workflow)
    return FileResponse(path=str(path), workflow=workflow)


@router.post("/workflow/open")
def open_workflow_file(req: OpenFileRequest, services: ServicesDep) -> FileResponse:
    workflow, path = load_from_file(req.path)
    services.trust.opened(workflow)  # de fora e ainda não confirmado: modo protegido (RF-2821)
    return FileResponse(path=str(path), workflow=workflow)
