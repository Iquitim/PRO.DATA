"""Modelos de ML guardados em disco, com versão (spec 033).

Ficam na pasta de dados do computador, na pasta da caixa. O arquivo do modelo é lido só dali: um fluxo
recebido de outra pessoa não traz modelo, e o caminho nunca vem da configuração.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from prodata.errors import InvalidInputError

log = logging.getLogger(__name__)
KEEP_ALWAYS = 10  # versões guardadas no modo "Treinar sempre"


def data_hash(df: pl.DataFrame) -> str:
    """Muda quando as linhas ou as colunas mudam, não importa por qual caminho os dados chegaram."""
    rows = int(df.hash_rows(seed=7).sum() or 0) if df.height else 0
    schema = "|".join(f"{name}:{dtype}" for name, dtype in df.schema.items())
    return hashlib.sha256(f"{df.height}|{schema}|{rows}".encode()).hexdigest()[:20]


def config_hash(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:20]


def _paths(folder: Path, version: int) -> tuple[Path, Path]:
    return folder / f"v{version}.joblib", folder / f"v{version}.json"


def meta(folder: Path, version: int) -> dict[str, Any] | None:
    path = _paths(folder, version)[1]
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        log.warning("Registro de modelo ilegível: %s", path)
        return None
    return data


def versions(folder: Path) -> list[int]:
    found = []
    for path in folder.glob("v*.json"):
        if path.stem[1:].isdigit() and _paths(folder, int(path.stem[1:]))[0].is_file():
            found.append(int(path.stem[1:]))
    return sorted(found)


def save(folder: Path, version: int, bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    import joblib

    model_path, meta_path = _paths(folder, version)
    tmp = model_path.with_suffix(".tmp")
    joblib.dump(bundle, tmp, compress=3)
    os.replace(tmp, model_path)
    record = {
        **info,
        "version": version,
        "trained_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
    }
    meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def load(folder: Path, version: int, record: dict[str, Any]) -> dict[str, Any]:
    import joblib

    model_path = _paths(folder, version)[0]
    again = f"Aumente a Versão para treinar de novo. ({model_path.name})"
    try:
        raw = model_path.read_bytes()
    except OSError as exc:
        raise InvalidInputError(f"O modelo guardado não pôde ser lido. {again}") from exc
    if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
        raise InvalidInputError(f"O arquivo do modelo guardado mudou fora do programa. {again}")
    try:
        bundle: dict[str, Any] = joblib.load(model_path)
    except Exception as exc:  # modelo de outra versão da biblioteca: mensagem acionável
        raise InvalidInputError(f"O modelo guardado é de outra versão do programa. {again}") from exc
    return bundle


def when(record: dict[str, Any]) -> str:
    try:
        return datetime.fromisoformat(str(record["trained_at"])).strftime("%d/%m/%Y")
    except KeyError, ValueError:
        return "data desconhecida"


def node_folder(state_root: Path, workflow_id: str, node_id: str) -> Path:
    """A pasta onde a caixa guarda as versões: o mesmo caminho de ``NodeContext.state_dir``, sem criar nada."""
    safe = lambda part: "".join(c if c.isalnum() or c in "-_" else "_" for c in part)  # noqa: E731
    return state_root / safe(workflow_id) / safe(node_id)


def listing(folder: Path) -> list[dict[str, Any]]:
    """As versões guardadas, da mais nova para a mais antiga, com o que a tela mostra de cada uma."""
    found = []
    for version in reversed(versions(folder) if folder.is_dir() else []):
        record = meta(folder, version) or {}
        found.append(
            {
                "version": version,
                "trained_at": record.get("trained_at", ""),
                "rows": record.get("rows"),
                "metrics": record.get("metrics") or {},
            }
        )
    return found


def delete(folder: Path, version: int, in_use: int | None) -> None:
    if version == in_use:
        raise InvalidInputError(
            f"A versão {version} é a que a caixa está usando. Escolha outra versão antes de apagar esta."
        )
    if version not in (versions(folder) if folder.is_dir() else []):
        raise InvalidInputError(f"A versão {version} não está guardada.")
    for path in _paths(folder, version):
        path.unlink(missing_ok=True)
