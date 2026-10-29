"""Modelo do arquivo de workflow (``.prodata.json``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class Container(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    color: str = "#64748b"
    opacity: float = Field(0.05, ge=0, le=0.4, description="Opacidade do fundo da caixa.")
    # Caixa desligada: a interface desativa os nós de dentro (ver spec 007, RF-712).
    disabled: bool = False
    x: float = 0
    y: float = 0
    width: float = 300
    height: float = 200


class Node(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    type: str
    label: str = ""
    x: float = 0
    y: float = 0
    config: dict[str, Any] = Field(default_factory=dict)
    disabled: bool = False
    # Ponto de cache (spec 012): entrega o resultado congelado e dispensa as caixas anteriores.
    cache_point: bool = False


class Edge(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: str
    source: str
    source_handle: str = Field("out", alias="sourceHandle")
    target: str
    target_handle: str = Field("in", alias="targetHandle")


class Workflow(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = "Novo fluxo"
    description: str = ""
    containers: list[Container] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> Workflow:
        ids = [n.id for n in self.nodes]
        duplicated = {i for i in ids if ids.count(i) > 1}
        if duplicated:
            raise ValueError(f"IDs de nó duplicados: {', '.join(sorted(duplicated))}")
        known = set(ids)
        for e in self.edges:
            if e.source not in known or e.target not in known:
                raise ValueError(f"Conexão '{e.id}' referencia nó inexistente.")
            if e.source == e.target:
                raise ValueError(f"Conexão '{e.id}' liga um nó a ele mesmo.")
        return self

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)
