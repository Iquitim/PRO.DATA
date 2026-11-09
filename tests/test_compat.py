"""Compatibilidade (specs 028 e 029): fluxos salvos por versões anteriores abrem e dão o mesmo resultado.

- `data/fluxo_0_5_9.prodata.json`: gravado pela 0.5.8 e confirmado na 0.5.9. A demonstração inteira e as caixas
  que mudaram nessas versões, escritas do jeito antigo.
- `data/fluxo_0_6_0.prodata.json`: o mesmo, mais o que entrou na 0.6.0: Data Quality (com a lista da entrada L),
  constantes do fluxo e um valor compartilhado guardado no arquivo.
- `data/fluxo_0_6_1.prodata.json`: o mesmo fluxo, com o resultado gravado pela 0.6.1 (referência da spec 030).

O resultado esperado de cada saída fica em `data/<fluxo>_resultados.json`, como uma impressão digital das linhas.
Para gravar o esperado de novo, só quando uma mudança de resultado for intencional:
    PRODATA_UPDATE_COMPAT=1 uv run pytest tests/test_compat.py
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

DATA = Path(__file__).resolve().parent / "data"
VERSIONS = ["0_5_9", "0_6_0", "0_6_1"]
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


@pytest.mark.parametrize("version", VERSIONS)
def test_saved_flow_gives_the_same_results(version: str, client: TestClient) -> None:
    flow = json.loads((DATA / f"fluxo_{version}.prodata.json").read_text(encoding="utf-8"))
    expected_file = DATA / f"fluxo_{version}_resultados.json"
    found = _outputs(client, flow)
    if os.environ.get("PRODATA_UPDATE_COMPAT"):
        expected_file.write_text(
            json.dumps(found, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    assert set(found) == set(expected), sorted(set(found) ^ set(expected))
    changed = {k: (expected[k]["rows"], found[k]["rows"]) for k in expected if found[k] != expected[k]}
    assert not changed, f"Saídas com resultado diferente da {version.replace('_', '.')}: {changed}"
