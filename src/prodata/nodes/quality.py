"""Data Quality (spec 028, RF-2831..2837): confere cada linha contra regras prontas, sem escrever fórmula.

O que passa em todas as regras sai por P; o que falha em alguma sai por F, com as colunas ``regra`` e ``motivo``.
Vazio passa nas regras de formato (CPF, e-mail, faixa...): quem cobra o preenchimento é a regra "Não vazio",
para cada falha ter um motivo só.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from prodata.engine import formula
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

QualityKind = Literal[
    "not_empty", "unique", "cpf", "cnpj", "email", "number_range", "date", "allowed", "formula"
]
RULE_NAMES: dict[str, str] = {
    "not_empty": "Não vazio",
    "unique": "Sem duplicados",
    "cpf": "CPF válido",
    "cnpj": "CNPJ válido",
    "email": "E-mail válido",
    "number_range": "Número na faixa",
    "date": "Data válida",
    "allowed": "Valor permitido",
    "formula": "Fórmula livre",
}
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s.]+$"
_ALL_BUT_FORMULA = [k for k in RULE_NAMES if k != "formula"]


class QualityRule(BaseModel):
    kind: QualityKind = Field("not_empty", title="Regra", json_schema_extra=ui(labels=RULE_NAMES))
    column: str = Field(
        "", title="Coluna", json_schema_extra=ui(widget="column", show_if={"kind": _ALL_BUT_FORMULA})
    )
    also: list[str] = Field(
        default_factory=list,
        title="Junto com",
        description="Opcional: a repetição conta a combinação destas colunas com a coluna acima.",
        json_schema_extra=ui(widget="columns", show_if={"kind": ["unique"]}),
    )
    min: float | None = Field(None, title="Mínimo", json_schema_extra=ui(show_if={"kind": ["number_range"]}))
    max: float | None = Field(None, title="Máximo", json_schema_extra=ui(show_if={"kind": ["number_range"]}))
    date_min: str = Field(
        "",
        title="A partir de",
        description="AAAA-MM-DD. Vazio: sem limite.",
        json_schema_extra=ui(show_if={"kind": ["date"]}),
    )
    date_max: str = Field(
        "",
        title="Até",
        description="AAAA-MM-DD. Vazio: sem limite.",
        json_schema_extra=ui(show_if={"kind": ["date"]}),
    )
    not_future: bool = Field(
        False, title="Não pode ser no futuro", json_schema_extra=ui(show_if={"kind": ["date"]})
    )
    values_from: Literal["list", "table"] = Field(
        "list",
        title="De onde vem a lista",
        json_schema_extra=ui(
            labels={"list": "Digitar os valores", "table": "De outra tabela, pela entrada L"},
            show_if={"kind": ["allowed"]},
        ),
    )
    values: list[str] = Field(
        default_factory=list,
        title="Valores permitidos",
        json_schema_extra=ui(widget="allowed_values", show_if={"kind": ["allowed"], "values_from": ["list"]}),
    )
    list_column: str = Field(
        "",
        title="Coluna da lista [L]",
        description="Cada valor que aparece nesta coluna vale como permitido. Vazios são ignorados.",
        json_schema_extra=ui(
            widget="column", port="L", show_if={"kind": ["allowed"], "values_from": ["table"]}
        ),
    )
    ignore_case: bool = Field(
        True, title="Sem diferenciar maiúsculas", json_schema_extra=ui(show_if={"kind": ["allowed"]})
    )
    expression: str = Field(
        "",
        title="A linha passa quando",
        description="Ex.: [idade] >= 18 AND [uf] != 'XX'",
        json_schema_extra=ui(widget="expression", show_if={"kind": ["formula"]}),
    )
    message: str = Field(
        "",
        title="Motivo quando falha",
        description="Opcional. Vazio: mostra a fórmula.",
        json_schema_extra=ui(show_if={"kind": ["formula"]}),
    )


class QualityConfig(ToolConfig):
    rules: list[QualityRule] = Field(
        default_factory=list, title="Regras", json_schema_extra=ui(widget="quality_rules")
    )
    stop: Literal["never", "any", "pct"] = Field(
        "never",
        title="Interromper o fluxo",
        description="A caixa fica em erro e nada do que vem depois dela executa.",
        json_schema_extra=ui(
            group="Controle",
            labels={
                "never": "Nunca: o que falha sai em F",
                "any": "Se qualquer linha falhar",
                "pct": "Se falhar mais do que uma porcentagem",
            },
        ),
    )
    stop_pct: float = Field(
        5,
        ge=0,
        le=100,
        title="Porcentagem de falha aceita (%)",
        json_schema_extra=ui(group="Controle", show_if={"stop": ["pct"]}, step=0.5),
    )


# ------------------------------------------------------------------ CPF e CNPJ


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def valid_cpf(text: str) -> bool:
    """Com ou sem pontos e traço. Onze dígitos iguais têm dígito verificador certo, mas não são CPF."""
    d = _digits(text)
    if len(d) != 11 or len(set(d)) == 1 or re.search(r"[^\d.\-\s]", text):
        return False
    for size in (9, 10):
        total = sum(int(d[i]) * (size + 1 - i) for i in range(size))
        if (total * 10 % 11) % 10 != int(d[size]):
            return False
    return True


def valid_cnpj(text: str) -> bool:
    """Numérico ou alfanumérico (Receita Federal, a partir de julho de 2026): a letra vale o código ASCII menos 48."""
    raw = re.sub(r"[.\-/\s]", "", text.strip().upper())
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", raw) or len(set(raw)) == 1:
        return False
    values = [ord(c) - 48 for c in raw]
    for size in (12, 13):
        weights = (
            [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if size == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        )
        rest = sum(v * w for v, w in zip(values[:size], weights, strict=True)) % 11
        if (0 if rest < 2 else 11 - rest) != values[size]:
            return False
    return True


# ------------------------------------------------------------------ regras


def _text(df: pl.DataFrame, column: str) -> pl.Series:
    return df[column].cast(pl.String, strict=False)


def _filled(text: pl.Series) -> pl.Series:
    return text.is_not_null() & (text.str.strip_chars() != "")


def _checked(text: pl.Series, check: Any) -> pl.Series:
    """Aplica a verificação uma vez por valor distinto: cadastros repetem muito o mesmo valor."""
    unique = text.drop_nulls().unique()
    lookup = dict(zip(unique.to_list(), [bool(check(v)) for v in unique.to_list()], strict=True))
    return text.replace_strict(lookup, default=True, return_dtype=pl.Boolean)


def _as_date(series: pl.Series) -> pl.Series:
    if series.dtype == pl.Date:
        return series
    if isinstance(series.dtype, pl.Datetime):
        return series.dt.date()
    text = series.cast(pl.String, strict=False).str.strip_chars()
    return pl.select(
        pl.coalesce(
            text.str.to_date("%d/%m/%Y", strict=False),
            text.str.to_date("%Y-%m-%d", strict=False),
            text.str.to_date("%d-%m-%Y", strict=False),
        )
    ).to_series()


def _number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


Failure = tuple[pl.Series, str]


def _formula_rule(df: pl.DataFrame, rule: QualityRule) -> Failure:
    if not rule.expression.strip():
        raise ValueError("Escreva a fórmula da regra Fórmula livre.")
    reason = rule.message.strip() or f"Não atende a: {rule.expression.strip()}"
    return ~formula.evaluate_mask(df, rule.expression), reason


def _not_empty(df: pl.DataFrame, rule: QualityRule) -> Failure:
    return ~_filled(_text(df, rule.column)), f"Vazio em [{rule.column}]"


def _unique(df: pl.DataFrame, rule: QualityRule) -> Failure:
    keys = [rule.column, *[c for c in rule.also if c and c != rule.column]]
    if missing := [c for c in keys if c not in df.columns]:
        raise ValueError(f"Coluna(s) inexistente(s) na regra Sem duplicados: {', '.join(missing)}")
    names = "], [".join(keys)
    return df.select(pl.struct(keys).is_duplicated()).to_series(), f"Repetido em [{names}]"


def _document(check: Any, label: str) -> Any:
    def run(df: pl.DataFrame, rule: QualityRule) -> Failure:
        text = _text(df, rule.column)
        return _filled(text) & ~_checked(text, check), f"{label} inválido em [{rule.column}]"

    return run


def _email(df: pl.DataFrame, rule: QualityRule) -> Failure:
    text = _text(df, rule.column)
    return _filled(text) & ~text.str.strip_chars().str.contains(EMAIL), f"E-mail inválido em [{rule.column}]"


def _number_range(df: pl.DataFrame, rule: QualityRule) -> Failure:
    col = rule.column
    if not df[col].dtype.is_numeric():
        raise ValueError(f"A regra Número na faixa vale para colunas de número: [{col}] não é.")
    values = df[col].cast(pl.Float64)
    none = pl.Series([False] * df.height)
    low = values < rule.min if rule.min is not None else none
    high = values > rule.max if rule.max is not None else none
    lo = _number(rule.min) if rule.min is not None else "…"
    hi = _number(rule.max) if rule.max is not None else "…"
    return (low | high).fill_null(False), f"Fora da faixa de {lo} a {hi} em [{col}]"


def _date(df: pl.DataFrame, rule: QualityRule) -> Failure:
    col = rule.column
    dates = _as_date(df[col])
    bad = _filled(_text(df, col)) & dates.is_null()
    if rule.date_min.strip():
        bad = bad | (dates < date.fromisoformat(rule.date_min.strip())).fill_null(False)
    if rule.date_max.strip():
        bad = bad | (dates > date.fromisoformat(rule.date_max.strip())).fill_null(False)
    if rule.not_future:
        bad = bad | (dates > date.today()).fill_null(False)
    return bad, f"Data inválida ou fora do período em [{col}]"


def list_values(rule: QualityRule, lists: pl.DataFrame | None) -> list[str]:
    """A lista permitida: a digitada, ou os valores da coluna escolhida na entrada L (sem vazios)."""
    if rule.values_from == "list":
        return [v.strip() for v in rule.values if v.strip()]
    if lists is None:
        raise ValueError(f"Conecte na entrada [L] a tabela com os valores permitidos de [{rule.column}].")
    if not rule.list_column:
        raise ValueError(f"Escolha a coluna de [L] com os valores permitidos de [{rule.column}].")
    if rule.list_column not in lists.columns:
        raise ValueError(f"A coluna [{rule.list_column}] não existe na entrada [L].")
    text = _text(lists, rule.list_column).str.strip_chars()
    return text.filter(text.is_not_null() & (text != "")).unique(maintain_order=True).to_list()


def _allowed(df: pl.DataFrame, rule: QualityRule) -> Failure:
    col = rule.column
    allowed = [v.strip() for v in rule.values if v.strip()]
    if not allowed and rule.values_from == "table":
        raise ValueError(
            f"A coluna [{rule.list_column}] da entrada [L] está vazia: não há valores permitidos."
        )
    if not allowed:
        raise ValueError(f"Informe os valores permitidos da regra em [{col}].")
    text = _text(df, col)
    norm = text.str.strip_chars()
    if rule.ignore_case:
        norm = norm.str.to_lowercase()
        allowed = [v.lower() for v in allowed]
    return _filled(text) & ~norm.is_in(allowed), f"Valor fora da lista em [{col}]"


CHECKS: dict[str, Any] = {
    "formula": _formula_rule,
    "not_empty": _not_empty,
    "unique": _unique,
    "cpf": _document(valid_cpf, "CPF"),
    "cnpj": _document(valid_cnpj, "CNPJ"),
    "email": _email,
    "number_range": _number_range,
    "date": _date,
    "allowed": _allowed,
}


def rule_failures(df: pl.DataFrame, rule: QualityRule) -> Failure:
    """Máscara das linhas que falham e o motivo, para uma regra."""
    if rule.kind != "formula":
        if not rule.column:
            raise ValueError(f"Escolha a coluna da regra {RULE_NAMES[rule.kind]}.")
        if rule.column not in df.columns:
            raise ValueError(
                f"A coluna [{rule.column}] da regra {RULE_NAMES[rule.kind]} não existe na entrada."
            )
    mask, reason = CHECKS[rule.kind](df, rule)
    return mask, reason


def _free_name(df: pl.DataFrame, name: str) -> str:
    while name in df.columns:
        name = f"{name}_dq"
    return name


def with_lists(rules: list[QualityRule], lists: pl.DataFrame | None) -> list[QualityRule]:
    """Cada "Valor permitido" com a lista já pronta, venha ela digitada ou da entrada L."""
    return [
        r.model_copy(update={"values": list_values(r, lists)}) if r.kind == "allowed" else r for r in rules
    ]


def check_quality(
    df: pl.DataFrame, rules: list[QualityRule], lists: pl.DataFrame | None = None
) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, Any]]]:
    """Devolve P, F e a contagem de falhas por regra. ``lists`` é a tabela da entrada L, quando ligada."""
    if not rules:
        raise ValueError("Escolha ao menos uma regra.")
    rules = with_lists(rules, lists)
    masks = []
    counts = []
    for rule in rules:
        mask, reason = rule_failures(df, rule)
        mask = mask.fill_null(False)
        masks.append((mask, RULE_NAMES[rule.kind], reason))
        counts.append({"rule": RULE_NAMES[rule.kind], "column": rule.column, "failed": int(mask.sum())})
    any_fail = pl.select(pl.any_horizontal([m for m, _, _ in masks])).to_series()
    rule_col = _free_name(df, "regra")
    reason_col = _free_name(df, "motivo")
    joined = df.with_columns(
        pl.concat_list([pl.when(pl.lit(m)).then(pl.lit(name)) for m, name, _ in masks])
        .list.drop_nulls()
        .list.join(" · ")
        .alias(rule_col),
        pl.concat_list([pl.when(pl.lit(m)).then(pl.lit(reason)) for m, _, reason in masks])
        .list.drop_nulls()
        .list.join(" · ")
        .alias(reason_col),
    )
    return df.filter(~any_fail), joined.filter(any_fail), counts


def _annotation(cfg: QualityConfig) -> str:
    if not cfg.rules:
        return "Escolha as regras"
    return f"{len(cfg.rules)} regra(s)"


@tool(
    type="prep.data_quality",
    name="Data Quality",
    category="prep",
    icon="quality",
    description="Confere cada linha contra regras prontas: o que passa sai em [P]; o que falha sai em [F], com o motivo.",
    config=QualityConfig,
    inputs=[
        Port("in", "I", "Entrada"),
        # Só aparece quando alguma regra "Valor permitido" usa a lista de outra tabela (RF-2840).
        Port("L", "L", "Lista de valores", required=False, when={"rules[].values_from": ["table"]}),
    ],
    outputs=[Port("P", "P", "Passou"), Port("F", "F", "Falhou")],
    annotate=_annotation,
    explainer="quality",
)
def data_quality(ctx: NodeContext, cfg: QualityConfig) -> NodeOutput:
    passed, failed, counts = check_quality(ctx.input(), cfg.rules, ctx.inputs.get("L"))
    total = passed.height + failed.height
    pct = failed.height / total * 100 if total else 0.0
    if failed.height and (cfg.stop == "any" or (cfg.stop == "pct" and pct > cfg.stop_pct)):
        worst = sorted(counts, key=lambda c: -c["failed"])[:3]
        detail = "; ".join(f"{c['failed']} em {c['rule']} [{c['column']}]" for c in worst if c["failed"])
        limit = "" if cfg.stop == "any" else f" (aceito: {cfg.stop_pct:g}%)".replace(".", ",")
        raise ValueError(
            f"Fluxo interrompido: {failed.height} de {total} linhas falharam, {pct:.1f}%".replace(".", ",")
            + f"{limit}. {detail}."
        )
    return NodeOutput(
        tables={"P": passed, "F": failed},
        extra={"dq_failed": failed.height, "dq_passed": passed.height, "dq_rules": counts},
    )
