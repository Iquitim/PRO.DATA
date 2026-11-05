"""Aba SQL (spec 020): gera o código do fluxo e confere o resultado com o motor."""

from __future__ import annotations

import io
import threading
import time
import zipfile
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Path, Response
from pydantic import BaseModel

from prodata.api.deps import Services, ServicesDep
from prodata.domain.workflow import ID_PATTERN, Workflow
from prodata.engine.graph import GraphError
from prodata.engine.sql.fragment import slug
from prodata.engine.sql.plan import OK, Env, Output, SqlPlan, build_plan, temporary_output
from prodata.engine.sql.render import render, to_text
from prodata.engine.sql.verify import CancelledError, Verification, output_state, verify
from prodata.errors import InvalidInputError

router = APIRouter(prefix="/api/sql", tags=["sql"])


class GenerateRequest(BaseModel):
    workflow: Workflow
    selection: list[str] = []
    temporary_node: str | None = None


class DownloadRequest(GenerateRequest):
    mode: str = "selection"  # "selection" | "zip"


def _env(services: Services, workflow: Workflow) -> Env:
    return Env(
        services.cache,
        services.datasets,
        services.queries,
        lambda n: services.runner.is_fresh(workflow, n),
        services.apis,
    )


def _plan(services: Services, workflow: Workflow) -> SqlPlan:
    try:
        return build_plan(workflow, _env(services, workflow))
    except GraphError as exc:
        raise InvalidInputError(str(exc)) from exc


# ---------------------------------------------------------------- conferência em segundo plano


class _Job:
    def __init__(self, signature: str, fresh: frozenset[str]) -> None:
        self.signature = signature
        self.fresh = fresh  # caixas com resultado válido no início: arquivo que mudou invalida a conferência
        self.cancel = threading.Event()
        self.result: Verification | None = None
        self.error = ""
        self.done = False
        self.started = time.monotonic()


_jobs: dict[str, _Job] = {}
_jobs_lock = threading.Lock()


def _signature(workflow: Workflow) -> str:
    """Muda com a configuração do fluxo, não com a posição das caixas: arrastar não refaz a conferência."""
    nodes = sorted((n.id, n.type, str(n.config), n.disabled, n.label) for n in workflow.nodes)
    edges = sorted((e.source, e.source_handle, e.target, e.target_handle) for e in workflow.edges)
    return str(hash((tuple(nodes), tuple(edges))))


def _fresh_nodes(services: Services, workflow: Workflow) -> frozenset[str]:
    return frozenset(n.id for n in workflow.nodes if services.runner.is_fresh(workflow, n.id))


def _visible_result(services: Services, workflow: Workflow) -> tuple[Verification | None, bool]:
    with _jobs_lock:
        job = _jobs.get(workflow.id)
    # Conferência de outro estado do fluxo (ou de um arquivo que já mudou) não vale mais (RF-2023).
    if job is None or job.signature != _signature(workflow) or job.fresh != _fresh_nodes(services, workflow):
        return None, False
    return job.result, not job.done


def _states(plan: SqlPlan, outputs: list[Output], result: Verification | None) -> dict[str, str]:
    states = {}
    for output in outputs:
        state = output_state(plan, output, result)
        extra = (
            f" ({state['checked']} de {state['total']} transformações conferidas)"
            if state.get("total")
            else ""
        )
        states[output.id] = f"{state['label']}{extra}"
    return states


def _resolve(plan: SqlPlan, req: GenerateRequest) -> tuple[list[Output], Output | None]:
    if req.temporary_node and any(n.id == req.temporary_node for n in plan.workflow.nodes):
        temporary = temporary_output(plan, req.temporary_node)
        if temporary is not None:
            return [temporary], temporary
    chosen = [o for o in (plan.output(i) for i in req.selection) if o is not None]
    if chosen:
        return chosen, None
    tables = [o for o in plan.outputs if o.kind == "table"]
    # Sem seleção: a primeira tabela que vira SQL por inteiro; senão, a primeira saída que houver.
    first = next((o for o in tables if o.stop is None), tables[0] if tables else None)
    if first is None and plan.outputs:
        first = plan.outputs[0]
    return ([first], None) if first else ([], None)


def _block_view(plan: SqlPlan, result: Verification | None) -> list[dict[str, Any]]:
    checks = result.blocks if result else {}
    return [
        {
            "id": b.id,
            "node_id": b.node_id,
            "port": b.port,
            "name": b.name,
            "status": b.status,
            "reason": b.reason,
            "explain": b.fragment.explain if b.fragment else "",
            "notes": b.fragment.notes if b.fragment else [],
            "deps": b.deps,
            "rows": b.rows,
            "columns": len(b.columns),
            "check": asdict(checks[b.id]) if b.id in checks else None,
            "data_warning": bool(b.fragment and b.fragment.data_warning),
        }
        for b in plan.blocks.values()
    ]


