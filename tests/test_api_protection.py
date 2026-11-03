"""A API local é só do próprio programa: páginas externas não podem ler nem alterar nada."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prodata.config import Settings
from prodata.main import create_app

EVIL = "https://site-malicioso.example"
LOCAL = "http://127.0.0.1:47615"


@pytest.fixture
def desktop(tmp_path: Path):
    settings = Settings(
        storage_dir=tmp_path / "s",
        port=47615,
        cors_origins=[LOCAL],
        secrets_backend="memory",
        log_level="WARNING",
    )
    with TestClient(create_app(settings), base_url=LOCAL) as client:
        yield client


def test_own_address_works(desktop: TestClient) -> None:
    assert desktop.get("/api/health").status_code == 200
    assert desktop.get("/api/health", headers={"Host": "localhost:47615"}).status_code == 200


@pytest.mark.parametrize("host", ["malicioso.example", "malicioso.example:47615", "192.168.0.10:47615"])
def test_dns_rebinding_is_refused(desktop: TestClient, host: str) -> None:
    assert desktop.get("/api/workflows", headers={"Host": host}).status_code == 400
    assert desktop.get("/", headers={"Host": host}).status_code == 400


def test_other_site_cannot_upload(desktop: TestClient) -> None:
    """Formulário de outro site não passa pela pré-verificação do navegador: precisa ser recusado aqui."""
    before = len(desktop.get("/api/datasets").json())
    response = desktop.post(
        "/api/datasets", files={"file": ("x.csv", b"a\n1\n", "text/csv")}, headers={"Origin": EVIL}
    )
    assert response.status_code == 403
    assert len(desktop.get("/api/datasets").json()) == before


@pytest.mark.parametrize("origin", [EVIL, "null", "http://127.0.0.1:9999"])
def test_other_origins_cannot_change_anything(desktop: TestClient, origin: str) -> None:
    workflow = desktop.get("/api/workflows").json()[0]
    assert desktop.delete(f"/api/workflows/{workflow['id']}", headers={"Origin": origin}).status_code == 403
    assert desktop.get(f"/api/workflows/{workflow['id']}").status_code == 200


def test_the_program_itself_can_change(desktop: TestClient) -> None:
    workflow = desktop.get("/api/workflows").json()[0]
    demo = desktop.get(f"/api/workflows/{workflow['id']}").json()
    response = desktop.post(
        "/api/sql/generate",
        content=json.dumps({"workflow": demo}),
        headers={"Origin": LOCAL, "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_same_origin_on_another_port_works(tmp_path: Path) -> None:
    """Segunda janela do programa usa outra porta: a página continua sendo a dele."""
    settings = Settings(
        storage_dir=tmp_path / "s",
        port=51000,
        cors_origins=[LOCAL],
        secrets_backend="memory",
        log_level="WARNING",
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:51000") as client:
        demo = client.get(f"/api/workflows/{client.get('/api/workflows').json()[0]['id']}").json()
        headers = {"Origin": "http://127.0.0.1:51000"}
        assert client.post("/api/sql/generate", json={"workflow": demo}, headers=headers).status_code == 200


def test_publishing_on_the_network_is_an_explicit_choice(tmp_path: Path) -> None:
    settings = Settings(
        storage_dir=tmp_path / "s", host="0.0.0.0", secrets_backend="memory", log_level="WARNING"
    )
    with TestClient(create_app(settings), base_url="http://192.168.0.10:8765") as client:
        assert client.get("/api/health").status_code == 200
