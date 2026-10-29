"""Ferramentas de enriquecimento de texto.

O único provedor disponível é ``local-heuristic``: regras determinísticas que
simulam a saída de um LLM, para demonstrar o fluxo sem custo nem chave de API.
Um provedor real deve ler a chave de uma variável de ambiente, nunca do workflow.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import polars as pl
from pydantic import Field

from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, ToolConfig, tool

_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_PROVIDER_LABELS = {"local-heuristic": "Heurística local (simulado)"}


def render_template(template: str, row: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: "" if row.get(m.group(1)) is None else str(row[m.group(1)]), template)


def _recommend(row: dict[str, Any]) -> tuple[str, str]:
    def num(key: str, default: float) -> float:
        value = row.get(key)
        return float(value) if isinstance(value, int | float) else default

    mrr, nps = num("mrr_mensal", 0.0), num("nps", 7)
    at_risk = str(row.get("status", "")).upper() == "RISCO" or bool(row.get("inadimplente")) or nps <= 5
    if at_risk:
        return "Retenção prioritária: agendar revisão executiva em 48h e plano de sucesso.", "Risco"
    if mrr >= 4500 or nps >= 9:
        return "Expansão: conta madura, oferecer módulos adicionais.", "Oportunidade"
    return "Nutrição: acompanhar adoção mensal e oferecer treinamento.", "Estável"


class PromptConfig(ToolConfig):
    provider: Literal["local-heuristic"] = Field(
        "local-heuristic", title="Provedor", json_schema_extra=ui(labels=_PROVIDER_LABELS)
    )
    prompt_template: str = Field(
        "Analise o cliente {{nome_empresa}} ({{segmento}}) e sugira a próxima ação.",
        title="Prompt",
        description="Use {{coluna}} para inserir valores da linha.",
        json_schema_extra=ui(widget="template"),
    )
    output_column: str = Field("ia_recomendacao", title="Coluna de saída")
    include_prompt: bool = Field(False, title="Incluir prompt renderizado")
    include_label: bool = Field(True, title="Incluir classificação")


@tool(
    type="genai.llm_prompt",
    name="Prompt Column",
    category="genai",
    icon="bot",
    description="Gera uma coluna de texto por linha a partir de um prompt. Provedor atual: heurística local (simulado).",
    config=PromptConfig,
    annotate=lambda c: f"→ {c.output_column}",
)
def llm_prompt(ctx: NodeContext, cfg: PromptConfig) -> NodeOutput:
    df = ctx.input()
    rows = df.to_dicts()
    results = [_recommend(r) for r in rows]
    cols = [pl.Series(cfg.output_column, [r[0] for r in results], dtype=pl.String)]
    if cfg.include_label:
        cols.append(pl.Series(f"{cfg.output_column}_classe", [r[1] for r in results], dtype=pl.String))
    if cfg.include_prompt:
        cols.append(
            pl.Series(
                f"{cfg.output_column}_prompt",
                [render_template(cfg.prompt_template, r) for r in rows],
                dtype=pl.String,
            )
        )
    return NodeOutput(tables={"out": df.with_columns(cols)})


_NEGATIVE = ("cancelar", "duplicada", "erro", "timeout", "urgente", "lentidão", "falha", "reclama")
_POSITIVE = ("excelente", "satisfeita", "expandir", "economizou", "aumentou", "ótimo", "parabéns")


def _extract(text: str) -> tuple[str, str, float, str]:
    low = text.lower()
    if any(w in low for w in _NEGATIVE):
        topic = "Financeiro" if any(w in low for w in ("fatura", "cobrança", "estorno")) else "Infraestrutura"
        return "Negativo", topic, 85.0, "Escalar para o time responsável"
    if any(w in low for w in _POSITIVE):
        return "Positivo", "Expansão", 10.0, "Encaminhar para o executivo de contas"
    return "Neutro", "Dúvida operacional", 25.0, "Enviar documentação e agendar treinamento"


class ExtractorConfig(ToolConfig):
    provider: Literal["local-heuristic"] = Field(
        "local-heuristic", title="Provedor", json_schema_extra=ui(labels=_PROVIDER_LABELS)
    )
    source_column: str = Field("", title="Coluna de texto", json_schema_extra=ui(widget="column"))
    prefix: str = Field("ia_", title="Prefixo das colunas geradas")


@tool(
    type="genai.structured_extractor",
    name="Text Extractor",
    category="genai",
    icon="braces",
    description="Extrai sentimento, tópico, risco e ação sugerida de um texto livre. Provedor atual: heurística local.",
    config=ExtractorConfig,
    annotate=lambda c: f"de {c.source_column}" if c.source_column else "Escolha a coluna",
)
def structured_extractor(ctx: NodeContext, cfg: ExtractorConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.source_column not in df.columns:
        raise ValueError("Escolha a coluna de texto.")
    parsed = [_extract(t or "") for t in df[cfg.source_column].cast(pl.String).to_list()]
    p = cfg.prefix
    return NodeOutput(
        tables={
            "out": df.with_columns(
                pl.Series(f"{p}sentimento", [x[0] for x in parsed], dtype=pl.String),
                pl.Series(f"{p}topico", [x[1] for x in parsed], dtype=pl.String),
                pl.Series(f"{p}risco_pct", [x[2] for x in parsed], dtype=pl.Float64),
                pl.Series(f"{p}acao_sugerida", [x[3] for x in parsed], dtype=pl.String),
            )
        }
    )