def _output_view(plan: SqlPlan, output: Output, result: Verification | None) -> dict[str, Any]:
    state = output_state(plan, output, result)
    tail = plan.tail(output)
    return {
        "id": output.id,
        "node_id": output.node_id,
        "port": output.port,
        "name": output.name,
        "kind": output.kind,
        "steps": output.steps,
        "stop": output.stop,
        "temporary": output.temporary,
        "rows": tail.rows if tail is not None and output.stop is None else None,
        "export_file": tail.fragment.export_file if tail is not None and tail.fragment else "",
        "state": state,
    }


@router.post("/generate")
def generate(req: GenerateRequest, services: ServicesDep) -> dict[str, Any]:
    """Código e caminhos da seleção. Só lê a configuração: nada do fluxo é executado (RF-2008)."""
    plan = _plan(services, req.workflow)
    result, running = _visible_result(services, req.workflow)
    outputs, temporary = _resolve(plan, req)
    parts = render(plan, outputs, _states(plan, outputs, result))
    views = [_output_view(plan, o, result) for o in plan.outputs]
    selected = [o.id for o in outputs]
    return {
        "dialect": "duckdb",
        "blocks": _block_view(plan, result),
        "outputs": views,
        "selection": selected,
        "selected_views": [_output_view(plan, o, result) for o in outputs],
        "temporary": _output_view(plan, temporary, result) if temporary else None,
        "parts": [asdict(p) for p in parts],
        "text": to_text(parts) if parts else "",
        "verifying": running,
        "verified": result is not None,
        "ok_blocks": sum(1 for b in plan.blocks.values() if b.status == OK),
    }


@router.post("/verify")
def start_verification(req: GenerateRequest, services: ServicesDep) -> dict[str, Any]:
    """Inicia a conferência. Uma nova conferência do mesmo fluxo cancela a anterior (RF-2024)."""
    workflow = req.workflow
    signature = _signature(workflow)
    fresh = _fresh_nodes(services, workflow)
    with _jobs_lock:
        current = _jobs.get(workflow.id)
        if (
            current is not None
            and current.signature == signature
            and current.fresh == fresh
            and not current.done
        ):
            return {"started": False}
        if current is not None:
            current.cancel.set()
        job = _Job(signature, fresh)
        _jobs[workflow.id] = job

    def work() -> None:
        try:
            env = _env(services, workflow)
            job.result = verify(build_plan(workflow, env), env, job.cancel)
        except CancelledError:
            pass
        except Exception as exc:  # a conferência nunca pode derrubar o programa
            job.error = str(exc)
        finally:
            job.done = True

    threading.Thread(target=work, name="prodata-sql-verify", daemon=True).start()
    return {"started": True}


@router.get("/verify/{workflow_id}")
def verification_status(workflow_id: Annotated[str, Path(pattern=ID_PATTERN)]) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(workflow_id)
    if job is None:
        return {"running": False, "done": False, "error": ""}
    return {"running": not job.done, "done": job.done, "error": job.error}


@router.post("/download")
def download(req: DownloadRequest, services: ServicesDep) -> Response:
    """Um .sql com a seleção, ou um .zip com um .sql por saída mais o unificado (RF-2028)."""
    plan = _plan(services, req.workflow)
    result, _ = _visible_result(services, req.workflow)
    name = slug(req.workflow.name or "fluxo")
    if req.mode != "zip":
        outputs, _temporary = _resolve(plan, req)
        text = to_text(render(plan, outputs, _states(plan, outputs, result)))
        file = f"{name}.sql" if len(outputs) != 1 else f"{name}__{slug(outputs[0].name)}.sql"
        return Response(text, media_type="application/sql", headers=_attachment(file))
    tables = [o for o in plan.outputs if o.kind == "table"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for output in tables:
            base = slug(output.name)
            file = base if base not in used else f"{base}_{len(used)}"
            used.add(file)
            archive.writestr(f"{file}.sql", to_text(render(plan, [output], _states(plan, [output], result))))
        if len(tables) > 1:
            archive.writestr(
                "_todas_as_saidas.sql", to_text(render(plan, tables, _states(plan, tables, result)))
            )
    return Response(buffer.getvalue(), media_type="application/zip", headers=_attachment(f"{name}.zip"))


def _attachment(file: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{file}"'}
