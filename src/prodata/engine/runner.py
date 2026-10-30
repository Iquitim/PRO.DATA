"""Execução de workflows: validação, ordem topológica, cache incremental e propagação de falhas."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import ValidationError

from prodata.connectors.queries import QueryStore, source_query_id
from prodata.connectors.store import ConnectionStore
from prodata.domain.execution import (
    AnchorSummary,
    ColumnSummary,
    EdgeTelemetry,
    ExecutionReport,
    LogEntry,
    NodeResult,
)
from prodata.domain.workflow import Node, Workflow
from prodata.engine import graph
from prodata.engine.cache import FrozenEntry, NodeEntry, ResultCache
from prodata.engine.profiling import simple_type
from prodata.errors import NotFoundError, ProdataError
from prodata.ingestion.datasets import DatasetStore
from prodata.nodes import REGISTRY, NodeContext, ToolSpec
from prodata.nodes.io import OutputDataConfig, export_path

log = logging.getLogger(__name__)


class SkippedError(Exception):
    """Falha de um nó com mensagem para o usuário e, opcionalmente, o campo afetado."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class _Inputs:
    tables: dict[str, pl.DataFrame]
    models: dict[str, dict[str, Any]]
    fingerprints: dict[str, str]


def _summarize(entry: NodeEntry) -> dict[str, AnchorSummary]:
    anchors: dict[str, AnchorSummary] = {}
    for port, df in entry.tables.items():
        nulls = df.null_count().row(0) if df.width else ()
        anchors[port] = AnchorSummary(
            kind="data",
            row_count=df.height,
            col_count=df.width,
            columns=[
                ColumnSummary(
                    name=name,
                    type=simple_type(dtype),
                    ok_pct=round(100 - (n / df.height * 100), 1) if df.height else 100.0,
                )
                for (name, dtype), n in zip(df.schema.items(), nulls, strict=True)
            ],
        )
    for port, bundle in entry.models.items():
        anchors[port] = AnchorSummary(
            kind="model", row_count=1, col_count=len(bundle["feature_columns"]), metrics=bundle["metrics"]
        )
    return anchors


def _validation_message(exc: ValidationError) -> tuple[str, str | None]:
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"]) or None
    return f"Configuração inválida em '{field}': {first['msg']}", field


