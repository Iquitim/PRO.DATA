"""Ferramentas de entrada e saída."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.connectors import jira_read, sql
from prodata.connectors.api import read_api
from prodata.connectors.api_loop import run_loop
from prodata.connectors.api_model import source_api_id
from prodata.connectors.jira_model import source_jira_id
from prodata.connectors.queries import read_definition, source_query_id
from prodata.domain.labels import (
    DEFAULT_LABEL,
    LABEL_NAMES,
    Confidentiality,
    needs_protection,
)
from prodata.engine import constants as constants_engine
from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.ingestion.datasets import resolve_inside, sanitize_filename
from prodata.ingestion.options import ReadOptions
from prodata.ingestion.readers import read_table
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool
from prodata.nodes.excel_output import (
    MAX_SHEETS,
    _sheet_list,
    write_excel_book,
)
from prodata.services.audit import log_export

# ------------------------------------------------------------------ Input Data


JIRA_FULL_DAYS = 30


class InputDataConfig(ReadOptions, ToolConfig):
    dataset: str = Field(
        "",
        title="Fonte",
        description="Arquivo, consulta de banco ou API cadastrados na vista Dados. APIs com variável, como {sigla}, ficam no API Loop.",
        json_schema_extra=ui(widget="dataset"),
    )
    limit: int = Field(0, ge=0, title="Limite de linhas", description="0 = todas as linhas.")


def _source_signature(ctx: NodeContext, cfg: InputDataConfig) -> str:
    if not cfg.dataset:
        return ""
    jira_id = source_jira_id(cfg.dataset)
    if jira_id is not None:
        # Cada execução pergunta ao Jira o que mudou: o guardado local evita refazer a carga inteira.
        return "" if ctx.jira is None else f"j{ctx.jira.query(jira_id).digest()}t{time.time_ns()}"
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
    if source_jira_id(cfg.dataset):
        return "Jira"
    if source_api_id(cfg.dataset):
        return "API"
    return "Consulta de banco" if source_query_id(cfg.dataset) else cfg.dataset


def _source_on_request(ctx: NodeContext, cfg: InputDataConfig) -> str | None:
    """Um POST pode gravar do outro lado: não roda só porque o fluxo foi aberto."""
    if source_jira_id(cfg.dataset):
        return "Esta caixa só busca no Jira quando você clica em Executar."
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
    description="Lê qualquer fonte cadastrada na vista Dados: arquivos (CSV, Excel, Parquet, JSON, Arrow), consultas de banco ou APIs.",
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
    if source_jira_id(cfg.dataset) is not None:
        return _read_jira(ctx, cfg)
    api_id = source_api_id(cfg.dataset)
    if api_id is not None:
        if ctx.apis is None:
            raise ValueError("APIs não estão disponíveis neste ambiente.")
        api = _with_constants(ctx.apis.get(api_id), ctx)
        frame, result = read_api(api, ctx.apis.secret_reader(api.id))
        extra: dict[str, Any] = {"source": api.name, "source_read_at": _now(), "api_pages": result.pages}
        if result.truncated:
            extra["warnings"] = [
                f"Parou no limite de {result.pages} páginas e ainda havia mais: aumente o limite na vista Dados."
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


def _read_jira(ctx: NodeContext, cfg: InputDataConfig) -> NodeOutput:
    if ctx.jira is None:
        raise ValueError("O Jira não está disponível neste ambiente.")
    query = ctx.jira.query(source_jira_id(cfg.dataset))
    frame, info = jira_read.load(query, ctx.jira, report=ctx.report)
    extra: dict[str, Any] = {
        "source": query.name,
        "source_read_at": _now(),
        "jira_calls": info["calls"],
        "jira_incremental": info["incremental"],
    }
    full_at = info.get("full_at")
    if full_at and datetime.now(UTC) - datetime.fromisoformat(full_at) > timedelta(days=JIRA_FULL_DAYS):
        extra["warnings"] = [
            f"A última releitura completa foi há mais de {JIRA_FULL_DAYS} dias: o que foi excluído no Jira ainda aparece aqui. Faça a releitura na vista Dados."
        ]
    return NodeOutput(tables={"out": frame.head(cfg.limit) if cfg.limit else frame}, extra=extra)


def _with_constants(api: Any, ctx: NodeContext) -> Any:
    """Constantes no endereço e nos parâmetros fixos da API (spec 028): entram com o valor de agora."""
    if not ctx.constants:
        return api
    fill = lambda text: constants_engine.fill_text(text, ctx.constants)  # noqa: E731
    return api.model_copy(
        update={
            "url": fill(api.url),
            "params": [p if p.secret else p.model_copy(update={"value": fill(p.value)}) for p in api.params],
            "headers": [
                h if h.secret else h.model_copy(update={"value": fill(h.value)}) for h in api.headers
            ],
        }
    )


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
        title="Limite de pedidos à API",
        description="Conta todos os pedidos, com páginas e novas tentativas. Ao chegar aqui, a caixa para, e o que faltou sai em E.",
    )
    stop_after_failures: int = Field(
        10,
        ge=0,
        le=100_000,
        title="Parar depois de quantas falhas seguidas",
        description="Evita insistir numa API fora do ar ou com credencial errada. 0 = não para.",
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
    api = _with_constants(ctx.apis.get(cfg.source), ctx)
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
        stop_after_failures=cfg.stop_after_failures,
        progress=lambda done, total: ctx.report(f"{done}/{total} chamadas"),
    )
    warnings = []
    if result.failed:
        warnings.append(f"{result.failed} de {result.calls} chamadas falharam: veja a saída E.")
    if result.truncated:
        warnings.append(f"{result.truncated} chamadas pararam no limite de páginas da API.")
    if result.stopped:
        warnings.insert(0, f"Parou antes do fim: {result.stopped}")
    extra: dict[str, Any] = {
        "api_calls": result.calls,
        "api_failed": result.failed,
        "api_requests": result.requests,
    }
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
    confidentiality: Confidentiality = Field(
        DEFAULT_LABEL,
        title="Rótulo de confidencialidade",
        description=(
            "No Excel, fica nas propriedades do arquivo, na impressão e na cor da aba. "
            "Nos outros formatos, Confidencial e Restrito entram no nome do arquivo."
        ),
        json_schema_extra=ui(widget="confidentiality", labels=LABEL_NAMES),
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


def export_path(exports_dir: Path, cfg: OutputDataConfig) -> Path:
    stem = Path(sanitize_filename(cfg.filename or "resultado")).stem
    # Fora do Excel, o arquivo não tem onde guardar o rótulo: ele vai no nome.
    if cfg.format != "excel" and needs_protection(cfg.confidentiality):
        stem += f"_{cfg.confidentiality.upper()}"
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
        f"{c.filename}{_EXTENSIONS[c.format]}"
        + (f" · {c.sheet_name}" if c.format == "excel" else "")
        + (f" · {LABEL_NAMES[c.confidentiality]}" if needs_protection(c.confidentiality) else "")
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
            write_excel_book(sheets, path, cfg.if_exists == "add_sheet", cfg.confidentiality)
        case "json":
            df.write_json(path)
        case "arrow":
            df.write_ipc(path, compression="zstd")
        case _:
            df.write_parquet(path)
    extra: dict[str, Any] = {
        "exported_file": path.name,
        "export_action": action,
        "confidentiality": cfg.confidentiality,
    }
    tables = [t for _, t in sheets] or [df]
    log_export(
        f"Output Data ({cfg.format})",
        path.name,
        LABEL_NAMES[cfg.confidentiality],
        sum(t.height for t in tables),
        max(t.width for t in tables),
    )
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
    description="(Antiga) Lê uma tabela ou consulta SQL. Use o Input Data com uma consulta da vista Dados.",
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
