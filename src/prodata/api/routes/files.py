"""Fluxos salvos e abertos em qualquer pasta escolhida pelo usuário (spec 009, RF-907)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

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
def save_workflow_file(req: SaveFileRequest) -> FileResponse:
    graph.topological_order(req.workflow)  # recusa ciclos antes de salvar
    path = save_to_file(req.workflow, req.path)
    return FileResponse(path=str(path), workflow=req.workflow)


@router.post("/workflow/open")
def open_workflow_file(req: OpenFileRequest) -> FileResponse:
    workflow, path = load_from_file(req.path)
    return FileResponse(path=str(path), workflow=workflow)
