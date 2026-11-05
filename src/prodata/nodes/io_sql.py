"""Tradução para SQL das caixas de entrada e saída (spec 020)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import polars as pl

from prodata.connectors.api_model import source_api_id
from prodata.connectors.queries import source_query_id
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
from prodata.ingestion.options import ReadOptions
from prodata.ingestion.readers import read_table, resolve_options
from prodata.nodes.io import (
    _EXTENSIONS,
    BrowseConfig,
    DatabaseInputConfig,
    InputDataConfig,
    OutputDataConfig,
    TextInputConfig,
    text_input,
)

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
