"""Conferência do SQL com o motor (RF-2019 a RF-2024).

Por etapa: roda o SQL com as entradas já calculadas e compara com a saída da caixa. De ponta a ponta: roda o caminho a
partir das fontes em arquivo. Nunca consulta banco nem grava nada: a conexão só pode ler os arquivos de origem.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from typing import Any

import duckdb
import polars as pl

from prodata.engine.sql.fragment import SourceInfo, arrow_safe, lit
from prodata.engine.sql.macros import install_all
from prodata.engine.sql.plan import OK, Env, Output, SqlPlan

# Acima disso a comparação ficaria lenta demais para uma conferência em segundo plano.
MAX_ROWS = 2_000_000
DECIMALS = 6
EXAMPLES = 3

SAME = "same"
DIFFERENT = "different"
UNCHECKED = "unchecked"
SKIPPED = "skipped"


@dataclass
class BlockCheck:
    state: str
    detail: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Verification:
    blocks: dict[str, BlockCheck] = field(default_factory=dict)
    outputs: dict[str, BlockCheck] = field(default_factory=dict)
    # Fontes cuja leitura não foi conferida a partir do arquivo.
    unchecked_sources: dict[str, str] = field(default_factory=dict)


class CancelledError(Exception):
    pass


def _family(dtype: pl.DataType) -> str:
    if dtype.is_numeric():
        return "número"
    if dtype == pl.String:
        return "texto"
    if dtype == pl.Boolean:
        return "booleano"
    if dtype == pl.Date:
        return "data"
    if isinstance(dtype, pl.Datetime):
        return "data e hora"
    return str(dtype)


def _normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Forma comparável: números como decimal arredondado, datas com a mesma resolução, o resto como texto."""
    exprs = []
    for name, dtype in df.schema.items():
        col = pl.col(name)
        if dtype.is_numeric():
            exprs.append(col.cast(pl.Float64, strict=False).round(DECIMALS).alias(name))
        elif isinstance(dtype, pl.Datetime):
            exprs.append(
                col.cast(pl.Datetime("us"), strict=False)
                .dt.replace_time_zone(None)
                .cast(pl.String)
                .alias(name)
            )
        else:
            exprs.append(col.cast(pl.String, strict=False).alias(name))
    return df.select(exprs)


def compare(sql: pl.DataFrame, engine: pl.DataFrame, ordered_by: list[str] | None = None) -> BlockCheck:
    """Mesmas colunas, tipos compatíveis e o mesmo conjunto de linhas, com repetições (RF-2022)."""
    if sql.columns != engine.columns:
        only_sql = [c for c in sql.columns if c not in engine.columns]
        only_engine = [c for c in engine.columns if c not in sql.columns]
        parts = []
        if only_sql:
            parts.append("a mais no SQL: " + ", ".join(only_sql))
        if only_engine:
            parts.append("faltando no SQL: " + ", ".join(only_engine))
        return BlockCheck(
            DIFFERENT, "Colunas diferentes" + (f" ({'; '.join(parts)})" if parts else " (ordem)")
        )
    wrong = [
        f"{c} ({_family(a)} no SQL, {_family(b)} no fluxo)"
        for c, a, b in zip(sql.columns, sql.dtypes, engine.dtypes, strict=True)
        if _family(a) != _family(b)
    ]
    if wrong:
        return BlockCheck(DIFFERENT, "Tipos diferentes: " + ", ".join(wrong))
    a, b = _normalize(sql), _normalize(engine)
    if not a.columns:
        return BlockCheck(SAME)
    key = "__repeticao"
    with_key = [d.with_columns(pl.int_range(pl.len()).over(pl.struct(a.columns)).alias(key)) for d in (a, b)]
    on = [*a.columns, key]
    only_sql_rows = with_key[0].join(with_key[1], on=on, how="anti", nulls_equal=True)
    only_engine_rows = with_key[1].join(with_key[0], on=on, how="anti", nulls_equal=True)
    if only_sql_rows.height or only_engine_rows.height:
        examples = [
            {"lado": side, **{k: None if v is None else str(v) for k, v in row.items()}}
            for side, table in (("SQL", only_sql_rows), ("fluxo", only_engine_rows))
            for row in table.drop(key).head(EXAMPLES).rows(named=True)
        ]
        return BlockCheck(
            DIFFERENT,
            f"{only_sql_rows.height} linha(s) só no SQL e {only_engine_rows.height} só no fluxo",
            examples,
        )
    if ordered_by and not a.select(ordered_by).equals(b.select(ordered_by)):
        return BlockCheck(DIFFERENT, "As linhas são as mesmas, mas a ordem é diferente")
    return BlockCheck(SAME)


