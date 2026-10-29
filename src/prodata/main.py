"""Factory da aplicação FastAPI. Nada é criado em disco no import, só no ``create_app``."""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from prodata import __version__
from prodata.api.deps import Services
from prodata.api.errors import install_error_handlers
from prodata.api.routes import routers
from prodata.config import Settings
from prodata.connectors import ConnectionStore, KeyringSecretStore, MemorySecretStore, SecretStore
from prodata.connectors.queries import QueryStore
from prodata.domain.workflow import Workflow
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY
from prodata.samples.datasets import ensure_sample_datasets
from prodata.samples.workflows import DEMO_WORKFLOW_ID, demo_workflow
from prodata.services.workflows import WorkflowRepository

WEB_DIR = Path(__file__).parent / "web"
log = logging.getLogger("prodata")


def build_services(settings: Settings) -> Services:
    settings.ensure_dirs()
    datasets = DatasetStore(settings.datasets_dir, settings.max_upload_mb * 1024 * 1024)
    cache = ResultCache(settings.cache_dir)
    workflows = WorkflowRepository(settings.workflows_dir)
    secrets: SecretStore = (
        KeyringSecretStore() if settings.secrets_backend == "keyring" else MemorySecretStore()
    )
    connections = ConnectionStore(settings.connections_file, secrets)
    queries = QueryStore(settings.queries_file)
    if settings.seed_samples:
        ensure_sample_datasets(settings.datasets_dir)
        if not workflows.exists(DEMO_WORKFLOW_ID) or _uses_removed_tools(workflows.get(DEMO_WORKFLOW_ID)):
            workflows.save(Workflow.model_validate(demo_workflow()))
    return Services(
        settings=settings,
        datasets=datasets,
        cache=cache,
        runner=WorkflowRunner(cache, datasets, settings.exports_dir, connections, queries),
        workflows=workflows,
        connections=connections,
        queries=queries,
    )


def _uses_removed_tools(workflow: Workflow) -> bool:
    """Demonstração antiga (ex.: com as ferramentas de IA generativa removidas na spec 013)."""
    return any(n.type not in REGISTRY for n in workflow.nodes)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="PRO.DATA",
        version=__version__,
        description="API do motor de pipelines visuais (Polars + DuckDB + Arrow).",
    )
    app.state.services = build_services(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    for router in routers:
        app.include_router(router)

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def revalidate_static(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Módulos ES não passam por bundler com hash no nome: força revalidação (ETag) a cada carga.
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(index_html(), headers={"Cache-Control": "no-cache"})

    log.info("PRO.DATA %s pronto (storage: %s)", __version__, settings.storage_dir)
    threading.Thread(target=_warm_up, name="prodata-warmup", daemon=True).start()
    return app


def _warm_up() -> None:
    """Carrega em segundo plano o que é pesado e só é usado depois (ML, motor de fórmulas).

    O servidor já atende enquanto isso; o primeiro treino não paga ~0,7 s de importação.
    """
    try:
        for module in (
            "sklearn.ensemble",
            "sklearn.linear_model",
            "sklearn.metrics",
            "sklearn.model_selection",
        ):
            importlib.import_module(module)
        from prodata.engine import formula

        formula.connect().close()
    except Exception:  # aquecimento é otimização: falhar aqui não pode derrubar o servidor
        log.debug("Aquecimento em segundo plano falhou", exc_info=True)


PRELOAD_MARKER = "<!-- modulepreload: o servidor insere aqui a pré-carga de todos os módulos JS -->"


def index_html() -> str:
    """index.html com <link rel="modulepreload"> para cada módulo: o navegador baixa todos em
    paralelo em vez de descobri-los em cascata. Lido a cada pedido (barato) para refletir edições."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    modules = sorted(p.name for p in (WEB_DIR / "js").glob("*.js") if p.name != "main.js")
    links = "\n".join(f'  <link rel="modulepreload" href="/static/js/{m}" />' for m in modules)
    return html.replace(PRELOAD_MARKER, links)
