"""Do plano ao código: uma saída vira uma consulta; várias viram um código unificado (RF-2005, RF-2006)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from prodata import __version__
from prodata.engine.sql.fragment import comment, q
from prodata.engine.sql.macros import macros_used, preamble
from prodata.engine.sql.plan import DISABLED, NO_SQL, NOT_READY, OK, Output, SqlPlan

# O estado da saída fala do resultado, não de onde o código roda: isto precisa estar escrito para quem recebe o arquivo.
DIALECT_NOTE = "-- Dialeto: DuckDB. Para rodar no Microsoft Fabric, é preciso adaptar a leitura de arquivos e as funções próprias do DuckDB."


@dataclass
class Part:
    text: str
    block: str | None = None  # bloco ligado à trilha
    kind: str = "step"  # "header" | "macros" | "step" | "section" | "final" | "stop"


def _indent(text: str, spaces: int) -> str:
    return "\n".join(" " * spaces + line if line else line for line in text.split("\n"))


def _feeds(plan: SqlPlan, output: Output) -> list[str]:
    """Etapas que levam até a tabela de saída, sem as que só alimentam a caixa onde o caminho para."""
    tail = plan.tail(output)
    if tail is None:
        return []
    needed: set[str] = set()
    stack = [tail.id]
    while stack:
        current = stack.pop()
        if current in needed or plan.blocks[current].status != OK:
            continue
        needed.add(current)
        stack.extend(plan.blocks[current].deps)
    return [s for s in output.steps if s in needed]


def _stop_reason(plan: SqlPlan, output: Output) -> str:
    assert output.stop is not None
    block = plan.blocks[output.stop]
    node = plan.workflow.node(block.node_id)
    return comment(f"{node.label or node.type}: {block.reason}")


def _constant_note(name: str, used: str) -> str:
    """Como cada constante entrou no código; a do sistema muda a cada dia (spec 029, RF-2998)."""
    kind, value = used.split(":", 1)
    if kind == "sistema":
        return f"{name} = data do dia (Today() nas fórmulas; {value} nos demais campos, ao gerar)"
    return f"{name} = {value}"


def _sources(plan: SqlPlan, steps: list[str]) -> list[str]:
    found: list[str] = []
    for step in steps:
        fragment = plan.blocks[step].fragment
        if fragment and fragment.source and fragment.source.display not in found:
            found.append(fragment.source.display)
    return found


def _final(plan: SqlPlan, output: Output) -> list[Part]:
    tail = plan.tail(output)
    if output.stop is not None:
        status = plan.blocks[output.stop].status
        opening = {NO_SQL: "Sem tradução", DISABLED: "Caixa desligada", NOT_READY: "Depende dos dados"}.get(
            status, "Etapa a revisar"
        )
        ending = (
            "Daqui em diante, a lógica fica no PRO.DATA."
            if status == NO_SQL
            else "O código vai até a etapa anterior."
        )
        parts = [Part(f"-- {opening}: {_stop_reason(plan, output)} {ending}", kind="stop")]
        if tail is not None:
            parts.append(Part(f"SELECT * FROM {q(tail.name)};", tail.id, "final"))
        return parts
    assert tail is not None and tail.fragment is not None
    if tail.fragment.visual_sql:
        return [Part(f"{tail.fragment.visual_sql};", tail.id, "final")]
    written = (
        f"-- No PRO.DATA, esta saída grava {comment(tail.fragment.export_file)}\n"
        if tail.fragment.export_file
        else ""
    )
    return [Part(f"{written}SELECT * FROM {q(tail.name)};", tail.id, "final")]


def _header(plan: SqlPlan, outputs: list[Output], steps: list[str], states: dict[str, str]) -> str:
    wf = plan.workflow
    lines = [f"-- PRO.DATA {__version__} · {comment(wf.name)} · gerado em {date.today():%d/%m/%Y}"]
    lines.append(DIALECT_NOTE)
    lines.append(
        ("-- Saídas: " if len(outputs) > 1 else "-- Saída: ") + comment(", ".join(o.name for o in outputs))
    )
    lines.append("-- Fontes necessárias: " + comment(", ".join(_sources(plan, steps)) or "nenhuma"))
    used: dict[str, str] = {}
    for step in steps:
        used |= plan.workflow.node(plan.blocks[step].node_id).config.get("__constants") or {}
    if used:
        values = ", ".join(_constant_note(name, value) for name, value in sorted(used.items()))
        lines.append(f"-- Constantes usadas (o valor já está no código): {comment(values)}")
    for output in outputs:
        state = states.get(output.id)
        if state:
            lines.append(f"-- Conferência de {comment(output.name)}: {state}")
        if output.stop is not None:
            lines.append(f"-- Atenção: {comment(output.name)} para em {_stop_reason(plan, output)}")
    notes: list[str] = []
    for step in steps:
        fragment = plan.blocks[step].fragment
        for note in fragment.notes if fragment else []:
            line = f"-- Ressalva em {plan.blocks[step].name}: {comment(note)}"
            if line not in notes:
                notes.append(line)
    return "\n".join([*lines, *notes])


def render(plan: SqlPlan, outputs: list[Output], states: dict[str, str] | None = None) -> list[Part]:
    """Partes do código para as saídas escolhidas. A trilha e o código compartilham os blocos."""
    states = states or {}
    if not outputs:
        return []
    if len(outputs) == 1:
        output = outputs[0]
        steps = _feeds(plan, output)
        return _with_preamble(plan, outputs, steps, states, _single(plan, output, steps))
    usage: dict[str, int] = {}
    per_output = {o.id: _feeds(plan, o) for o in outputs}
    for steps in per_output.values():
        for step in steps:
            usage[step] = usage.get(step, 0) + 1
    ordered = [b for b in plan.blocks if b in usage]
    return _with_preamble(plan, outputs, ordered, states, _unified(plan, outputs, per_output, usage, ordered))


def _single(plan: SqlPlan, output: Output, steps: list[str]) -> list[Part]:
    parts: list[Part] = []
    for i, step in enumerate(steps):
        block = plan.blocks[step]
        head = "WITH\n" if i == 0 else ""
        tail = "," if i < len(steps) - 1 else ""
        parts.append(Part(f"{head}  {q(block.name)} AS (\n{_indent(block.sql, 4)}\n  ){tail}", step))
    return parts + _final(plan, output)


def _view(plan: SqlPlan, step: str) -> Part:
    block = plan.blocks[step]
    return Part(f"CREATE OR REPLACE TEMP VIEW {q(block.name)} AS\n{_indent(block.sql, 2)};", step)


def _unified(
    plan: SqlPlan,
    outputs: list[Output],
    per_output: dict[str, list[str]],
    usage: dict[str, int],
    ordered: list[str],
) -> list[Part]:
    parts: list[Part] = []
    shared = [b for b in ordered if usage[b] > 1]
    if shared:
        parts.append(Part("-- Etapas compartilhadas (usadas por mais de uma saída)", kind="section"))
        parts += [_view(plan, b) for b in shared]
    for output in outputs:
        only = [b for b in per_output[output.id] if usage[b] == 1]
        if only:
            parts.append(Part(f"-- Só de {comment(output.name)}", kind="section"))
            parts += [_view(plan, b) for b in only]
    parts.append(Part("-- Saídas", kind="section"))
    for output in outputs:
        parts.append(Part(f"-- {comment(output.name)}", kind="section"))
        parts += _final(plan, output)
    return parts


def _with_preamble(
    plan: SqlPlan, outputs: list[Output], steps: list[str], states: dict[str, str], body: list[Part]
) -> list[Part]:
    parts = [Part(_header(plan, outputs, steps, states), kind="header")]
    code = "\n".join(p.text for p in body)
    if macros_used(code):
        parts.append(Part("-- Funções usadas no código\n" + preamble(code), kind="macros"))
    return parts + body


def to_text(parts: list[Part]) -> str:
    return "\n\n".join(p.text for p in parts) + "\n"
