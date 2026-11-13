"""Pastas de arquivos da aba Dados (spec 035): cadastro, situação e prévia dos arquivos empilhados."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from prodata.api.deps import ServicesDep
from prodata.engine.profiling import schema_of
from prodata.engine.serialize import json_rows
from prodata.errors import InvalidInputError, NotFoundError
from prodata.ingestion.folders import FolderEntry, FolderSource, folder_files, read_folder, status_of

router = APIRouter(prefix="/api/folders", tags=["dados"])

# A prévia lê o começo de poucos arquivos: o bastante para ver a tabela, sem esperar a pasta inteira.
PREVIEW_FILES = 20
CHECK_FILES = 60


def _entry(source: FolderSource) -> FolderEntry:
    return FolderEntry(**source.model_dump(), status=status_of(source))


@router.get("")
def list_folders(services: ServicesDep) -> list[FolderEntry]:
    return [_entry(s) for s in services.datasets.folders.list()]


@router.post("", status_code=201)
def create_folder(source: FolderSource, services: ServicesDep) -> FolderEntry:
    return _entry(services.datasets.folders.save(source.model_copy(update={"id": ""})))


@router.put("/{source_id}")
def update_folder(source_id: str, source: FolderSource, services: ServicesDep) -> FolderEntry:
    return _entry(services.datasets.folders.save(source, previous=source_id))


@router.delete("/{source_id}", status_code=204)
def delete_folder(source_id: str, services: ServicesDep) -> Response:
    services.datasets.folders.delete(source_id)
    return Response(status_code=204)


class LinkEachRequest(BaseModel):
    folder: str
    pattern: str = "*"


@router.post("/link-each")
def link_each(req: LinkEachRequest, services: ServicesDep) -> dict[str, Any]:
    """Um por arquivo: cada arquivo que casa com o padrão vira um arquivo vinculado, lido onde está."""
    files = folder_files(req.folder, req.pattern)
    if not files:
        raise InvalidInputError(
            f"Nenhum arquivo em {req.folder.strip()} casa com '{req.pattern.strip() or '*'}'."
        )
    linked, skipped = services.datasets.link_many(files)
    return {"linked": [d.model_dump(mode="json") for d in linked], "skipped": skipped}


class PreviewRequest(BaseModel):
    source: FolderSource


@router.post("/preview")
def preview_folder(req: PreviewRequest, rows: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    """Arquivos que entram, quais têm colunas diferentes e as primeiras linhas já empilhadas."""
    source = req.source
    try:
        files = source.files()
    except NotFoundError as exc:
        return {"files": [], "total": 0, "error": str(exc), "missing": True}
    except InvalidInputError as exc:
        return {"files": [], "total": 0, "error": str(exc), "missing": False}
    listed = [
        {
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat(),
            "odd": False,
        }
        for p in files
    ]
    out: dict[str, Any] = {"files": listed, "total": len(files), "error": "", "missing": False}
    if not files:
        return out
    per_file = max(5, rows // min(len(files), PREVIEW_FILES))
    try:
        table, odd = read_folder(files[:CHECK_FILES], source, source.file_column, limit=per_file)
    except InvalidInputError as exc:
        return {**out, "error": str(exc)}
    for item in listed:
        item["odd"] = item["name"] in odd
    out |= {
        "columns": schema_of(table),
        "rows": json_rows(table.head(rows)),
        "checked": min(len(files), CHECK_FILES),
    }
    return out
