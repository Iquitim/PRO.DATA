"""Onde cada fonte é usada (spec 028, RF-2811..2815): fluxos da biblioteca, caixas que leem e o que vem depois.

O índice é refeito só quando algum arquivo da biblioteca muda, comparando data de modificação e tamanho, para a
vista Dados abrir rápido mesmo com centenas de fluxos.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from prodata.engine.constants import node_refs
from prodata.services.workflows import SUFFIX

log = logging.getLogger(__name__)

API = "api:"


def source_keys(node_type: str, config: dict[str, Any]) -> list[str]:
    """As fontes que uma caixa lê: o nome do arquivo, ``sql:<id>`` ou ``api:<id>``."""
    if node_type == "io.input_data" and config.get("dataset"):
        return [str(config["dataset"])]
    if node_type == "io.api_loop" and config.get("source"):
        return [f"{API}{config['source']}"]
    return []


def _downstream(edges: list[dict[str, Any]], start: str) -> list[str]:
    """Caixas depois de ``start``, na ordem em que os dados passam por elas."""
    following: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        following[str(edge.get("source"))].append(str(edge.get("target")))
    seen: list[str] = []
    queue = list(following[start])
    while queue:
        current = queue.pop(0)
        if current in seen or current == start:
            continue
        seen.append(current)
        queue.extend(following[current])
    return seen


def _brief(node: dict[str, Any]) -> dict[str, str]:
    return {"id": str(node.get("id")), "label": str(node.get("label") or ""), "type": str(node.get("type"))}


def _uses(data: dict[str, Any], has_constants: bool = True) -> dict[str, dict[str, Any]]:
    """Lê só caixas e ligações do arquivo: validar o fluxo inteiro custaria segundos com centenas deles."""
    nodes = {str(n.get("id")): n for n in data.get("nodes", []) if isinstance(n, dict)}
    edges = [e for e in data.get("edges", []) if isinstance(e, dict)]
    found: dict[str, dict[str, Any]] = {}
    for node in nodes.values():
        raw = node.get("config")
        config: dict[str, Any] = raw if isinstance(raw, dict) else {}
        names = node_refs(str(node.get("type")), config) if has_constants else set()
        refs = (f"const:{n}" for n in sorted(names))
        for key in [*source_keys(str(node.get("type")), config), *refs]:
            entry = found.setdefault(
                key,
                {
                    "workflow_id": str(data.get("id")),
                    "workflow": str(data.get("name") or data.get("id")),
                    "readers": [],
                    "downstream": [],
                },
            )
            entry["readers"].append(_brief(node))
            for next_id in _downstream(edges, str(node.get("id"))):
                if next_id in nodes and next_id not in {d["id"] for d in entry["downstream"]}:
                    entry["downstream"].append(_brief(nodes[next_id]))
    return found


class UsageIndex:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()
        self._stamp: tuple[tuple[str, float, int], ...] = ()
        self._index: dict[str, list[dict[str, Any]]] = {}

    def _current_stamp(self) -> tuple[tuple[str, float, int], ...]:
        files = []
        for path in self.folder.glob(f"*{SUFFIX}"):
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((path.name, stat.st_mtime, stat.st_size))
        return tuple(sorted(files))

    def get(self) -> dict[str, list[dict[str, Any]]]:
        """``{fonte: [uso por fluxo]}``. Fluxo ilegível fica de fora e vai para o log."""
        stamp = self._current_stamp()
        with self._lock:
            if stamp == self._stamp:
                return self._index
            index: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for name, _, _ in stamp:
                path = self.folder / name
                try:
                    text = path.read_text(encoding="utf-8")
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("não é um fluxo")
                except (OSError, ValueError) as exc:
                    log.warning("Fluxo ignorado no índice de uso: %s (%s)", name, exc)
                    continue
                # Sem "[#" no arquivo, não há constante: poupa percorrer cada configuração.
                for key, entry in _uses(data, "[#" in text).items():
                    index[key].append(entry)
            for entries in index.values():
                entries.sort(key=lambda e: e["workflow"].lower())
            self._index = dict(index)
            self._stamp = stamp
            return self._index
