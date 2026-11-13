"""Abertura protegida (spec 028): um fluxo de fora não executa nada até a pessoa confirmar.

A confiança vale para o conteúdo, guardado como uma impressão digital (hash) do fluxo, nunca o fluxo em si. Mudar o
arquivo fora do programa muda a impressão, e o fluxo volta ao modo protegido. As mudanças feitas no próprio
programa entram como confiáveis quando o fluxo já era confiável.

Quem decide é o servidor: a tela só mostra. Um fluxo bloqueado é recusado ao executar, qualquer que seja o caminho.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from prodata.domain.workflow import Workflow
from prodata.errors import ProdataError

log = logging.getLogger(__name__)
MAX_FINGERPRINTS = 20_000  # bem acima do uso real; evita que o arquivo cresça sem limite


class ProtectedWorkflowError(ProdataError):
    code = "protected"


def fingerprint(workflow: Workflow) -> str:
    """Impressão digital do conteúdo. Usa o modelo já lido, para o formato do arquivo não importar."""
    raw = json.dumps(workflow.model_dump(mode="json", by_alias=True), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TrustRegistry:
    """``confianca.json``: impressões digitais confiáveis e ids bloqueados. Só identificações, nada do conteúdo."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._trusted: dict[str, None] = {}  # dict mantém a ordem: os mais antigos saem primeiro
        self._blocked: set[str] = set()
        # Versão lida do disco por id: a tela completa a configuração com os padrões ao abrir, então o que ela
        # confirma não é idêntico ao arquivo. Confiar nas duas evita pedir confirmação de novo na próxima abertura.
        self._read: dict[str, str] = {}
        self.started = path.is_file()
        if self.started:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._trusted = dict.fromkeys(data.get("trusted", []))
                self._blocked = set(data.get("blocked", []))
            except OSError, ValueError, AttributeError:
                # Registro ilegível: na dúvida, ninguém é confiável até confirmar de novo.
                log.warning("Registro de confiança ilegível: os fluxos de fora pedirão confirmação de novo")

    # ------------------------------------------------------------------ gravação

    def _save(self) -> None:
        while len(self._trusted) > MAX_FINGERPRINTS:
            self._trusted.pop(next(iter(self._trusted)))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"version": 1, "trusted": list(self._trusted), "blocked": sorted(self._blocked)}, indent=1
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def start(self, workflows: list[Workflow]) -> None:
        """Na primeira vez (atualização para a 0.6), os fluxos da biblioteca já existentes começam confiáveis."""
        with self._lock:
            if self.started:
                return
            for workflow in workflows:
                self._trusted[fingerprint(workflow)] = None
            self.started = True
            self._save()

    # ------------------------------------------------------------------ consultas

    def is_blocked(self, workflow_id: str) -> bool:
        with self._lock:
            return workflow_id in self._blocked

    def check_runnable(self, workflow_id: str) -> None:
        if self.is_blocked(workflow_id):
            raise ProtectedWorkflowError(
                "Este fluxo veio de fora e está em modo protegido: nada foi executado. "
                "Confira o que ele faz na faixa do topo e escolha Confiar e executar."
            )

    # ------------------------------------------------------------------ eventos

    def opened(self, workflow: Workflow) -> bool:
        """Fluxo lido de um arquivo ou da biblioteca. Devolve se está liberado; se não, bloqueia o id."""
        with self._lock:
            fingerprint_now = fingerprint(workflow)
            self._read[workflow.id] = fingerprint_now
            trusted = fingerprint_now in self._trusted
            if trusted:
                return workflow.id not in self._blocked
            self._blocked.add(workflow.id)
            self._save()
            return False

    def created(self, workflow: Workflow) -> None:
        """Fluxo gerado pelo próprio programa, como o exemplo: confiável e liberado."""
        with self._lock:
            self._trusted[fingerprint(workflow)] = None
            self._blocked.discard(workflow.id)
            self._save()

    def confirm(self, workflow: Workflow) -> None:
        """A pessoa conferiu e confiou: vale o que está na tela e a versão que foi lida do arquivo."""
        with self._lock:
            self._trusted[fingerprint(workflow)] = None
            if read := self._read.pop(workflow.id, None):
                self._trusted[read] = None
            self._blocked.discard(workflow.id)
            self._save()

    def saved(self, workflow: Workflow) -> None:
        """Gravado pelo programa: a mudança feita aqui continua confiável, se o fluxo já era."""
        with self._lock:
            if workflow.id in self._blocked:
                return
            self._trusted[fingerprint(workflow)] = None
            self._save()


