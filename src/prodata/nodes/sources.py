"""Entradas sem fonte cadastrada (spec 033): uma pasta inteira e linhas geradas."""

from __future__ import annotations

import fnmatch
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import Field

from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.ingestion.detect import EXTENSIONS
from prodata.ingestion.options import ReadOptions
from prodata.ingestion.readers import read_table
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

MAX_FILES = 500
MAX_ROWS = 5_000_000

# ------------------------------------------------------------------ Input Folder


class InputFolderConfig(ReadOptions, ToolConfig):
    folder: str = Field(
        "",
        title="Pasta",
        description="Caminho completo. O PRO.DATA só lê: nunca grava, move ou apaga o que está nela.",
        json_schema_extra=ui(widget="folder", placeholder="D:\\Fechamento\\2026-10"),
    )
    pattern: str = Field(
        "*.xlsx",
        title="Arquivos",
        description="Padrão do nome: * vale qualquer trecho e ? um caractere. Ex.: vendas_*.xlsx",
        json_schema_extra=ui(placeholder="vendas_*.xlsx"),
    )
    file_column: str = Field(
        "arquivo",
        title="Coluna com o nome do arquivo",
        description="Vazio = não criar. Serve para saber de qual arquivo veio cada linha.",
    )
    limit: int = Field(0, ge=0, title="Limite de linhas por arquivo", description="0 = todas as linhas.")


def folder_files(cfg: InputFolderConfig) -> list[Path]:
    """Arquivos da pasta que casam com o padrão, em ordem de nome. Só a pasta escolhida, sem subpastas."""
    raw = cfg.folder.strip()
    if not raw:
        raise InvalidInputError("Escolha a pasta.")
    folder = Path(raw)
    if not folder.is_absolute():
        raise InvalidInputError("A pasta precisa ser um caminho completo, como D:\\Fechamento\\2026-10.")
    if not folder.is_dir():
        raise InvalidInputError(f"A pasta não existe: {folder}")
    pattern = cfg.pattern.strip() or "*"
    if any(c in pattern for c in "/\\") or ".." in pattern:
        raise InvalidInputError("O padrão vale para o nome do arquivo: não pode ter barras nem '..'.")
    found = sorted(
        (
            p
            for p in folder.iterdir()
            if p.is_file()
            and p.suffix.lower() in EXTENSIONS
            and not p.name.startswith("~$")  # arquivo temporário do Excel aberto
            and fnmatch.fnmatch(p.name.lower(), pattern.lower())
        ),
        key=lambda p: p.name.lower(),
    )
    if len(found) > MAX_FILES:
        raise InvalidInputError(
            f"{len(found)} arquivos casam com '{pattern}': o limite é {MAX_FILES}. Use um padrão mais específico."
        )
    return found


def _folder_signature(_ctx: NodeContext, cfg: InputFolderConfig) -> str:
    try:
        files = folder_files(cfg)
    except InvalidInputError:
        return ""
    return "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in files)


@tool(
    type="io.input_folder",
    explainer="input_folder",
    name="Input Folder",
    category="inout",
    icon="directory",
    description="Lê todos os arquivos de uma pasta que casam com um padrão de nome, como vendas_*.xlsx, e empilha as linhas.",
    config=InputFolderConfig,
    inputs=[],
    outputs=[Port("out", "O", "Dados")],
    annotate=lambda c: c.pattern or "Escolha a pasta",
    fingerprint=_folder_signature,
)
def input_folder(ctx: NodeContext, cfg: InputFolderConfig) -> NodeOutput:
    files = folder_files(cfg)
    if not files:
        raise InvalidInputError(
            f"Nenhum arquivo em {cfg.folder.strip()} casa com '{cfg.pattern.strip() or '*'}'."
        )
    column = cfg.file_column.strip()
    frames: list[pl.DataFrame] = []
    odd: list[str] = []
    first: list[str] = []
    for i, path in enumerate(files, start=1):
        ctx.report(f"{i}/{len(files)} arquivos")
        frame = read_table(path, cfg, n_rows=cfg.limit or None)
        if not frames:
            first = frame.columns
        elif set(frame.columns) != set(first):
            odd.append(path.name)
        if column:
            if column in frame.columns:
                raise InvalidInputError(
                    f"'{path.name}' já tem uma coluna '{column}': troque o nome da coluna do arquivo."
                )
            frame = frame.with_columns(pl.lit(path.name).alias(column))
        frames.append(frame)
    try:
        table = pl.concat(frames, how="diagonal_relaxed")
    except pl.exceptions.PolarsError as exc:
        raise InvalidInputError(
            f"Os arquivos têm colunas com tipos que não combinam: {str(exc).splitlines()[0]}"
        ) from exc
    extra: dict[str, Any] = {"folder_files": [p.name for p in files], "source_read_at": _now()}
    if odd:
        shown = ", ".join(odd[:5]) + ("…" if len(odd) > 5 else "")
        extra["warnings"] = [
            f"{len(odd)} arquivo(s) com colunas diferentes de {files[0].name}: {shown}. O que falta fica vazio."
        ]
    return NodeOutput(tables={"out": table}, extra=extra)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------------ Generate Rows

_WEEKDAYS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]
_MONTHS = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
_STEP = {"day": "1d", "week": "1w", "month": "1mo", "quarter": "1q", "year": "1y"}


