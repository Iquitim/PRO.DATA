"""Manual dentro do programa (spec 029, RF-2983..2989): gerado do guia, com links que apontam para algo que existe."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from prodata.nodes import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "src" / "prodata" / "web" / "manual"
TARGETS_JS = (ROOT / "src" / "prodata" / "web" / "js" / "manual_targets.js").read_text(encoding="utf-8")
GUIDE = ROOT / "docs" / "guia" / "guia.html"


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("gerar_manual", ROOT / "docs" / "guia" / "gerar_manual.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manual() -> dict[str, Any]:
    return json.loads((MANUAL / "manual.json").read_text(encoding="utf-8"))


def _html(manual: dict[str, Any]) -> str:
    return "\n".join(c["html"] for c in manual["chapters"])


def test_manual_is_generated_from_the_guide() -> None:
    expected = _generator().render()
    assert (MANUAL / "manual.json").read_text(encoding="utf-8") == expected, (
        "Rode: uv run python docs/guia/gerar_manual.py"
    )


def test_every_chapter_has_a_title_and_text(manual: dict[str, Any]) -> None:
    assert len(manual["chapters"]) == 19
    for chapter in manual["chapters"]:
        assert chapter["title"] and chapter["html"] and chapter["sections"], chapter["id"]


def test_every_show_link_has_a_target(manual: dict[str, Any]) -> None:
    keys = set(re.findall(r"^  (\w+): \{ (?:view|sel|panel)", TARGETS_JS, re.M))
    used = set(re.findall(r'data-show="(\w+)"', _html(manual)))
    assert used, "o guia não tem nenhum Mostrar onde fica"
    assert used <= keys, used - keys


def test_every_tool_link_is_a_real_tool(manual: dict[str, Any]) -> None:
    used = set(re.findall(r'data-tool="([\w.]+)"', _html(manual)))
    assert len(used) > 10 and used <= set(REGISTRY), used - set(REGISTRY)


def test_context_chapters_exist(manual: dict[str, Any]) -> None:
    block = TARGETS_JS[TARGETS_JS.index("export const CONTEXT") :]
    titles = {c["title"] for c in manual["chapters"]}
    wanted = set(re.findall(r"'([A-ZÀ-Ú][^']+)'", block))
    assert wanted and wanted <= titles, wanted - titles


def test_every_image_exists(manual: dict[str, Any]) -> None:
    names = set(re.findall(r'data-img="([^"]+)"', _html(manual)))
    assert len(names) > 40
    assert not [n for n in names if not (MANUAL / "img" / n).is_file()]


def test_images_have_a_dark_version(manual: dict[str, Any]) -> None:
    names = set(re.findall(r'data-img="([^"]+)"', _html(manual)))
    missing = [n for n in names if not (MANUAL / "img-escuro" / n).is_file()]
    assert not missing, missing


def test_interactive_parts_stay_out_of_the_pdf() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    assert ".manual-only { display: none; }" in guide
    assert not re.search(r"<button(?![^>]*manual-only)", guide), "todo botão do guia é só do Manual"


def test_examples_exist_and_run(manual: dict[str, Any], client: TestClient) -> None:
    used = set(re.findall(r'data-try="(\w+)"', _html(manual)))
    assert used == {p.stem for p in (MANUAL / "exemplos").glob("*.json")}
    for name in sorted(used):
        flow = json.loads((MANUAL / "exemplos" / f"{name}.json").read_text(encoding="utf-8"))
        report = client.post("/api/execute", json={"workflow": flow})
        assert report.status_code == 200, (name, report.text[:300])
        bad = {
            k: v.get("error") for k, v in report.json()["node_results"].items() if v["status"] != "executed"
        }
        assert not bad, (name, bad)


def test_guide_cover_shows_the_current_version() -> None:
    from prodata import __version__

    guide = (Path(__file__).resolve().parents[1] / "docs/guia/guia.html").read_text(encoding="utf-8")
    assert f"Versão {__version__} ·" in guide
