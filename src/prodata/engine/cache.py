"""Cache de resultados por porta: memória quente + Apache Arrow IPC em disco."""

from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import shutil
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from prodata.engine import profiling
from prodata.errors import InvalidInputError

log = logging.getLogger(__name__)
FALLBACK_MEMORY = 8 * 1024**3


def total_memory() -> int:
    """Memória do computador, sem depender de biblioteca extra."""
    try:
        if os.name == "nt":

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong)
                    for name in ("total", "free", "page", "page_free", "virtual", "virtual_free", "extended")
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            windll = getattr(ctypes, "windll")  # noqa: B009 (só existe no Windows, e o mypy do CI roda no Linux)
            if windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total)
            return FALLBACK_MEMORY
        sysconf = getattr(os, "sysconf")  # noqa: B009 (não existe no Windows, e o mypy roda nele)
        return int(sysconf("SC_PAGE_SIZE")) * int(sysconf("SC_PHYS_PAGES"))
    except AttributeError, OSError, ValueError:
        return FALLBACK_MEMORY


class StoredTables(Mapping[str, pl.DataFrame]):
    """Tabelas de uma caixa (spec 033): na memória enquanto couberem; depois só no disco, e voltam quando pedidas."""

    def __init__(
        self,
        loaded: Mapping[str, pl.DataFrame],
        reload: Callable[[str], pl.DataFrame],
        touched: Callable[[], None],
    ) -> None:
        self._ports = list(loaded)
        self._loaded = dict(loaded)
        self._reload = reload
        self._touched = touched

    def __getitem__(self, port: str) -> pl.DataFrame:
        if port not in self._ports:
            raise KeyError(port)
        df = self._loaded.get(port)
        if df is None:
            df = self._reload(port)
            self._loaded[port] = df
            self._touched()
        return df

    def __contains__(self, port: object) -> bool:
        return port in self._ports  # o padrão do Mapping traria a tabela do disco só para responder

    def __iter__(self) -> Iterator[str]:
        return iter(self._ports)

    def __len__(self) -> int:
        return len(self._ports)

    def in_memory(self) -> int:
        return sum(int(df.estimated_size()) for df in self._loaded.values())

    def release(self) -> None:
        self._loaded.clear()


def _safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in part)


@dataclass
class NodeEntry:
    fingerprint: str
    tables: Mapping[str, pl.DataFrame] = field(default_factory=dict)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    # Linhas, colunas e preenchimento por porta, calculados uma vez: ler o resumo não traz a tabela do disco.
    summary: Any = None


@dataclass
class FrozenEntry:
    """Resultado congelado de um ponto de cache (spec 012)."""

    signature: str
    entry: NodeEntry
    frozen_at: str


