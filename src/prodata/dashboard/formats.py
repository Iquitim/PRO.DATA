"""Formato dos itens do dashboard (spec 014, RF-1410..RF-1413, RF-1440..RF-1442).

Declarativos como as ferramentas (constituição III): o painel Formato é gerado destes modelos.
O formato só muda a aparência; nunca exige executar o fluxo de novo.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from prodata.forms import ui
from prodata.nodes.base import describe_fields

CARD = "Cartão"
COLORS = "Cores"
LABELS = "Rótulos e legenda"
AXES = "Eixos"


def _color(value: str) -> str:
    """Só #rrggbb (ou vazio = padrão do tema): o valor vai para estilos da página."""
    value = value.strip().lower()
    if value and not (
        len(value) == 7 and value[0] == "#" and all(c in "0123456789abcdef" for c in value[1:])
    ):
        raise ValueError("Cor inválida: use o formato #rrggbb.")
    return value


Color = Annotated[str, AfterValidator(_color)]


def _color_map(value: dict[str, str]) -> dict[str, str]:
    return {k[:200]: _color(v) for k, v in list(value.items())[:50] if _color(v)}


class _Format(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CardFormat(_Format):
    show_title: bool = Field(True, title="Mostrar título")
    title: str = Field(
        "",
        title="Título",
        max_length=200,
        json_schema_extra=ui(placeholder="Igual ao da caixa no fluxo", show_if={"show_title": [True]}),
    )
    title_size: int = Field(
        14, ge=10, le=32, title="Tamanho do título", json_schema_extra=ui(show_if={"show_title": [True]})
    )
    title_align: Literal["left", "center"] = Field(
        "left",
        title="Alinhamento do título",
        json_schema_extra=ui(labels={"left": "Esquerda", "center": "Centro"}),
    )
    show_subtitle: bool = Field(True, title="Mostrar subtítulo")
    background: Color = Field("", title="Fundo", json_schema_extra=ui(widget="color", group=CARD))
    border: bool = Field(True, title="Borda", json_schema_extra=ui(group=CARD))
    border_color: Color = Field(
        "", title="Cor da borda", json_schema_extra=ui(widget="color", group=CARD, show_if={"border": [True]})
    )
    radius: int = Field(10, ge=0, le=32, title="Cantos arredondados", json_schema_extra=ui(group=CARD))
    shadow: bool = Field(False, title="Sombra", json_schema_extra=ui(group=CARD))


class ChartFormat(CardFormat):
    palette: Literal["brand", "alt", "single", "custom"] = Field(
        "brand",
        title="Cores",
        json_schema_extra=ui(
            group=COLORS,
            labels={
                "brand": "Paleta da marca",
                "alt": "Paleta alternativa",
                "single": "Uma cor só",
                "custom": "Uma cor por categoria",
            },
        ),
    )
    color: Color = Field(
        "", title="Cor", json_schema_extra=ui(widget="color", group=COLORS, show_if={"palette": ["single"]})
    )
    category_colors: Annotated[dict[str, str], AfterValidator(_color_map)] = Field(
        default_factory=dict,
        title="Cor de cada categoria",
        json_schema_extra=ui(widget="category_colors", group=COLORS, show_if={"palette": ["custom"]}),
    )
    data_labels: Literal["none", "max", "max_min"] = Field(
        "max",
        title="Rótulos de dados",
        description="Números em destaque no gráfico. Os demais aparecem ao passar o mouse.",
        json_schema_extra=ui(
            group=LABELS, labels={"none": "Nenhum", "max": "Maior valor", "max_min": "Maior e menor"}
        ),
    )
    label_format: Literal["compact", "full"] = Field(
        "compact",
        title="Formato dos números",
        json_schema_extra=ui(
            group=LABELS, labels={"compact": "Compacto (1,2 mi)", "full": "Completo (1.234.567)"}
        ),
    )
    decimals: int = Field(1, ge=0, le=4, title="Casas decimais", json_schema_extra=ui(group=LABELS))
    prefix: str = Field(
        "", max_length=10, title="Prefixo", json_schema_extra=ui(group=LABELS, placeholder="R$ ")
    )
    suffix: str = Field(
        "", max_length=10, title="Sufixo", json_schema_extra=ui(group=LABELS, placeholder="%")
    )
    show_legend: bool = Field(
        True, title="Mostrar legenda", description="Gráficos de rosca.", json_schema_extra=ui(group=LABELS)
    )
    grid: bool = Field(True, title="Linhas de grade", json_schema_extra=ui(group=AXES))
    x_title: str = Field("", max_length=80, title="Título do eixo X", json_schema_extra=ui(group=AXES))
    y_title: str = Field("", max_length=80, title="Título do eixo Y", json_schema_extra=ui(group=AXES))
    y_min: float | None = Field(
        None, title="Mínimo do eixo Y", json_schema_extra=ui(group=AXES, widget="optional_number")
    )
    y_max: float | None = Field(
        None, title="Máximo do eixo Y", json_schema_extra=ui(group=AXES, widget="optional_number")
    )


class KpiFormat(CardFormat):
    value_size: int = Field(30, ge=16, le=96, title="Tamanho do número")
    value_color: Color = Field("", title="Cor do número", json_schema_extra=ui(widget="color"))
    align: Literal["left", "center"] = Field(
        "left", title="Alinhamento", json_schema_extra=ui(labels={"left": "Esquerda", "center": "Centro"})
    )
    show_footer: bool = Field(True, title="Mostrar rodapé (métrica e linhas)")


class VisualFormat(ChartFormat, KpiFormat):
    """Validação no arquivo: um visual pode ser gráfico ou KPI."""


class TextFormat(_Format):
    size: int = Field(16, ge=8, le=96, title="Tamanho")
    bold: bool = Field(False, title="Negrito")
    italic: bool = Field(False, title="Itálico")
    color: Color = Field("", title="Cor", json_schema_extra=ui(widget="color"))
    align: Literal["left", "center", "right"] = Field(
        "left",
        title="Alinhamento",
        json_schema_extra=ui(labels={"left": "Esquerda", "center": "Centro", "right": "Direita"}),
    )
    vertical: Literal["top", "middle", "bottom"] = Field(
        "top",
        title="Posição vertical",
        json_schema_extra=ui(labels={"top": "Topo", "middle": "Meio", "bottom": "Base"}),
    )
    background: Color = Field("", title="Fundo", json_schema_extra=ui(widget="color"))


class ImageFormat(_Format):
    fit: Literal["contain", "cover", "fill"] = Field(
        "contain",
        title="Encaixe",
        json_schema_extra=ui(
            labels={"contain": "Inteira, sem cortar", "cover": "Preencher (corta)", "fill": "Esticar"}
        ),
    )
    opacity: int = Field(100, ge=10, le=100, title="Opacidade (%)")
    radius: int = Field(0, ge=0, le=64, title="Cantos arredondados")


class ShapeFormat(_Format):
    shape: Literal["rect", "line"] = Field(
        "rect", title="Forma", json_schema_extra=ui(labels={"rect": "Retângulo", "line": "Linha"})
    )
    fill: Color = Field(
        "", title="Preenchimento", json_schema_extra=ui(widget="color", show_if={"shape": ["rect"]})
    )
    opacity: int = Field(100, ge=5, le=100, title="Opacidade (%)")
    stroke: Color = Field("", title="Cor da borda/linha", json_schema_extra=ui(widget="color"))
    stroke_width: int = Field(1, ge=0, le=16, title="Espessura")
    radius: int = Field(
        12, ge=0, le=64, title="Cantos arredondados", json_schema_extra=ui(show_if={"shape": ["rect"]})
    )


FORMATS: dict[str, type[_Format]] = {
    "chart": ChartFormat,
    "kpi": KpiFormat,
    "text": TextFormat,
    "image": ImageFormat,
    "shape": ShapeFormat,
}
VALIDATORS: dict[str, type[_Format]] = {
    "visual": VisualFormat,
    "text": TextFormat,
    "image": ImageFormat,
    "shape": ShapeFormat,
}


def describe_formats() -> dict[str, list[dict[str, Any]]]:
    return {kind: describe_fields(model) for kind, model in FORMATS.items()}


def clean_format(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Valida e guarda só o que difere do padrão (arquivo de fluxo enxuto)."""
    model = VALIDATORS[kind]
    return model.model_validate(data).model_dump(mode="json", exclude_defaults=True)
