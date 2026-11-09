"""Do Jira para a tabela (spec 030): colunas, texto simples, datas, carga incremental e retomada.

A carga guarda no disco o que já veio. Se cair no meio, a próxima continua de onde parou. Depois da primeira,
só o que mudou é buscado; a releitura completa existe porque o que foi excluído no Jira não aparece como mudança.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import polars as pl

from prodata.connectors.jira import JiraClient
from prodata.connectors.jira_model import JiraQuery
from prodata.connectors.jira_store import JiraStore

# Coluna da tabela -> campo do Jira.
BASE_COLUMNS = {
    "chave": "key",
    "projeto": "project",
    "tipo": "issuetype",
    "status": "status",
    "categoria_status": "statusCategory",
    "prioridade": "priority",
    "resumo": "summary",
    "responsavel": "assignee",
    "relator": "reporter",
    "criado_em": "created",
    "atualizado_em": "updated",
    "resolvido_em": "resolutiondate",
    "prazo": "duedate",
    "rotulos": "labels",
    "componentes": "components",
    "pai": "parent",
    "descricao": "description",
}
_DATES = {"criado_em", "atualizado_em", "resolvido_em"}
REQUESTED = [f for c, f in BASE_COLUMNS.items() if c not in ("chave", "categoria_status")]
HISTORY_SCHEMA = {
    "chave": pl.String,
    "mudanca_id": pl.String,
    "quando": pl.Datetime("us"),
    "autor": pl.String,
    "campo": pl.String,
    "de": pl.String,
    "para": pl.String,
}
COMMENT_SCHEMA = {
    "chave": pl.String,
    "comentario_id": pl.String,
    "autor": pl.String,
    "criado_em": pl.Datetime("us"),
    "atualizado_em": pl.Datetime("us"),
    "texto": pl.String,
}
CHANGED_MARGIN = timedelta(
    days=1
)  # o JQL compara em minutos e no fuso da conta: uma folga garante que nada escape
BATCH = 200
SEARCH_FIELDS = ["updated"]
PREVIEW_ROWS = 50


def adf_text(node: Any) -> str:
    """O formato de documento do Jira vira texto simples."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji", "status", "date"):
        attrs = node.get("attrs", {})
        return str(attrs.get("text") or attrs.get("shortName") or "")
    inner = "".join(adf_text(c) for c in node.get("content", []))
    return f"{inner}\n" if kind in ("paragraph", "heading", "listItem", "codeBlock", "blockquote") else inner


def plain(value: Any) -> Any:
    """Campo do Jira (usuário, opção, lista, documento) vira um valor de coluna."""
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return adf_text(value).strip()
        for key in ("displayName", "name", "value", "key"):
            if value.get(key) is not None:
                return str(value[key])
        return json.dumps(value, ensure_ascii=False)[:500]
    if isinstance(value, list):
        return ", ".join(str(plain(v)) for v in value if v is not None)
    return value