class ResultCache:
    """Guarda as saídas de cada nó, indexadas por workflow e nó.

    As tabelas também são persistidas em ``<cache_dir>/<workflow>/<nó>__<porta>.arrow``
    para inspeção externa (DuckDB, Polars, pandas). Modelos de ML ficam só em memória.
    """

    def __init__(self, cache_dir: Path, memory_bytes: int = 0) -> None:
        self.cache_dir = cache_dir
        # Um quarto da memória do computador, ou o que PRODATA_CACHE_MEMORY_MB mandar.
        self.memory_limit = memory_bytes or total_memory() // 4
        self._order: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._entries: dict[tuple[str, str], NodeEntry] = {}
        self._profiles: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._frozen: dict[tuple[str, str], FrozenEntry] = {}
        self._lock = threading.RLock()

    def get(self, workflow_id: str, node_id: str) -> NodeEntry | None:
        with self._lock:
            entry = self._entries.get((workflow_id, node_id))
            if entry is not None:
                self._order.move_to_end((workflow_id, node_id))
            return entry

    def put(self, workflow_id: str, node_id: str, entry: NodeEntry, *, persist: bool = True) -> None:
        key = (workflow_id, node_id)
        # Só o que foi gravado em disco pode sair da memória: dali ele volta.
        if (
            persist
            and self._persist(workflow_id, node_id, entry)
            and not isinstance(entry.tables, StoredTables)
        ):
            entry.tables = StoredTables(
                entry.tables,
                reload=lambda port: self._read(workflow_id, node_id, port),
                touched=lambda: self._shrink(keep=key),
            )
        with self._lock:
            self._entries[key] = entry
            self._order[key] = None
            self._order.move_to_end(key)
            for stale in [k for k in self._profiles if k[:2] == key]:
                del self._profiles[stale]
        self._shrink(keep=key)

    # ------------------------------------------------------------------ memória (spec 033, RF-3391)

    def memory_used(self) -> int:
        with self._lock:
            return sum(
                e.tables.in_memory()
                if isinstance(e.tables, StoredTables)
                else sum(int(df.estimated_size()) for df in e.tables.values())
                for e in self._entries.values()
            )

    def _shrink(self, keep: tuple[str, str]) -> None:
        """Acima do limite, as tabelas usadas há mais tempo ficam só no disco."""
        with self._lock:
            used = self.memory_used()
            if used <= self.memory_limit:
                return
            for key in list(self._order):
                tables = self._entries[key].tables if key in self._entries else None
                if key == keep or not isinstance(tables, StoredTables):
                    continue
                size = tables.in_memory()
                if not size:
                    continue
                tables.release()
                used -= size
                if used <= self.memory_limit:
                    return

    def _read(self, workflow_id: str, node_id: str, anchor: str) -> pl.DataFrame:
        path = self.cache_dir / _safe(workflow_id) / f"{_safe(node_id)}__{_safe(anchor)}.arrow"
        try:
            # Lê para a memória: um arquivo mapeado ficaria travado no Windows ao atualizar o cache.
            return pl.read_ipc(io.BytesIO(path.read_bytes()))
        except (OSError, pl.exceptions.PolarsError) as exc:
            self.drop(workflow_id, node_id)
            raise InvalidInputError(
                "O resultado guardado desta caixa não está mais no disco: execute o fluxo de novo."
            ) from exc

    # ------------------------------------------------------------------ pontos de cache (spec 012)

    def _frozen_dir(self, workflow_id: str) -> Path:
        return self.cache_dir / _safe(workflow_id) / "frozen"

    def freeze(self, workflow_id: str, node_id: str, entry: NodeEntry, signature: str) -> FrozenEntry:
        """Congela o resultado: memória + disco (tabelas em Arrow, metadados em JSON)."""
        frozen = FrozenEntry(signature, entry, datetime.now(UTC).isoformat(timespec="seconds"))
        with self._lock:
            self._frozen[(workflow_id, node_id)] = frozen
        folder = self._frozen_dir(workflow_id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for anchor, df in entry.tables.items():
                df.write_ipc(folder / f"{_safe(node_id)}__{_safe(anchor)}.arrow", compression="zstd")
            meta = {
                "signature": signature,
                "frozen_at": frozen.frozen_at,
                "ports": list(entry.tables),
                "has_models": bool(entry.models),
                "elapsed_ms": entry.elapsed_ms,
                "extra": entry.extra,
            }
            (folder / f"{_safe(node_id)}.json").write_text(json.dumps(meta, default=str), encoding="utf-8")
        except (OSError, TypeError, pl.exceptions.PolarsError) as exc:
            log.warning("Ponto de cache %s/%s ficou só em memória: %s", workflow_id, node_id, exc)
        return frozen

    def frozen(self, workflow_id: str, node_id: str) -> FrozenEntry | None:
        """Instantâneo do ponto de cache: da memória ou, depois de reiniciar, do disco."""
        with self._lock:
            cached = self._frozen.get((workflow_id, node_id))
        if cached is not None:
            return cached
        folder = self._frozen_dir(workflow_id)
        meta_path = folder / f"{_safe(node_id)}.json"
        if not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("has_models"):
                return None  # modelos de ML não vão para o disco: precisa treinar de novo
            tables = {
                # Lê para a memória: um arquivo mapeado ficaria travado no Windows ao atualizar o cache.
                port: pl.read_ipc(
                    io.BytesIO((folder / f"{_safe(node_id)}__{_safe(port)}.arrow").read_bytes())
                )
                for port in meta["ports"]
            }
        except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            log.warning("Ponto de cache ilegível %s/%s: %s", workflow_id, node_id, exc)
            return None
        entry = NodeEntry(
            fingerprint=f"frozen:{meta['signature']}",
            tables=tables,
            extra=meta.get("extra") or {},
            elapsed_ms=meta.get("elapsed_ms", 0.0),
        )
        loaded = FrozenEntry(meta["signature"], entry, meta.get("frozen_at", ""))
        with self._lock:
            self._frozen[(workflow_id, node_id)] = loaded
        return loaded

    def unfreeze(self, workflow_id: str, node_id: str) -> None:
        with self._lock:
            self._frozen.pop((workflow_id, node_id), None)
        folder = self._frozen_dir(workflow_id)
        for path in folder.glob(f"{_safe(node_id)}__*.arrow") if folder.is_dir() else []:
            path.unlink(missing_ok=True)
        (folder / f"{_safe(node_id)}.json").unlink(missing_ok=True)

    def prune_frozen(self, workflow_id: str, keep: set[str]) -> None:
        """Descarta instantâneos de caixas que deixaram de ser ponto de cache."""
        with self._lock:
            known = {k[1] for k in self._frozen if k[0] == workflow_id}
        folder = self._frozen_dir(workflow_id)
        if folder.is_dir():
            known |= {p.stem for p in folder.glob("*.json")}
        for node_id in known - {_safe(k) for k in keep} - keep:
            self.unfreeze(workflow_id, node_id)

    def drop(self, workflow_id: str, node_id: str) -> None:
        with self._lock:
            self._entries.pop((workflow_id, node_id), None)
            self._order.pop((workflow_id, node_id), None)

    def prune(self, workflow_id: str, keep: set[str]) -> None:
        """Remove entradas de nós que não existem mais no workflow."""
        with self._lock:
            for key in [k for k in self._entries if k[0] == workflow_id and k[1] not in keep]:
                del self._entries[key]
                self._order.pop(key, None)

    def clear_workflow(self, workflow_id: str) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == workflow_id]:
                del self._entries[key]
                self._order.pop(key, None)
        shutil.rmtree(self.cache_dir / _safe(workflow_id), ignore_errors=True)

    def table(self, workflow_id: str, node_id: str, anchor: str) -> pl.DataFrame | None:
        entry = self.get(workflow_id, node_id)
        return entry.tables.get(anchor) if entry else None

    def profile(self, workflow_id: str, node_id: str, anchor: str) -> dict[str, Any] | None:
        key = (workflow_id, node_id, anchor)
        with self._lock:
            if key in self._profiles:
                return self._profiles[key]
        df = self.table(workflow_id, node_id, anchor)
        if df is None:
            return None
        result = profiling.profile(df)
        with self._lock:
            self._profiles[key] = result
        return result

    def _persist(self, workflow_id: str, node_id: str, entry: NodeEntry) -> bool:
        """Grava as tabelas em Arrow. Devolve se todas foram gravadas."""
        folder = self.cache_dir / _safe(workflow_id)
        saved = True
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Não foi possível criar %s: %s", folder, exc)
            return False
        for anchor, df in entry.tables.items():
            path = folder / f"{_safe(node_id)}__{_safe(anchor)}.arrow"
            try:
                df.write_ipc(path, compression="zstd")
            except (OSError, pl.exceptions.PolarsError) as exc:
                log.warning("Não foi possível persistir %s: %s", path, exc)
                saved = False
        return saved