# ---------------------------------------------------------------- resumo do que o fluxo faz

_FORMULA_TOOLS = {"prep.formula", "prep.filter", "prep.multirow", "prep.multi_field"}


def summary(workflow: Workflow, names: dict[str, str]) -> list[dict[str, Any]]:
    """O que alguém precisa conferir antes de confiar: o que lê, o que chama, o que calcula e onde grava.

    ``names``: nome legível das consultas e APIs cadastradas (``sql:id`` e ``api:id``), quando existem aqui.
    """
    items: list[dict[str, Any]] = []
    for node in workflow.nodes:
        cfg = node.config
        label = node.label or node.type
        item: dict[str, Any] | None = None
        if node.type == "io.input_data":
            source = str(cfg.get("dataset") or "")
            kind = (
                "folder"
                if source.startswith("folder:")
                else "api"
                if source.startswith(("api:", "jira:"))
                else "query"
                if source.startswith("sql:")
                else "file"
            )
            known = names.get(source, source)
            missing = kind != "file" and source not in names
            item = {"kind": kind, "detail": known or "sem fonte escolhida", "missing": missing}
        elif node.type == "io.api_loop":
            key = f"api:{cfg.get('source') or ''}"
            item = {
                "kind": "api",
                "detail": f"uma chamada por linha · {names.get(key, cfg.get('source') or 'sem API')}",
                "missing": bool(cfg.get("source")) and key not in names,
            }
        elif node.type == "io.database_input":
            item = {"kind": "query", "detail": "consulta escrita na caixa", "missing": False}
        elif node.type == "io.input_folder":
            # Spec 033: quem recebe o fluxo precisa ver de qual pasta do computador ele lê.
            item = {
                "kind": "folder",
                "detail": f"{cfg.get('pattern') or '*'} em {cfg.get('folder') or 'pasta não escolhida'}",
                "missing": False,
            }
        elif node.type == "flow.subflow":
            key = f"flow:{cfg.get('workflow') or ''}"
            item = {
                "kind": "subflow",
                "detail": names.get(key, str(cfg.get("workflow") or "sem fluxo escolhido")),
                "missing": bool(cfg.get("workflow")) and key not in names,
            }
        elif node.type == "prep.regex":
            item = {"kind": "formula", "detail": str(cfg.get("pattern") or "")[:120], "missing": False}
        elif node.type == "transform.sql_query":
            item = {
                "kind": "sql",
                "detail": " ".join(str(cfg.get("sql") or "").split())[:120],
                "missing": False,
            }
        elif node.type in _FORMULA_TOOLS:
            texts = [str(f.get("expression") or "") for f in cfg.get("formulas", []) if isinstance(f, dict)]
            texts.append(
                str(cfg.get("expression") or "") if cfg.get("mode", "expression") == "expression" else ""
            )
            text = " · ".join(t for t in texts if t.strip())
            if not text:
                continue
            item = {"kind": "formula", "detail": " ".join(text.split())[:120], "missing": False}
        elif node.type == "io.output_data":
            folder = str(cfg.get("folder") or "pasta padrão de exportações")
            template = f" · lê o modelo {cfg['template']}" if cfg.get("template") else ""
            item = {
                "kind": "output",
                "detail": f"{cfg.get('filename') or 'saida'} em {folder}{template}",
                "missing": False,
            }
        if item:
            items.append({"node_id": node.id, "label": label, **item})
    return items
