"""Pasta de arquivos como fonte da aba Dados (spec 035): vários arquivos de um padrão viram uma tabela só.

A pasta é só lida, onde está: o PRO.DATA nunca grava, move ou apaga nada nela (constituição IV). O cadastro fica num
arquivo ao lado da lista de arquivos vinculados; os fluxos guardam só ``folder:<id>``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import threading
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, Field, ValidationError, field_validator

from prodata.errors import ConflictError, InvalidInputError, NotFoundError
from prodata.ingestion.detect import EXTENSIONS
from prodata.ingestion.options import ReadOptions

FOLDER_PREFIX = "folder:"
MAX_FILES = 500
MAX_SOURCES = 500


def source_folder_id(source: str) -> str | None:
    """``folder:fechamento`` → ``fechamento``; outra fonte → None."""
    return source[len(FOLDER_PREFIX) :] if source.startswith(FOLDER_PREFIX) else None


def check_pattern(pattern: str) -> str:
    pattern = pattern.strip() or "*"
    if any(c in pattern for c in "/\\") or ".." in pattern:
        raise InvalidInputError("O padrão vale para o nome do arquivo: não pode ter barras nem '..'.")
    return pattern


def folder_files(folder: str, pattern: str) -> list[Path]:
    """Arquivos da pasta que casam com o padrão, em ordem de nome. Só a pasta escolhida, sem subpastas."""
    raw = folder.strip()
    if not raw:
        raise InvalidInputError("Escolha a pasta.")
    path = Path(raw)
    if not path.is_absolute():
        raise InvalidInputError("A pasta precisa ser um caminho completo, como D:\\Fechamento\\2026-10.")
    if not path.is_dir():
        raise NotFoundError(f"A pasta não existe: {path}. Ela foi movida ou renomeada?")
    wanted = check_pattern(pattern)
    found = sorted(
        (
            p
            for p in path.iterdir()
            if p.is_file()
            and p.suffix.lower() in EXTENSIONS
            and not p.name.startswith("~$")  # arquivo temporário do Excel aberto
            and fnmatch.fnmatch(p.name.lower(), wanted.lower())
        ),
        key=lambda p: p.name.lower(),
    )
    if len(found) > MAX_FILES:
        raise InvalidInputError(
            f"{len(found)} arquivos casam com '{wanted}': o limite é {MAX_FILES}. Use um padrão mais específico."
        )
    return found


def files_signature(files: list[Path]) -> str:
    return "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in files)


def read_folder(
    files: list[Path],
    options: ReadOptions,
    file_column: str,
    *,
    limit: int | None = None,
    report: Callable[[str], None] | None = None,
) -> tuple[pl.DataFrame, list[str]]:
    """Empilha os arquivos. Devolve a tabela e os arquivos com colunas diferentes das do primeiro."""
    from prodata.ingestion.readers import read_table  # evita ciclo na carga do pacote

    column = file_column.strip()
    frames: list[pl.DataFrame] = []
    odd: list[str] = []
    first: list[str] = []
    for i, path in enumerate(files, start=1):
        if report:
            report(f"{i}/{len(files)} arquivos")
        frame = read_table(path, options, n_rows=limit)
        if not frames:
            first = frame.columns
        elif set(frame.columns) != set(first):
            odd.append(path.name)
        if column:
            if column in frame.columns:
                raise InvalidInputError(
                    f"'{path.name}' já tem uma coluna '{column}': troque o nome da coluna do arquivo."
                )
            frame = frame.with_columns(pl.lit(path.name).alias(column))
        frames.append(frame)
    if not frames:
        return pl.DataFrame(), []
    try:
        return pl.concat(frames, how="diagonal_relaxed"), odd
    except pl.exceptions.PolarsError as exc:
        raise InvalidInputError(
            f"Os arquivos têm colunas com tipos que não combinam: {str(exc).splitlines()[0]}"
        ) from exc


def odd_warning(odd: list[str], first: str) -> str:
    shown = ", ".join(odd[:5]) + ("…" if len(odd) > 5 else "")
    return f"{len(odd)} arquivo(s) com colunas diferentes de {first}: {shown}. O que falta fica vazio."


class FolderSource(ReadOptions):
    """O cadastro. As opções de leitura valem para todos os arquivos da pasta."""

    id: str = Field("", pattern=r"^[a-z0-9_-]{0,60}$")
    name: str = Field(min_length=1, max_length=80)
    folder: str = Field(min_length=1, max_length=400)
    pattern: str = Field("*.xlsx", max_length=120)
    file_column: str = Field("arquivo", max_length=60)

    @field_validator("name", "file_column")
    @classmethod
    def _line(cls, value: str) -> str:
        return " ".join("".join(c if c.isprintable() else " " for c in value).split())

    def digest(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def files(self) -> list[Path]:
        return folder_files(self.folder, self.pattern)


class FolderStatus(BaseModel):
    files: int = 0
    newest: datetime | None = None
    missing: bool = False
    error: str = ""


class FolderEntry(FolderSource):
    status: FolderStatus = Field(default_factory=FolderStatus)


def status_of(source: FolderSource) -> FolderStatus:
    try:
        files = source.files()
    except NotFoundError as exc:
        return FolderStatus(missing=True, error=str(exc))
    except InvalidInputError as exc:
        return FolderStatus(error=str(exc))
    newest = max((p.stat().st_mtime for p in files), default=None)
    return FolderStatus(files=len(files), newest=datetime.fromtimestamp(newest, tz=UTC) if newest else None)


def _slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:40] or "pasta"


class FolderSources:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, FolderSource]:
        if not self.path.is_file():
            return {}
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
            return {s.id: s for s in (FolderSource.model_validate(item) for item in data)}
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            raise InvalidInputError(f"Lista de pastas de arquivos corrompida: {self.path}") from exc

    def _write(self, sources: dict[str, FolderSource]) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        items = [s.model_dump(mode="json") for s in sorted(sources.values(), key=lambda s: s.name.lower())]
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[FolderSource]:
        return sorted(self._read().values(), key=lambda s: s.name.lower())

    def get(self, source_id: str) -> FolderSource:
        found = self._read().get(source_id)
        if found is None:
            raise NotFoundError(
                f"A pasta de arquivos '{source_id}' não está cadastrada neste computador. Cadastre na vista Dados."
            )
        return found

    def save(self, source: FolderSource, previous: str | None = None) -> FolderSource:
        """Cria (sem id) ou atualiza (com o id de antes). A pasta precisa existir na hora de salvar."""
        path = Path(source.folder.strip())
        if not path.is_absolute():
            raise InvalidInputError("A pasta precisa ser um caminho completo, como D:\\Fechamento\\2026-10.")
        if not path.is_dir():
            raise NotFoundError(f"A pasta não existe: {path}")
        clean = source.model_copy(update={"folder": str(path), "pattern": check_pattern(source.pattern)})
        with self._lock:
            sources = self._read()
            if previous:
                if previous not in sources:
                    raise NotFoundError("Esta pasta de arquivos não existe mais.")
                clean = clean.model_copy(update={"id": previous})
            else:
                if len(sources) >= MAX_SOURCES:
                    raise InvalidInputError(f"O limite é de {MAX_SOURCES} pastas de arquivos.")
                base = clean.id or _slug(clean.name)
                new_id, n = base, 2
                while new_id in sources:
                    new_id, n = f"{base}_{n}", n + 1
                clean = clean.model_copy(update={"id": new_id})
            if any(s.id != clean.id and s.name.casefold() == clean.name.casefold() for s in sources.values()):
                raise ConflictError(f"Já existe uma pasta de arquivos chamada '{clean.name}'.")
            sources[clean.id] = clean
            self._write(sources)
        return clean

    def delete(self, source_id: str) -> None:
        """Só esquece o cadastro: a pasta e os arquivos ficam intactos."""
        with self._lock:
            sources = self._read()
            if sources.pop(source_id, None) is None:
                raise NotFoundError("Esta pasta de arquivos não existe mais.")
            self._write(sources)

    def signature(self, source_id: str) -> str:
        """Muda quando o cadastro muda ou quando entra, sai ou muda um arquivo da pasta."""
        source = self.get(source_id)
        try:
            files = source.files()
        except InvalidInputError as exc:  # padrão demais: a execução mostra o erro, a assinatura só registra
            return f"{source.digest()}#erro:{exc}"
        return f"{source.digest()}#{files_signature(files)}"
