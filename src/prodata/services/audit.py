"""Registro local das exportações (spec 026): quem exportou o quê, e com qual rótulo. Nunca os dados."""

from __future__ import annotations

import getpass
import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

audit_log = logging.getLogger("prodata.audit")
audit_log.setLevel(logging.INFO)
audit_log.propagate = False
LOG_NAME = "exportacoes.log"


def setup_audit(storage_dir: Path) -> None:
    """Grava em ``logs/exportacoes.log``, dentro da pasta de dados do programa."""
    for old in list(audit_log.handlers):
        audit_log.removeHandler(old)
        old.close()
    logs = storage_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / LOG_NAME, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_log.addHandler(handler)


def _user() -> str:
    try:
        return getpass.getuser()
    except OSError, KeyError, ImportError:
        return "desconhecido"


def log_export(
    kind: str, file: str, label: str, rows: int | None = None, columns: int | None = None, **extra: Any
) -> None:
    entry = {
        "quando": datetime.now(UTC).isoformat(timespec="seconds"),
        "usuario": _user(),
        "tipo": kind,
        "arquivo": file,
        "rotulo": label,
        "linhas": rows,
        "colunas": columns,
        **extra,
    }
    audit_log.info(json.dumps(entry, ensure_ascii=False))
