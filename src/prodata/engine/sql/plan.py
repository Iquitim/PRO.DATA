"""Do fluxo aos blocos: caminho por porta, saídas e nomes estáveis (spec 020).

Só lê a configuração. Nada aqui executa o fluxo; o esquema de cada bloco vem de um ``DESCRIBE`` feito sobre tabelas
vazias, o que permite acompanhar a edição (RF-2008).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import duckdb
import polars as pl
from pydantic import ValidationError

from prodata.connectors.api import ApiStore
from prodata.connectors.queries import QueryStore
from prodata.domain.workflow import Workflow
from prodata.engine import graph
from prodata.engine.cache import ResultCache
from prodata.engine.formula import FormulaError
from prodata.engine.sql.fragment import (
    OWN_RESULT,
    SQL_REGISTRY,
    Fragment,
    NoTranslationError,
    NotReadyError,
    SqlContext,
    SqlInput,
    arrow_safe,
    kind_of,
    q,
    single_select,
    slug,
)
from prodata.engine.sql.macros import macro_cursor
from prodata.errors import ProdataError
from prodata.ingestion.datasets import DatasetStore
from prodata.nodes import REGISTRY

OK = "ok"
NO_SQL = "no_sql"
ERROR = "error"
DISABLED = "disabled"
NOT_READY = "not_ready"
BLOCKED = "blocked"

VISUAL_TYPES = frozenset({"bi.chart", "bi.kpi_card", "bi.table", "bi.venn"})
OUTPUT_TYPE = "io.output_data"


@dataclass
class Env:
    cache: ResultCache
    datasets: DatasetStore | None = None
    queries: QueryStore | None = None
    # O resultado guardado ainda corresponde à configuração atual da caixa?
    fresh: Callable[[str], bool] = lambda _node: False
    apis: ApiStore | None = None


@dataclass
class Block:
    id: str
    node_id: str
    port: str
    name: str
    status: str = OK
    reason: str = ""
    fragment: Fragment | None = None
    deps: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: int | None = None

    @property
    def sql(self) -> str:
        return self.fragment.sql if self.fragment else ""


@dataclass
class Output:
    id: str
    node_id: str
    port: str
    name: str
    kind: str  # "table" | "visual"
    steps: list[str]  # todos os blocos do caminho, em ordem
    stop: str | None = None  # primeiro bloco do caminho que impede o SQL
    temporary: bool = False


@dataclass
class SqlPlan:
    workflow: Workflow
    blocks: dict[str, Block]
    outputs: list[Output]

    def output(self, output_id: str) -> Output | None:
        return next((o for o in self.outputs if o.id == output_id), None)

    def ok_steps(self, output: Output) -> list[str]:
        return [b for b in output.steps if self.blocks[b].status == OK]

    def tail(self, output: Output) -> Block | None:
        """Bloco do qual sai a tabela: a própria saída ou, se o caminho para, o último que dá para rodar."""
        final = self.blocks[f"{output.node_id}|{output.port}"]
        if final.status == OK:
            return final
        steps = self.ok_steps(output)
        return self.blocks[steps[-1]] if steps else None


def block_id(node_id: str, port: str) -> str:
    return f"{node_id}|{port}"


def _names(workflow: Workflow) -> dict[str, str]:
    """Nomes por caixa, na ordem do arquivo: editar uma caixa não renomeia as outras (RF-2007)."""
    used: dict[str, int] = {}
    names: dict[str, str] = {}
    for node in workflow.nodes:
        spec = REGISTRY.get(node.type)
        base = slug(node.label or (spec.name if spec else node.type))
        used[base] = used.get(base, 0) + 1
        names[node.id] = base if used[base] == 1 else f"{base}_{used[base]}"
    return names


def _ports(workflow: Workflow, node_id: str, node_type: str) -> list[tuple[str, str]]:
    spec = REGISTRY.get(node_type)
    if spec:
        return [(p.id, p.kind) for p in spec.outputs]
    handles = {e.source_handle for e in workflow.edges if e.source == node_id}
    return [(h, "data") for h in sorted(handles)] or [("out", "data")]


def _sample(env: Env, workflow: Workflow, node_id: str) -> Callable[[str], pl.DataFrame | None]:
    def read(port: str) -> pl.DataFrame | None:
        if port == OWN_RESULT:
            if not env.fresh(node_id):
                return None
            entry = env.cache.get(workflow.id, node_id)
            return next(iter(entry.tables.values()), None) if entry else None
        for e in workflow.edges:
            if e.target == node_id and e.target_handle == port and env.fresh(e.source):
                return env.cache.table(workflow.id, e.source, e.source_handle)
        return None

    return read


def _translate(
    workflow: Workflow, node_id: str, env: Env, inputs: dict[str, SqlInput]
) -> tuple[str, str, dict[str, Fragment]]:
    node = workflow.node(node_id)
    spec = REGISTRY.get(node.type)
    translator = SQL_REGISTRY.get(node.type)
    if spec is None:
        return NO_SQL, f"Ferramenta desconhecida: {node.type}", {}
    if translator is None:
        return NO_SQL, f"{spec.name} não tem equivalente em SQL.", {}
    try:
        cfg = spec.config.model_validate(node.config)
        ctx = SqlContext(inputs, env.datasets, env.queries, _sample(env, workflow, node_id), env.apis)
        return OK, "", translator(ctx, cfg)
    except NoTranslationError as exc:
        return NO_SQL, str(exc), {}
    except NotReadyError as exc:
        return NOT_READY, str(exc), {}
    except ValidationError as exc:
        return ERROR, str(exc.errors()[0]["msg"]), {}
    except (ValueError, FormulaError, ProdataError, OSError) as exc:
        return ERROR, str(exc), {}


def _describe(con: duckdb.DuckDBPyConnection, block: Block) -> None:
    """Cria a visão do bloco e lê as colunas. Fonte em arquivo vira tabela vazia com o esquema do motor."""
    fragment = block.fragment
    assert fragment is not None
    if fragment.source is not None and fragment.source.schema is not None:
        con.register(block.name, arrow_safe(pl.DataFrame(schema=fragment.source.schema)))
    else:
        # Gerar o código nunca executa nada: só uma consulta entra aqui (RF-2002, RF-2032).
        if not single_select(con, fragment.sql):
            raise ValueError("Esta caixa tem mais de um comando SQL: só uma consulta pode entrar no código.")
        con.execute(f"CREATE OR REPLACE TEMP VIEW {q(block.name)} AS {fragment.sql}")
    if fragment.visual_sql:
        con.execute(f"DESCRIBE {fragment.visual_sql}")


def _schema(con: duckdb.DuckDBPyConnection, name: str) -> tuple[list[str], dict[str, str]]:
    rows = con.execute(f"DESCRIBE {q(name)}").fetchall()
    return [str(r[0]) for r in rows], {str(r[0]): kind_of(str(r[1])) for r in rows}


def build_plan(workflow: Workflow, env: Env) -> SqlPlan:
    order = graph.reading_order(workflow)
    names = _names(workflow)
    blocks: dict[str, Block] = {}
    schemas: dict[str, SqlInput] = {}
    con = macro_cursor()
    try:
        for node_id in order:
            node = workflow.node(node_id)
            incoming = [e for e in workflow.edges if e.target == node_id]
            deps = [block_id(e.source, e.source_handle) for e in incoming]
            ports = _ports(workflow, node_id, node.type)
            status, reason, fragments = _node_status(workflow, node_id, env, incoming, blocks, schemas)
            for port, kind in ports:
                name = names[node_id] if len(ports) == 1 else f"{names[node_id]}__{slug(port)}"
                block = Block(block_id(node_id, port), node_id, port, name, status, reason, deps=deps)
                if status == OK and kind == "model":
                    block.status, block.reason = NO_SQL, "Modelo de ML não tem equivalente em SQL."
                elif status == OK:
                    block.fragment = fragments.get(port)
                    if block.fragment is None:
                        block.status, block.reason = NO_SQL, "Esta saída não tem equivalente em SQL."
                    else:
                        _attach(con, block, env, workflow, schemas)
                blocks[block.id] = block
    finally:
        con.close()
    return SqlPlan(workflow, blocks, _outputs(workflow, blocks, names, order))


def _node_status(
    workflow: Workflow,
    node_id: str,
    env: Env,
    incoming: list,
    blocks: dict[str, Block],
    schemas: dict[str, SqlInput],
) -> tuple[str, str, dict[str, Fragment]]:
    node = workflow.node(node_id)
    # Sem tradução é sempre sem tradução, mesmo atrás de outra caixa que também não tem (RF-2033).
    if node.type not in SQL_REGISTRY:
        return _translate(workflow, node_id, env, {})
    if node.disabled:
        return DISABLED, "Caixa desligada.", {}
    for edge in incoming:
        upstream = blocks.get(block_id(edge.source, edge.source_handle))
        if upstream is not None and upstream.status != OK:
            return BLOCKED, f"Depende de uma etapa sem SQL: {upstream.name}.", {}
    inputs = {
        e.target_handle: schemas[block_id(e.source, e.source_handle)]
        for e in incoming
        if block_id(e.source, e.source_handle) in schemas
    }
    return _translate(workflow, node_id, env, inputs)


def _attach(
    con: duckdb.DuckDBPyConnection, block: Block, env: Env, workflow: Workflow, schemas: dict[str, SqlInput]
) -> None:
    try:
        _describe(con, block)
        columns, kinds = _schema(con, block.name)
    except (duckdb.Error, ValueError) as exc:
        block.status = ERROR
        block.reason = str(exc).split("\n")[0]
        block.fragment = None
        return
    block.columns = columns
    schemas[block.id] = SqlInput(block.name, columns, kinds)
    if env.fresh(block.node_id):
        table = env.cache.table(workflow.id, block.node_id, block.port)
        block.rows = table.height if table is not None else None


def _path(workflow: Workflow, block: str, blocks: dict[str, Block], order: list[str]) -> list[str]:
    """Blocos necessários para uma saída, por porta: L e R ficam de fora se só o J é usado (RF-2004)."""
    seen: set[str] = set()
    stack = [block]
    while stack:
        current = stack.pop()
        if current in seen or current not in blocks:
            continue
        seen.add(current)
        stack.extend(blocks[current].deps)
    position = {n: i for i, n in enumerate(order)}
    return sorted(seen, key=lambda b: (position[blocks[b].node_id], b))


def _stop(steps: list[str], blocks: dict[str, Block]) -> str | None:
    """A primeira causa real no caminho. Quem só depende dela (bloqueado) não é a causa."""
    return next((s for s in steps if blocks[s].status not in (OK, BLOCKED)), None)


def _outputs(
    workflow: Workflow, blocks: dict[str, Block], names: dict[str, str], order: list[str]
) -> list[Output]:
    has_child = {e.source for e in workflow.edges}
    found: list[Output] = []
    for node_id in order:
        node = workflow.node(node_id)
        spec = REGISTRY.get(node.type)
        label = node.label or (spec.name if spec else node.type)
        for port, kind in _ports(workflow, node_id, node.type):
            if kind == "model":
                continue
            bid = block_id(node_id, port)
            is_visual = node.type in VISUAL_TYPES
            # Saída solta de uma caixa com outra saída conectada não entra (ex.: L e R de um Join que só usa o J).
            if not (node.type == OUTPUT_TYPE or is_visual or node_id not in has_child):
                continue
            ports = _ports(workflow, node_id, node.type)
            data_ports = [p for p, k in ports if k == "data"]
            name = label if len(data_ports) == 1 else f"{label} ({port})"
            steps = _path(workflow, bid, blocks, order)
            found.append(
                Output(
                    bid, node_id, port, name, "visual" if is_visual else "table", steps, _stop(steps, blocks)
                )
            )
    return found


def temporary_output(plan: SqlPlan, node_id: str, port: str | None = None) -> Output | None:
    """Código até uma caixa qualquer: a saída é temporária e não fica na lista (RF-2013)."""
    node = plan.workflow.node(node_id)
    ports = [p for p, k in _ports(plan.workflow, node_id, node.type) if k == "data"]
    connected = {e.source_handle for e in plan.workflow.edges if e.source == node_id}
    chosen = (
        port if port in ports else next((p for p in ports if p in connected), ports[0] if ports else None)
    )
    if chosen is None:
        return None
    order = graph.reading_order(plan.workflow)
    bid = block_id(node_id, chosen)
    steps = _path(plan.workflow, bid, plan.blocks, order)
    label = node.label or node.type
    return Output(bid, node_id, chosen, label, "table", steps, _stop(steps, plan.blocks), temporary=True)
