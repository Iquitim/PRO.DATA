from fastapi.testclient import TestClient

from prodata.samples.workflows import DEMO_WORKFLOW_ID


def test_catalog(client: TestClient) -> None:
    data = client.get("/api/catalog").json()
    assert len(data["tools"]) >= 21
    assert {c["id"] for c in data["categories"]} >= {"inout", "prep", "transform", "bi", "ml"}


def test_index_is_served(client: TestClient) -> None:
    assert client.get("/").status_code == 200


def test_dataset_upload_preview_delete(client: TestClient) -> None:
    content = "produto;preço\nCafé;12,50\n".encode("cp1252")
    res = client.post("/api/datasets", files={"file": ("../../precos.csv", content, "text/csv")})
    assert res.status_code == 201 and res.json()["name"] == "precos.csv"

    again = client.post("/api/datasets", files={"file": ("precos.csv", content, "text/csv")})
    assert again.status_code == 409

    preview = client.post("/api/datasets/precos.csv/preview", json={}).json()
    assert preview["options"]["delimiter"] == ";"
    assert preview["rows"] == [{"produto": "Café", "preço": 12.5}]

    names = [d["name"] for d in client.get("/api/datasets").json()]
    assert "precos.csv" in names
    assert client.delete("/api/datasets/precos.csv").status_code == 204
    assert client.post("/api/datasets/precos.csv/preview", json={}).status_code == 404


def test_upload_too_large(client: TestClient) -> None:
    res = client.post("/api/datasets", files={"file": ("big.csv", b"x" * (1024 * 1024 + 1), "text/csv")})
    assert res.status_code == 413


def test_preview_rejects_traversal(client: TestClient) -> None:
    assert client.post("/api/datasets/..%5Cpyproject.toml/preview", json={}).status_code in (400, 404)


def test_execute_and_page_results(client: TestClient) -> None:
    wf = client.get(f"/api/workflows/{DEMO_WORKFLOW_ID}").json()
    report = client.post("/api/execute", json={"workflow": wf}).json()
    assert all(r["status"] == "executed" for r in report["node_results"].values())

    page = client.get(
        f"/api/results/{wf['id']}/n_join/J",
        params={"limit": 5, "offset": 5, "sort_col": "mrr_mensal", "sort_desc": True},
    ).json()
    assert len(page["rows"]) == 5 and page["offset"] == 5
    values = [r["mrr_mensal"] for r in page["rows"]]
    assert values == sorted(values, reverse=True)
    assert page["profile"]["columns"][0]["histogram"]

    assert client.get(f"/api/results/{wf['id']}/n_join/X").status_code == 404


def test_execute_rejects_cycle(client: TestClient) -> None:
    wf = {
        "id": "ciclo",
        "nodes": [{"id": "a", "type": "io.browse"}, {"id": "b", "type": "io.browse"}],
        "edges": [{"id": "1", "source": "a", "target": "b"}, {"id": "2", "source": "b", "target": "a"}],
    }
    res = client.post("/api/execute", json={"workflow": wf})
    assert res.status_code == 422 and "ciclo" in res.json()["detail"]


def test_workflow_crud(client: TestClient) -> None:
    wf = {"id": "meu_fluxo", "name": "Meu fluxo", "nodes": [], "edges": []}
    assert client.put("/api/workflows/meu_fluxo", json=wf).status_code == 200
    assert "meu_fluxo" in [w["id"] for w in client.get("/api/workflows").json()]
    assert client.get("/api/workflows/meu_fluxo").json()["name"] == "Meu fluxo"
    assert client.delete("/api/workflows/meu_fluxo").status_code == 204
    assert client.get("/api/workflows/meu_fluxo").status_code == 404
    assert client.get("/api/workflows/..%2F..%2Fx").status_code in (404, 422)


def test_formula_validate(client: TestClient) -> None:
    ok = client.post(
        "/api/formula/validate", json={"expression": "[a] * 2", "columns": [{"name": "a", "type": "Int64"}]}
    )
    assert ok.json()["valid"]