def _connection(files: list[str] | None = None) -> duckdb.DuckDBPyConnection:
    """Conexão em memória que só lê os arquivos indicados e não grava em lugar nenhum (RF-2032)."""
    con = duckdb.connect(":memory:")
    install_all(con)
    # Sem acesso externo não há carga automática: as extensões de leitura entram antes, se estiverem disponíveis.
    for extension in ("excel", "encodings"):
        with contextlib.suppress(duckdb.Error):
            con.execute(f"LOAD {extension}")
    if files:
        con.execute("SET allowed_paths = [" + ", ".join(lit(f) for f in files) + "]")
    con.execute("SET enable_external_access = false")
    return con


def _input_tables(plan: SqlPlan, env: Env, block_id: str) -> dict[str, pl.DataFrame] | None:
    tables = {}
    for dep in plan.blocks[block_id].deps:
        upstream = plan.blocks[dep]
        table = (
            env.cache.table(plan.workflow.id, upstream.node_id, upstream.port)
            if env.fresh(upstream.node_id)
            else None
        )
        if table is None:
            return None
        tables[upstream.name] = table
    return tables


def _check_block(plan: SqlPlan, env: Env, block_id: str, con: duckdb.DuckDBPyConnection) -> BlockCheck:
    block = plan.blocks[block_id]
    fragment = block.fragment
    if fragment is None:
        return BlockCheck(SKIPPED, block.reason)
    if not env.fresh(block.node_id):
        return BlockCheck(UNCHECKED, "Execute o fluxo: o resultado guardado é de antes da última alteração.")
    if not fragment.comparable:
        return BlockCheck(SKIPPED, "Amostra aleatória não é comparável.")
    if fragment.source is not None:
        return BlockCheck(SKIPPED, "Fonte: conferida na verificação de ponta a ponta.")
    expected = env.cache.table(plan.workflow.id, block.node_id, block.port)
    inputs = _input_tables(plan, env, block_id)
    if expected is None or inputs is None:
        return BlockCheck(UNCHECKED, "Execute o fluxo para conferir esta etapa.")
    if expected.height > MAX_ROWS or any(t.height > MAX_ROWS for t in inputs.values()):
        return BlockCheck(UNCHECKED, "Não conferido: tabela grande demais.")
    try:
        for name, table in inputs.items():
            con.register(name, arrow_safe(table))
        result = con.sql(fragment.sql).pl()
    except duckdb.PermissionException:
        return BlockCheck(UNCHECKED, "Não conferido: a consulta lê arquivos por conta própria.")
    except duckdb.Error as exc:
        return BlockCheck(DIFFERENT, "O SQL não executou: " + str(exc).split("\n")[0])
    finally:
        for name in inputs:
            con.unregister(name)
    return compare(result, expected, fragment.ordered_by)


def _without_path(message: str, source: SourceInfo) -> str:
    """Mensagem do DuckDB sem o caminho real do arquivo (RF-2030)."""
    assert source.path is not None
    return message.replace(source.path.as_posix(), source.display).replace(str(source.path), source.display)


def _check_end_to_end(plan: SqlPlan, env: Env, verification: Verification, cancel: threading.Event) -> None:
    """Roda todo o caminho a partir das fontes. Uma fonte que não dá para ler entra pelo resultado guardado."""
    blocks = [b for b in plan.blocks.values() if b.status == OK and b.fragment]
    files = [
        str(b.fragment.source.path)
        for b in blocks
        if b.fragment and b.fragment.source and b.fragment.source.path
    ]
    con = _connection([f.replace("\\", "/") for f in files] + files)
    try:
        ready: set[str] = set()
        for block in blocks:
            if cancel.is_set():
                raise CancelledError
            fragment = block.fragment
            assert fragment is not None
            if any(d not in ready for d in block.deps):
                continue
            source = fragment.source
            try:
                if source is not None and (source.path is None or not source.file_check):
                    raise duckdb.Error("Fonte de banco")
                sql = fragment.sql
                if source is not None and source.path is not None:
                    sql = sql.replace(lit(source.display), lit(source.path.as_posix()))
                con.execute(f'CREATE OR REPLACE TEMP VIEW "{block.name}" AS {sql}')
                if source is not None:
                    con.execute(f'SELECT * FROM "{block.name}" LIMIT 0')
                ready.add(block.id)
            except duckdb.Error as exc:
                if source is None:
                    continue
                table = (
                    env.cache.table(plan.workflow.id, block.node_id, block.port)
                    if env.fresh(block.node_id)
                    else None
                )
                if table is None:
                    continue
                con.register(block.name, arrow_safe(table))
                ready.add(block.id)
                verification.unchecked_sources[block.id] = (
                    "consulta de banco não é relida na conferência"
                    if source.path is None
                    else "leitura não conferida: " + _without_path(str(exc).split("\n")[0], source)
                )
        for output in plan.outputs:
            if cancel.is_set():
                raise CancelledError
            verification.outputs[output.id] = _check_output(plan, env, con, output, ready)
    finally:
        con.close()


