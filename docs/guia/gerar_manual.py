"""Gera src/prodata/web/manual/manual.json a partir de guia.html: o Manual do programa e o PDF têm uma fonte só.

    uv run python docs/guia/gerar_manual.py

As partes interativas são marcações no guia, com a classe ``manual-only`` (no PDF não aparecem):
``data-show`` (Mostrar onde fica) e ``data-try`` (Experimentar). Nome de ferramenta em negrito ou itálico vira link.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from prodata.nodes import REGISTRY

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "guia.html"
OUTPUT = HERE.parents[1] / "src" / "prodata" / "web" / "manual" / "manual.json"

_SECTION = re.compile(r'<section(?: class="chapter")?>\s*(.*?)</section>', re.S)
_EYEBROW = re.compile(r'<div class="eyebrow">(.*?)</div>\s*', re.S)
_TITLE = re.compile(r"<h2>(.*?)</h2>\s*", re.S)
_H3 = re.compile(r"<h3>(.*?)</h3>", re.S)
_IMG = re.compile(r'<img src="[^"]*/manual/img/([^"]+)"')
_TAG = re.compile(r"<[^>]+>")
_ONLY_MANUAL = re.compile(r'<(div|button)[^>]*class="manual-only[^"]*"[^>]*>.*?</\1>', re.S)


def _plain(text: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", _ONLY_MANUAL.sub(" ", text))).split())


def _link_tools(text: str, names: dict[str, str]) -> str:
    """<strong>Join</strong>, <em>Join</em> e a célula de tabela com o nome da ferramenta viram link."""

    def inline(m: re.Match[str]) -> str:
        tool = names.get(m.group(2))
        return f'<{m.group(1)}><span class="m-tool" data-tool="{tool}">{m.group(2)}</span></{m.group(1)}>' if tool else m.group(0)

    def cell(m: re.Match[str]) -> str:
        tool = names.get(m.group(1))
        return f'<td class="tool"><span class="m-tool" data-tool="{tool}">{m.group(1)}</span></td>' if tool else m.group(0)

    return re.sub(r'<td class="tool">([^<]+)</td>', cell, re.sub(r"<(strong|em)>([^<]+)</\1>", inline, text))


def _sections(body: str) -> tuple[str, list[dict[str, str]]]:
    """Dá um id a cada <h3> e devolve o corpo e o texto de cada seção, para a busca."""
    found: list[dict[str, str]] = []
    parts = _H3.split(body)
    out = [parts[0]]
    if _plain(parts[0]):
        found.append({"id": "", "title": "", "text": _plain(parts[0])})
    for i in range(1, len(parts), 2):
        section = f"s{(i + 1) // 2}"
        out.append(f'<h3 id="{section}">{parts[i]}</h3>{parts[i + 1]}')
        found.append({"id": section, "title": _plain(parts[i]), "text": _plain(parts[i + 1])})
    return "".join(out), found


def build() -> dict[str, Any]:
    source = SOURCE.read_text(encoding="utf-8")
    source = source[source.index("<body") :]
    names = {spec.name: spec.type for spec in REGISTRY.values() if not getattr(spec, "hidden", False)}
    chapters = []
    for index, match in enumerate(_SECTION.finditer(source)):
        raw = match.group(1)
        eyebrow = _EYEBROW.search(raw)
        title = _TITLE.search(raw)
        if not title:
            continue
        label = html.unescape(eyebrow.group(1)) if eyebrow else ""
        number = label.split(" · ")[0] if " · " in label else ""
        body = _TITLE.sub("", _EYEBROW.sub("", raw, count=1), count=1)
        body = _IMG.sub(r'<img data-img="\1"', body)
        body, sections = _sections(_link_tools(body, names))
        chapters.append({"id": f"c{index}", "number": number, "label": label, "title": _plain(title.group(1)), "html": body.strip(), "sections": sections})
    return {"chapters": chapters}


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=0, sort_keys=True) + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"Gerado: {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
