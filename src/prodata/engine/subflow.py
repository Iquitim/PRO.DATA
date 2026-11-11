"""Subfluxos (spec 033): um fluxo da biblioteca executado como uma etapa de outro."""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import polars as pl

from prodata.domain.workflow import Node, Workflow
from prodata.errors import InvalidInputError, NotFoundError

if TYPE_CHECKING:
    from prodata.engine.runner import WorkflowRunner
    from prodata.nodes.base import NodeContext

MAX_DEPTH = 5
INPUT = "flow.input"
OUTPUT = "flow.output"
SUBFLOW = "flow.subflow"
PORTS = {1: "", 2: "2", 3: "3"}
# Caixas que leem de fora ou gravam: com elas dentro, o subfluxo roda de novo a cada execução.
_LIVE = ("io.api_loop", "io.output_data", "io.database_input", "control.compare_runs")


def in_port(number: int) -> str:
    return f"in{PORTS[number]}"


def out_port(number: int) -> str:
    return f"out{PORTS[number]}"


def _library(runner: WorkflowRunner) -> Any:
    if runner.workflows is None:
        raise InvalidInputError("Subfluxos não estão disponíveis neste ambiente.")
    return runner.workflows


def load(runner: WorkflowRunner, child_id: str) -> Workflow:
    if not child_id:
        raise InvalidInputError("Escolha o fluxo que esta caixa executa.")
    try:
        child: Workflow = _library(runner).get(child_id)
    except NotFoundError as exc:
        raise InvalidInputError(
            f"O subfluxo '{child_id}' não está na biblioteca deste computador. Abra e salve o fluxo de origem aqui."
        ) from exc
    if runner.guard is not None:
        runner.guard(child.id)
    return child


def _is_live(node: Node) -> bool:
    dataset = str(node.config.get("dataset") or "")
    return node.type in _LIVE or dataset.startswith(("sql:", "api:", "jira:"))


def signature(runner: WorkflowRunner, child_id: str, depth: int = 0) -> str:
    """Muda quando o fluxo de origem, um subfluxo dele ou um arquivo que ele lê muda."""
    if depth > MAX_DEPTH or not child_id or runner.workflows is None:
        return ""
    try:
        child: Workflow = runner.workflows.get(child_id)
    except NotFoundError:
        return "sumiu"
    parts = [json.dumps(child.model_dump(mode="json", by_alias=True), sort_keys=True)]
    for node in child.nodes:
        if node.disabled:
            continue
        if node.type == SUBFLOW:
            parts.append(signature(runner, str(node.config.get("workflow") or ""), depth + 1))
        elif _is_live(node):
            parts.append(str(time.time_ns()))
        elif node.type == "io.input_data" and node.config.get("dataset"):
            try:
                parts.append(runner.datasets.signature(str(node.config["dataset"])))
            except NotFoundError:
                parts.append("sumiu")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def run(
    runner: WorkflowRunner, parent: Workflow, node: Node, child_id: str, ctx: NodeContext
) -> dict[str, pl.DataFrame]:
    from prodata.engine.runner import WorkflowRunner as Runner

    child = load(runner, child_id)
    # IDs de verdade dos fluxos em execução: dentro de um subfluxo, ``parent.id`` é o do cache daquele uso.
    chain = runner.chain or (parent.id,)
    if child.id in chain:
        raise InvalidInputError(f"O subfluxo '{child.name}' acabaria chamando a si mesmo.")
    if len(chain) > MAX_DEPTH:
        raise InvalidInputError(f"Subfluxo dentro de subfluxo vale até {MAX_DEPTH} níveis.")

    # Cada uso tem o próprio cache: o mesmo subfluxo em dois fluxos não mistura resultados.
    scope = "sub_" + hashlib.sha256(f"{parent.id}|{node.id}|{child.id}".encode()).hexdigest()[:24]
    inner = Runner(
        runner.cache,
        runner.datasets,
        runner.exports_dir,
        runner.connections,
        runner.queries,
        runner.apis,
        runner.constants,
        runner.jira,
        state_dir=runner.state_dir,
        workflows=runner.workflows,
        secret_key=runner.secret_key,
        guard=runner.guard,
    )
    inner.chain = (*chain, child.id)
    inner.injected = {
        port: (table, ctx.input_fingerprints.get(port, "")) for port, table in ctx.inputs.items()
    }
    scoped = child.model_copy(update={"id": scope})
    report = inner.run(scoped, hold_exports=ctx.hold)

    for inner_node in scoped.nodes:
        result = report.node_results.get(inner_node.id)
        if result is not None and result.status == "error":
            label = inner_node.label or inner_node.type
            raise InvalidInputError(f"Subfluxo '{child.name}': a caixa '{label}' falhou. {result.error}")

    tables: dict[str, pl.DataFrame] = {}
    for inner_node in scoped.nodes:
        if inner_node.type != OUTPUT or inner_node.disabled:
            continue
        number = int(inner_node.config.get("number") or 1)
        entry = runner.cache.get(scope, inner_node.id)
        if entry is None or "out" not in entry.tables:
            label = inner_node.label or f"Subflow Output {number}"
            raise InvalidInputError(f"Subfluxo '{child.name}': a saída '{label}' não recebeu dados.")
        tables[out_port(number)] = entry.tables["out"]
    if not tables:
        raise InvalidInputError(
            f"O fluxo '{child.name}' não tem caixa Subflow Output: é ela que devolve o resultado."
        )
    return tables
