"""Biblioteca de modelos (spec 033): um modelo treinado ganha nome e pode ser usado em outros fluxos e computadores.

O arquivo ``.modelo`` usa o formato do skops, e não pickle: ler um pickle executa o código que estiver dentro
dele, e um modelo recebido de outra pessoa não pode ter esse poder. Aqui o arquivo só é aberto se tudo o que
ele contém estiver na lista de tipos de modelo que o próprio PRO.DATA treina.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from prodata.errors import InvalidInputError, NotFoundError

SUFFIX = ".modelo"
MAX_BYTES = 200 * 1024 * 1024
FORMAT = 1
# Tudo o que um modelo do PRO.DATA pode conter além dos tipos básicos. Qualquer outra coisa recusa o arquivo.
TRUSTED = ("sklearn.tree._tree.Tree",)
ESTIMATORS = {
    "RandomForestClassifier",
    "RandomForestRegressor",
    "GradientBoostingClassifier",
    "GradientBoostingRegressor",
    "LogisticRegression",
    "LinearRegression",
}
_KEYS = {"model", "task_type", "target_column", "feature_columns", "encoders", "classes", "metrics"}


def slug(name: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", name.strip(), flags=re.UNICODE).strip().replace(" ", "_")
    if not text:
        raise InvalidInputError("Dê um nome ao modelo, com letras ou números.")
    return text[:60]


def folder_of(state_root: Path | None) -> Path:
    if state_root is None:
        raise InvalidInputError("A biblioteca de modelos não está disponível neste ambiente.")
    folder = state_root.parent / "modelos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _payload(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    importance: pl.DataFrame | None = bundle.get("importance")
    return {
        "format": FORMAT,
        **{key: bundle[key] for key in _KEYS},
        "importance": importance.to_dict(as_series=False) if importance is not None else {},
        "info": info,
    }


def to_bytes(bundle: dict[str, Any], info: dict[str, Any]) -> bytes:
    from skops.io import dumps

    data: bytes = dumps(_payload(bundle, info))
    return data


def from_bytes(data: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """O modelo e as informações dele. Recusa o que não for um modelo feito pelo PRO.DATA."""
    from skops.io import get_untrusted_types, loads

    refuse = "O arquivo não é um modelo do PRO.DATA"
    if len(data) > MAX_BYTES:
        raise InvalidInputError("O arquivo do modelo passa de 200 MB.")
    try:
        unknown = set(get_untrusted_types(data=data)) - set(TRUSTED)
        if unknown:
            raise InvalidInputError(
                f"{refuse}: traz conteúdo que não pertence a um modelo ({sorted(unknown)[0]})."
            )
        payload = loads(data, trusted=list(TRUSTED))
    except InvalidInputError:
        raise
    except Exception as exc:  # arquivo corrompido, de outro programa ou de outra versão
        raise InvalidInputError(f"{refuse}, ou foi feito por uma versão incompatível.") from exc
    if not isinstance(payload, dict) or not payload.keys() >= _KEYS:
        raise InvalidInputError(f"{refuse}.")
    if type(payload["model"]).__name__ not in ESTIMATORS:
        raise InvalidInputError(f"{refuse}: tipo de modelo desconhecido.")
    importance = payload.get("importance") or {}
    bundle = {key: payload[key] for key in _KEYS}
    bundle["importance"] = pl.DataFrame(
        importance, schema={"variavel": pl.String, "importancia_pct": pl.Float64}
    )
    raw_info = payload.get("info")
    info: dict[str, Any] = dict(raw_info) if isinstance(raw_info, dict) else {}
    return bundle, info


def _card(name: str, bundle: dict[str, Any], info: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "name": name,
        "task_type": bundle["task_type"],
        "algorithm": (bundle["metrics"] or {}).get("algorithm", ""),
        "target_column": bundle["target_column"],
        "feature_columns": list(bundle["feature_columns"]),
        "classes": list(bundle["classes"]),
        "metrics": bundle["metrics"],
        "trained_at": info.get("trained_at", ""),
        "rows": info.get("rows"),
        "version": info.get("version"),
        "origin": info.get("origin", ""),
        "sha256": digest,
    }


def store(folder: Path, name: str, data: bytes) -> dict[str, Any]:
    """Grava um arquivo de modelo já conferido e a ficha que a lista mostra."""
    bundle, info = from_bytes(data)
    key = slug(name)
    card = _card(key, bundle, info, hashlib.sha256(data).hexdigest())
    tmp = folder / f"{key}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / f"{key}{SUFFIX}")
    (folder / f"{key}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    return card


def publish(folder: Path, name: str, bundle: dict[str, Any], record: dict[str, Any], origin: str) -> None:
    """O Model Trainer guarda o modelo com nome. Regrava só quando o modelo é outro."""
    key = slug(name)
    stamp = f"{record.get('version')}|{record.get('trained_at')}|{origin}"
    current = card(folder, key) if (folder / f"{key}.json").is_file() else None
    if current is not None and current.get("stamp") == stamp:
        return
    info = {
        "trained_at": record.get("trained_at") or datetime.now().astimezone().isoformat(timespec="seconds"),
        "rows": record.get("rows"),
        "version": record.get("version"),
        "origin": origin,
    }
    saved = store(folder, key, to_bytes(bundle, info))
    (folder / f"{key}.json").write_text(
        json.dumps({**saved, "stamp": stamp}, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def card(folder: Path, name: str) -> dict[str, Any]:
    path = folder / f"{slug(name)}.json"
    if not path.is_file() or not path.with_suffix(SUFFIX).is_file():
        raise NotFoundError(
            f"O modelo '{name}' não está na biblioteca deste computador. Importe o arquivo dele."
        )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def cards(folder: Path) -> list[dict[str, Any]]:
    found = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stem.lower()):
        if path.with_suffix(SUFFIX).is_file():
            try:
                found.append(json.loads(path.read_text(encoding="utf-8")))
            except OSError, ValueError:
                continue
    return found


def file_bytes(folder: Path, name: str) -> bytes:
    card(folder, name)
    return (folder / f"{slug(name)}{SUFFIX}").read_bytes()


def load(folder: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """O modelo pronto para o Predictor e a ficha dele. O arquivo é conferido de novo a cada leitura."""
    info = card(folder, name)
    bundle, _ = from_bytes(file_bytes(folder, name))
    return bundle, info


def delete(folder: Path, name: str) -> None:
    card(folder, name)
    for suffix in (SUFFIX, ".json"):
        (folder / f"{slug(name)}{suffix}").unlink(missing_ok=True)
