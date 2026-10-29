"""Opções de leitura compartilhadas entre o nó Input Data, o preview e os testes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from prodata.forms import ui

FileFormat = Literal["auto", "csv", "excel", "parquet", "json", "ndjson", "arrow"]

# Campos que só fazem sentido para texto delimitado / planilhas.
_CSV = {"$format": ["csv"]}
_TABULAR = {"$format": ["csv", "excel"]}


class ReadOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: FileFormat = Field(
        "auto",
        title="Formato",
        description="'auto' detecta pela extensão e pelo conteúdo.",
        json_schema_extra=ui(
            group="Leitura",
            labels={
                "auto": "Automático",
                "csv": "CSV / texto delimitado",
                "excel": "Excel",
                "parquet": "Parquet",
                "json": "JSON (array)",
                "ndjson": "JSON Lines",
                "arrow": "Arrow IPC / Feather",
            },
        ),
    )
    delimiter: Literal["auto", ",", ";", "\t", "|"] = Field(
        "auto",
        title="Delimitador",
        json_schema_extra=ui(
            group="Leitura",
            show_if=_CSV,
            labels={
                "auto": "Automático",
                ",": "Vírgula (,)",
                ";": "Ponto e vírgula (;)",
                "\t": "Tabulação",
                "|": "Barra vertical (|)",
            },
        ),
    )
    encoding: Literal["auto", "utf-8", "utf-8-sig", "cp1252", "latin-1"] = Field(
        "auto",
        title="Encoding",
        json_schema_extra=ui(
            group="Leitura",
            show_if=_CSV,
            labels={
                "auto": "Automático",
                "utf-8": "UTF-8",
                "utf-8-sig": "UTF-8 com BOM",
                "cp1252": "Windows-1252",
                "latin-1": "ISO-8859-1",
            },
        ),
    )
    decimal: Literal["auto", ".", ","] = Field(
        "auto",
        title="Separador decimal",
        json_schema_extra=ui(
            group="Leitura",
            show_if=_CSV,
            labels={"auto": "Automático", ".": "Ponto (1.5)", ",": "Vírgula (1,5)"},
        ),
    )
    sheet: str = Field(
        "",
        title="Aba",
        description="Vazio = primeira aba.",
        json_schema_extra=ui(widget="sheet", group="Leitura", show_if={"$format": ["excel"]}),
    )
    skip_rows: int = Field(
        0,
        ge=0,
        title="Pular linhas iniciais",
        description="Linhas acima da tabela (título, logotipo…). No Excel, contadas desde a linha 1: "
        "cabeçalho na linha 4 → pular 3.",
        json_schema_extra=ui(group="Leitura", show_if=_TABULAR),
    )
    skip_columns: int = Field(
        0,
        ge=0,
        title="Pular colunas iniciais",
        description="Descarta as N primeiras colunas que aparecem na prévia. No Excel, colunas vazias "
        "à esquerda da tabela já são ignoradas sozinhas: só conte as que têm conteúdo.",
        json_schema_extra=ui(group="Leitura", show_if=_TABULAR),
    )
    has_header: bool = Field(
        True,
        title="Primeira linha é cabeçalho",
        description="A primeira linha depois das puladas tem os nomes das colunas.",
        json_schema_extra=ui(group="Leitura", show_if=_TABULAR),
    )
    null_values: str = Field(
        "",
        title="Valores nulos",
        description="Separados por vírgula, ex.: NA, NULL, -",
        json_schema_extra=ui(group="Avançado", show_if=_CSV, placeholder="NA, NULL"),
    )
    infer_schema_rows: int = Field(
        10_000,
        ge=0,
        title="Linhas para inferir tipos",
        description="0 = arquivo inteiro.",
        json_schema_extra=ui(group="Avançado"),
    )
    parse_dates: bool = Field(
        True, title="Detectar datas", json_schema_extra=ui(group="Avançado", show_if=_CSV)
    )

    def null_tokens(self) -> list[str]:
        return [t.strip() for t in self.null_values.split(",") if t.strip()]
