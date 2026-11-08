"""Regra de idioma (spec 029, RF-2961 e RF-2962): a interface fala português e usa um nome para cada coisa.

- Ferramentas e funções de fórmula ficam em inglês: são o vocabulário do produto, como no Alteryx.
- Uma ferramenta colocada no fluxo é uma **caixa**; o agrupador é uma **etapa**; o arquivo é um **fluxo**.

O teste lê o texto que a pessoa vê: textos entre aspas do JavaScript (sem comentários), o HTML da página e as
mensagens do servidor (sem docstrings nem comentários). Nome de variável e de classe CSS não entram.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "prodata"
FORBIDDEN = {
    "nó": re.compile(r"(?<![\w-])[Nn]ós?(?![\w])"),
    "caixa de organização": re.compile(r"[Cc]aixa de organização"),
    "contêiner": re.compile(r"[Cc]ont[êe]iner"),
    "Workflow": re.compile(r"\bWorkflow\s+(não|inválido|salvo|aberto)"),
    # A vista Dados cadastra; a aba Fontes, à esquerda, só busca e arrasta; a aba Resultado mostra a tabela.
    "aba Dados": re.compile(r"\baba Dados\b"),
}
_COMMENT = re.compile(r"/\*.*?\*/|(?<![:'\"`\\])//[^\n]*", re.S)
_JS_STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|\"(?:[^\"\\\n]|\\.)*\"")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _js_texts(path: Path) -> list[str]:
    code = _COMMENT.sub(" ", path.read_text(encoding="utf-8"))
    return [m.group(0) for m in _JS_STRING.finditer(code)]


def _py_texts(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def _visible() -> list[tuple[str, str]]:
    found = [(f.name, t) for f in sorted((ROOT / "web" / "js").glob("*.js")) for t in _js_texts(f)]
    found += [
        ("index.html", _HTML_COMMENT.sub(" ", (ROOT / "web" / "index.html").read_text(encoding="utf-8")))
    ]
    found += [(str(f.relative_to(ROOT)), t) for f in sorted(ROOT.rglob("*.py")) for t in _py_texts(f)]
    return found


# Palavras de busca da paleta: os nomes antigos continuam achando a Etapa, para quem já se acostumou.
SEARCH_SYNONYMS = {"palette.js": "caixa de organização organizacao contêiner"}


def test_interface_uses_one_name_for_each_thing() -> None:
    leaks = [
        f"{where}: {word} em {text.strip()[:90]!r}"
        for where, text in _visible()
        for word, pattern in FORBIDDEN.items()
        if pattern.search(text) and SEARCH_SYNONYMS.get(where, "\0") not in text
    ]
    assert not leaks, "Texto visível fora da regra de idioma:\n" + "\n".join(leaks)


def test_column_types_and_tabs_are_not_shown_raw() -> None:
    """Dois casos que a lista de palavras não pega: o texto partido em pedaços e o tipo vindo direto do motor."""
    for path in sorted((ROOT / "web" / "js").glob("*.js")):
        code = path.read_text(encoding="utf-8")
        assert not re.search(r"aba ',\s*h\('\w+', \{\}, 'Dados'\)", code), path.name
        assert not re.search(r"class: 'th-type'[^)]*\}, c\.(raw_)?type\)", code), path.name
