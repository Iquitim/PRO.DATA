"""Resultado de uma execução de workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

NodeStatus = Literal["executed", "cached", "error", "skipped", "disabled"]


class ColumnSummary(BaseModel):
    name: str
    type: str
    ok_pct: float


class AnchorSummary(BaseModel):
    kind: Literal["data", "model"]
    row_count: int
    col_count: int
    columns: list[ColumnSummary] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class NodeResult(BaseModel):
    status: NodeStatus
    elapsed_ms: float = 0.0
    anchors: dict[str, AnchorSummary] = Field(default_factory=dict)
    annotation: str = ""
    error: str | None = None
    error_field: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class EdgeTelemetry(BaseModel):
    kind: Literal["data", "model"]
    row_count: int


class LogEntry(BaseModel):
    node_id: str
    node_name: str
    status: NodeStatus
    elapsed_ms: float
    message: str


class ExecutionReport(BaseModel):
    workflow_id: str
    total_elapsed_ms: float
    node_results: dict[str, NodeResult]
    edge_telemetry: dict[str, EdgeTelemetry]
    bi_widgets: list[dict[str, Any]]
    logs: list[LogEntry]
