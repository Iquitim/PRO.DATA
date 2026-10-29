from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from prodata import __version__
from prodata.engine import formula
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


@router.post("/formula/validate")
def validate_formula(req: ValidateFormulaRequest) -> dict[str, Any]:
    return formula.validate(req.expression, req.columns)
