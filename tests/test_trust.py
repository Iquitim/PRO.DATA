"""Abertura protegida (spec 028, RF-2821..2826): fluxo de fora não executa nada até a pessoa confirmar."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from prodata.config import Settings
from prodata.domain.workflow import Workflow
from prodata.main import create_app
from prodata.services.trust import TrustRegistry, fingerprint

FLOW: dict[str, Any] = {
    "id": "recebido",
    "name": "Recebido",
    "nodes": [
        {"id": "t", "type": "io.text_input", "config": {"table": {"columns": ["v"], "rows": [[1], [2]]}}},
        {
            "id": "f",
            "type": "prep.formula",
            "config": {
                "formulas": [{"target": "new", "column": "x", "type": "Auto", "expression": "[v] * 2"}]
            },
        },
        {"id": "o", "type": "io.output_data", "config": {"filename": "saida", "format": "csv"}},
    ],
    "edges": [
        {"id": "e1", "source": "t", "target": "f"},
        {"id": "e2", "source": "f", "target": "o"},
    ],
}


def write_flow(folder: Path, flow: dict[str, Any] = FLOW) -> Path:
    path = folder / "recebido.prodata.json"
    path.write_text(json.dumps(flow), encoding="utf-8")
    return path


def open_file(client: TestClient, path: Path) -> dict[str, Any]:
    res = client.post("/api/files/workflow/open", json={"path": str(path)})
    assert res.status_code == 200, res.text
    workflow: dict[str, Any] = res.json()["workflow"]
    return workflow


def execute(client: TestClient, workflow: dict[str, Any]) -> Any:
    return client.post("/api/execute", json={"workflow": workflow})


def state(client: TestClient, workflow: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = client.post("/api/trust/state", json={"workflow": workflow}).json()
    return out


def test_file_from_outside_opens_protected_and_runs_nothing(client: TestClient, tmp_path: Path) -> None:
    workflow = open_file(client, write_flow(tmp_path))
    res = execute(client, workflow)
    assert res.status_code == 423
    assert "modo protegido" in res.json()["detail"]
    assert state(client, workflow)["protected"] is True


def test_summary_lists_what_the_flow_does(client: TestClient, tmp_path: Path) -> None:
    workflow = open_file(client, write_flow(tmp_path))
    kinds = {(i["node_id"], i["kind"]) for i in state(client, workflow)["summary"]}
    assert ("f", "formula") in kinds and ("o", "output") in kinds


def test_confirming_releases_the_flow(client: TestClient, tmp_path: Path) -> None:
    workflow = open_file(client, write_flow(tmp_path))
    confirmed = client.post("/api/trust/confirm", json={"workflow": workflow}).json()
    assert confirmed == {"protected": False, "summary": []}
    assert execute(client, workflow).status_code == 200


def test_confirmed_file_opens_released_next_time(client: TestClient, tmp_path: Path) -> None:
    path = write_flow(tmp_path)
    client.post("/api/trust/confirm", json={"workflow": open_file(client, path)})
    assert execute(client, open_file(client, path)).status_code == 200


def test_file_changed_outside_goes_back_to_protected(client: TestClient, tmp_path: Path) -> None:
    path = write_flow(tmp_path)
    client.post("/api/trust/confirm", json={"workflow": open_file(client, path)})
    changed = json.loads(json.dumps(FLOW))
    changed["nodes"][1]["config"]["formulas"][0]["expression"] = "[v] * 3"
    write_flow(tmp_path, changed)
    assert execute(client, open_file(client, path)).status_code == 423


def test_edits_made_in_the_program_stay_trusted(client: TestClient, tmp_path: Path) -> None:
    path = write_flow(tmp_path)
    workflow = open_file(client, path)
    client.post("/api/trust/confirm", json={"workflow": workflow})
    workflow["name"] = "Mudado aqui"
    client.post("/api/files/workflow/save", json={"path": str(path), "workflow": workflow})
    assert execute(client, open_file(client, path)).status_code == 200


def test_saving_a_protected_flow_does_not_trust_it(client: TestClient, tmp_path: Path) -> None:
    path = write_flow(tmp_path)
    workflow = open_file(client, path)
    client.put(f"/api/workflows/{workflow['id']}", json=workflow)
    assert execute(client, client.get(f"/api/workflows/{workflow['id']}").json()).status_code == 423


def test_borrowing_the_id_of_a_trusted_flow_does_not_bypass(client: TestClient, tmp_path: Path) -> None:
    """Um arquivo de fora com o mesmo id de um fluxo da biblioteca não herda a confiança dele."""
    mine = dict(FLOW, id="meu_fluxo")
    assert client.put("/api/workflows/meu_fluxo", json=mine).status_code == 200
    assert execute(client, mine).status_code == 200
    evil = json.loads(json.dumps(mine))
    evil["nodes"][1]["config"]["formulas"][0]["expression"] = "[v] * 100"
    opened = open_file(client, write_flow(tmp_path, evil))
    assert execute(client, opened).status_code == 423
    assert execute(client, mine).status_code == 423  # até confirmar, nenhum conteúdo com esse id executa


def test_new_flow_created_here_runs(client: TestClient) -> None:
    assert execute(client, dict(FLOW, id="novo_aqui")).status_code == 200


def test_demo_is_trusted(client: TestClient) -> None:
    demo = client.get("/api/workflows/demo").json()
    assert state(client, demo)["protected"] is False


def test_sql_verification_refuses_protected_flow(client: TestClient, tmp_path: Path) -> None:
    workflow = open_file(client, write_flow(tmp_path))
    assert client.post("/api/sql/verify", json={"workflow": workflow}).status_code == 423
    assert (
        client.post("/api/sql/generate", json={"workflow": workflow}).status_code == 200
    )  # ver o código é livre


def test_library_already_there_starts_trusted_on_upgrade(settings: Settings) -> None:
    """Atualização para a 0.6: o que já estava na biblioteca não pede confirmação (RF-2825)."""
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    (settings.workflows_dir / "antigo.prodata.json").write_text(
        json.dumps(dict(FLOW, id="antigo")), encoding="utf-8"
    )
    with TestClient(create_app(settings)) as client:
        workflow = client.get("/api/workflows/antigo").json()
        assert execute(client, workflow).status_code == 200


def test_library_file_changed_outside_is_protected(client: TestClient, settings: Settings) -> None:
    assert client.put("/api/workflows/lib", json=dict(FLOW, id="lib")).status_code == 200
    path = settings.workflows_dir / "lib.prodata.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["nodes"][1]["config"]["formulas"][0]["expression"] = "[v] * 7"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert execute(client, client.get("/api/workflows/lib").json()).status_code == 423


def test_protection_survives_a_restart(settings: Settings, tmp_path: Path) -> None:
    with TestClient(create_app(settings)) as client:
        workflow = open_file(client, write_flow(tmp_path))
    with TestClient(create_app(settings)) as client:
        assert execute(client, workflow).status_code == 423


def test_registry_keeps_only_fingerprints(tmp_path: Path) -> None:
    registry = TrustRegistry(tmp_path / "confianca.json")
    workflow = Workflow.model_validate(FLOW)
    registry.start([])
    registry.opened(workflow)
    registry.confirm(workflow)
    text = (tmp_path / "confianca.json").read_text(encoding="utf-8")
    assert fingerprint(workflow) in text
    assert "[v] * 2" not in text and "Recebido" not in text


def test_unreadable_registry_trusts_nothing(tmp_path: Path) -> None:
    (tmp_path / "confianca.json").write_text("{quebrado", encoding="utf-8")
    registry = TrustRegistry(tmp_path / "confianca.json")
    assert registry.opened(Workflow.model_validate(FLOW)) is False


def test_confirming_the_screen_version_also_trusts_the_file(client: TestClient, tmp_path: Path) -> None:
    """A tela completa a configuração com os padrões ao abrir: o arquivo como está continua confiável depois."""
    path = write_flow(tmp_path)
    screen = open_file(client, path)
    screen["nodes"][0]["config"]["extra_padrao"] = "preenchido pela tela"
    client.post("/api/trust/confirm", json={"workflow": screen})
    assert execute(client, open_file(client, path)).status_code == 200
