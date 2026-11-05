from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from prodata.config import Settings
from prodata.connectors import api as api_module
from prodata.connectors import api_policy
from prodata.connectors.api_store import ApiStore
from prodata.connectors.secrets import MemorySecretStore
from prodata.domain.workflow import Workflow
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.main import create_app
from prodata.samples.apis import seed_example_apis
from prodata.samples.datasets import ensure_sample_datasets
from prodata.samples.workflows import demo_workflow

REGIOES = {"SP": "Sudeste", "RJ": "Sudeste", "MG": "Sudeste", "PR": "Sul", "BA": "Nordeste"}
UFS = ["AC", "BA", "DF", "GO", "MG", "PE", "PR", "RJ", "RS", "SC", "SP"]


def fake_ibge(request: httpx.Request) -> httpx.Response:
    """Respostas no formato do IBGE: nenhum teste sai para a rede."""
    if request.url.path.endswith("/estados"):
        return httpx.Response(
            200,
            json=[
                {
                    "id": i,
                    "sigla": uf,
                    "nome": f"Estado {uf}",
                    "regiao": {"id": 1, "nome": REGIOES.get(uf, "Outra")},
                }
                for i, uf in enumerate(UFS)
            ],
        )
    if "/municipios" in request.url.path:
        uf = request.url.path.split("/")[-2]
        return httpx.Response(
            200, json=[{"municipio-id": f"{uf}{i}", "municipio-nome": f"Cidade {i}"} for i in range(3)]
        )
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(api_module, "_transport", httpx.MockTransport(fake_ibge))
    # Nem consulta de nome sai da máquina, e a política instalada nesta máquina não interfere.
    monkeypatch.setattr(api_policy, "resolve", lambda _host: ["93.184.216.34"])
    monkeypatch.setenv(api_policy.POLICY_ENV, str(tmp_path / "sem-politica.json"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        storage_dir=tmp_path / "storage",
        max_upload_mb=1,
        log_level="WARNING",
        secrets_backend="memory",
        allowed_hosts=["testserver"],
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def store(tmp_path: Path) -> DatasetStore:
    root = tmp_path / "datasets"
    ensure_sample_datasets(root)
    return DatasetStore(root, max_bytes=1024 * 1024)


@pytest.fixture
def runner(tmp_path: Path, store: DatasetStore) -> WorkflowRunner:
    exports = tmp_path / "exports"
    exports.mkdir()
    apis = ApiStore(tmp_path / "apis.json", MemorySecretStore())
    seed_example_apis(apis)
    return WorkflowRunner(ResultCache(tmp_path / "cache"), store, exports, apis=apis)


@pytest.fixture
def demo() -> Workflow:
    return Workflow.model_validate(demo_workflow())
