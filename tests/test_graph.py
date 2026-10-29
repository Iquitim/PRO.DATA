import pytest
from pydantic import ValidationError

from prodata.domain.workflow import Workflow
from prodata.engine.graph import GraphError, ancestors, topological_order


def _wf(edges: list[tuple[str, str]], nodes: str = "abcd") -> Workflow:
    return Workflow.model_validate(
        {
            "id": "t",
            "nodes": [{"id": n, "type": "io.browse"} for n in nodes],
            "edges": [{"id": f"{s}{t}", "source": s, "target": t} for s, t in edges],
        }
    )


def test_topological_order_respects_dependencies() -> None:
    order = topological_order(_wf([("c", "b"), ("b", "a"), ("d", "a")]))
    assert order.index("c") < order.index("b") < order.index("a")
    assert order.index("d") < order.index("a")


def test_cycle_is_rejected() -> None:
    with pytest.raises(GraphError, match="ciclo"):
        topological_order(_wf([("a", "b"), ("b", "c"), ("c", "a")]))


def test_ancestors() -> None:
    wf = _wf([("a", "b"), ("b", "c"), ("d", "c")])
    assert ancestors(wf, "c") == {"a", "b", "d"}
    assert ancestors(wf, "a") == set()


def test_edges_must_reference_existing_nodes() -> None:
    with pytest.raises(ValidationError, match="inexistente"):
        _wf([("a", "z")])


def test_duplicated_node_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicados"):
        _wf([], nodes="aa")