class GenerateRowsConfig(ToolConfig):
    mode: Literal["dates", "numbers"] = Field(
        "dates",
        title="Gerar",
        json_schema_extra=ui(labels={"dates": "Datas (calendário)", "numbers": "Números em sequência"}),
    )
    column: str = Field("data", title="Nome da coluna")
    start_date: str = Field(
        "",
        title="De",
        description="2026-01-01 ou 01/01/2026. Aceita constante, como [#mes_referencia].",
        json_schema_extra=ui(show_if={"mode": ["dates"]}, placeholder="2026-01-01"),
    )
    end_date: str = Field(
        "",
        title="Até",
        description="Vazio = hoje.",
        json_schema_extra=ui(show_if={"mode": ["dates"]}, placeholder="2026-12-31"),
    )
    every: Literal["day", "week", "month", "quarter", "year"] = Field(
        "day",
        title="Uma linha por",
        json_schema_extra=ui(
            show_if={"mode": ["dates"]},
            labels={"day": "Dia", "week": "Semana", "month": "Mês", "quarter": "Trimestre", "year": "Ano"},
        ),
    )
    calendar: bool = Field(
        True,
        title="Colunas de calendário",
        description="Ano, mês, dia, trimestre, dia da semana, fim de semana e ano-mês.",
        json_schema_extra=ui(show_if={"mode": ["dates"]}),
    )
    start: float = Field(1, title="De", json_schema_extra=ui(show_if={"mode": ["numbers"]}, step=1))
    end: float = Field(10, title="Até", json_schema_extra=ui(show_if={"mode": ["numbers"]}, step=1))
    step: float = Field(
        1, title="De quanto em quanto", json_schema_extra=ui(show_if={"mode": ["numbers"]}, step=1)
    )


def parse_day(text: str, what: str) -> date:
    raw = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise InvalidInputError(f"'{raw}' não é uma data em {what}: use 2026-01-31 ou 31/01/2026.")


def _dates(cfg: GenerateRowsConfig, name: str) -> pl.DataFrame:
    if not cfg.start_date.strip():
        raise InvalidInputError("Informe a data inicial em 'De'.")
    start = parse_day(cfg.start_date, "'De'")
    end = parse_day(cfg.end_date, "'Até'") if cfg.end_date.strip() else date.today()
    if end < start:
        raise InvalidInputError("A data final é anterior à inicial.")
    if cfg.every == "day" and (end - start).days + 1 > MAX_ROWS:
        raise InvalidInputError(f"O intervalo passa de {MAX_ROWS:,} linhas.".replace(",", "."))
    days = pl.date_range(start, end, interval=_STEP[cfg.every], eager=True).alias(name)
    table = pl.DataFrame([days])
    if not cfg.calendar:
        return table
    d = pl.col(name)
    return table.with_columns(
        d.dt.year().cast(pl.Int64).alias("ano"),
        d.dt.month().cast(pl.Int64).alias("mes"),
        d.dt.day().cast(pl.Int64).alias("dia"),
        d.dt.quarter().cast(pl.Int64).alias("trimestre"),
        d.dt.strftime("%Y-%m").alias("ano_mes"),
        d.dt.month()
        .replace_strict(dict(enumerate(_MONTHS, start=1)), return_dtype=pl.String)
        .alias("nome_mes"),
        d.dt.weekday().cast(pl.Int64).alias("dia_semana"),
        d.dt.weekday()
        .replace_strict(dict(enumerate(_WEEKDAYS, start=1)), return_dtype=pl.String)
        .alias("nome_dia"),
        (d.dt.weekday() >= 6).alias("fim_de_semana"),
        (d == d.dt.month_end()).alias("ultimo_dia_do_mes"),
    )


def _numbers(cfg: GenerateRowsConfig, name: str) -> pl.DataFrame:
    if cfg.step == 0:
        raise InvalidInputError("O passo não pode ser zero.")
    count = int((cfg.end - cfg.start) / cfg.step) + 1
    if count < 1:
        raise InvalidInputError("Com esse passo, a sequência nunca chega ao valor final.")
    if count > MAX_ROWS:
        raise InvalidInputError(f"A sequência passa de {MAX_ROWS:,} linhas.".replace(",", "."))
    whole = all(float(v).is_integer() for v in (cfg.start, cfg.end, cfg.step))
    values = [cfg.start + i * cfg.step for i in range(count)]
    return pl.DataFrame({name: [int(v) for v in values] if whole else values})


@tool(
    type="io.generate_rows",
    explainer="generate_rows",
    name="Generate Rows",
    category="inout",
    icon="list",
    description="Cria linhas sem ler arquivo: um calendário entre duas datas ou números em sequência.",
    config=GenerateRowsConfig,
    inputs=[],
    outputs=[Port("out", "O", "Linhas")],
    annotate=lambda c: (
        f"{c.start_date or '?'} a {c.end_date or 'hoje'}" if c.mode == "dates" else f"{c.start:g} a {c.end:g}"
    ),
    # Sem data final, o calendário vai até hoje: muda quando o dia muda.
    fingerprint=lambda _ctx, c: (
        date.today().isoformat() if c.mode == "dates" and not c.end_date.strip() else ""
    ),
)
def generate_rows(ctx: NodeContext, cfg: GenerateRowsConfig) -> NodeOutput:
    name = cfg.column.strip() or ("data" if cfg.mode == "dates" else "numero")
    return NodeOutput(tables={"out": _dates(cfg, name) if cfg.mode == "dates" else _numbers(cfg, name)})
