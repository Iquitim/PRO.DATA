"""Factory da aplicação FastAPI. Nada é criado em disco no import, só no ``create_app``."""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from prodata import __version__
from prodata.api.deps import Services
from prodata.api.errors import install_error_handlers
from prodata.api.routes import routers
from prodata.config import Settings
from prodata.connectors import ConnectionStore, KeyringSecretStore, MemorySecretStore, SecretStore
from prodata.connectors.api_store import ApiStore
from prodata.connectors.jira_store import JiraStore
from prodata.connectors.queries import QueryStore
from prodata.domain.workflow import Workflow
from prodata.engine.cache import ResultCache
from prodata.engine.runner import WorkflowRunner
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY
from prodata.samples.apis import refresh_example_docs, seed_example_apis
from prodata.samples.datasets import ensure_sample_datasets
from prodata.samples.workflows import (
    DEMO_V3_NODES,
    DEMO_WORKFLOW_ID,
    add_api_section,
    add_replay_section,
    demo_workflow,
)
from prodata.services.audit import setup_audit
from prodata.services.constants import ConstantStore
from prodata.services.trust import TrustRegistry
from prodata.services.usage import UsageIndex
from prodata.services.workflows import WorkflowRepository

WEB_DIR = Path(__file__).parent / "web"
log = logging.getLogger("prodata")


def build_services(settings: Settings) -> Services:
    settings.ensure_dirs()
    setup_audit(settings.storage_dir)
    datasets = DatasetStore(settings.datasets_dir, settings.max_upload_mb * 1024 * 1024)
    cache = ResultCache(settings.cache_dir)
    workflows = WorkflowRepository(settings.workflows_dir)
    secrets: SecretStore = (
        KeyringSecretStore() if settings.secrets_backend == "keyring" else MemorySecretStore()
    )
    connections = ConnectionStore(settings.connections_file, secrets)
    queries = QueryStore(settings.queries_file)
    apis = ApiStore(settings.apis_file, secrets)
    jira = JiraStore(settings.storage_dir / "jira", secrets)
    trust = TrustRegistry(settings.storage_dir / "confianca.json")
    constants = ConstantStore(settings.storage_dir / "constantes.json")
    # Na atualização para a 0.6, o que já estava na biblioteca começa confiável (RF-2825).
    trust.start([workflows.get(s.id) for s in workflows.list()])
    if settings.seed_samples:
        ensure_sample_datasets(settings.datasets_dir)
        if not workflows.exists(DEMO_WORKFLOW_ID) or _uses_removed_tools(workflows.get(DEMO_WORKFLOW_ID)):
            workflows.save(Workflow.model_validate(demo_workflow()))
            seed_example_apis(apis)
        else:
            saved = workflows.get(DEMO_WORKFLOW_ID).model_dump(mode="json", by_alias=True)
            with_api = add_api_section(saved)
            if with_api or add_replay_section(saved):
                add_replay_section(saved)
                workflows.save(Workflow.model_validate(saved))
            if with_api:
                seed_example_apis(apis)
        refresh_example_docs(apis)
        if workflows.exists(DEMO_WORKFLOW_ID):
            trust.created(workflows.get(DEMO_WORKFLOW_ID))
    return Services(
        settings=settings,
        datasets=datasets,
        cache=cache,
        runner=WorkflowRunner(
            cache, datasets, settings.exports_dir, connections, queries, apis, constants, jira
        ),
        workflows=workflows,
        connections=connections,
        queries=queries,
        apis=apis,
        jira=jira,
        trust=trust,
        usage=UsageIndex(settings.workflows_dir),
        constants=constants,
    )


def _uses_removed_tools(workflow: Workflow) -> bool:
    """Demonstração antiga: usa ferramentas removidas (spec 013) ou é anterior ao Pareto e ao Venn (spec 014)."""
    ids = {n.id for n in workflow.nodes}
    return any(n.type not in REGISTRY for n in workflow.nodes) or not ids.intersection(DEMO_V3_NODES)


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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_accepted_hosts(settings))
    install_error_handlers(app)
    for router in routers:
        app.include_router(router)

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def refuse_other_sites(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # O CORS só esconde a resposta: um envio de arquivo vindo de outro site ainda seria executado.
        origin = request.headers.get("origin")
        if (
            origin
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and not _same_origin(origin, request.headers.get("host", ""), settings.cors_origins)
        ):
            return JSONResponse({"detail": "Pedido de outro site recusado."}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

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
        return HTMLResponse(
            index_html(), headers={"Cache-Control": "no-cache", "Content-Security-Policy": APP_CSP}
        )

    log.info("PRO.DATA %s pronto (storage: %s)", __version__, settings.storage_dir)
    threading.Thread(target=_warm_up, name="prodata-warmup", daemon=True).start()
    return app


def _accepted_hosts(settings: Settings) -> list[str]:
    """Só o próprio computador: com outro nome de host, uma página externa leria a API (DNS rebinding)."""
    if settings.host in ("0.0.0.0", "::"):  # noqa: S104  (só compara o que foi configurado)
        return ["*"]
    return sorted({"127.0.0.1", "localhost", settings.host, *settings.allowed_hosts})


def _same_origin(origin: str, host: str, allowed: list[str]) -> bool:
    return origin in allowed or urlsplit(origin).netloc == host


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


# Só roda script do próprio programa e nada sai para outro endereço, mesmo que algo consiga entrar na página.
# Estilo em linha é usado nos desenhos; imagens em data:/blob: são as do dashboard e as geradas para exportar.
APP_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)

PRELOAD_MARKER = "<!-- modulepreload: o servidor insere aqui a pré-carga de todos os módulos JS -->"


def index_html() -> str:
    """index.html com <link rel="modulepreload"> para cada módulo: o navegador baixa todos em
    paralelo em vez de descobri-los em cascata. Lido a cada pedido (barato) para refletir edições."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    modules = sorted(p.name for p in (WEB_DIR / "js").glob("*.js") if p.name != "main.js")
    links = "\n".join(f'  <link rel="modulepreload" href="/static/js/{m}" />' for m in modules)
    return html.replace(PRELOAD_MARKER, links)
