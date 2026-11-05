"""O documento para IA (docs/contexto-ia.md) continua certo: em dia com o catálogo, e o exemplo dele executa."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from prodata.domain.workflow import Workflow
from prodata.nodes import REGISTRY

DOCS = Path(__file__).resolve().parent.parent / "docs"
spec = importlib.util.spec_from_file_location("gerar_contexto_ia", DOCS / "gerar_contexto_ia.py")
assert spec and spec.loader
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_document_is_up_to_date() -> None:
    written = (DOCS / "contexto-ia.md").read_text(encoding="utf-8")
    assert written == generator.render(), "Rode: uv run python docs/gerar_contexto_ia.py"


def test_document_lists_every_tool_in_use() -> None:
    text = generator.render()
    for name, tool in REGISTRY.items():
        assert f"`{name}`" in text, name
        if not tool.hidden:
            for field in tool.config.model_fields:
                assert f"`{field}`" in text, (name, field)


def test_example_uses_only_real_fields() -> None:
    """Campo com nome errado seria ignorado em silêncio: o exemplo não pode ensinar isso."""

    def keys(model: Any, data: dict[str, Any], where: str) -> None:
        for key, value in data.items():
            assert key in model.model_fields, f"{where}: {key}"
            annotation = model.model_fields[key].annotation
            inner = getattr(annotation, "__args__", (annotation,))[0]
            items = value if isinstance(value, list) else [value]
            if hasattr(inner, "model_fields") or hasattr(annotation, "model_fields"):
                target = inner if hasattr(inner, "model_fields") else annotation
                for item in items:
                    keys(target, item, f"{where}.{key}")

    for node in generator.EXAMPLE["nodes"]:
        keys(REGISTRY[node["type"]].config, node["config"], node["id"])


def test_example_connects_real_ports() -> None:
    flow = Workflow.model_validate(generator.EXAMPLE)
    types = {n.id: REGISTRY[n.type] for n in flow.nodes}
    for edge in flow.edges:
        assert edge.source_handle in [p.id for p in types[edge.source].outputs], edge.id
        assert edge.target_handle in [p.id for p in types[edge.target].inputs], edge.id


def test_example_runs_and_gives_the_expected_totals(client: Any) -> None:
    res = client.post("/api/execute", json={"workflow": generator.EXAMPLE})
    assert res.status_code == 200, res.text
    report = res.json()["node_results"]
    assert {r["status"] for r in report.values()} == {"executed"}, report
    rows = client.get(f"/api/results/{generator.EXAMPLE['id']}/por_uf/out").json()["rows"]
    assert {r["uf"]: r["total"] for r in rows} == {"SP": 400, "RJ": 250}


@pytest.mark.parametrize("danger", ["senha", "token"])
def test_document_warns_about_secrets(danger: str) -> None:
    assert danger in generator.render().lower()
