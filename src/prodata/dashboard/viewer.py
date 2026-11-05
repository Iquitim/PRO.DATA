"""Junta os módulos da interface que o HTML exportado usa num script só, sem servidor e sem arquivos ao lado."""

from __future__ import annotations

import re
from pathlib import Path

# Em ordem de dependência.
MODULES = (
    "icons.js",
    "dom.js",
    "charts.js",
    "dash_filters.js",
    "dash_cards.js",
    "dash_compute.js",
    "dash_crypt.js",
    "dash_viewer.js",
)

_IMPORT = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*'\./([\w.]+)';\s*$", re.MULTILINE)
_EXPORT_DECL = re.compile(
    r"^export\s+(async\s+function\*?|function\*?|const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE
)
_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\};?\s*$", re.MULTILINE)


def _bindings(names: str) -> str:
    parts = [n.strip() for n in names.split(",") if n.strip()]
    return ", ".join(p.replace(" as ", ": ") for p in parts)


def wrap_module(name: str, source: str) -> str:
    if unsupported := re.search(
        r"^import\s+(?!\{)|^export\s+default|^export\s*\*|\bimport\(", source, re.MULTILINE
    ):
        raise ValueError(f"{name}: forma de módulo não suportada no HTML ({unsupported.group(0)!r}).")
    exported = [m.group(2) for m in _EXPORT_DECL.finditer(source)]
    for match in _EXPORT_LIST.finditer(source):
        exported += [n.split(" as ")[0].strip() for n in match.group(1).split(",") if n.strip()]
    body = _EXPORT_LIST.sub("", source)
    body = _EXPORT_DECL.sub(lambda m: f"{m.group(1)} {m.group(2)}", body)
    body = _IMPORT.sub(lambda m: f"const {{ {_bindings(m.group(1))} }} = __m[{m.group(2)!r}];", body)
    if re.search(r"^\s*import\s", body, re.MULTILINE):
        raise ValueError(f"{name}: importação que o HTML não sabe juntar.")
    names = ", ".join(exported)
    return f"(function () {{\n{body}\n__m[{name!r}] = {{ {names} }};\n}})();\n"


def build_viewer(web_js: Path) -> str:
    pieces = [wrap_module(name, (web_js / name).read_text(encoding="utf-8")) for name in MODULES]
    return '"use strict";\nconst __m = {};\n' + "".join(pieces)
