"""API Loop: uma chamada por linha, com ritmo, limite de pedidos e parada por falhas (spec 021 e 026)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import polars as pl

from prodata.connectors.api import ApiClient
from prodata.connectors.api_model import ApiDefinition, ApiError, RequestLimitError
from prodata.connectors.api_records import rows_to_frame


class _Pace:
    """Distribui as chamadas no tempo, somando todas as threads."""

    def __init__(self, per_second: float) -> None:
        self.gap = 1 / per_second if per_second > 0 else 0.0
        self.next = 0.0
        self.lock = threading.Lock()

    def __call__(self) -> None:
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.gap
        if start > now:
            time.sleep(start - now)


LOOP_CALL = "__pd_chamada"


@dataclass
class LoopResult:
    table: pl.DataFrame
    errors: pl.DataFrame
    calls: int
    failed: int
    truncated: int
    # Pedidos reais à API, com páginas e novas tentativas.
    requests: int = 0
    # Por que a caixa parou antes de chamar tudo.
    stopped: str = ""


def run_loop(
    df: pl.DataFrame,
    source: ApiDefinition,
    secret: Callable[[str], str | None],
    *,
    concurrency: int = 4,
    per_second: float = 5,
    max_calls: int = 1000,
    stop_on_error: bool = False,
    keep_columns: bool = True,
    progress: Callable[[int, int], None] | None = None,
    columns: dict[str, str] | None = None,
    stop_after_failures: int = 10,
) -> LoopResult:
    """Chama a API uma vez para cada combinação de valores e junta as respostas às linhas de entrada.

    ``columns`` diz de qual coluna vem cada variável; sem escolha, vale a coluna de mesmo nome.
    """
    source.check()
    origin = _columns_of_variables(source, df, columns)
    used = list(dict.fromkeys(origin.values()))
    calls = df.select(used).unique(maintain_order=True).with_row_index(LOOP_CALL)
    if calls.height > max_calls:
        raise ApiError(
            f"A tabela pede {calls.height:_} chamadas e o limite desta caixa está em {max_calls:_} pedidos. ".replace(
                "_", "."
            )
            + "Filtre a tabela ou aumente o limite, se a API aguentar."
        )
    run = _LoopRun(origin, calls.height, stop_on_error, stop_after_failures, progress)
    with (
        ApiClient(source, secret, pace=_Pace(per_second), request_limit=max_calls) as client,
        ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool,
    ):
        list(pool.map(lambda item: run.call(client, item), calls.to_dicts()))
    if stop_on_error and run.errors:
        raise ApiError(f"O loop parou no primeiro erro: {run.first_error or run.errors[min(run.errors)][0]}")
    result = _loop_tables(df, calls, used, run.rows, run.errors, keep_columns, run.truncated)
    result.requests = client.requests
    result.stopped = run.stopped
    return result


def _columns_of_variables(
    source: ApiDefinition, df: pl.DataFrame, columns: dict[str, str] | None
) -> dict[str, str]:
    """De qual coluna vem cada variável do endereço, ou o erro que explica o que falta."""
    wanted = source.placeholders()
    if not wanted:
        raise ApiError(
            "Esta API não pede nenhuma variável: use o Input Data. "
            "Para o endereço mudar a cada chamada, escreva o nome entre chaves nele, como {sigla}."
        )
    origin = {p: (columns or {}).get(p) or p for p in wanted}
    if missing := [p for p in wanted if origin[p] not in df.columns]:
        names = ", ".join("{" + p + "}" for p in missing)
        raise ApiError(
            f"A API pede {names}, mas a tabela de entrada não tem essa coluna. Escolha a coluna no API Loop. "
            f"A tabela traz: {', '.join(df.columns)[:200]}."
        )
    return origin


class _LoopRun:
    """O andamento de um loop, somando as threads: respostas, erros e quando parar."""

    def __init__(
        self,
        origin: dict[str, str],
        total: int,
        stop_on_error: bool,
        stop_after_failures: int,
        progress: Callable[[int, int], None] | None,
    ) -> None:
        self.origin = origin
        self.total = total
        self.stop_on_error = stop_on_error
        self.stop_after_failures = stop_after_failures
        self.progress = progress
        self.rows: dict[int, list[dict[str, Any]]] = {}
        self.errors: dict[int, tuple[str, int | None]] = {}
        self.truncated = 0
        self.done = 0
        self.in_a_row = 0
        self.stopped = ""
        self.first_error = ""
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def halt(self, reason: str) -> None:
        self.stopped = self.stopped or reason
        self.stop.set()

    def call(self, client: ApiClient, item: dict[str, Any]) -> None:
        index = int(item[LOOP_CALL])
        values = {p: item[column] for p, column in self.origin.items()}
        try:
            if self.stop.is_set():
                self.errors[index] = (f"Não foi chamada: {self.stopped}", None)
                return
            if empty := [p for p, v in values.items() if v is None]:
                raise ApiError(f"Valor vazio em [{self.origin[empty[0]]}]: a chamada não foi feita.")
            result = client.fetch(values)
            self.rows[index] = result.rows
            with self.lock:
                self.in_a_row = 0
                if result.truncated:
                    self.truncated += 1
        except RequestLimitError as exc:
            self.errors[index] = (exc.message, None)
            self.halt(exc.message)
        except ApiError as exc:
            self._failed(index, exc)
        finally:
            with self.lock:
                self.done += 1
                if self.progress:
                    self.progress(self.done, self.total)

    def _failed(self, index: int, exc: ApiError) -> None:
        self.errors[index] = (exc.message, exc.status)
        with self.lock:
            self.first_error = self.first_error or exc.message
            self.in_a_row += 1
            many = self.stop_after_failures and self.in_a_row >= self.stop_after_failures
        if self.stop_on_error:
            self.stop.set()
        elif many:
            self.halt(
                f"a caixa parou depois de {self.stop_after_failures} falhas seguidas. A última: {exc.message}"
            )


def _loop_tables(
    df: pl.DataFrame,
    calls: pl.DataFrame,
    used: list[str],
    rows: dict[int, list[dict[str, Any]]],
    errors: dict[int, tuple[str, int | None]],
    keep_columns: bool,
    truncated: int,
) -> LoopResult:
    position = "__pd_ordem"
    ok_rows = [{LOOP_CALL: i, **r} for i in sorted(rows) for r in rows[i]]
    answered = rows_to_frame(ok_rows) if ok_rows else pl.DataFrame({LOOP_CALL: pl.Series([], dtype=pl.Int64)})
    answered = answered.with_columns(pl.col(LOOP_CALL).cast(pl.UInt32))
    linked = df.join(calls, on=used, how="left", nulls_equal=True, maintain_order="left")
    failed = pl.DataFrame(
        {
            LOOP_CALL: pl.Series(list(errors), dtype=pl.UInt32),
            "erro": pl.Series([e[0] for e in errors.values()], dtype=pl.String),
            "status_http": pl.Series([e[1] for e in errors.values()], dtype=pl.Int64),
        }
    )
    bad = linked.join(failed, on=LOOP_CALL, how="inner", maintain_order="left").drop(LOOP_CALL)
    good = linked.filter(pl.col(LOOP_CALL).is_in(list(rows)))
    if keep_columns:
        clash = {c: f"{c}_api" for c in answered.columns if c in df.columns}
        answered = answered.rename(clash)
    else:
        good = good.select(LOOP_CALL)
    table = (
        good.with_row_index(position)
        .join(answered, on=LOOP_CALL, how="left", maintain_order="left")
        .sort(position, maintain_order=True)
        .drop(position, LOOP_CALL)
    )
    return LoopResult(table, bad, calls.height, len(errors), truncated)
