"""Gera os ícones e as imagens do instalador a partir do escudo do Grupo Protege.

- ``packaging/prodata.ico``: ícone do PRO.DATA.exe e do instalador (escudo oficial).
- ``packaging/wizard-*.bmp``: imagens das telas do instalador (Inno Setup), em três escalas.

Os PNGs em ``packaging/brand/`` são o logotipo oficial (``src/prodata/web/brand/*.svg``)
renderizado com fundo transparente.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

SIZES = [16, 24, 32, 48, 64, 128, 256]
HERE = Path(__file__).resolve().parent
SHIELD = HERE / "brand" / "protege-escudo-1024.png"
SHIELD_LIGHT = HERE / "brand" / "protege-escudo-claro-1024.png"  # para fundo azul-marinho
OUT = HERE / "prodata.ico"

NAVY = (4, 49, 84)
NAVY_DEEP = (3, 34, 58)
GOLD = (149, 121, 60)
WHITE = (255, 255, 255)

# Inno Setup: imagem lateral 164x314 e pequena 55x58 a 100%; 150% e 200% para telas de alta densidade.
SCALES = {100: 1.0, 150: 1.5, 200: 2.0}


def _shield(path: Path, size: int) -> Image.Image:
    return Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def wizard_image(scale: float) -> Image.Image:
    """Faixa lateral: gradiente azul-marinho, escudo claro e filete dourado embaixo."""
    w, h = round(164 * scale), round(314 * scale)
    img = Image.new("RGB", (w, h), NAVY)
    for y in range(h):  # gradiente vertical simples, do marinho escuro ao marinho
        t = y / max(1, h - 1)
        color = tuple(round(NAVY_DEEP[i] + (NAVY[i] - NAVY_DEEP[i]) * t) for i in range(3))
        img.paste(color, (0, y, w, y + 1))
    shield = _shield(SHIELD_LIGHT, round(w * 0.72))
    img.paste(shield, ((w - shield.width) // 2, round(h * 0.18)), shield)
    img.paste(GOLD, (0, h - round(7 * scale), w, h))
    return img


def wizard_small_image(scale: float) -> Image.Image:
    """Canto superior direito das páginas do instalador: escudo oficial sobre branco."""
    w, h = round(55 * scale), round(58 * scale)
    img = Image.new("RGB", (w, h), WHITE)
    shield = _shield(SHIELD, round(min(w, h) * 0.92))
    img.paste(shield, ((w - shield.width) // 2, (h - shield.height) // 2), shield)
    return img


def main() -> None:
    source = Image.open(SHIELD).convert("RGBA")
    images = [source.resize((s, s), Image.Resampling.LANCZOS) for s in SIZES]
    images[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"Ícone gerado: {OUT}")
    for pct, scale in SCALES.items():
        wizard_image(scale).save(HERE / f"wizard-{pct}.bmp")
        wizard_small_image(scale).save(HERE / f"wizard-small-{pct}.bmp")
    print("Imagens do instalador geradas: wizard-*.bmp")


if __name__ == "__main__":
    main()
