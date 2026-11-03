"""Operações de grafo sobre o workflow: ordenação topológica e ancestrais."""

from __future__ import annotations

import hashlib
import json
from collections import deque

from prodata.domain.workflow import Workflow


class GraphError(ValueError):
    """Grafo inválido (por exemplo, com ciclo)."""


def topological_order(workflow: Workflow) -> list[str]:
    """Ordem de Kahn, estável em relação à ordem dos nós no arquivo."""
    ids = [n.id for n in workflow.nodes]
    indegree = dict.fromkeys(ids, 0)
    children: dict[str, list[str]] = {i: [] for i in ids}
    for e in workflow.edges:
        children[e.source].append(e.target)
        indegree[e.target] += 1

    queue = deque(i for i in ids if indegree[i] == 0)
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(order) != len(ids):
        cyclic = sorted(i for i in ids if indegree[i] > 0)
        raise GraphError(f"O fluxo contém um ciclo envolvendo: {', '.join(cyclic)}")
    return order


def reading_order(workflow: Workflow) -> list[str]:
    """Ordem de dependência que segue cada cadeia até onde der: é a que se lê bem de cima a baixo (spec 020)."""
    ids = [n.id for n in workflow.nodes]
    indegree = dict.fromkeys(ids, 0)
    children: dict[str, list[str]] = {i: [] for i in ids}
    for e in workflow.edges:
        children[e.source].append(e.target)
        indegree[e.target] += 1
    position = {i: index for index, i in enumerate(ids)}
    ready = [i for i in ids if indegree[i] == 0]
    order: list[str] = []
    last: str | None = None
    while ready:
        following = [c for c in children[last] if c in ready] if last else []
        current = following[0] if following else _needed_next(ready, order, children, indegree, position)
        ready.remove(current)
        order.append(current)
        last = current
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(ids):
        cyclic = sorted(i for i in ids if indegree[i] > 0)
        raise GraphError(f"O fluxo contém um ciclo envolvendo: {', '.join(cyclic)}")
    return order


def _needed_next(
    ready: list[str],
    placed: list[str],
    children: dict[str, list[str]],
    indegree: dict[str, int],
    position: dict[str, int],
) -> str:
    """Sem continuação direta: prefere o que destrava uma caixa já começada; depois, a ordem do arquivo."""
    started = {c for i in placed for c in children[i] if indegree[c] > 0}
    return min(ready, key=lambda i: (not (set(children[i]) & started), position[i]))


def ancestors(workflow: Workflow, node_id: str) -> set[str]:
    parents: dict[str, list[str]] = {}
    for e in workflow.edges:
        parents.setdefault(e.target, []).append(e.source)
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        for parent in parents.get(stack.pop(), []):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def upstream_signature(workflow: Workflow, node_id: str) -> str:
    """Assinatura da caixa e de tudo o que vem antes dela (tipo, configuração, habilitação, ligações).

    Não olha os dados: é o que permite a um ponto de cache não reler as entradas. Qualquer
    mudança antes do ponto muda a assinatura e invalida o cache (spec 012, RF-1206).
    """
    scope = ancestors(workflow, node_id) | {node_id}
    nodes = sorted(
        (n.id, n.type, json.dumps(n.config, sort_keys=True, default=str), n.disabled)
        for n in workflow.nodes
        if n.id in scope
    )
    edges = sorted(
        (e.source, e.source_handle, e.target, e.target_handle)
        for e in workflow.edges
        if e.source in scope and e.target in scope
    )
    raw = json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def needed_nodes(workflow: Workflow, order: list[str], stops: set[str]) -> set[str]:
    """Caixas que precisam executar: anda para trás a partir das finais de `order` sem
    atravessar `stops` (pontos de cache válidos, que entregam o resultado guardado)."""
    in_scope = set(order)
    parents: dict[str, list[str]] = {}
    has_child: set[str] = set()
    for e in workflow.edges:
        if e.source in in_scope and e.target in in_scope:
            parents.setdefault(e.target, []).append(e.source)
            has_child.add(e.source)
    stack = [n for n in order if n not in has_child]
    needed: set[str] = set()
    while stack:
        current = stack.pop()
        if current in needed:
            continue
        needed.add(current)
        if current not in stops:
            stack.extend(parents.get(current, []))
    return needed
