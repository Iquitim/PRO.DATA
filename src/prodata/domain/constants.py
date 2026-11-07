"""Modelo das constantes (spec 028): um valor com nome, do fluxo ou compartilhado na vista Dados."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
ConstantType = Literal["text", "number", "date"]


class ConstantValue(BaseModel):
    type: ConstantType = "text"
    value: str = ""

    @model_validator(mode="after")
    def _check_value(self) -> ConstantValue:
        if self.type == "number":
            try:
                float(self.value.replace(",", "."))
            except ValueError:
                raise ValueError(f'"{self.value}" não é um número.') from None
        if self.type == "date":
            try:
                date.fromisoformat(self.value)
            except ValueError:
                raise ValueError(f'"{self.value}" não é uma data no formato AAAA-MM-DD.') from None
        return self


class Constant(ConstantValue):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = Field("", max_length=300)
