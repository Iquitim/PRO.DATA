"""Constantes compartilhadas (spec 028, RF-2841, RF-2848): cadastradas na vista Dados, valem para todos os fluxos."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from prodata.domain.constants import Constant
from prodata.errors import InvalidInputError, NotFoundError

_LIST = TypeAdapter(list[Constant])


class ConstantStore:
    """``constantes.json`` na pasta de dados: nome, tipo, valor e descrição de cada uma."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Constant]:
        if not self.path.is_file():
            return {}
        try:
            items = _LIST.validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise InvalidInputError(f"Lista de constantes corrompida em {self.path.name}: {exc}") from exc
        return {c.name: c for c in items}

    def _write(self, items: dict[str, Constant]) -> None:
        tmp = self.path.with_suffix(".tmp")
        data = [c.model_dump(mode="json") for c in sorted(items.values(), key=lambda c: c.name.lower())]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def all(self) -> dict[str, Constant]:
        with self._lock:
            return self._read()

    def list(self) -> list[Constant]:
        return sorted(self.all().values(), key=lambda c: c.name.lower())

    def save(self, constant: Constant, previous: str | None = None) -> Constant:
        """Cria ou altera. ``previous``: nome antigo, quando a constante é renomeada."""
        with self._lock:
            items = self._read()
            if constant.name in items and constant.name != previous:
                raise InvalidInputError(f"Já existe uma constante compartilhada chamada {constant.name}.")
            if previous and previous != constant.name:
                items.pop(previous, None)
            items[constant.name] = constant
            self._write(items)
            return constant

    def delete(self, name: str) -> None:
        with self._lock:
            items = self._read()
            if name not in items:
                raise NotFoundError(f"Constante não encontrada: {name}")
            items.pop(name)
            self._write(items)
