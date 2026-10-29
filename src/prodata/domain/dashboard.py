"""Layout do dashboard gravado no fluxo (spec 014).

O fluxo define os dados (caixas de BI); o dashboard define onde e como mostrar.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PAGE_WIDTH = 1600
PAGE_HEIGHTS = {"16:9": 900, "a4-landscape": 1131, "a4-portrait": 2263}
MAX_IMAGE_BYTES = 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/svg+xml")

# Um SVG embutido vira parte da página: nada que execute código ou busque conteúdo de fora.
_SVG_FORBIDDEN = re.compile(
    r"<\s*script|<\s*foreignObject|<\s*iframe|<\s*object|<\s*embed|\son\w+\s*=|javascript:"
    r"|(?:xlink:)?href\s*=\s*[\"']\s*(?!#|data:image/)",
    re.IGNORECASE,
)

PageSize = Literal["16:9", "a4-landscape", "a4-portrait", "free"]
ItemKind = Literal["visual", "text", "image", "shape"]


class DashPage(BaseModel):
    size: PageSize = "16:9"
    # Só vale para size="free"; nos demais a altura vem do formato.
    height: int = Field(900, ge=400, le=20000)
    background: str = ""

    @property
    def pixel_height(self) -> int:
        return self.height if self.size == "free" else PAGE_HEIGHTS[self.size]


class DashItem(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: ItemKind = "visual"
    node_id: str | None = None
    x: int = 0
    y: int = 0
    w: int = Field(320, ge=24)
    h: int = Field(160, ge=24)
    format: dict[str, Any] = Field(default_factory=dict)
    content: str = ""

    @model_validator(mode="after")
    def _check_kind(self) -> DashItem:
        if self.kind == "visual" and not self.node_id:
            raise ValueError(f"O visual '{self.id}' precisa da caixa de BI de origem.")
        if self.kind == "image" and self.content:
            check_image(self.content)
        if self.kind == "text":
            self.content = self.content[:5000]
        # Import tardio: os modelos de formato usam o gerador de formulários das ferramentas.
        from prodata.dashboard.formats import clean_format

        self.format = clean_format(self.kind, self.format)
        return self


class Dashboard(BaseModel):
    page: DashPage = Field(default_factory=DashPage)
    items: list[DashItem] = Field(default_factory=list)  # ordem = camada (o último fica por cima)
    hidden: list[str] = Field(default_factory=list)  # caixas de BI fora da página (RF-1407)

    @field_validator("items")
    @classmethod
    def _unique_ids(cls, items: list[DashItem]) -> list[DashItem]:
        ids = [i.id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("IDs de itens do dashboard duplicados.")
        return items

    def prune(self, node_ids: set[str]) -> None:
        """Esquece visuais de caixas que não existem mais no fluxo (spec 010, RF-1406)."""
        self.items = [i for i in self.items if i.kind != "visual" or i.node_id in node_ids]
        self.hidden = [n for n in dict.fromkeys(self.hidden) if n in node_ids]


def check_image(data_uri: str) -> None:
    """Imagens ficam dentro do fluxo como data URI: só PNG, JPEG ou SVG sem código, até 1 MB."""
    match = re.fullmatch(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)", data_uri)
    if not match or match.group(1) not in IMAGE_TYPES:
        raise ValueError("A imagem precisa ser PNG, JPG ou SVG.")
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Imagem corrompida.") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("A imagem passa de 1 MB. Reduza o tamanho antes de inserir.")
    if match.group(1) == "image/svg+xml" and _SVG_FORBIDDEN.search(raw.decode("utf-8", "replace")):
        raise ValueError("O SVG contém scripts ou links externos e não pode ser usado.")
