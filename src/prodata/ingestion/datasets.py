"""Repositório de datasets confinado a um diretório."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel

from prodata.errors import ConflictError, InvalidInputError, NotFoundError, TooLargeError
from prodata.ingestion.detect import EXTENSIONS

CHUNK = 1024 * 1024


class DatasetInfo(BaseModel):
    name: str
    format: str
    size_bytes: int
    modified_at: datetime


def resolve_inside(base: Path, name: str) -> Path:
    """Resolve ``name`` dentro de ``base``; recusa qualquer caminho que escape dele."""
    # "\" é separador no Windows mas não no Linux: recusar em qualquer sistema mantém a regra igual.
    if "\\" in name:
        raise InvalidInputError(f"Nome de arquivo inválido: {name!r}")
    root = base.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise InvalidInputError(f"Nome de arquivo inválido: {name!r}")
    return candidate


def sanitize_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    stem = unicodedata.normalize("NFKC", stem)
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._") or "dataset"
    return f"{stem[:120]}{suffix}"


class DatasetStore:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, name: str) -> Path:
        path = resolve_inside(self.root, name)
        if not path.is_file():
            raise NotFoundError(f"Dataset não encontrado: {name}")
        return path

    def info(self, path: Path) -> DatasetInfo:
        stat = path.stat()
        return DatasetInfo(
            name=path.name,
            format=EXTENSIONS.get(path.suffix.lower(), "csv"),
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    def list(self) -> list[DatasetInfo]:
        files = (p for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
        return [self.info(p) for p in sorted(files, key=lambda p: p.name.lower())]

    def signature(self, name: str) -> str:
        """Muda sempre que o conteúdo do arquivo muda; entra no fingerprint do nó."""
        stat = self.resolve(name).stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}"

    def save(self, filename: str, stream: BinaryIO, *, overwrite: bool = False) -> DatasetInfo:
        name = sanitize_filename(filename)
        if Path(name).suffix.lower() not in EXTENSIONS:
            allowed = ", ".join(sorted(EXTENSIONS))
            raise InvalidInputError(f"Extensão não suportada. Use uma destas: {allowed}")
        target = resolve_inside(self.root, name)
        if target.exists() and not overwrite:
            raise ConflictError(f"Já existe um dataset chamado '{name}'.")

        partial = target.with_name(target.name + ".part")
        written = 0
        try:
            with partial.open("wb") as out:
                while chunk := stream.read(CHUNK):
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise TooLargeError(f"Arquivo maior que o limite de {self.max_bytes // CHUNK} MB.")
                    out.write(chunk)
            if written == 0:
                raise InvalidInputError("Arquivo vazio.")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        return self.info(target)

    def delete(self, name: str) -> None:
        self.resolve(name).unlink()
