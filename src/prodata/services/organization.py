"""Organização da vista Dados (spec 034): pastas, nome de exibição, descrição e fixadas.

Só metadados para a tela: nenhum fluxo lê este arquivo, e nada nele muda o que uma caixa executa. As fontes são
identificadas pela mesma chave da tela (``file:vendas.xlsx``, ``query:abc``...).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from prodata.errors import InvalidInputError, NotFoundError

log = logging.getLogger(__name__)

Color = Literal["azul", "verde", "ambar", "roxo", "vermelho", "cinza"]
KEY = re.compile(r"^(file|query|api|jira|jiraconn|conn|const):.{1,300}$", re.S)
MAX_FOLDERS = 100
MAX_SOURCES = 5000


def _plain(value: str, limit: int) -> str:
    """Texto de uma linha, sem caracteres de controle. Vira texto na tela, nunca HTML."""
    text = "".join(c if c.isprintable() else " " if c.isspace() else "" for c in value)
    return " ".join(text.split())[:limit]


class Folder(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]{6,16}$")
    name: str = Field(min_length=1, max_length=60)
    color: Color = "azul"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = _plain(value, 60)
        if not cleaned:
            raise ValueError("Dê um nome à pasta.")
        return cleaned


class SourceInfo(BaseModel):
    folder: str = ""
    label: str = Field("", max_length=120)
    description: str = Field("", max_length=1000)
    owner: str = Field("", max_length=120)
    pinned: bool = False

    @field_validator("label", "owner")
    @classmethod
    def _line(cls, value: str) -> str:
        return _plain(value, 120)

    @field_validator("description")
    @classmethod
    def _text(cls, value: str) -> str:
        lines = [
            "".join(c for c in line if c.isprintable() or c == "\t").strip() for line in value.splitlines()
        ]
        return "\n".join(lines).strip()[:1000]

    def empty(self) -> bool:
        return self == SourceInfo()


class Organization(BaseModel):
    folders: list[Folder] = Field(default_factory=list)
    sources: dict[str, SourceInfo] = Field(default_factory=dict)


class SourceChanges(BaseModel):
    """O que muda nas fontes escolhidas. Campo ausente fica como está."""

    folder: str | None = None
    label: str | None = None
    description: str | None = None
    owner: str | None = None
    pinned: bool | None = None


def check_key(key: str) -> str:
    if not KEY.match(key):
        raise InvalidInputError(f"Fonte desconhecida: {key[:60]}")
    return key


class OrganizationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def get(self) -> Organization:
        if not self.path.is_file():
            return Organization()
        try:
            return Organization.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            # Arquivo estragado não pode travar a vista: começa vazio e avisa no log.
            log.warning("Organização da vista Dados ilegível, começando vazia: %s", exc)
            return Organization()

    def _save(self, org: Organization) -> Organization:
        org.sources = {k: v for k, v in org.sources.items() if not v.empty()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(org.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(tmp, self.path)
        return org

    # ------------------------------------------------------------------ pastas

    def add_folder(self, name: str, color: Color = "azul") -> Organization:
        with self._lock:
            org = self.get()
            if len(org.folders) >= MAX_FOLDERS:
                raise InvalidInputError(f"O limite é de {MAX_FOLDERS} pastas.")
            folder = Folder(id=secrets.token_hex(4), name=name, color=color)
            if any(f.name.casefold() == folder.name.casefold() for f in org.folders):
                raise InvalidInputError(f'Já existe uma pasta chamada "{folder.name}".')
            org.folders.append(folder)
            return self._save(org)

    def update_folder(self, folder_id: str, name: str, color: Color) -> Organization:
        with self._lock:
            org = self.get()
            found = next((f for f in org.folders if f.id == folder_id), None)
            if found is None:
                raise NotFoundError("Pasta não encontrada.")
            changed = Folder(id=found.id, name=name, color=color)
            if any(f.id != folder_id and f.name.casefold() == changed.name.casefold() for f in org.folders):
                raise InvalidInputError(f'Já existe uma pasta chamada "{changed.name}".')
            org.folders = [changed if f.id == folder_id else f for f in org.folders]
            return self._save(org)

    def delete_folder(self, folder_id: str) -> Organization:
        """As fontes da pasta voltam para "Sem pasta": nenhuma fonte é apagada."""
        with self._lock:
            org = self.get()
            if not any(f.id == folder_id for f in org.folders):
                raise NotFoundError("Pasta não encontrada.")
            org.folders = [f for f in org.folders if f.id != folder_id]
            for info in org.sources.values():
                if info.folder == folder_id:
                    info.folder = ""
            return self._save(org)

    def move_folder(self, folder_id: str, position: int) -> Organization:
        with self._lock:
            org = self.get()
            found = next((f for f in org.folders if f.id == folder_id), None)
            if found is None:
                raise NotFoundError("Pasta não encontrada.")
            rest = [f for f in org.folders if f.id != folder_id]
            rest.insert(max(0, min(position, len(rest))), found)
            org.folders = rest
            return self._save(org)

    # ------------------------------------------------------------------ fontes

    def change_sources(self, keys: list[str], changes: SourceChanges) -> Organization:
        with self._lock:
            org = self.get()
            folders = {f.id for f in org.folders}
            if changes.folder and changes.folder not in folders:
                raise NotFoundError("Pasta não encontrada.")
            fields = changes.model_dump(exclude_none=True)
            for key in dict.fromkeys(check_key(k) for k in keys):
                current = org.sources.get(key, SourceInfo())
                org.sources[key] = SourceInfo.model_validate({**current.model_dump(), **fields})
            if len(org.sources) > MAX_SOURCES:
                raise InvalidInputError("Fontes demais para organizar.")
            return self._save(org)

    def forget(self, keys: list[str]) -> Organization:
        """A fonte foi excluída: a organização dela sai junto."""
        with self._lock:
            org = self.get()
            for key in keys:
                org.sources.pop(check_key(key), None)
            return self._save(org)
