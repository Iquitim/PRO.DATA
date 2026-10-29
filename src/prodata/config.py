"""Configuração da aplicação, lida de variáveis de ambiente com prefixo ``PRODATA_``."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRODATA_", env_file=".env", extra="ignore")

    storage_dir: Path = PROJECT_ROOT / "storage"
    host: str = "127.0.0.1"
    port: int = 8765
    reload: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://127.0.0.1:8765", "http://localhost:8765"]
    max_upload_mb: int = 200
    seed_samples: bool = True
    secrets_backend: Literal["keyring", "memory"] = "keyring"
    results_page_max: int = 1000

    @cached_property
    def datasets_dir(self) -> Path:
        return self.storage_dir / "datasets"

    @cached_property
    def cache_dir(self) -> Path:
        return self.storage_dir / "cache"

    @cached_property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    @cached_property
    def connections_file(self) -> Path:
        return self.storage_dir / "connections.json"

    @cached_property
    def queries_file(self) -> Path:
        return self.storage_dir / "queries.json"

    @cached_property
    def workflows_dir(self) -> Path:
        return self.storage_dir / "workflows"

    def ensure_dirs(self) -> None:
        for d in (self.datasets_dir, self.cache_dir, self.exports_dir, self.workflows_dir):
            d.mkdir(parents=True, exist_ok=True)
