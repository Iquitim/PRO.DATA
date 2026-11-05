"""Modo escuro legível (spec 021): o texto mantém contraste 4,5:1 com o fundo."""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parents[1] / "src/prodata/web"
TOKENS = (WEB / "css/tokens.css").read_text(encoding="utf-8")


def block(selector: str) -> dict[str, str]:
    start = TOKENS.index(selector)
    body = TOKENS[start : TOKENS.index("}", start)]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", body))


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


DARK = block(':root[data-theme="dark"]')
LIGHT = block(":root {")
CATEGORIES = ["inout", "prep", "transform", "bi", "ml", "org"]


def mix(color: str, other: str, share: float) -> str:
    """Como color-mix em sRGB: ``share`` de ``color`` e o resto de ``other``."""
    values = [
        round(int(color[i : i + 2], 16) * share + int(other[i : i + 2], 16) * (1 - share)) for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{v:02x}" for v in values)


@pytest.mark.parametrize(
    "text", ["text", "text-2", "text-3", "accent", "ok", "warn", "err", "fx-kw", "fx-str", "fx-num", "fx-col"]
)
@pytest.mark.parametrize("background", ["bg", "surface", "surface-2"])
def test_dark_text_is_readable(text: str, background: str) -> None:
    assert contrast(DARK[text], DARK[background]) >= 4.5, (text, background)


def test_dark_background_is_dracula_not_black() -> None:
    assert DARK["surface"] == "#282a36"
    assert DARK["text"] == "#f8f8f2"
    assert luminance(DARK["bg"]) > luminance("#18181a")


def test_both_dark_blocks_match() -> None:
    assert block('[data-theme="light"]) {') == DARK


def test_accent_button_text_is_readable() -> None:
    assert contrast(DARK["accent-text"], DARK["accent"]) >= 4.5


@pytest.mark.parametrize("category", CATEGORIES)
def test_each_category_has_its_color(category: str) -> None:
    """Sem esta regra, caixas e paleta perdem a cor sem erro nenhum (aconteceu na 0.5.5)."""
    assert f'[data-category="{category}"] {{ --cat: var(--cat-{category}); }}' in TOKENS
    assert f"cat-{category}" in LIGHT and f"cat-{category}" in DARK


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["claro", "escuro"])
@pytest.mark.parametrize("category", CATEGORIES)
def test_node_stays_readable(theme: dict[str, str], category: str) -> None:
    color = theme[f"cat-{category}"]
    assert contrast(theme["surface"], color) >= 3, "ícone sobre a cor da família"
    tint = mix(color, theme["surface"], 0.10)  # o ponto mais colorido do fundo da caixa
    assert contrast(theme["text"], tint) >= 4.5, "nome da caixa"
    assert contrast(theme["text-2"], tint) >= 4.5, "resumo da caixa"
    assert contrast(color, theme["canvas"]) >= 3, "faixa lateral contra o canvas"


def test_every_css_variable_exists() -> None:
    """Uma variável sem definição faz a regra sumir em silêncio, sem erro em lugar nenhum."""
    css = "\n".join(p.read_text(encoding="utf-8") for p in (WEB / "css").glob("*.css"))
    scripts = "\n".join(p.read_text(encoding="utf-8") for p in (WEB / "js").glob("*.js"))
    defined = set(re.findall(r"(--[\w-]+)\s*:", css)) | set(re.findall(r"[\'\"](--[\w-]+)[\'\"]", scripts))
    defined |= set(re.findall(r"--[\w-]+(?=[\'\"`]?\s*[:,])", scripts))
    used = set(re.findall(r"var\((--[\w-]+)\s*\)", css))
    assert not used - defined
