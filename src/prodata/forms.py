"""Metadados de formulário anexados aos campos Pydantic (lidos por ``describe_fields``)."""

from __future__ import annotations

from typing import Any


def ui(
    *,
    widget: str | None = None,
    group: str | None = None,
    show_if: dict[str, list[Any]] | None = None,
    port: str | None = None,
    placeholder: str | None = None,
    labels: dict[str, str] | None = None,
    step: float | None = None,
    source: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Metadados de UI de um campo.

    - ``widget``: força o tipo de controle (``column``, ``columns``, ``expression``, ``sql``...).
    - ``group``: seção do formulário; campos sem grupo aparecem primeiro.
    - ``show_if``: ``{"campo": [valores]}``; ``$format`` refere-se ao formato do arquivo.
    - ``port``: para widgets de coluna, de qual porta de entrada vêm as opções.
    - ``labels``: rótulos legíveis para opções de ``Literal``.
    - ``source``: campo com o nome da coluna cujos valores o widget lista (``column_values``).
    - ``max_items``: quantos itens podem ser escolhidos no máximo.
    """
    meta = {
        "widget": widget,
        "group": group,
        "show_if": show_if,
        "port": port,
        "placeholder": placeholder,
        "labels": labels,
        "step": step,
        "source": source,
        "max_items": max_items,
    }
    return {k: v for k, v in meta.items() if v is not None}