def to_local(value: Any) -> datetime | None:
    """Data do Jira (texto com fuso ou milissegundos) na hora local, sem fuso."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        moment = datetime.fromtimestamp(value / 1000, UTC)
    else:
        text = str(value)
        if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":  # ...-0300 -> ...-03:00
            text = f"{text[:-2]}:{text[-2:]}"
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone().replace(tzinfo=None)


def field_names(client: JiraClient) -> dict[str, str]:
    return {str(f["id"]): str(f["name"]) for f in client.fields()}


def issue_row(issue: dict[str, Any], custom: dict[str, str]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    row: dict[str, Any] = {}
    for column, source in BASE_COLUMNS.items():
        if column == "chave":
            row[column] = issue.get("key")
        elif column == "categoria_status":
            row[column] = plain(((fields.get("status") or {}).get("statusCategory") or {}).get("name"))
        elif column in _DATES:
            row[column] = to_local(fields.get(source))
        elif source == "project":
            row[column] = (fields.get("project") or {}).get("key")
        elif source == "parent":
            row[column] = (fields.get("parent") or {}).get("key")
        else:
            row[column] = plain(fields.get(source))
    for field_id, name in custom.items():
        value = plain(fields.get(field_id))
        row[name] = None if value is None else str(value)
    return row


def history_rows(key: str, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for change in changes:
        when = to_local(change.get("created"))
        author = plain(change.get("author"))
        for item in change.get("items", []):
            rows.append({
                "chave": key, "mudanca_id": str(change.get("id", "")), "quando": when, "autor": author,
                "campo": item.get("field"), "de": item.get("fromString"), "para": item.get("toString"),
            })  # fmt: skip
    return rows


def comment_rows(key: str, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chave": key, "comentario_id": str(c.get("id", "")), "autor": plain(c.get("author")),
            "criado_em": to_local(c.get("created")), "atualizado_em": to_local(c.get("updated")),
            "texto": adf_text(c.get("body")).strip(),
        }
        for c in comments
    ]  # fmt: skip


def _frame(rows: list[dict[str, Any]], schema: dict[str, Any] | None = None) -> pl.DataFrame:
    if schema is not None:
        return pl.DataFrame(rows, schema=schema)
    return pl.DataFrame(rows, infer_schema_length=None)


def _custom_columns(query: JiraQuery, names: dict[str, str]) -> dict[str, str]:
    taken = set(BASE_COLUMNS)
    found = {}
    for field_id in query.fields:
        label = names.get(field_id, field_id)
        while label in taken:
            label = f"{label}_jira"
        taken.add(label)
        found[field_id] = label
    return found


def preview(query: JiraQuery, client: JiraClient) -> tuple[pl.DataFrame, int]:
    """As primeiras linhas e o total aproximado, sem guardar nada."""
    jql = query.to_jql()
    total = client.count(jql)
    if query.table == "issues":
        custom = _custom_columns(query, field_names(client))
        issues, _ = next(client.search_pages(jql, [*REQUESTED, *custom], size=PREVIEW_ROWS))
        return _frame([issue_row(i, custom) for i in issues]), total
    issues, _ = next(client.search_pages(jql, SEARCH_FIELDS, size=20))
    return _detail_frame(query, client, issues).head(PREVIEW_ROWS), total


def _detail_frame(query: JiraQuery, client: JiraClient, issues: list[dict[str, Any]]) -> pl.DataFrame:
    if query.table == "history":
        by_id = client.changelogs([str(i["id"]) for i in issues]) if issues else {}
        rows = [r for i in issues for r in history_rows(str(i["key"]), by_id.get(str(i["id"]), []))]
        return _frame(rows, HISTORY_SCHEMA)
    rows = [r for i in issues for r in comment_rows(str(i["key"]), client.comments_of(str(i["key"])))]
    return _frame(rows, COMMENT_SCHEMA)


class Loader:
    """Uma carga: completa, retomada ou só com o que mudou."""

    def __init__(
        self, query: JiraQuery, store: JiraStore, client: JiraClient, report: Callable[[str], None]
    ) -> None:
        self.query = query
        self.client = client
        self.report = report
        self.table = store.local_path(query.id, "parquet")
        self.partial = store.local_path(query.id, "parcial.parquet")
        self.meta_path = store.local_path(query.id, "json")
        self.progress_path = store.local_path(query.id, "progresso.json")

    def meta(self) -> dict[str, Any]:
        if not self.meta_path.is_file():
            return {}
        data: dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return data if data.get("digest") == self.query.digest() and self.table.is_file() else {}

    def _progress(self) -> dict[str, Any]:
        if not (self.progress_path.is_file() and self.partial.is_file()):
            return {}
        data: dict[str, Any] = json.loads(self.progress_path.read_text(encoding="utf-8"))
        return data if data.get("digest") == self.query.digest() else {}

    def _checkpoint(self, frame: pl.DataFrame, **state: Any) -> None:
        tmp = self.partial.with_suffix(".tmp")
        frame.write_parquet(tmp)
        os.replace(tmp, self.partial)
        self.progress_path.write_text(json.dumps({"digest": self.query.digest(), **state}), encoding="utf-8")

    def _finish(self, frame: pl.DataFrame, started: datetime, full: bool, before: dict[str, Any]) -> None:
        tmp = self.table.with_suffix(".tmp")
        frame.write_parquet(tmp)
        os.replace(tmp, self.table)
        self.meta_path.write_text(json.dumps({
            "digest": self.query.digest(), "synced_at": started.isoformat(),
            "full_at": started.isoformat() if full else before.get("full_at"), "rows": frame.height,
            "calls": self.client.calls,
        }), encoding="utf-8")  # fmt: skip
        self.partial.unlink(missing_ok=True)
        self.progress_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ demandas

    def _issues_full(self, resume: dict[str, Any], custom: dict[str, str]) -> pl.DataFrame:
        frame = pl.read_parquet(self.partial) if resume else None
        token = resume.get("token")
        fields = [*REQUESTED, *custom]
        for issues, next_token in self.client.search_pages(self.query.to_jql(), fields, token=token):
            page = _frame([issue_row(i, custom) for i in issues])
            frame = page if frame is None else pl.concat([frame, page], how="diagonal_relaxed")
            self.report(f"{frame.height:,} demandas lidas".replace(",", "."))
            if next_token:
                self._checkpoint(frame, stage="issues", token=next_token)
        return frame if frame is not None else pl.DataFrame({c: [] for c in BASE_COLUMNS})

    def _issues_changed(self, since: str, custom: dict[str, str]) -> pl.DataFrame:
        old = pl.read_parquet(self.table)
        fields = [*REQUESTED, *custom]
        fresh: list[dict[str, Any]] = []
        for issues, _ in self.client.search_pages(self.query.changed_since(since), fields):
            fresh += [issue_row(i, custom) for i in issues]
        if not fresh:
            return old
        page = _frame(fresh)
        return pl.concat(
            [old.join(page.select("chave"), on="chave", how="anti"), page], how="diagonal_relaxed"
        ).sort("criado_em")

    # ------------------------------------------------------------------ histórico e comentários

    def _all_issues(self, jql: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for issues, _ in self.client.search_pages(jql, SEARCH_FIELDS):
            found += issues
        return found

    def _details_full(self, resume: dict[str, Any]) -> pl.DataFrame:
        issues = self._all_issues(self.query.to_jql())
        done = set(resume.get("done", []))
        schema = HISTORY_SCHEMA if self.query.table == "history" else COMMENT_SCHEMA
        frame = pl.read_parquet(self.partial) if resume else pl.DataFrame(schema=cast(Any, schema))
        pending = [i for i in issues if i["key"] not in done]
        for start in range(0, len(pending), BATCH):
            chunk = pending[start : start + BATCH]
            frame = pl.concat([frame, _detail_frame(self.query, self.client, chunk)])
            done.update(i["key"] for i in chunk)
            self.report(f"{len(done):,} de {len(issues):,} demandas".replace(",", "."))
            self._checkpoint(frame, stage="details", done=sorted(done))
        return frame

    def _details_changed(self, since: str) -> pl.DataFrame:
        old = pl.read_parquet(self.table)
        issues = self._all_issues(self.query.changed_since(since))
        if not issues:
            return old
        fresh = pl.concat(
            [
                _detail_frame(self.query, self.client, issues[i : i + BATCH])
                for i in range(0, len(issues), BATCH)
            ]
        )
        keys = pl.DataFrame({"chave": [i["key"] for i in issues]})
        return pl.concat([old.join(keys, on="chave", how="anti"), fresh]).sort(
            "chave", "quando" if self.query.table == "history" else "criado_em"
        )

    # ------------------------------------------------------------------ carga

    def run(self, *, full: bool = False) -> pl.DataFrame:
        started = datetime.now(UTC)
        before = self.meta()
        changed_only = bool(before) and not full
        custom = _custom_columns(self.query, field_names(self.client)) if self.query.table == "issues" else {}
        if changed_only:
            since = (datetime.fromisoformat(before["synced_at"]) - CHANGED_MARGIN).strftime("%Y-%m-%d %H:%M")
            frame = (
                self._issues_changed(since, custom)
                if self.query.table == "issues"
                else self._details_changed(since)
            )
        else:
            resume = self._progress()
            if resume:
                self.report("Continuando de onde parou")
            frame = (
                self._issues_full(resume, custom)
                if self.query.table == "issues"
                else self._details_full(resume)
            )
        self._finish(frame, started, not changed_only, before)
        return frame


def load(
    query: JiraQuery, store: JiraStore, *, full: bool = False, report: Callable[[str], None] = lambda _t: None
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Traz a consulta e devolve a tabela e o que aconteceu na carga."""
    with store.client(query.connection, report=report) as client:
        loader = Loader(query, store, client, report)
        changed_only = bool(loader.meta()) and not full
        frame = loader.run(full=full)
        return frame, {"calls": client.calls, "incremental": changed_only, **loader.meta()}


def status(query: JiraQuery, store: JiraStore) -> dict[str, Any]:
    loader = Loader(query, store, None, lambda _t: None)  # type: ignore[arg-type]
    meta = loader.meta()
    return {
        "synced_at": meta.get("synced_at"),
        "full_at": meta.get("full_at"),
        "rows": meta.get("rows"),
        "interrupted": bool(loader._progress()),
    }
