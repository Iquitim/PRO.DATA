"""Erros de domínio. A API traduz ``code`` em status HTTP; o motor não conhece HTTP."""

from __future__ import annotations


class ProdataError(Exception):
    code = "invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ProdataError):
    code = "not_found"


class ConflictError(ProdataError):
    code = "conflict"


class InvalidInputError(ProdataError):
    code = "invalid"


class TooLargeError(ProdataError):
    code = "too_large"
