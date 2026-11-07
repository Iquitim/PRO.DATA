"""Compatibilidade com a 0.5.9 (spec 028): o fluxo salvo por ela abre e dá o mesmo resultado em todas as saídas.

O fluxo de `data/fluxo_0_5_9.prodata.json` foi gravado pela 0.5.8 e confirmado igual na 0.5.9. Ele traz a
demonstração inteira e as caixas que mudaram nessas versões, escritas do jeito antigo. O resultado esperado de cada
saída fica em `data/fluxo_0_5_9_resultados.json`, como uma impressão digital das linhas.

Para gravar o esperado de novo, só quando uma mudança de resultado for intencional:
    PRODATA_UPDATE_COMPAT=1 uv run pytest tests/test_compat_059.py
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

DATA = Path(__file__).resolve().parent / "data"
FLOW = DATA / "fluxo_0_5_9.prodata.json"
EXPECTED = DATA / "fluxo_0_5_9_resultados.json"
# O treino de ML usa uma semente fixa, mas a ordem interna das árvores pode variar entre máquinas.
SKIP = {"n_trainer", "n_pred"}


def _digest(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _outputs(client: TestClient, flow: dict[str, Any]) -> dict[str, Any]:
    report = client.post("/api/execute", json={"workflow": flow})
    assert report.status_code == 200, report.text[:300]
    results = report.json()["node_results"]
    bad = {
        k: (v["status"], (v.get("error") or "")[:120])
        for k, v in results.items()
        if v["status"] != "executed"
    }
    assert not bad, bad
    found: dict[str, Any] = {}
    for node_id, result in results.items():
        if node_id in SKIP:
            continue
        for anchor in result.get("anchors") or {}:
            rows: list[dict[str, Any]] = []
            columns: Any = None
            while True:
                page = client.get(
                    f"/api/results/{flow['id']}/{node_id}/{anchor}",
                    params={"limit": 1000, "offset": len(rows)},
                )
                if page.status_code == 404:  # saída de modelo: não é tabela
                    break
                body = page.json()
                rows += body["rows"]
                columns = list(rows[0]) if rows else body["col_count"]
                if not body["rows"] or len(rows) >= body["row_count"]:
                    break
            if columns is not None:
                found[f"{node_id}/{anchor}"] = {
                    "columns": columns,
                    "rows": len(rows),
                    "digest": _digest(rows),
                }
    return found


def test_flow_from_0_5_9_gives_the_same_results(client: TestClient) -> None:
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    found = _outputs(client, flow)
    if os.environ.get("PRODATA_UPDATE_COMPAT"):
        EXPECTED.write_text(json.dumps(found, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert set(found) == set(expected), sorted(set(found) ^ set(expected))
    changed = {k: (expected[k]["rows"], found[k]["rows"]) for k in expected if found[k] != expected[k]}
    assert not changed, f"Saídas com resultado diferente da 0.5.9: {changed}"
