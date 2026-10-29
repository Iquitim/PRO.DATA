"""Acesso tipado aos serviços montados em ``app.state`` pelo ``create_app``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from prodata.config import Settings
from prodata.connectors import ConnectionStore
from prodata.connectors.queries import QueryStore
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.services.workflows import WorkflowRepository


@dataclass
class Services:
    settings: Settings
    datasets: DatasetStore
    cache: ResultCache
    runner: WorkflowRunner
    workflows: WorkflowRepository
    connections: ConnectionStore
    queries: QueryStore


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]
