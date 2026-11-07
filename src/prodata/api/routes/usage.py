"""Onde cada fonte é usada (spec 028, RF-2811..2815)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from prodata.api.deps import ServicesDep

router = APIRouter(prefix="/api/usage", tags=["dados"])


@router.get("")
def usage(services: ServicesDep) -> dict[str, list[dict[str, Any]]]:
    """``{fonte: [{workflow_id, workflow, readers, downstream}]}``, só com os fluxos da biblioteca."""
    return services.usage.get()
