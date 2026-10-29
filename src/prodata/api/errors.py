"""Tradução de erros de domínio para respostas HTTP padronizadas ``{detail, code}``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from prodata.engine.formula import FormulaError
from prodata.engine.graph import GraphError
from prodata.errors import ProdataError

_STATUS = {"not_found": 404, "conflict": 409, "too_large": 413, "invalid": 400}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProdataError)
    async def _domain(_: Request, exc: ProdataError) -> JSONResponse:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=_STATUS.get(exc.code, 400))

    @app.exception_handler(GraphError)
    async def _graph(_: Request, exc: GraphError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "invalid_graph"}, status_code=422)

    @app.exception_handler(FormulaError)
    async def _formula(_: Request, exc: FormulaError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "invalid_formula"}, status_code=400)
