"""O código continua dividido (spec 027): nenhum arquivo cresce além do limite sem alguém decidir."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "prodata"
MAX_LINES = 800


def _source_files() -> list[Path]:
    return [p for p in SRC.rglob("*") if p.suffix in {".py", ".js", ".css"} and "__pycache__" not in p.parts]


def test_no_source_file_passes_the_limit() -> None:
    big = {
        str(p.relative_to(SRC)): n
        for p in _source_files()
        if (n := len(p.read_text(encoding="utf-8").splitlines())) > MAX_LINES
    }
    assert not big, f"Divida estes arquivos (limite de {MAX_LINES} linhas): {big}"


def test_javascript_has_no_import_cycles() -> None:
    graph = {
        p.name: re.findall(r"from '\./([\w.]+)'", p.read_text(encoding="utf-8"))
        for p in (SRC / "web" / "js").glob("*.js")
    }
    done: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        assert name not in path, " > ".join((*path, name))
        if name not in done:
            for child in graph.get(name, []):
                visit(child, (*path, name))
            done.add(name)

    for name in graph:
        visit(name, ())


def test_viewer_does_not_depend_on_the_program() -> None:
    """O HTML exportado roda sozinho: o que entra nele não pode puxar a API local nem o fluxo aberto."""
    from prodata.dashboard.viewer import MODULES

    for name in MODULES:
        imports = re.findall(r"from '\./([\w.]+)'", (SRC / "web" / "js" / name).read_text(encoding="utf-8"))
        assert set(imports) <= set(MODULES), (name, imports)
