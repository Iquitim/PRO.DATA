"""Repositório de workflows em arquivos ``<id>.prodata.json``."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from prodata.domain.workflow import Workflow
from prodata.errors import InvalidInputError, NotFoundError

log = logging.getLogger(__name__)
SUFFIX = ".prodata.json"


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    modified_at: datetime


class WorkflowRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        # Chamadores passam IDs já validados por ID_PATTERN (rotas e modelo Workflow),
        # então o caminho não tem como escapar do diretório.
        return self.root / f"{workflow_id}{SUFFIX}"

    def list(self) -> list[WorkflowSummary]:
        items: list[WorkflowSummary] = []
        for path in sorted(self.root.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                wf = Workflow.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, OSError) as exc:
                log.warning("Workflow inválido ignorado: %s (%s)", path.name, exc)
                continue
            items.append(
                WorkflowSummary(
                    id=wf.id,
                    name=wf.name,
                    description=wf.description,
                    node_count=len(wf.nodes),
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                )
            )
        return items

    def get(self, workflow_id: str) -> Workflow:
        path = self._path(workflow_id)
        if not path.is_file():
            raise NotFoundError(f"Workflow não encontrado: {workflow_id}")
        return Workflow.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, workflow_id: str) -> bool:
        return self._path(workflow_id).is_file()

    def save(self, workflow: Workflow) -> Workflow:
        path = self._path(workflow.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(workflow.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, path)
        return workflow

    def delete(self, workflow_id: str) -> None:
        path = self._path(workflow_id)
        if not path.is_file():
            raise NotFoundError(f"Workflow não encontrado: {workflow_id}")
        path.unlink()


# ---------------------------------------------------------------- arquivos fora da biblioteca (spec 009)


def external_path(raw: str) -> Path:
    """Caminho de um ``.prodata.json`` escolhido pelo usuário: absoluto, com pasta existente."""
    path = Path(raw.strip())
    if not raw.strip() or not path.is_absolute():
        raise InvalidInputError(
            "Informe o caminho completo do arquivo, como D:\\Fluxos\\vendas.prodata.json."
        )
    if not path.name.lower().endswith(SUFFIX):
        path = path.with_name(path.name.removesuffix(".json") + SUFFIX)
    if not path.parent.is_dir():
        raise InvalidInputError(f"A pasta não existe: {path.parent}")
    return path.resolve()


def save_to_file(workflow: Workflow, raw_path: str) -> Path:
    path = external_path(raw_path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(workflow.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, path)
    return path


def load_from_file(raw_path: str) -> tuple[Workflow, Path]:
    path = external_path(raw_path)
    if not path.is_file():
        raise NotFoundError(f"Arquivo não encontrado: {path}")
    try:
        return Workflow.model_validate_json(path.read_text(encoding="utf-8")), path
    except ValidationError as exc:
        raise InvalidInputError(f"O arquivo não é um fluxo do PRO.DATA válido: {path.name}") from exc
