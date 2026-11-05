"""Ferramentas de entrada e saída."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl
import xlsxwriter
from pydantic import BaseModel, Field

from prodata.connectors import sql
from prodata.connectors.api import read_api, run_loop, source_api_id
from prodata.connectors.queries import read_definition, source_query_id
from prodata.engine.sql.fragment import (
    OWN_RESULT,
    Fragment,
    SourceInfo,
    SqlContext,
    join_list,
    kind_of,
    lit,
    q,
    slug,
    sql_for,
)
from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.ingestion.datasets import resolve_inside, sanitize_filename
from prodata.ingestion.options import ReadOptions
from prodata.ingestion.readers import read_table, resolve_options
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

# ------------------------------------------------------------------ Input Data


class InputDataConfig(ReadOptions, ToolConfig):
    dataset: str = Field(
        "",
        title="Fonte",
        description="Arquivo, consulta de banco ou API cadastrados na aba Dados. APIs com variável, como {sigla}, ficam no API Loop.",
        json_schema_extra=ui(widget="dataset"),
    )
    limit: int = Field(0, ge=0, title="Limite de linhas", description="0 = todas as linhas.")


def _source_signature(ctx: NodeContext, cfg: InputDataConfig) -> str:
    if not cfg.dataset:
        return ""
    api_id = source_api_id(cfg.dataset)
    if api_id is not None:
        if ctx.apis is None:
            return ""
        api = ctx.apis.get(api_id)
        # Sem reaproveitar, cada execução chama de novo: a resposta pode ter mudado.
        return f"a{api.digest()}" + ("" if api.cache_results else f"t{time.time_ns()}")
    query_id = source_query_id(cfg.dataset)
    if query_id is None:
        return ctx.datasets.signature(cfg.dataset)
    if ctx.queries is None:
        return ""
    query = ctx.queries.get(query_id)
    # Sem cache, um carimbo de tempo força nova consulta (o banco pode ter mudado).
    return f"q{query.digest()}" + ("" if query.cache_results else f"t{time.time_ns()}")


def _source_annotation(cfg: InputDataConfig) -> str:
    if not cfg.dataset:
        return "Escolha uma fonte"
    if source_api_id(cfg.dataset):
        return "API"
    return "Consulta de banco" if source_query_id(cfg.dataset) else cfg.dataset


def _source_on_request(ctx: NodeContext, cfg: InputDataConfig) -> str | None:
    """Um POST pode gravar do outro lado: não roda só porque o fluxo foi aberto."""
    api_id = source_api_id(cfg.dataset)
    if api_id is None or ctx.apis is None:
        return None
    api = ctx.apis.get(api_id)
    if api.method != "GET":
        return "Esta caixa faz um POST na API. Clique em Executar para chamar."
    return "Esta caixa só chama a API quando você clica em Executar." if api.hold_on_open else None


@tool(
    type="io.input_data",
    name="Input Data",
    category="inout",
    icon="database",
    description="Lê qualquer fonte da aba Dados: arquivos (CSV, Excel, Parquet, JSON, Arrow), consultas de banco ou APIs.",
    config=InputDataConfig,
    inputs=[],
    outputs=[Port("out", "O", "Dados")],
    annotate=_source_annotation,
    fingerprint=_source_signature,
    only_on_request=_source_on_request,
)
def input_data(ctx: NodeContext, cfg: InputDataConfig) -> NodeOutput:
    if not cfg.dataset:
        raise ValueError("Escolha uma fonte no campo 'Fonte'.")
    api_id = source_api_id(cfg.dataset)
    if api_id is not None:
        if ctx.apis is None:
            raise ValueError("APIs não estão disponíveis neste ambiente.")
        api = ctx.apis.get(api_id)
        frame, result = read_api(api, ctx.apis.secret_reader(api.id))
        extra: dict[str, Any] = {"source": api.name, "source_read_at": _now(), "api_pages": result.pages}
        if result.truncated:
            extra["warnings"] = [
                f"Parou no limite de {result.pages} páginas e ainda havia mais: aumente o limite na aba Dados."
            ]
        return NodeOutput(tables={"out": frame.head(cfg.limit) if cfg.limit else frame}, extra=extra)
    query_id = source_query_id(cfg.dataset)
    if query_id is not None:
        if ctx.queries is None or ctx.connections is None:
            raise ValueError("Consultas de banco não estão disponíveis neste ambiente.")
        query = ctx.queries.get(query_id)
        df = read_definition(query, ctx.connections, limit=cfg.limit or None)
        return NodeOutput(tables={"out": df}, extra={"source": query.name, "source_read_at": _now()})
    path = ctx.datasets.resolve(cfg.dataset)
    info = ctx.datasets.info_of(cfg.dataset)
    df = read_table(path, cfg, n_rows=cfg.limit or None)
    # Quando o arquivo foi modificado e se é vinculado: o Configurar mostra de quando são os dados (spec 017).
    extra = {
        "source_modified": info.modified_at.isoformat() if info.modified_at else None,
        "source_read_at": _now(),
    }
    if info.linked_path:
        extra["source_linked"] = info.linked_path
    return NodeOutput(tables={"out": df}, extra=extra)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------ API Loop


class ApiLoopConfig(ToolConfig):
    source: str = Field(
        "",
        title="API",
        description="Só aparecem as que têm variável, como {sigla}. As outras são lidas direto no Input Data.",
        json_schema_extra=ui(widget="api_source"),
    )
    columns: dict[str, str] = Field(
        default_factory=dict,
        title="De onde vem cada variável",
        description="Cada valor da coluna escolhida gera uma chamada à API.",
        json_schema_extra=ui(widget="api_params"),
    )
    keep_columns: bool = Field(
        True,
        title="Manter as colunas da tabela de entrada",
        description="Cada linha de resposta sai ao lado da linha que a pediu.",
    )
    concurrency: int = Field(4, ge=1, le=16, title="Chamadas ao mesmo tempo")
    calls_per_second: float = Field(
        5,
        ge=0,
        le=1000,
        title="Chamadas por segundo",
        description="Respeita o limite da API. 0 = sem limite.",
    )
    max_calls: int = Field(
        1000,
        ge=1,
        le=1_000_000,
        title="Limite de chamadas",
        description="Acima disso, nada é chamado: protege a cota da API de uma tabela maior do que o esperado.",
    )
    on_error: Literal["continue", "stop"] = Field(
        "continue",
        title="Se uma chamada falhar",
        json_schema_extra=ui(
            labels={"continue": "Seguir e listar na saída E", "stop": "Parar a caixa com erro"}
        ),
    )
    reuse: bool = Field(
        False,
        title="Reaproveitar resultado entre execuções",
        description="Só chama de novo se a tabela de entrada ou a API mudarem.",
    )


def _loop_signature(ctx: NodeContext, cfg: ApiLoopConfig) -> str:
    if not cfg.source or ctx.apis is None:
        return ""
    return ctx.apis.get(cfg.source).digest() + ("" if cfg.reuse else f"t{time.time_ns()}")


def _loop_on_request(_ctx: NodeContext, _cfg: ApiLoopConfig) -> str | None:
    return "Esta caixa faz uma chamada por linha na API. Clique em Executar para chamar."


@tool(
    type="io.api_loop",
    name="API Loop",
    category="inout",
    icon="repeat",
    description="Para APIs com variável, como {sigla}: chama uma vez para cada linha da tabela, com o valor da coluna que você escolher, e junta as respostas. A tabela pode vir de outra API.",
    config=ApiLoopConfig,
    outputs=[Port("out", "R", "Respostas"), Port("errors", "E", "Chamadas com erro")],
    fingerprint=_loop_signature,
    only_on_request=_loop_on_request,
    explainer="api_loop",
)
def api_loop(ctx: NodeContext, cfg: ApiLoopConfig) -> NodeOutput:
    if not cfg.source:
        raise ValueError("Escolha uma API no campo 'API'.")
    if ctx.apis is None:
        raise ValueError("APIs não estão disponíveis neste ambiente.")
    api = ctx.apis.get(cfg.source)
    result = run_loop(
        ctx.input(),
        api,
        ctx.apis.secret_reader(api.id),
        concurrency=cfg.concurrency,
        per_second=cfg.calls_per_second,
        max_calls=cfg.max_calls,
        stop_on_error=cfg.on_error == "stop",
        keep_columns=cfg.keep_columns,
        columns=cfg.columns,
        progress=lambda done, total: ctx.report(f"{done}/{total} chamadas"),
    )
    warnings = []
    if result.failed:
        warnings.append(f"{result.failed} de {result.calls} chamadas falharam: veja a saída E.")
    if result.truncated:
        warnings.append(f"{result.truncated} chamadas pararam no limite de páginas da API.")
    extra: dict[str, Any] = {"api_calls": result.calls, "api_failed": result.failed}
    if warnings:
        extra["warnings"] = warnings
    return NodeOutput(tables={"out": result.table, "errors": result.errors}, extra=extra)


# ------------------------------------------------------------------ Text Input


class TextTable(BaseModel):
    columns: list[str] = Field(default_factory=lambda: ["coluna_1"])
    rows: list[list[Any]] = Field(default_factory=lambda: [[""]])


class TextInputConfig(ToolConfig):
    table: TextTable = Field(default_factory=TextTable, title="Tabela", json_schema_extra=ui(widget="grid"))


def _infer_column(values: list[Any]) -> pl.Series:
    """Converte uma coluna digitada em texto para inteiro, decimal, booleano ou texto."""
    cleaned = [None if v is None or str(v).strip() == "" else str(v).strip() for v in values]
    present = [v for v in cleaned if v is not None]
    raw = pl.Series(cleaned, dtype=pl.String)
    if not present:
        return raw
    if all(v.lower() in ("true", "false", "verdadeiro", "falso", "sim", "não", "nao") for v in present):
        truthy = raw.str.to_lowercase().is_in(["true", "verdadeiro", "sim"])
        return pl.select(pl.when(raw.is_null()).then(None).otherwise(truthy)).to_series()
    as_int = raw.cast(pl.Int64, strict=False)
    if as_int.null_count() == raw.null_count():
        return as_int
    normalized = raw.str.replace_all(r"^(-?\d+),(\d+)$", "$1.$2")
    as_float = normalized.cast(pl.Float64, strict=False)
    if as_float.null_count() == raw.null_count():
        return as_float
    return raw


@tool(
    type="io.text_input",
    name="Text Input",
    category="inout",
    icon="table",
    description="Tabela pequena digitada ou colada direto no fluxo (de-para, parâmetros, metas).",
    config=TextInputConfig,
    inputs=[],
    outputs=[Port("out", "O", "Tabela")],
    annotate=lambda c: f"{len(c.table.rows)} linha(s) × {len(c.table.columns)} coluna(s)",
)
def text_input(ctx: NodeContext, cfg: TextInputConfig) -> NodeOutput:
    columns = [c.strip() or f"coluna_{i + 1}" for i, c in enumerate(cfg.table.columns)]
    if len(set(columns)) != len(columns):
        raise ValueError("Os nomes de coluna da tabela precisam ser únicos.")
    width = len(columns)
    rows = [(list(r) + [None] * width)[:width] for r in cfg.table.rows]
    data = {name: _infer_column([r[i] for r in rows]).alias(name) for i, name in enumerate(columns)}
    return NodeOutput(tables={"out": pl.DataFrame(list(data.values()))})


# ------------------------------------------------------------------ Browse


class BrowseConfig(ToolConfig):
    notes: str = Field("", title="Anotações", json_schema_extra=ui(widget="textarea"))


@tool(
    type="io.browse",
    name="Browse",
    category="inout",
    icon="eye",
    description="Ponto de inspeção: repassa os dados sem alteração para conferir perfil e qualidade.",
    config=BrowseConfig,
)
def browse(ctx: NodeContext, cfg: BrowseConfig) -> NodeOutput:
    return NodeOutput(tables={"out": ctx.input()})


# ------------------------------------------------------------------ Output Data

ExportFormat = Literal["parquet", "csv", "excel", "json", "arrow"]
_EXTENSIONS: dict[str, str] = {
    "parquet": ".parquet",
    "csv": ".csv",
    "excel": ".xlsx",
    "json": ".json",
    "arrow": ".arrow",
}


class OutputDataConfig(ToolConfig):
    filename: str = Field("resultado", title="Nome do arquivo", description="A extensão segue o formato.")
    folder: str = Field(
        "",
        title="Pasta de destino",
        description="Vazio = pasta padrão de exportações do PRO.DATA.",
        json_schema_extra=ui(widget="folder"),
    )
    format: ExportFormat = Field(
        "excel",
        title="Formato",
        json_schema_extra=ui(
            labels={
                "parquet": "Parquet",
                "csv": "CSV (;)",
                "excel": "Excel",
                "json": "JSON",
                "arrow": "Arrow IPC",
            }
        ),
    )
    sheet_name: str = Field(
        "Dados",
        title="Nome da planilha",
        json_schema_extra=ui(show_if={"format": ["excel"]}),
    )
    # Nome da planilha de cada entrada extra (spec 021). A entrada principal usa ``sheet_name``.
    sheet_names: dict[str, str] = Field(
        default_factory=dict,
        title="Planilhas das outras entradas",
        description="No Excel, ligue mais tabelas nesta caixa: cada uma vira uma planilha do mesmo arquivo.",
        json_schema_extra=ui(widget="sheet_ports", show_if={"format": ["excel"]}),
    )
    if_exists: Literal["ask", "replace", "new_file", "add_sheet"] = Field(
        "ask",
        title="Se o arquivo já existir",
        description='"Adicionar planilha" só vale para Excel: vários Output Data podem montar um arquivo só.',
        json_schema_extra=ui(
            labels={
                "ask": "Perguntar ao executar",
                "replace": "Substituir o arquivo",
                "new_file": "Criar um novo arquivo (data e hora no nome)",
                "add_sheet": "Adicionar ou atualizar esta planilha (Excel)",
            },
        ),
    )


_BAD_SHEET_CHARS = set("[]:*?/\\")
MAX_SHEETS = 8


def sheet_title(raw: str) -> str:
    """Nome de planilha aceito pelo Excel: 1 a 31 caracteres, sem colchetes, : * ? / ou barra invertida."""
    name = raw.strip() or "Dados"
    bad = sorted(set(name) & _BAD_SHEET_CHARS)
    if bad:
        raise InvalidInputError(f"O nome da planilha não pode ter {' '.join(bad)}.")
    if len(name) > 31:
        raise InvalidInputError("O nome da planilha tem no máximo 31 caracteres.")
    return name


def write_excel_sheet(df: pl.DataFrame, path: Path, sheet: str, add: bool) -> None:
    """Grava a planilha. Com ``add`` e arquivo existente, mantém as outras planilhas (e a posição desta)."""
    if not (add and path.exists()):
        df.write_excel(path, worksheet=sheet, autofit=True)
        return
    from openpyxl import load_workbook

    try:
        book = load_workbook(path)
    except Exception as exc:  # arquivo corrompido ou que não é xlsx: mensagem acionável
        raise InvalidInputError(
            f"Não foi possível abrir {path.name} para adicionar a planilha: {exc}"
        ) from exc
    position = len(book.sheetnames)
    if sheet in book.sheetnames:
        position = book.sheetnames.index(sheet)
        del book[sheet]
    ws = book.create_sheet(sheet, position)
    ws.append(df.columns)
    for row in df.iter_rows():
        ws.append(list(row))
    for i, col in enumerate(df.columns, start=1):  # largura aproximada, como o autofit do write_excel
        sample = [len(str(v)) for v in df[col].head(200).to_list() if v is not None]
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max([len(col), *sample]) + 2)
    tmp = path.with_name(path.name + ".tmp")
    book.save(tmp)
    os.replace(tmp, path)


def _sheet_list(
    df: pl.DataFrame, extras: dict[str, pl.DataFrame], cfg: OutputDataConfig
) -> list[tuple[str, pl.DataFrame]]:
    """Planilhas do arquivo, na ordem das entradas. Nomes são conferidos antes de gravar qualquer coisa."""
    ordered = sorted(extras, key=lambda p: int(p[2:]))
    sheets = [(sheet_title(cfg.sheet_name), df)]
    sheets += [(sheet_title(cfg.sheet_names.get(p) or f"Planilha {p[2:]}"), extras[p]) for p in ordered]
    seen: set[str] = set()
    for name, _ in sheets:
        if name.casefold() in seen:  # o Excel não diferencia maiúsculas
            raise InvalidInputError(
                f'Duas planilhas com o nome "{name}": cada entrada precisa de um nome próprio.'
            )
        seen.add(name.casefold())
    return sheets


def write_excel_book(sheets: list[tuple[str, pl.DataFrame]], path: Path, add: bool) -> None:
    """Grava as planilhas. Sem ``add``, a pasta de trabalho é criada de uma vez, num arquivo temporário."""
    if add or len(sheets) == 1:
        for i, (name, table) in enumerate(sheets):
            write_excel_sheet(table, path, name, add or i > 0)
        return
    tmp = path.with_name(path.name + ".tmp.xlsx")
    with xlsxwriter.Workbook(tmp) as book:
        for name, table in sheets:
            table.write_excel(book, worksheet=name, autofit=True)
    os.replace(tmp, path)


def export_path(exports_dir: Path, cfg: OutputDataConfig) -> Path:
    stem = Path(sanitize_filename(cfg.filename or "resultado")).stem
    name = stem + _EXTENSIONS[cfg.format]
    if not cfg.folder.strip():
        return resolve_inside(exports_dir, name)
    # Pasta escolhida pelo usuário (constituição IV, exceção da spec 009): absoluta e já existente.
    folder = Path(cfg.folder.strip())
    if not folder.is_absolute():
        raise InvalidInputError("A pasta de destino precisa ser um caminho completo, como D:\\Relatorios.")
    if not folder.is_dir():
        raise InvalidInputError(f"A pasta de destino não existe: {folder}")
    return folder.resolve() / name


def new_file_path(path: Path) -> Path:
    """Mesmo nome com data e hora (e um número, se ainda assim existir): o arquivo antigo fica intacto."""
    stamp = datetime.now().strftime("%Y-%m-%d %Hh%M")
    candidate = path.with_name(f"{path.stem} {stamp}{path.suffix}")
    n = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} {stamp} ({n}){path.suffix}")
        n += 1
    return candidate


@tool(
    type="io.output_data",
    name="Output Data",
    category="inout",
    icon="download",
    description="Grava o resultado em Parquet, CSV, Excel, JSON ou Arrow, na pasta padrão ou numa pasta escolhida.",
    config=OutputDataConfig,
    inputs=[
        Port("in", "I", "Entrada"),
        *[
            Port(f"in{i}", str(i), f"Planilha {i}", required=False, when={"format": ["excel"]})
            for i in range(2, MAX_SHEETS + 1)
        ],
    ],
    annotate=lambda c: (
        f"{c.filename}{_EXTENSIONS[c.format]}" + (f" · {c.sheet_name}" if c.format == "excel" else "")
    ),
    side_effect=True,
)
def output_data(ctx: NodeContext, cfg: OutputDataConfig) -> NodeOutput:
    df = ctx.input()
    extras = {p: t for p, t in ctx.inputs.items() if p != "in"}
    if extras and cfg.format != "excel":
        raise InvalidInputError("Só o formato Excel recebe várias tabelas: cada uma vira uma planilha.")
    sheets = _sheet_list(df, extras, cfg) if cfg.format == "excel" else []
    if cfg.if_exists == "add_sheet" and cfg.format != "excel":
        raise InvalidInputError(
            '"Adicionar planilha" só vale para Excel. Escolha outra opção em "Se o arquivo já existir".'
        )
    path = export_path(ctx.exports_dir, cfg)
    existed = path.exists()
    # "Perguntar" sem ninguém para responder (ex.: execução pela API): nunca sobrescreve em silêncio (spec 017).
    if existed and cfg.if_exists in ("ask", "new_file"):
        path = new_file_path(path)
    action = (
        "criado"
        if not existed
        else {"replace": "substituído", "add_sheet": "planilha atualizada"}.get(cfg.if_exists, "novo arquivo")
    )
    match cfg.format:
        case "csv":
            df.write_csv(path, separator=";")
        case "excel":
            write_excel_book(sheets, path, cfg.if_exists == "add_sheet")
        case "json":
            df.write_json(path)
        case "arrow":
            df.write_ipc(path, compression="zstd")
        case _:
            df.write_parquet(path)
    extra: dict[str, Any] = {"exported_file": path.name, "export_action": action}
    if len(sheets) > 1:
        extra["exported_sheets"] = [name for name, _ in sheets]
    if cfg.folder.strip():
        extra["exported_path"] = str(path)
    return NodeOutput(tables={"out": df}, extra=extra)


# ------------------------------------------------------------------ Database Input


class DatabaseInputConfig(ToolConfig):
    connection: str = Field("", title="Conexão", json_schema_extra=ui(widget="connection"))
    mode: Literal["table", "query"] = Field(
        "table", title="Ler", json_schema_extra=ui(labels={"table": "Uma tabela", "query": "Consulta SQL"})
    )
    table: str = Field(
        "",
        title="Tabela",
        description="esquema.tabela",
        json_schema_extra=ui(widget="db_table", show_if={"mode": ["table"]}),
    )
    query: str = Field(
        "",
        title="Consulta",
        description="Somente SELECT/WITH: a conexão é somente leitura.",
        json_schema_extra=ui(widget="db_query", show_if={"mode": ["query"]}),
    )
    limit: int = Field(0, ge=0, title="Limite de linhas", description="0 = todas as linhas.")
    cache_results: bool = Field(
        False,
        title="Reaproveitar resultado",
        description="Desligado: o banco é consultado de novo a cada execução.",
        json_schema_extra=ui(group="Avançado"),
    )


def _database_freshness(ctx: NodeContext, cfg: DatabaseInputConfig) -> str:
    # Sem cache, um carimbo de tempo força nova consulta (o banco pode ter mudado).
    return "cached" if cfg.cache_results else f"t{time.time_ns()}"


def _database_annotation(cfg: DatabaseInputConfig) -> str:
    if cfg.mode == "table":
        return cfg.table or "Escolha uma tabela"
    return " ".join(cfg.query.split())[:50] or "Escreva a consulta"


@tool(
    type="io.database_input",
    name="Database Input",
    category="inout",
    icon="server",
    description="(Antiga) Lê uma tabela ou consulta SQL. Use o Input Data com uma consulta da aba Dados.",
    config=DatabaseInputConfig,
    inputs=[],
    outputs=[Port("out", "O", "Dados")],
    annotate=_database_annotation,
    fingerprint=_database_freshness,
    hidden=True,
)
def database_input(ctx: NodeContext, cfg: DatabaseInputConfig) -> NodeOutput:
    if ctx.connections is None:
        raise ValueError("Conexões com banco não estão disponíveis neste ambiente.")
    if not cfg.connection:
        raise ValueError("Escolha uma conexão.")
    conn = ctx.connections.get(cfg.connection)
    if cfg.mode == "table":
        if not cfg.table:
            raise ValueError("Escolha uma tabela.")
        query = sql.table_query(conn, cfg.table)
    else:
        query = cfg.query
    df = sql.read_sql(conn, ctx.connections.password(conn.id), query, limit=cfg.limit or None)
    return NodeOutput(tables={"out": df})


# ------------------------------------------------------------------ tradução para SQL (spec 020)

_READ_FUNCTIONS = {"parquet": "read_parquet", "json": "read_json", "ndjson": "read_ndjson", "arrow": "read_arrow", "excel": "read_xlsx"}  # fmt: skip
_SCHEMA_ROWS = 50
_CHUNK = 1024 * 1024
# Bytes em que CP1252 e Latin-1 diferem (€, aspas curvas, travessão...).
_CP1252_ONLY = bytes(range(0x80, 0xA0))


@lru_cache(maxsize=32)
def _latin1_is_exact(path: Path, _modified: float, _size: int) -> bool:
    """O DuckDB lê Latin-1 sem extensão. Sem os bytes em que diferem, o resultado é idêntico ao de CP1252."""
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            if len(chunk.translate(None, _CP1252_ONLY)) != len(chunk):
                return False
    return True


def _encoding(path: Path, encoding: str) -> str:
    if encoding == "cp1252":
        info = path.stat()
        return "latin-1" if _latin1_is_exact(path, info.st_mtime, info.st_size) else "cp1252"
    return encoding


_DUCK_TYPES: dict[pl.DataType | type[pl.DataType], str] = {
    pl.Int64: "BIGINT",
    pl.Float64: "DOUBLE",
    pl.String: "VARCHAR",
    pl.Boolean: "BOOLEAN",
    pl.Date: "DATE",
}


def _read_call(name: str, path: Path, opts: ReadOptions, extra: tuple[str, ...] = ()) -> str:
    """Leitura sem o caminho real do arquivo: só o nome do dataset entra no código (RF-2030)."""
    args = [lit(name)]
    if opts.format == "csv":
        args += [f"delim = {lit(opts.delimiter)}", f"header = {lit(opts.has_header)}"]
        if opts.decimal == ",":
            args.append("decimal_separator = ','")
        if opts.encoding not in ("utf-8", "utf-8-sig"):
            args.append(f"encoding = {lit(_encoding(path, opts.encoding))}")
        if opts.skip_rows:
            args.append(f"skip = {opts.skip_rows}")
        if tokens := opts.null_tokens():
            args.append("nullstr = [" + ", ".join(lit(t) for t in tokens) + "]")
        args += extra
        return f"read_csv({', '.join(args)})"
    if opts.format == "excel":
        if opts.sheet:
            args.append(f"sheet = {lit(opts.sheet)}")
        args.append(f"header = {lit(opts.has_header)}")
    return f"{_READ_FUNCTIONS[opts.format]}({', '.join(args)})"


@lru_cache(maxsize=64)
def _sniffed_types(sql: str, _modified: float, _size: int) -> tuple[tuple[str, str], ...]:
    """Tipos que o DuckDB deduz para o arquivo. Lê só o começo dele, e nada mais roda nesta conexão."""
    with duckdb.connect(":memory:") as con:
        try:
            return tuple(
                (str(r[0]), str(r[1])) for r in con.execute(f"DESCRIBE SELECT * FROM {sql}").fetchall()
            )
        except duckdb.Error:
            return ()


def _csv_extras(name: str, path: Path, opts: ReadOptions, schema: pl.Schema) -> tuple[str, ...]:
    """O que precisa ir explícito para o DuckDB ler o CSV como o motor: nomes sem cabeçalho e tipos que divergem.

    "007" é número para o motor e texto para o DuckDB; T/F é texto para o motor e booleano para o DuckDB.
    """
    extras: list[str] = []
    if not opts.has_header:
        names = [f"_pular_{i}" for i in range(opts.skip_columns)] + list(schema)
        extras.append("names = [" + ", ".join(lit(c) for c in names) + "]")
    call = _read_call(name, path, opts, tuple(extras)).replace(lit(name), lit(path.as_posix()), 1)
    info = path.stat()
    sniffed = dict(_sniffed_types(call, info.st_mtime, info.st_size))
    fixes = {
        c: _DUCK_TYPES[t]
        for c, t in schema.items()
        if c in sniffed and t in _DUCK_TYPES and kind_of(sniffed[c]) != kind_of(_DUCK_TYPES[t])
    }
    if fixes:
        extras.append("types = {" + ", ".join(f"{lit(c)}: {lit(t)}" for c, t in fixes.items()) + "}")
    return tuple(extras)


@sql_for("io.input_data")
def input_data_sql(ctx: SqlContext, cfg: InputDataConfig) -> dict[str, Fragment]:
    if not cfg.dataset:
        raise ValueError("Escolha uma fonte no campo 'Fonte'.")
    api_id = source_api_id(cfg.dataset)
    if api_id is not None:
        assert ctx.apis is not None
        return {"out": _database_source(ctx, ctx.apis.get(api_id).name, cfg.limit, "da API", "de uma API")}
    query_id = source_query_id(cfg.dataset)
    if query_id is not None:
        assert ctx.queries is not None
        return {"out": _database_source(ctx, ctx.queries.get(query_id).name, cfg.limit)}
    assert ctx.datasets is not None
    path = ctx.datasets.resolve(cfg.dataset)
    opts = resolve_options(path, cfg)
    cached = ctx.sample(OWN_RESULT)
    schema = (cached if cached is not None else read_table(path, cfg, n_rows=_SCHEMA_ROWS)).schema
    extras = _csv_extras(cfg.dataset, path, opts, schema) if opts.format == "csv" else ()
    read = _read_call(cfg.dataset, path, opts, extras)
    sql = f"SELECT * FROM {read}"
    notes = []
    if opts.skip_columns:
        sql = f"SELECT {', '.join(q(c) for c in schema)} FROM {read}"
    if cfg.limit:
        sql += f"\nLIMIT {cfg.limit}"
    if opts.format == "excel":
        notes.append(
            "A planilha é lida pela extensão do DuckDB; os tipos podem diferir da leitura do PRO.DATA."
        )
    if opts.format == "arrow":
        notes.append(
            "O DuckDB não lê Arrow sem uma extensão adicional: prefira converter a fonte para Parquet."
        )
    lower = [c.lower() for c in schema]
    if len(set(lower)) != len(lower):
        notes.append(
            "Há colunas que só diferem em maiúsculas: o DuckDB não as distingue, então renomeie uma delas."
        )
    return {"out": Fragment(sql, f"Lê {cfg.dataset}", notes, source=SourceInfo(cfg.dataset, path, schema))}


def _database_source(
    ctx: SqlContext, name: str, limit: int, reading: str = "do banco", origin: str = "do banco de origem"
) -> Fragment:
    """Fonte de banco: o SQL original é do banco, não do DuckDB, então a etapa aponta para uma tabela."""
    table = slug(name)
    cached = ctx.sample(OWN_RESULT)
    if cached is None:
        raise ValueError(f"Execute o fluxo para ler as colunas desta fonte {reading}.")
    sql = f"SELECT * FROM {q(table)}" + (f"\nLIMIT {limit}" if limit else "")
    note = f'A fonte "{name}" é {origin}: crie a tabela {table} com ela, ou troque pelo nome da tabela no destino.'
    return Fragment(
        sql, f"Lê {name}, {reading}", [note], source=SourceInfo(table, None, cached.schema, file_check=False)
    )


@sql_for("io.database_input")
def database_input_sql(ctx: SqlContext, cfg: DatabaseInputConfig) -> dict[str, Fragment]:
    return {
        "out": _database_source(
            ctx, cfg.table if cfg.mode == "table" and cfg.table else "consulta do banco", cfg.limit
        )
    }


@sql_for("io.text_input")
def text_input_sql(ctx: SqlContext, cfg: TextInputConfig) -> dict[str, Fragment]:
    df = text_input(None, cfg).tables["out"]  # type: ignore[arg-type]  # não usa o contexto
    types: dict[pl.DataType | type[pl.DataType], str] = {
        pl.Int64: "BIGINT",
        pl.Float64: "DOUBLE",
        pl.Boolean: "BOOLEAN",
    }
    casts = [types.get(t, "VARCHAR") for t in df.dtypes]
    rows = [
        # A primeira linha fixa os tipos: uma coluna só com vazios não pode virar outra coisa.
        "("
        + ", ".join(f"CAST({lit(v)} AS {c})" if i == 0 else lit(v) for v, c in zip(row, casts, strict=True))
        + ")"
        for i, row in enumerate(df.rows())
    ]
    names = ", ".join(q(c) for c in df.columns)
    sql = (
        f"SELECT *\nFROM (VALUES\n  {join_list(rows)}\n) AS t({names})"
        if rows
        else f"SELECT {', '.join(f'NULL AS {q(c)}' for c in df.columns)} WHERE FALSE"
    )
    warning = "Esta etapa leva para o código os dados digitados na tabela."
    return {
        "out": Fragment(sql, f"Tabela digitada com {df.height} linha(s)", [warning], data_warning=warning)
    }


@sql_for("io.browse")
def browse_sql(ctx: SqlContext, cfg: BrowseConfig) -> dict[str, Fragment]:
    return {"out": Fragment(f"SELECT * FROM {q(ctx.input().block)}", "Só repassa os dados, para inspeção")}


@sql_for("io.output_data")
def output_data_sql(ctx: SqlContext, cfg: OutputDataConfig) -> dict[str, Fragment]:
    file = f"{cfg.filename}{_EXTENSIONS[cfg.format]}"
    extras = sorted((p for p in ctx.inputs if p != "in"), key=lambda p: int(p[2:]))
    notes = []
    if extras:
        names = ", ".join(ctx.inputs[p].block for p in extras)
        notes.append(
            f"O arquivo tem {len(extras) + 1} planilhas: este código é o da primeira. As demais vêm de {names}."
        )
    sql = f"SELECT * FROM {q(ctx.input().block)}"
    explain = f"Grava {file}" + (f", com {len(extras) + 1} planilhas" if extras else "")
    return {"out": Fragment(sql, explain, notes, export_file=file)}
