from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from prodata.api.deps import ServicesDep
from prodata.domain.workflow import ID_PATTERN, Workflow
from prodata.engine import graph
from prodata.samples.workflows import demo_workflow
from prodata.services.workflows import WorkflowSummary

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
WorkflowId = Annotated[str, Path(pattern=ID_PATTERN)]


@router.get("")
def list_workflows(services: ServicesDep) -> list[WorkflowSummary]:
    return services.workflows.list()


@router.get("/demo")
def get_demo() -> Workflow:
    return Workflow.model_validate(demo_workflow())


@router.get("/{workflow_id}")
def get_workflow(workflow_id: WorkflowId, services: ServicesDep) -> Workflow:
    return services.workflows.get(workflow_id)


@router.put("/{workflow_id}")
def save_workflow(workflow_id: WorkflowId, workflow: Workflow, services: ServicesDep) -> Workflow:
    if workflow.id != workflow_id:
        workflow = workflow.model_copy(update={"id": workflow_id})
    graph.topological_order(workflow)  # recusa ciclos antes de salvar
    return services.workflows.save(workflow)


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: WorkflowId, services: ServicesDep) -> Response:
    services.workflows.delete(workflow_id)
    services.cache.clear_workflow(workflow_id)
    return Response(status_code=204)