def _check_output(
    plan: SqlPlan, env: Env, con: duckdb.DuckDBPyConnection, output: Output, ready: set[str]
) -> BlockCheck:
    tail = plan.tail(output)
    if tail is None or output.stop is not None or tail.id not in ready:
        return BlockCheck(SKIPPED, "Caminho interrompido antes da saída.")
    fragments = [plan.blocks[s].fragment for s in plan.ok_steps(output)]
    if not all(f is not None and f.comparable for f in fragments):
        return BlockCheck(SKIPPED, "O caminho tem amostra aleatória.")
    expected = env.cache.table(plan.workflow.id, tail.node_id, tail.port) if env.fresh(tail.node_id) else None
    if expected is None:
        return BlockCheck(UNCHECKED, "Execute o fluxo para conferir esta saída.")
    if expected.height > MAX_ROWS:
        return BlockCheck(UNCHECKED, "Não conferido: tabela grande demais.")
    fragment = tail.fragment
    try:
        result = con.sql(f'SELECT * FROM "{tail.name}"').pl()
        if fragment is not None and fragment.visual_sql:
            con.execute(fragment.visual_sql).fetchall()  # não é comparada com o gráfico, mas precisa rodar
    except duckdb.PermissionException:
        return BlockCheck(UNCHECKED, "Não conferido: a consulta lê arquivos por conta própria.")
    except duckdb.Error as exc:
        return BlockCheck(DIFFERENT, "O código da saída não executou: " + str(exc).split("\n")[0])
    return compare(result, expected, fragment.ordered_by if fragment else None)


def verify(plan: SqlPlan, env: Env, cancel: threading.Event | None = None) -> Verification:
    cancel = cancel or threading.Event()
    verification = Verification()
    # Uma conexão para todas as etapas: criar as macros a cada etapa custava mais que a própria comparação.
    con = _connection()
    try:
        for block_id, block in plan.blocks.items():
            if cancel.is_set():
                raise CancelledError
            if block.status == OK:
                verification.blocks[block_id] = _check_block(plan, env, block_id, con)
    finally:
        con.close()
    _check_end_to_end(plan, env, verification, cancel)
    return verification


# ---------------------------------------------------------------- estado único da saída (RF-2019)

READY = "ready"
READY_NOTES = "ready_notes"
PARTIAL = "partial"
MISMATCH = "mismatch"
PENDING = "pending"

STATE_LABELS = {
    READY: "Conferido",
    READY_NOTES: "Conferido, com ressalvas",
    PARTIAL: "Parcial",
    MISMATCH: "Não bate",
    PENDING: "Ainda não conferido",
}


def output_state(plan: SqlPlan, output: Output, verification: Verification | None) -> dict[str, Any]:
    """O que mostrar para a saída: um estado só, os motivos e as contagens."""
    steps = plan.ok_steps(output)
    notes: list[str] = []
    for step in steps:
        fragment = plan.blocks[step].fragment
        for note in fragment.notes if fragment else []:
            if note not in notes:
                notes.append(note)
    if output.stop is not None:
        return {
            "state": PARTIAL,
            "label": STATE_LABELS[PARTIAL],
            "stop": output.stop,
            "notes": notes,
            "checked": 0,
            "total": 0,
        }
    if verification is None:
        return {"state": PENDING, "label": STATE_LABELS[PENDING], "notes": notes, "checked": 0, "total": 0}
    checks = [verification.blocks[s] for s in steps if s in verification.blocks]
    comparable = [c for c in checks if c.state != SKIPPED]
    same = sum(1 for c in comparable if c.state == SAME)
    end = verification.outputs.get(output.id)
    base = {"notes": notes, "checked": same, "total": len(comparable)}
    problems = [c for c in checks if c.state == DIFFERENT]
    if end is not None and end.state == DIFFERENT:
        problems.append(end)
    if problems:
        return {
            "state": MISMATCH,
            "label": STATE_LABELS[MISMATCH],
            "detail": problems[0].detail,
            "examples": problems[0].examples,
            **base,
        }
    if any(c.state == UNCHECKED for c in comparable) or end is None or end.state == UNCHECKED:
        detail = next((c.detail for c in comparable if c.state == UNCHECKED), end.detail if end else "")
        return {"state": PENDING, "label": STATE_LABELS[PENDING], "detail": detail, **base}
    for step in steps:
        if step in verification.unchecked_sources:
            notes.append(f"{plan.blocks[step].name}: {verification.unchecked_sources[step]}.")
    if end.state == SKIPPED:
        notes.append(end.detail)
    if notes:
        return {"state": READY_NOTES, "label": STATE_LABELS[READY_NOTES], **base}
    return {"state": READY, "label": STATE_LABELS[READY], **base}
