from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prodata.config import Settings
from prodata.domain.workflow import Workflow
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.main import create_app
from prodata.samples.datasets import ensure_sample_datasets
from prodata.samples.workflows import demo_workflow


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        storage_dir=tmp_path / "storage", max_upload_mb=1, log_level="WARNING", secrets_backend="memory"
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
    return WorkflowRunner(ResultCache(tmp_path / "cache"), store, exports)


@pytest.fixture
def demo() -> Workflow:
    return Workflow.model_validate(demo_workflow())
