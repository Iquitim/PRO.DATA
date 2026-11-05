"""Mede os vazios do guia em PDF (spec 025): nenhuma página pode ficar só com um título, uma legenda ou uma sobra.

    uv run --no-project --with pypdfium2 --with pillow python docs/guia/verificar_pdf.py

A sobra no fim de um capítulo é normal, porque cada capítulo começa em página nova: conta só o vazio no meio da
página, uma página quase sem conteúdo ou uma página que termina cedo sem o capítulo ter acabado.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops

PDF = Path(__file__).resolve().parent / "PRO.DATA-Guia-do-Produto.pdf"
MIN_CONTENT = 0.30  # conteúdo até 30% da altura, no mínimo
MAX_GAP = 0.30  # maior vazio entre dois blocos da mesma página
MIN_MID_CHAPTER = 0.62  # no meio de um capítulo, a página vai pelo menos até aqui
SOURCE = PDF.with_name("guia.html")


def measure(page) -> tuple[float, float]:
    image = page.render(scale=1).to_pil().convert("L")
    width, height = image.size
    background = Image.new("L", (width, height), image.getpixel((2, height // 2)))
    marks = ImageChops.difference(image, background).point(lambda v: 255 if v > 12 else 0)
    top, bottom = int(height * 0.06), int(height * 0.92)
    body = marks.crop((0, top, width, bottom))
    box = body.getbbox()
    if not box:
        return 0.0, 1.0
    filled = [body.crop((0, y, width, y + 1)).getbbox() is not None for y in range(box[1], box[3])]
    gap = best = 0
    for row in filled:
        gap = 0 if row else gap + 1
        best = max(best, gap)
    return (box[3] + top) / height, best / height


def main() -> None:
    pdf = pdfium.PdfDocument(str(PDF))
    titles = re.findall(r"<h2>(.*?)</h2>", SOURCE.read_text(encoding="utf-8"))
    texts = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    starts = {i for i, text in enumerate(texts) if any(t in text[:200] for t in titles)}
    bad = []
    for i in range(1, len(pdf)):  # a capa tem outro desenho
        end, gap = measure(pdf[i])
        title = texts[i][:70].replace("\r", " ").replace("\n", " ")
        ends_chapter = i + 1 in starts or i + 1 == len(pdf)
        problem = end < MIN_CONTENT or gap > MAX_GAP or (end < MIN_MID_CHAPTER and not ends_chapter)
        print(f"p{i + 1:02d} conteudo ate {end * 100:3.0f}%  maior vazio {gap * 100:3.0f}% {'<<<' if problem else ''}".rstrip())
        if problem:
            bad.append((i + 1, title))
    print(f"{len(pdf)} paginas; {len(bad)} com problema")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
