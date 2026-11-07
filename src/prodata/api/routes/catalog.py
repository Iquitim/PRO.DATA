from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from prodata import __version__
from prodata.api.deps import ServicesDep
from prodata.domain.constants import Constant
from prodata.engine import constants as constants_engine
from prodata.engine import formula, multirow
from prodata.ingestion.detect import EXTENSIONS
from prodata.nodes import CATEGORIES, catalog

router = APIRouter(prefix="/api", tags=["catálogo"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    """Ferramentas disponíveis, com portas e descrição dos campos de configuração."""
    return {
        "version": __version__,
        "categories": CATEGORIES,
        "tools": catalog(),
        "file_formats": EXTENSIONS,
        "formula_functions": formula.function_catalog(),
        "formula_keywords": {"control": formula.KEYWORDS, "logical": formula.LOGICAL},
    }


class ValidateFormulaRequest(BaseModel):
    expression: str
    columns: list[dict[str, str]] = []
    multirow: bool = False
    # Constantes do fluxo aberto (spec 028); as compartilhadas vêm do cadastro.
    constants: list[Constant] = []


@router.post("/formula/validate")
def validate_formula(req: ValidateFormulaRequest, services: ServicesDep) -> dict[str, Any]:
    known = {**services.constants.all(), **{c.name: c for c in req.constants}}
    if missing := sorted(constants_engine.node_refs("", {"expression": req.expression}) - set(known)):
        return {
            "valid": False,
            "error": f"A constante [#{missing[0]}] não existe: cadastre na vista Dados ou nas constantes do fluxo.",
            "sql": None,
        }
    expression = constants_engine.fill_expression(req.expression, known)
    expression = multirow.for_validation(expression) if req.multirow else expression
    return formula.validate(expression, req.columns)