class WorkflowRunner:
    def __init__(
        self,
        cache: ResultCache,
        datasets: DatasetStore,
        exports_dir: Path,
        connections: ConnectionStore | None = None,
        queries: QueryStore | None = None,
    ) -> None:
        self.cache = cache
        self.datasets = datasets
        self.exports_dir = exports_dir
        self.connections = connections
        self.queries = queries
        self._lock = threading.Lock()
        # Andamento das execuções em curso, por fluxo (spec 018): a interface consulta para iluminar a caixa da vez.
        self._progress: dict[str, dict[str, Any]] = {}

    def run(
        self, workflow: Workflow, target_node_id: str | None = None, *, hold_exports: bool = False
    ) -> ExecutionReport:
        """Executa o fluxo. ``hold_exports``: execução automática (ao abrir o fluxo, trocar de aba): exportações
        em "Perguntar" cujo arquivo já existe esperam o usuário clicar em Executar (spec 017)."""
        started = time.perf_counter()
        order = graph.topological_order(workflow)
        if target_node_id:
            if target_node_id not in order:
                raise graph.GraphError(f"Nó alvo inexistente: {target_node_id}")
            keep = graph.ancestors(workflow, target_node_id) | {target_node_id}
            order = [n for n in order if n in keep]

        progress: dict[str, Any] = {"order": order, "running": None, "done": {}}
        self._progress[workflow.id] = progress
        try:
            return self._run_locked(workflow, order, progress, started, hold_exports)
        finally:
            self._progress.pop(workflow.id, None)

    def progress(self, workflow_id: str) -> dict[str, Any]:
        """Caixa em execução e caixas já concluídas da execução em curso (vazio se nada roda)."""
        current = self._progress.get(workflow_id)
        if current is None:
            return {"running": None, "done": {}, "order": [], "active": False}
        return {
            "running": current["running"],
            "done": dict(current["done"]),
            "order": list(current["order"]),
            "active": True,
        }

    def _run_locked(
        self,
        workflow: Workflow,
        order: list[str],
        progress: dict[str, Any],
        started: float,
        hold_exports: bool,
    ) -> ExecutionReport:
        results: dict[str, NodeResult] = {}
        fingerprints: dict[str, str] = {}
        widgets: list[dict[str, Any]] = []
        logs: list[LogEntry] = []

        with self._lock:
            self.cache.prune(workflow.id, {n.id for n in workflow.nodes})
            frozen, signatures = self._valid_cache_points(workflow, order)
            needed = graph.needed_nodes(workflow, order, set(frozen)) if frozen else set(order)
            for node_id in order:
                node = workflow.node(node_id)
                spec = REGISTRY.get(node.type)
                waiting = self._waiting_export(node) if hold_exports else None
                progress["running"] = node_id
                if node_id not in needed:
                    result = self._held_result(workflow, node, spec)
                elif waiting:
                    result = NodeResult(
                        status="skipped",
                        annotation="Arquivo já existe: clique em Executar",
                        error=f"{waiting} já existe. Clique em Executar para escolher entre substituir ou criar outro.",
                        extra={"export_waiting": waiting},
                    )
                elif node_id in frozen:
                    result = self._frozen_result(workflow, node, spec, frozen[node_id], fingerprints)
                else:
                    result = self._run_node(workflow, node, spec, results, fingerprints)
                    if node_id in signatures and result.status in ("executed", "cached"):
                        entry = self.cache.get(workflow.id, node_id)
                        if entry is not None:
                            saved = self.cache.freeze(workflow.id, node_id, entry, signatures[node_id])
                            result.extra = {
                                **result.extra,
                                "cache_point": "saved",
                                "frozen_at": saved.frozen_at,
                            }
                results[node_id] = result
                progress["done"][node_id] = result.status
                name = node.label or (spec.name if spec else node.type)
                logs.append(
                    LogEntry(
                        node_id=node_id,
                        node_name=name,
                        status=result.status,
                        elapsed_ms=result.elapsed_ms,
                        message=self._log_message(result),
                    )
                )
                if widget := result.extra.get("bi_widget"):
                    widgets.append({**widget, "node_id": node_id, "node_label": name})

        telemetry = {
            e.id: EdgeTelemetry(kind=anchor.kind, row_count=anchor.row_count)
            for e in workflow.edges
            if (src := results.get(e.source)) and (anchor := src.anchors.get(e.source_handle))
        }
        return ExecutionReport(
            workflow_id=workflow.id,
            total_elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            node_results=results,
            edge_telemetry=telemetry,
            bi_widgets=widgets,
            logs=logs,
        )

    # ------------------------------------------------------------------ pontos de cache (spec 012)

    def _valid_cache_points(
        self, workflow: Workflow, order: list[str]
    ) -> tuple[dict[str, FrozenEntry], dict[str, str]]:
        """Pontos com instantâneo ainda válido e a assinatura atual de todos os pontos."""
        points = [n for n in workflow.nodes if n.cache_point and not n.disabled]
        self.cache.prune_frozen(workflow.id, {n.id for n in points})
        signatures = {
            n.id: f"{graph.upstream_signature(workflow, n.id)}:{self._sources_signature(workflow, n.id)}"
            for n in points
            if n.id in order
        }
        frozen: dict[str, FrozenEntry] = {}
        for node_id, signature in signatures.items():
            snapshot = self.cache.frozen(workflow.id, node_id)
            if (
                snapshot is not None
                and snapshot.signature == signature
                and not _expired(snapshot, workflow.node(node_id).cache_refresh)
            ):
                frozen[node_id] = snapshot
            elif snapshot is not None:
                self.cache.unfreeze(workflow.id, node_id)  # algo antes do ponto mudou, ou o prazo venceu
        return frozen, signatures

    def _waiting_export(self, node: Node) -> str | None:
        """Nome do arquivo, se for uma exportação em "Perguntar" que encontraria o arquivo já existente."""
        if node.type != "io.output_data" or node.disabled:
            return None
        try:
            cfg = OutputDataConfig.model_validate(node.config)
            path = export_path(self.exports_dir, cfg)
        except ValidationError, ProdataError:
            return None
        return path.name if cfg.if_exists == "ask" and path.exists() else None

    def _sources_signature(self, workflow: Workflow, node_id: str) -> str:
        """Data e tamanho dos arquivos de origem antes do ponto (spec 017): um arquivo atualizado
        invalida o cache. Fontes de banco não aparecem aqui; para elas existe a renovação por prazo."""
        parts = []
        for upstream in sorted(graph.ancestors(workflow, node_id)):
            node = workflow.node(upstream)
            dataset = str(node.config.get("dataset") or "")
            if node.type != "io.input_data" or not dataset or source_query_id(dataset) is not None:
                continue
            try:
                parts.append(f"{dataset}={self.datasets.signature(dataset)}")
            except NotFoundError:
                parts.append(f"{dataset}=sumiu")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]

    def _frozen_result(
        self,
        workflow: Workflow,
        node: Node,
        spec: ToolSpec | None,
        snapshot: FrozenEntry,
        fingerprints: dict[str, str],
    ) -> NodeResult:
        self.cache.put(workflow.id, node.id, snapshot.entry, persist=False)
        fingerprints[node.id] = f"frozen:{snapshot.signature}"
        return NodeResult(
            status="cached",
            elapsed_ms=snapshot.entry.elapsed_ms,
            anchors=_summarize(snapshot.entry),
            annotation=self._annotation(node, spec),
            extra={**snapshot.entry.extra, "cache_point": "frozen", "frozen_at": snapshot.frozen_at},
        )

    def _held_result(self, workflow: Workflow, node: Node, spec: ToolSpec | None) -> NodeResult:
        """Caixa antes de um ponto de cache: não executa. Mostra o último resultado, se houver."""
        entry = self.cache.get(workflow.id, node.id)
        annotation = self._annotation(node, spec)
        if entry is not None:
            return NodeResult(
                status="cached", anchors=_summarize(entry), annotation=annotation, extra={"held": True}
            )
        return NodeResult(
            status="skipped",
            annotation=annotation,
            error="Em cache: o ponto de cache adiante já tem o resultado, esta caixa não precisou executar.",
            extra={"held": True},
        )

    @staticmethod
    def _annotation(node: Node, spec: ToolSpec | None) -> str:
        if spec is None:
            return ""
        try:
            return spec.annotation(spec.config.model_validate(node.config))
        except ValidationError:
            return ""

    # ------------------------------------------------------------------ nó a nó

    def _run_node(
        self,
        workflow: Workflow,
        node: Node,
        spec: ToolSpec | None,
        results: dict[str, NodeResult],
        fingerprints: dict[str, str],
    ) -> NodeResult:
        if spec is None:
            return NodeResult(status="error", error=f"Ferramenta desconhecida: {node.type}")
        if node.disabled:
            self.cache.drop(workflow.id, node.id)
            return NodeResult(status="disabled")

        try:
            cfg = spec.config.model_validate(node.config)
        except ValidationError as exc:
            message, field = _validation_message(exc)
            return NodeResult(status="error", error=message, error_field=field)
        annotation = spec.annotation(cfg)

        try:
            inputs = self._gather_inputs(workflow, node, spec, results, fingerprints)
        except SkippedError as skip:
            return NodeResult(status="skipped", error=skip.message, annotation=annotation)

        ctx = NodeContext(
            inputs.tables, inputs.models, self.datasets, self.exports_dir, self.connections, self.queries
        )
        started = time.perf_counter()
        try:
            fp = self._fingerprint(node, spec, cfg, ctx, inputs)
            cached = self.cache.get(workflow.id, node.id)
            if cached and cached.fingerprint == fp and not spec.side_effect:
                fingerprints[node.id] = fp
                return NodeResult(
                    status="cached",
                    elapsed_ms=cached.elapsed_ms,
                    anchors=_summarize(cached),
                    annotation=annotation,
                    extra=cached.extra,
                )
            output = spec.run(ctx, cfg)
        except (ProdataError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            self.cache.drop(workflow.id, node.id)
            return NodeResult(
                status="error",
                error=getattr(exc, "message", None) or str(exc),
                annotation=annotation,
                elapsed_ms=self._ms(started),
            )
        except Exception as exc:  # isolamento: um nó com bug não derruba o fluxo inteiro
            log.exception("Falha inesperada no nó %s (%s)", node.id, node.type)
            self.cache.drop(workflow.id, node.id)
            return NodeResult(
                status="error",
                error=f"Erro interno: {exc}",
                annotation=annotation,
                elapsed_ms=self._ms(started),
            )

        elapsed = self._ms(started)
        entry = NodeEntry(
            fingerprint=fp, tables=output.tables, models=output.models, extra=output.extra, elapsed_ms=elapsed
        )
        self.cache.put(workflow.id, node.id, entry)
        fingerprints[node.id] = fp
        return NodeResult(
            status="executed",
            elapsed_ms=elapsed,
            anchors=_summarize(entry),
            annotation=annotation,
            extra=output.extra,
        )

    def _gather_inputs(
        self,
        workflow: Workflow,
        node: Node,
        spec: ToolSpec,
        results: dict[str, NodeResult],
        fingerprints: dict[str, str],
    ) -> _Inputs:
        ports = {p.id: p for p in spec.inputs}
        found = _Inputs({}, {}, {})
        for edge in (e for e in workflow.edges if e.target == node.id):
            port = ports.get(edge.target_handle)
            if port is None:
                raise SkippedError(f"Conexão em porta inexistente [{edge.target_handle}].")
            parent = results.get(edge.source)
            if parent is None or parent.status not in ("executed", "cached"):
                parent_name = workflow.node(edge.source).label or edge.source
                raise SkippedError(f"Entrada [{port.label}] indisponível: '{parent_name}' não foi executado.")
            entry = self.cache.get(workflow.id, edge.source)
            if entry is None:
                raise SkippedError(f"Entrada [{port.label}] indisponível.")
            if port.kind == "model":
                if edge.source_handle not in entry.models:
                    raise SkippedError(f"A entrada [{port.label}] espera um modelo treinado.")
                found.models[port.id] = entry.models[edge.source_handle]
            else:
                if edge.source_handle not in entry.tables:
                    raise SkippedError(f"A entrada [{port.label}] espera uma tabela.")
                found.tables[port.id] = entry.tables[edge.source_handle]
            found.fingerprints[port.id] = f"{fingerprints[edge.source]}:{edge.source_handle}"

        missing = [p.label for p in spec.inputs if p.required and p.id not in found.fingerprints]
        if missing:
            raise SkippedError("Conecte a(s) entrada(s): " + ", ".join(f"[{m}]" for m in missing))
        return found

    @staticmethod
    def _fingerprint(node: Node, spec: ToolSpec, cfg: Any, ctx: NodeContext, inputs: _Inputs) -> str:
        payload = {
            "type": node.type,
            "config": cfg.model_dump(mode="json"),
            "inputs": dict(sorted(inputs.fingerprints.items())),
            "extra": spec.fingerprint(ctx, cfg) if spec.fingerprint else "",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]

    @staticmethod
    def _ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 1)

    @staticmethod
    def _log_message(result: NodeResult) -> str:
        rows = sum(a.row_count for a in result.anchors.values() if a.kind == "data")
        match result.status:
            case "executed":
                text = f"{rows:,} linha(s) em {result.elapsed_ms} ms".replace(",", ".")
                warnings = result.extra.get("warnings") or []
                return f"{text} · atenção: {' '.join(warnings)}" if warnings else text
            case "cached":
                return f"{rows:,} linha(s), reaproveitado do cache".replace(",", ".")
            case "disabled":
                return "Desabilitado"
            case _:
                return result.error or ""


def _expired(snapshot: FrozenEntry, refresh: str) -> bool:
    """Prazo do ponto de cache (spec 017): "daily" vale até o fim do dia (hora local); "hourly", por uma hora."""
    if refresh == "changes":
        return False
    frozen_at = datetime.fromisoformat(snapshot.frozen_at)
    now = datetime.now(UTC)
    if refresh == "hourly":
        return now - frozen_at >= timedelta(hours=1)
    return frozen_at.astimezone().date() != now.astimezone().date()
