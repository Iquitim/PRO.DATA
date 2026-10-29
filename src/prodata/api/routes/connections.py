"""Conexões com bancos. A senha só entra no PUT e nunca é devolvida."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel

from prodata.api.deps import ServicesDep
from prodata.connectors import Connection, ConnectionInfo, sql
from prodata.domain.workflow import ID_PATTERN
from prodata.engine.profiling import schema_of
from prodata.engine.serialize import json_rows

router = APIRouter(prefix="/api/connections", tags=["conexões"])
ConnectionId = Annotated[str, Path(pattern=ID_PATTERN)]


class SaveConnectionRequest(BaseModel):
    connection: Connection
    # None mantém a senha atual; "" remove.
    password: str | None = None


class PreviewRequest(BaseModel):
    mode: Literal["table", "query"] = "table"
    table: str = ""
    query: str = ""


@router.get("")
def list_connections(services: ServicesDep) -> list[ConnectionInfo]:
    return services.connections.list()


@router.put("/{connection_id}")
def save_connection(
    connection_id: ConnectionId, req: SaveConnectionRequest, services: ServicesDep
) -> ConnectionInfo:
    conn = req.connection.model_copy(update={"id": connection_id})
    return services.connections.save(conn, req.password)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(connection_id: ConnectionId, services: ServicesDep) -> Response:
    services.connections.delete(connection_id)
    return Response(status_code=204)


@router.post("/{connection_id}/test")
def test_connection(connection_id: ConnectionId, services: ServicesDep) -> dict[str, Any]:
    conn = services.connections.get(connection_id)
    try:
        sql.check_connection(conn, services.connections.password(conn.id))
    except sql.DatabaseError as exc:
        return {"ok": False, "message": exc.message}
    return {"ok": True, "message": f"Conectado a {conn.database} em {conn.host}."}


@router.get("/{connection_id}/tables")
def list_tables(connection_id: ConnectionId, services: ServicesDep) -> list[dict[str, str]]:
    conn = services.connections.get(connection_id)
    return sql.list_tables(conn, services.connections.password(conn.id))


@router.post("/{connection_id}/preview")
def preview(
    connection_id: ConnectionId,
    req: PreviewRequest,
    services: ServicesDep,
    rows: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    conn = services.connections.get(connection_id)
    query = sql.table_query(conn, req.table) if req.mode == "table" else req.query
    df = sql.read_sql(conn, services.connections.password(conn.id), query, limit=rows)
    return {"columns": schema_of(df), "rows": json_rows(df)}
