"""Constantes (spec 028, RF-2841..2850): um valor com nome, trocado num lugar só.

Escrita: ``[#nome]``. O motor troca a referência pelo valor antes de validar e executar, e guarda os valores usados na
configuração da caixa (``__constants``). Assim a assinatura de cada caixa muda junto com a constante: só o que a
usa é refeito, e o cache continua valendo para o resto.

Duas origens: as do fluxo (``Workflow.constants``) e as compartilhadas, cadastradas na vista Dados. O fluxo guarda o
valor de cada compartilhada que usa (``Workflow.shared_constants``), para rodar num computador sem o cadastro.

E as do sistema (spec 029, RF-2995): ``[#hoje]`` vale a data do dia, sem cadastro. Numa fórmula vira ``Today()``;
nos demais campos, a data em AAAA-MM-DD. O valor entra na assinatura da caixa: ela refaz quando o dia muda.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from prodata.domain.constants import Constant, ConstantValue

REF = re.compile(r"\[#([A-Za-z_][A-Za-z0-9_]{0,63})\]")
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
USED_KEY = "__constants"
# Campos de texto que aceitam constante além das fórmulas: o valor entra como está.
RAW_FIELDS = {("prep.filter", "value"), ("io.output_data", "filename")}
# Constantes do sistema: nomes reservados, com o que a fórmula escreve no lugar (RF-2995, RF-2997).
SYSTEM_FORMULA = {"hoje": "Today()"}
SYSTEM_DESCRIPTION = {"hoje": "A data de hoje, no formato AAAA-MM-DD. Muda sozinha a cada dia."}


class SystemValue(ConstantValue):
    """Valor de uma constante do sistema: a fórmula usa a função, o resto usa o valor."""

    formula: str = ""


def system_values(today: date | None = None) -> dict[str, SystemValue]:
    day = (today or date.today()).isoformat()
    return {"hoje": SystemValue(type="date", value=day, formula=SYSTEM_FORMULA["hoje"])}


def formula_literal(c: ConstantValue) -> str:
    """O valor escrito na linguagem de fórmula: número como número, data como data, texto entre aspas."""
    if isinstance(c, SystemValue):
        return c.formula
    if c.type == "number":
        return c.value.replace(",", ".")
    if c.type == "date":
        return f"ToDate('{c.value}')"
    return "'" + c.value.replace("'", "''") + "'"


def _outside_literals(text: str, change: Callable[[str], str]) -> str:
    """Aplica ``change`` fora dos textos entre aspas: '[#x]' escrito como texto fica como está."""
    pieces, last = [], 0
    for literal in _STRING_LITERAL.finditer(text):
        pieces.append(change(text[last : literal.start()]))
        pieces.append(literal.group(0))
        last = literal.end()
    pieces.append(change(text[last:]))
    return "".join(pieces)


def _refs_in(text: str, formula: bool) -> set[str]:
    if formula:
        found: set[str] = set()

        def collect(part: str) -> str:
            found.update(REF.findall(part))
            return part

        _outside_literals(text, collect)
        return found
    return set(REF.findall(text))


def node_refs(node_type: str, config: Any, extra_texts: list[str] | None = None) -> set[str]:
    """Constantes citadas pela caixa: nas fórmulas, nos campos de texto aceitos e nos textos extras (a API dela)."""
    found: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == USED_KEY:
                    continue
                if isinstance(value, str) and (key == "expression" or (node_type, key) in RAW_FIELDS):
                    found.update(_refs_in(value, key == "expression"))
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(config)
    for text in extra_texts or []:
        found.update(_refs_in(text, False))
    return found


def fill_text(text: str, values: dict[str, ConstantValue]) -> str:
    """Troca ``[#nome]`` pelo valor como está, para nome de arquivo, filtro básico e parâmetro de API."""
    return REF.sub(lambda m: values[m.group(1)].value if m.group(1) in values else m.group(0), text)


def fill_expression(text: str, values: dict[str, Any]) -> str:
    """Troca ``[#nome]`` numa fórmula pelo valor escrito na linguagem dela."""
    return _outside_literals(
        text,
        lambda part: REF.sub(
            lambda m: formula_literal(values[m.group(1)]) if m.group(1) in values else m.group(0), part
        ),
    )


def _fill_config(node_type: str, config: Any, values: dict[str, ConstantValue]) -> Any:
    def formula(text: str) -> str:
        return fill_expression(text, values)

    def walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {}
            for key, value in obj.items():
                if isinstance(value, str) and key == "expression":
                    out[key] = formula(value)
                elif isinstance(value, str) and (node_type, key) in RAW_FIELDS:
                    out[key] = fill_text(value, values)
                else:
                    out[key] = walk(value)
            return out
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return obj

    return walk(config)


@dataclass
class Resolution:
    """O fluxo com as constantes já trocadas, e o que precisa ser avisado em cada caixa."""

    workflow: Any
    problems: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    values: dict[str, dict[str, ConstantValue]] = field(default_factory=dict)


def resolve(
    workflow: Any,
    shared: dict[str, Constant],
    api_texts: Callable[[Any], list[str]] | None = None,
    today: date | None = None,
) -> Resolution:
    """Troca as constantes em cada caixa. Constante que falta ou que tem dois donos vira erro da caixa que a usa."""
    own = {c.name: c for c in workflow.constants}
    saved = workflow.shared_constants
    system = system_values(today)
    out = Resolution(workflow)
    nodes = []
    for node in workflow.nodes:
        refs = node_refs(node.type, node.config, api_texts(node) if api_texts else None)
        if not refs:
            nodes.append(node)
            continue
        values: dict[str, ConstantValue] = {}
        for name in sorted(refs):
            if name in system and (name in own or name in shared):
                # Fluxo de antes da 0.6.1 com uma constante própria de nome reservado: continua valendo.
                values[name] = own.get(name) or shared[name]
                out.warnings.setdefault(node.id, []).append(
                    f"[#{name}] agora é uma constante do sistema: renomeie a sua para não confundir."
                )
            elif name in system:
                values[name] = system[name]
            elif name in own and name in shared:
                out.problems[node.id] = (
                    f"A constante [#{name}] existe no fluxo e também é compartilhada: renomeie uma das duas."
                )
            elif name in own:
                values[name] = own[name]
            elif name in shared:
                values[name] = shared[name]
            elif name in saved:
                values[name] = saved[name]
                out.warnings.setdefault(node.id, []).append(
                    f"Constante compartilhada [#{name}] não cadastrada neste computador: usando o valor salvo no fluxo."
                )
            else:
                out.problems[node.id] = (
                    f"A constante [#{name}] não existe: cadastre na vista Dados ou nas constantes do fluxo."
                )
        out.values[node.id] = values
        config = _fill_config(node.type, node.config, values)
        config[USED_KEY] = {
            k: f"{'sistema' if isinstance(v, SystemValue) else v.type}:{v.value}" for k, v in values.items()
        }
        nodes.append(node.model_copy(update={"config": config}))
    out.workflow = workflow.model_copy(update={"nodes": nodes})
    return out


def snapshot(
    workflow: Any, shared: dict[str, Constant], api_texts: Callable[[Any], list[str]] | None = None
) -> dict[str, ConstantValue]:
    """Valores das compartilhadas que o fluxo usa: vão junto no arquivo (RF-2850)."""
    used: set[str] = set()
    for node in workflow.nodes:
        used |= node_refs(node.type, node.config, api_texts(node) if api_texts else None)
    used -= set(SYSTEM_FORMULA)  # a data de hoje não vai no arquivo: é sempre a do dia
    kept = {name: ConstantValue(type=c.type, value=c.value) for name, c in shared.items() if name in used}
    # O que já estava salvo e não está cadastrado aqui continua no arquivo, para não se perder.
    return {**{k: v for k, v in workflow.shared_constants.items() if k in used and k not in shared}, **kept}
