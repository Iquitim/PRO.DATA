"""Repositório de datasets confinado a um diretório."""

from __future__ import annotations

import json
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
    modified_at: datetime | None
    # Arquivo vinculado (spec 017): lido onde está, sempre na versão atual. None = cópia enviada.
    linked_path: str | None = None
    missing: bool = False


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
        # Vínculos (spec 017): nome → caminho absoluto de um arquivo escolhido pelo usuário.
        self._links_file = root.with_name(root.name + "_vinculos.json")

    # ------------------------------------------------------------------ vínculos (spec 017)

    def _links(self) -> dict[str, str]:
        if not self._links_file.is_file():
            return {}
        try:
            data = json.loads(self._links_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidInputError(f"Lista de arquivos vinculados corrompida: {self._links_file}") from exc
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_links(self, links: dict[str, str]) -> None:
        tmp = self._links_file.with_name(self._links_file.name + ".tmp")
        tmp.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._links_file)

    def link(self, raw_path: str, name: str | None = None) -> DatasetInfo:
        """Vincula um arquivo escolhido pelo usuário: absoluto, existente, extensão permitida (constituição IV)."""
        path = Path(raw_path.strip())
        if not raw_path.strip() or not path.is_absolute():
            raise InvalidInputError(
                "Informe o caminho completo do arquivo, como D:\\Relatorios\\vendas.xlsx."
            )
        if path.suffix.lower() not in EXTENSIONS:
            allowed = ", ".join(sorted(EXTENSIONS))
            raise InvalidInputError(f"Extensão não suportada. Use uma destas: {allowed}")
        if not path.is_file():
            raise NotFoundError(f"Arquivo não encontrado: {path}")
        label = sanitize_filename(name or path.name)
        if Path(label).suffix.lower() != path.suffix.lower():
            label = Path(label).stem + path.suffix.lower()
        links = self._links()
        if label in links or resolve_inside(self.root, label).exists():
            raise ConflictError(f"Já existe uma fonte chamada '{label}'. Dê outro nome ao vínculo.")
        links[label] = str(path.resolve())
        self._save_links(links)
        return self._info(label, path.resolve(), linked=True)

    def _info(self, name: str, path: Path, *, linked: bool) -> DatasetInfo:
        fmt = EXTENSIONS.get(path.suffix.lower(), "csv")
        try:
            stat = path.stat()
        except OSError:
            return DatasetInfo(
                name=name, format=fmt, size_bytes=0, modified_at=None, linked_path=str(path), missing=True
            )
        return DatasetInfo(
            name=name,
            format=fmt,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            linked_path=str(path) if linked else None,
        )

    def resolve(self, name: str) -> Path:
        linked = self._links().get(name)
        if linked is not None:
            path = Path(linked)
            if not path.is_file():
                raise NotFoundError(
                    f"O arquivo vinculado não foi encontrado: {path}. Ele foi movido ou renomeado?"
                )
            return path
        path = resolve_inside(self.root, name)
        if not path.is_file():
            raise NotFoundError(f"Dataset não encontrado: {name}")
        return path

    def info(self, path: Path) -> DatasetInfo:
        return self._info(path.name, path, linked=False)

    def info_of(self, name: str) -> DatasetInfo:
        linked = self._links().get(name)
        return self._info(name, Path(linked), linked=True) if linked else self.info(self.resolve(name))

    def list(self) -> list[DatasetInfo]:
        files = (p for p in self.root.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
        uploaded = [self.info(p) for p in files]
        linked = [self._info(n, Path(p), linked=True) for n, p in self._links().items()]
        return sorted([*uploaded, *linked], key=lambda d: d.name.lower())

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
        if (target.exists() and not overwrite) or name in self._links():
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
        links = self._links()
        if name in links:  # vínculo: só esquece o caminho; o arquivo do usuário fica intacto
            del links[name]
            self._save_links(links)
            return
        self.resolve(name).unlink()
