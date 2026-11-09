"""Conexões e consultas do Jira (spec 030). Token e e-mail entram por aqui e nunca voltam."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel

from prodata.api.deps import ServicesDep
from prodata.connectors import jira_read
from prodata.connectors.jira import JiraClient
from prodata.connectors.jira_model import (
    JiraConnection,
    JiraInfo,
    JiraQuery,
    JiraQueryDefinition,
    normalize_site,
)
from prodata.domain.workflow import ID_PATTERN
from prodata.engine.profiling import schema_of
from prodata.engine.serialize import json_rows

router = APIRouter(prefix="/api/jira", tags=["jira"])
ItemId = Annotated[str, Path(pattern=ID_PATTERN)]


class SaveConnection(BaseModel):
    connection: JiraConnection
    email: str | None = None
    token: str | None = None


class TestConnection(BaseModel):
    site: str
    email: str = ""
    token: str = ""
    id: str = ""  # conexão já salva: o que faltar vem do cofre


@router.get("/connections")
def list_connections(services: ServicesDep) -> list[JiraInfo]:
    return services.jira.connections()


@router.post("/test")
def test_connection(req: TestConnection, services: ServicesDep) -> dict[str, Any]:
    email = req.email or (services.jira.secrets.get(f"jira:{req.id}:email") if req.id else "") or ""
    token = req.token or (services.jira.secrets.get(f"jira:{req.id}:token") if req.id else "") or ""
    with JiraClient(normalize_site(req.site), email, token) as client:
        who = client.connect()
        return {
            "display_name": who.display_name,
            "token_kind": who.token_kind,
            "projects": len(client.projects()),
            "site": client.site,
        }


@router.put("/connections/{conn_id}")
def save_connection(conn_id: ItemId, req: SaveConnection, services: ServicesDep) -> JiraInfo:
    conn = req.connection.model_copy(update={"id": conn_id})
    return services.jira.save_connection(conn, req.email, req.token)


@router.delete("/connections/{conn_id}", status_code=204)
def delete_connection(conn_id: ItemId, services: ServicesDep) -> Response:
    services.jira.delete_connection(conn_id)
    return Response(status_code=204)


@router.get("/connections/{conn_id}/catalog")
def catalog(conn_id: ItemId, services: ServicesDep) -> dict[str, Any]:
    """O que a tela oferece: projetos, tipos, status e campos, com os nomes que aparecem no Jira."""
    with services.jira.client(conn_id) as client:
        return {
            "projects": [{"key": p.get("key"), "name": p.get("name")} for p in client.projects()],
            "issue_types": sorted({str(t.get("name")) for t in client.issue_types()}),
            "statuses": sorted({str(s.get("name")) for s in client.statuses()}),
            "fields": sorted(
                ({"id": f.get("id"), "name": f.get("name")} for f in client.fields() if f.get("custom")),
                key=lambda f: str(f["name"]).lower(),
            ),
        }


@router.get("/queries")
def list_queries(services: ServicesDep) -> list[dict[str, Any]]:
    return [{**q.model_dump(mode="json"), **jira_read.status(q, services.jira)} for q in services.jira.queries()]


@router.put("/queries/{query_id}")
def save_query(query_id: ItemId, query: JiraQuery, services: ServicesDep) -> JiraQuery:
    return services.jira.save_query(query.model_copy(update={"id": query_id}))


@router.delete("/queries/{query_id}", status_code=204)
def delete_query(query_id: ItemId, services: ServicesDep) -> Response:
    services.jira.delete_query(query_id)
    return Response(status_code=204)


@router.post("/queries/preview")
def preview(definition: JiraQueryDefinition, services: ServicesDep) -> dict[str, Any]:
    """Primeiras linhas e total aproximado, sem guardar nada."""
    jql = definition.to_jql()
    probe = JiraQuery(id="previa", name="prévia", **definition.model_dump())
    with services.jira.client(definition.connection) as client:
        frame, total = jira_read.preview(probe, client)
    return {"jql": jql, "total": total, "columns": schema_of(frame), "rows": json_rows(frame)}


@router.post("/queries/{query_id}/reload")
def reload_query(query_id: ItemId, services: ServicesDep, full: Annotated[bool, Query()] = True) -> dict[str, Any]:
    frame, info = jira_read.load(services.jira.query(query_id), services.jira, full=full)
    return {"rows": frame.height, **info}


@router.delete("/queries/{query_id}/local", status_code=204)
def forget_local(query_id: ItemId, services: ServicesDep) -> Response:
    services.jira.query(query_id)
    services.jira.forget(query_id)
    return Response(status_code=204)
