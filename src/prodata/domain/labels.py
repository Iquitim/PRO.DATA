"""Rótulos de confidencialidade do PRO.DATA (spec 026). Não são os rótulos de sensibilidade da Microsoft."""

from __future__ import annotations

from typing import Literal

Confidentiality = Literal["publico", "interno", "confidencial", "restrito"]
DEFAULT_LABEL: Confidentiality = "interno"
LABEL_NAMES: dict[str, str] = {
    "publico": "Público",
    "interno": "Interno",
    "confidencial": "Confidencial",
    "restrito": "Restrito",
}
LABEL_COLORS = {"publico": "#1A7F4F", "interno": "#2A63D6", "confidencial": "#D97706", "restrito": "#C8302F"}
ORDER = list(LABEL_NAMES)
# Propriedade do arquivo Excel que guarda o rótulo.
EXCEL_PROPERTY = "Classificação PRO.DATA"


def needs_protection(label: str) -> bool:
    return label in ("confidencial", "restrito")


def most_restrictive(a: str, b: str) -> str:
    rank = {k: i for i, k in enumerate(ORDER)}
    return a if rank.get(a, 1) >= rank.get(b, 1) else b


def level_from_name(name: str | None) -> str | None:
    """O nível a partir do nome gravado num arquivo."""
    return next((k for k, v in LABEL_NAMES.items() if v == name), None)
