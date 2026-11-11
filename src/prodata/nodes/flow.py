"""Subfluxos (spec 033): a caixa que executa outro fluxo e as que declaram a interface dele."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from prodata.engine.subflow import in_port
from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

Number = Literal[1, 2, 3]


class SubflowConfig(ToolConfig):
    workflow: str = Field(
        "",
        title="Fluxo",
        description="Um fluxo salvo na biblioteca que tenha Subflow Input e Subflow Output. Mudar o fluxo de origem muda todos os que o usam.",
        json_schema_extra=ui(widget="subflow"),
    )


def _signature(ctx: NodeContext, cfg: SubflowConfig) -> str:
    return ctx.subflow_signature(cfg.workflow) if ctx.subflow_signature and cfg.workflow else ""


@tool(
    type="flow.subflow",
    explainer="subflow",
    name="Subflow",
    category="control",
    icon="workflow",
    description="Executa outro fluxo da biblioteca como uma etapa. As entradas vão para as caixas Subflow Input dele; as saídas vêm das Subflow Output.",
    config=SubflowConfig,
    inputs=[
        Port("in", "1", "Entrada 1", required=False),
        Port("in2", "2", "Entrada 2", required=False),
        Port("in3", "3", "Entrada 3", required=False),
    ],
    outputs=[Port("out", "1", "Saída 1"), Port("out2", "2", "Saída 2"), Port("out3", "3", "Saída 3")],
    annotate=lambda c: c.workflow or "Escolha o fluxo",
    fingerprint=_signature,
)
def subflow(ctx: NodeContext, cfg: SubflowConfig) -> NodeOutput:
    if ctx.run_subflow is None:
        raise InvalidInputError("Subfluxos não estão disponíveis neste ambiente.")
    return NodeOutput(tables=ctx.run_subflow(cfg.workflow))


class SubflowInputConfig(ToolConfig):
    number: Number = Field(
        1,
        title="Entrada",
        description="Recebe o que estiver ligado nesta entrada da caixa Subflow.",
    )


def _input_signature(ctx: NodeContext, cfg: SubflowInputConfig) -> str:
    if ctx.injected is None:
        return "teste"
    table = ctx.injected.get(in_port(cfg.number))
    return table[1] if table else "vazio"


@tool(
    type="flow.input",
    name="Subflow Input",
    category="control",
    icon="download",
    description="Num fluxo usado como subfluxo, é por onde os dados entram. Aberto sozinho, repassa a tabela de teste ligada nela.",
    config=SubflowInputConfig,
    inputs=[Port("in", "T", "Tabela de teste", required=False)],
    annotate=lambda c: f"Entrada {c.number}",
    fingerprint=_input_signature,
)
def subflow_input(ctx: NodeContext, cfg: SubflowInputConfig) -> NodeOutput:
    if ctx.injected is not None:
        table = ctx.injected.get(in_port(cfg.number))
        if table is None:
            raise InvalidInputError(
                f"Ligue a entrada {cfg.number} da caixa Subflow: este fluxo precisa dela."
            )
        return NodeOutput(tables={"out": table[0]})
    if "in" not in ctx.inputs:
        raise InvalidInputError(
            "Ligue uma tabela de teste nesta caixa para executar o fluxo sozinho. "
            "Usado como subfluxo, ela recebe os dados de quem chamou."
        )
    return NodeOutput(tables={"out": ctx.inputs["in"]}, extra={"subflow_test": True})


class SubflowOutputConfig(ToolConfig):
    number: Number = Field(
        1,
        title="Saída",
        description="O que chega aqui sai nesta saída da caixa Subflow.",
    )


@tool(
    type="flow.output",
    name="Subflow Output",
    category="control",
    icon="upload",
    description="Num fluxo usado como subfluxo, é o que ele devolve para quem chamou.",
    config=SubflowOutputConfig,
    annotate=lambda c: f"Saída {c.number}",
)
def subflow_output(ctx: NodeContext, cfg: SubflowOutputConfig) -> NodeOutput:
    return NodeOutput(tables={"out": ctx.input()})
