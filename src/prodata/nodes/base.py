"""Registro declarativo de ferramentas.

Uma ferramenta é uma função decorada com ``@tool``, que recebe um ``NodeContext`` e
a configuração já validada, e devolve um ``NodeOutput``. O modelo de configuração
(Pydantic) é a única fonte de verdade para validação, valores padrão e formulário.
"""

from __future__ import annotations

import builtins
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo

from prodata.connectors.queries import QueryStore
from prodata.connectors.store import ConnectionStore
from prodata.errors import InvalidInputError
from prodata.ingestion.datasets import DatasetStore

CATEGORIES: list[dict[str, str]] = [
    {"id": "inout", "label": "Entrada e saída"},
    {"id": "prep", "label": "Preparação"},
    {"id": "transform", "label": "Combinar e transformar"},
    {"id": "bi", "label": "BI e indicadores"},
    {"id": "ml", "label": "Machine Learning"},
]


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True)
class Port:
    id: str
    label: str
    title: str
    kind: Literal["data", "model"] = "data"
    required: bool = True


@dataclass
class NodeContext:
    inputs: dict[str, pl.DataFrame]
    models: dict[str, dict[str, Any]]
    datasets: DatasetStore
    exports_dir: Path
    connections: ConnectionStore | None = None
    queries: QueryStore | None = None

    def input(self, port: str = "in") -> pl.DataFrame:
        if port not in self.inputs:
            raise InvalidInputError(f"Conecte a entrada [{port}].")
        return self.inputs[port]

    def model(self, port: str = "M") -> dict[str, Any]:
        if port not in self.models:
            raise InvalidInputError(f"Conecte um modelo treinado na entrada [{port}].")
        return self.models[port]


@dataclass
class NodeOutput:
    tables: dict[str, pl.DataFrame] = field(default_factory=dict)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[[NodeContext, Any], NodeOutput]


@dataclass(frozen=True)
class ToolSpec:
    type: str
    name: str
    category: str
    icon: str
    description: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    config: builtins.type[ToolConfig]
    run: RunFn
    annotate: Callable[[Any], str] | None = None
    # Valor extra que entra no fingerprint (ex.: assinatura do arquivo lido).
    fingerprint: Callable[[NodeContext, Any], str] | None = None
    # Ferramentas com efeito colateral (gravar arquivo) nunca usam cache.
    side_effect: bool = False
    # Fora da paleta (substituída), mas ainda executa em fluxos antigos.
    hidden: bool = False
    # Esquema visual mostrado no Configurar (spec 015): "crosstab", "transpose", "join".
    explainer: str | None = None

    def annotation(self, cfg: Any) -> str:
        if self.annotate is None:
            return ""
        try:
            return self.annotate(cfg)[:60]
        except AttributeError, IndexError, KeyError, TypeError:
            return ""

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "category": self.category,
            "icon": self.icon,
            "description": self.description,
            "inputs": [vars(p) for p in self.inputs],
            "outputs": [vars(p) for p in self.outputs],
            "default_config": self.config().model_dump(mode="json"),
            "config_fields": describe_fields(self.config),
            "hidden": self.hidden,
            "explainer": self.explainer,
        }


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    *,
    type: str,
    name: str,
    category: str,
    icon: str,
    description: str,
    config: builtins.type[ToolConfig],
    inputs: list[Port] | None = None,
    outputs: list[Port] | None = None,
    annotate: Callable[[Any], str] | None = None,
    fingerprint: Callable[[NodeContext, Any], str] | None = None,
    side_effect: bool = False,
    hidden: bool = False,
    explainer: str | None = None,
) -> Callable[[RunFn], RunFn]:
    def register(fn: RunFn) -> RunFn:
        if type in REGISTRY:
            raise RuntimeError(f"Ferramenta duplicada: {type}")
        REGISTRY[type] = ToolSpec(
            type=type,
            name=name,
            category=category,
            icon=icon,
            description=description,
            inputs=tuple(inputs if inputs is not None else [Port("in", "I", "Entrada")]),
            outputs=tuple(outputs if outputs is not None else [Port("out", "O", "Saída")]),
            config=config,
            run=fn,
            annotate=annotate,
            fingerprint=fingerprint,
            side_effect=side_effect,
            hidden=hidden,
            explainer=explainer,
        )
        return fn

    return register


# ---------------------------------------------------------------- descrição de formulários


def _unwrap_optional(annotation: Any) -> Any:
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _bounds(info: FieldInfo) -> dict[str, float]:
    out: dict[str, float] = {}
    for meta in info.metadata:
        for attr, key in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
            value = getattr(meta, attr, None)
            if value is not None:
                out[key] = value
    return out


def _describe_field(name: str, info: FieldInfo, default: Any) -> dict[str, Any]:
    extra: dict[str, Any] = dict(info.json_schema_extra) if isinstance(info.json_schema_extra, dict) else {}
    annotation = _unwrap_optional(info.annotation)
    origin = typing.get_origin(annotation)
    spec: dict[str, Any] = {
        "name": name,
        "title": info.title or name.replace("_", " ").capitalize(),
        "help": info.description or "",
        "default": default,
    }

    widget = extra.pop("widget", None)
    if origin is Literal:
        labels = extra.pop("labels", {})
        spec["options"] = [{"value": v, "label": labels.get(v, str(v))} for v in typing.get_args(annotation)]
        widget = widget or "select"
    elif annotation is bool:
        widget = widget or "toggle"
    elif annotation in (int, float):
        widget = widget or "number"
        spec.update(_bounds(info))
        spec["step"] = 1 if annotation is int else extra.pop("step", 0.01)
    elif origin is list:
        (item,) = typing.get_args(annotation) or (str,)
        if isinstance(item, type) and issubclass(item, BaseModel):
            widget = widget or "list"
            item_defaults = item().model_dump(mode="json")
            spec["item_fields"] = [
                _describe_field(n, f, item_defaults.get(n)) for n, f in item.model_fields.items()
            ]
            spec["item_default"] = item_defaults
        else:
            widget = widget or "tags"
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        widget = widget or "object"
    else:
        widget = widget or "text"

    spec["widget"] = widget
    spec.update(extra)  # show_if, group, port, placeholder (ver prodata.forms.ui)
    return spec


def describe_fields(model: type[BaseModel]) -> list[dict[str, Any]]:
    defaults = model().model_dump(mode="json")
    return [_describe_field(n, f, defaults.get(n)) for n, f in model.model_fields.items()]


def catalog() -> list[dict[str, Any]]:
    order = {c["id"]: i for i, c in enumerate(CATEGORIES)}
    specs = sorted(REGISTRY.values(), key=lambda s: order.get(s.category, 99))
    return [s.describe() for s in specs]
