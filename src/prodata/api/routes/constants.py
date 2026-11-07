"""Constantes compartilhadas (spec 028, RF-2848, RF-2849)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from prodata.api.deps import ServicesDep
from prodata.domain.constants import Constant

router = APIRouter(prefix="/api/constants", tags=["dados"])


class SaveConstant(BaseModel):
    constant: Constant
    previous: str | None = None


@router.get("")
def list_constants(services: ServicesDep) -> list[Constant]:
    return services.constants.list()


@router.post("")
def save_constant(req: SaveConstant, services: ServicesDep) -> Constant:
    return services.constants.save(req.constant, req.previous)


@router.delete("/{name}", status_code=204)
def delete_constant(name: str, services: ServicesDep) -> Response:
    services.constants.delete(name)
    return Response(status_code=204)
