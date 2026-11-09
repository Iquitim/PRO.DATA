"""Conexões e consultas do Jira Cloud (spec 030). O token e o e-mail ficam no cofre, nunca aqui."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from prodata.domain.workflow import ID_PATTERN
from prodata.errors import InvalidInputError

SOURCE_PREFIX = "jira:"
SITE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*\.atlassian\.net$")
TABLES = {"issues": "Demandas", "history": "Histórico de alterações", "comments": "Comentários"}
_ORDER_BY = re.compile(r"\border\s+by\b.*$", re.IGNORECASE | re.DOTALL)
Table = Literal["issues", "history", "comments"]


def source_jira_id(source: str) -> str | None:
    return source[len(SOURCE_PREFIX) :] if source.startswith(SOURCE_PREFIX) else None


def normalize_site(text: str) -> str:
    """Aceita o endereço como vier: com https, com o caminho de uma página do Jira ou só o nome."""
    raw = text.strip().lower()
    host = urlsplit(raw if "//" in raw else f"//{raw}").hostname or ""
    if "." not in host and host:
        host = f"{host}.atlassian.net"
    if not SITE_PATTERN.match(host):
        raise InvalidInputError(f'"{text}" não parece um Jira Cloud. O endereço termina em .atlassian.net.')
    return host


class JiraConnection(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    site: str

    @field_validator("site")
    @classmethod
    def _site(cls, value: str) -> str:
        return normalize_site(value)


class JiraInfo(JiraConnection):
    has_token: bool = False
    email: str = ""


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _clause(field: str, values: list[str]) -> str:
    return f"{field} in ({', '.join(_quoted(v) for v in values)})"


class JiraQueryDefinition(BaseModel):
    connection: str = Field(min_length=1)
    table: Table = "issues"
    projects: list[str] = Field(default_factory=list)
    issue_types: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    period_field: Literal["created", "updated", "resolved"] = "created"
    period_days: int = Field(0, ge=0, le=36500)
    advanced: bool = False
    jql: str = Field("", max_length=8000)
    # Campos do Jira que viram coluna, além dos de sempre. Vazio: só os de sempre.
    fields: list[str] = Field(default_factory=list)

    def to_jql(self) -> str:
        """O JQL que vai ao Jira. Sem ordem definida, do mais antigo para o mais novo."""
        if self.advanced:
            jql = self.jql.strip()
            if not jql:
                raise InvalidInputError("Escreva o JQL ou volte para os filtros.")
            return jql
        parts = []
        if self.projects:
            parts.append(_clause("project", self.projects))
        if self.issue_types:
            parts.append(_clause("issuetype", self.issue_types))
        if self.statuses:
            parts.append(_clause("status", self.statuses))
        if self.assignees:
            parts.append(_clause("assignee", self.assignees))
        if self.period_days:
            parts.append(f"{self.period_field} >= -{self.period_days}d")
        if not parts:
            raise InvalidInputError("Escolha ao menos um projeto: o Jira não aceita uma busca sem limite.")
        return f"{' AND '.join(parts)} ORDER BY created ASC"

    def changed_since(self, moment: str) -> str:
        """O mesmo recorte, só com o que mudou desde ``moment`` (AAAA-MM-DD HH:MM)."""
        body = _ORDER_BY.sub("", self.to_jql()).strip()
        return f'({body}) AND updated >= "{moment}" ORDER BY updated ASC'


class JiraQuery(JiraQueryDefinition):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)

    def digest(self) -> str:
        """Muda quando a definição muda: o guardado local deixa de valer."""
        data = self.model_dump(mode="json", exclude={"name"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
