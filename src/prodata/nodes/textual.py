"""Ferramentas de texto (spec 033): Regex, fórmula em várias colunas e máscara de dados pessoais."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from typing import Any, Literal

import polars as pl
from pydantic import Field

from prodata.engine import formula
from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, ToolConfig, tool

# ------------------------------------------------------------------ Regex


class RegexConfig(ToolConfig):
    column: str = Field("", title="Coluna", json_schema_extra=ui(widget="column"))
    pattern: str = Field(
        "",
        title="Padrão (expressão regular)",
        description="Parênteses formam grupos. Ex.: (\\d{2})/(\\d{4}) separa mês e ano de 10/2026.",
        json_schema_extra=ui(placeholder="(\\d{2})/(\\d{4})"),
    )
    mode: Literal["extract", "replace", "match"] = Field(
        "extract",
        title="O que fazer",
        json_schema_extra=ui(
            labels={
                "extract": "Extrair os grupos para colunas",
                "replace": "Substituir o que casar",
                "match": "Marcar as linhas que casam",
            }
        ),
    )
    names: list[str] = Field(
        default_factory=list,
        title="Nomes das colunas novas",
        description="Um por grupo, na ordem. Vazio = grupo_1, grupo_2…",
        json_schema_extra=ui(show_if={"mode": ["extract"]}),
    )
    replacement: str = Field(
        "",
        title="Trocar por",
        description="$1, $2… repetem os grupos.",
        json_schema_extra=ui(show_if={"mode": ["replace"]}),
    )
    output: str = Field(
        "",
        title="Coluna do resultado",
        description="Vazio = a própria coluna (Substituir) ou 'casou' (Marcar).",
        json_schema_extra=ui(show_if={"mode": ["replace", "match"]}),
    )
    ignore_case: bool = Field(False, title="Ignorar maiúsculas e minúsculas")


def _regex_error(exc: Exception) -> InvalidInputError:
    detail = " ".join(str(exc).split())
    return InvalidInputError(f"Padrão inválido: {detail[:200]}")


@tool(
    type="prep.regex",
    explainer="regex",
    name="Regex",
    category="prep",
    icon="search",
    description="Expressão regular numa coluna de texto: extrai grupos para colunas, substitui ou marca as linhas que casam.",
    config=RegexConfig,
    annotate=lambda c: c.pattern,
)
def regex(ctx: NodeContext, cfg: RegexConfig) -> NodeOutput:
    df = ctx.input()
    if cfg.column not in df.columns:
        raise InvalidInputError(
            f"Coluna '{cfg.column}' não existe na entrada." if cfg.column else "Escolha a coluna."
        )
    if not cfg.pattern:
        raise InvalidInputError("Escreva o padrão.")
    pattern = ("(?i)" if cfg.ignore_case else "") + cfg.pattern
    text = pl.col(cfg.column).cast(pl.String)
    try:
        if cfg.mode == "match":
            return NodeOutput(
                tables={
                    "out": df.with_columns(
                        text.str.contains(pattern).fill_null(False).alias(cfg.output.strip() or "casou")
                    )
                }
            )
        if cfg.mode == "replace":
            target = cfg.output.strip() or cfg.column
            return NodeOutput(
                tables={"out": df.with_columns(text.str.replace_all(pattern, cfg.replacement).alias(target))}
            )
        groups = df.select(text.str.extract_groups(pattern).alias("__g")).unnest("__g")
    except (pl.exceptions.PolarsError, ValueError) as exc:
        raise _regex_error(exc) from exc
    if not groups.width:
        # Sem parênteses, o que casou inteiro vira uma coluna.
        groups = df.select(text.str.extract(pattern, 0).alias("1"))
    names = [n.strip() for n in cfg.names if n.strip()]
    renamed = {
        old: (names[i] if i < len(names) else (old if not old.isdigit() else f"grupo_{i + 1}"))
        for i, old in enumerate(groups.columns)
    }
    groups = groups.rename(renamed)
    if clash := [c for c in groups.columns if c in df.columns]:
        raise InvalidInputError(f"Já existe coluna com o nome {', '.join(clash)}: escolha outros nomes.")
    return NodeOutput(tables={"out": pl.concat([df, groups], how="horizontal")})


# ------------------------------------------------------------------ Multi-Field Formula

_CURRENT = re.compile(r"\[_(atual|currentfield)_\]", re.IGNORECASE)


class MultiFieldConfig(ToolConfig):
    columns: list[str] = Field(default_factory=list, title="Colunas", json_schema_extra=ui(widget="columns"))
    expression: str = Field(
        "",
        title="Expressão",
        description="[_Atual_] é a coluna da vez. Ex.: Trim(Uppercase([_Atual_]))",
        json_schema_extra=ui(widget="expression", placeholder="Trim(Uppercase([_Atual_]))"),
    )
    target: Literal["replace", "new"] = Field(
        "replace",
        title="Resultado em",
        json_schema_extra=ui(labels={"replace": "A própria coluna", "new": "Uma coluna nova para cada uma"}),
    )
    prefix: str = Field("", title="Prefixo do nome novo", json_schema_extra=ui(show_if={"target": ["new"]}))
    suffix: str = Field(
        "_novo", title="Sufixo do nome novo", json_schema_extra=ui(show_if={"target": ["new"]})
    )
    type: Literal["Auto", "Float64", "Int64", "String", "Boolean", "Date"] = Field(
        "Auto",
        title="Tipo",
        json_schema_extra=ui(
            labels={
                "Auto": "Automático",
                "Float64": "Decimal",
                "Int64": "Inteiro",
                "String": "Texto",
                "Boolean": "Verdadeiro/falso",
                "Date": "Data",
            }
        ),
    )


@tool(
    type="prep.multi_field",
    explainer="multi_field",
    name="Multi-Field Formula",
    category="prep",
    icon="function",
    description="Aplica a mesma fórmula a várias colunas de uma vez. [_Atual_] é a coluna da vez.",
    config=MultiFieldConfig,
    annotate=lambda c: f"{len(c.columns)} coluna(s)",
)
def multi_field(ctx: NodeContext, cfg: MultiFieldConfig) -> NodeOutput:
    df = ctx.input()
    if not cfg.columns:
        raise InvalidInputError("Escolha as colunas.")
    if missing := [c for c in cfg.columns if c not in df.columns]:
        raise InvalidInputError(f"Coluna(s) inexistente(s) na entrada: {', '.join(missing)}")
    if not _CURRENT.search(cfg.expression):
        raise InvalidInputError("A expressão precisa de [_Atual_], que é a coluna da vez.")
    if cfg.target == "new" and not (cfg.prefix or cfg.suffix):
        raise InvalidInputError("Informe um prefixo ou sufixo para o nome das colunas novas.")
    rules: list[dict[str, Any]] = []
    for column in cfg.columns:
        expression = _CURRENT.sub(lambda _m, c=column: f"[{c}]", cfg.expression)  # type: ignore[misc]
        if cfg.target == "replace":
            rules.append(
                {"target": "existing", "existing": column, "expression": expression, "type": cfg.type}
            )
        else:
            name = f"{cfg.prefix}{column}{cfg.suffix}"
            rules.append({"target": "new", "column": name, "expression": expression, "type": cfg.type})
    return NodeOutput(tables={"out": formula.evaluate_columns(df, rules)})


# ------------------------------------------------------------------ Mask (LGPD)

MaskMethod = Literal["cpf", "cnpj", "email", "keep_last", "keep_first", "fixed", "code"]
HIDDEN = "***"


class MaskConfig(ToolConfig):
    columns: list[str] = Field(default_factory=list, title="Colunas", json_schema_extra=ui(widget="columns"))
    method: MaskMethod = Field(
        "cpf",
        title="Como proteger",
        json_schema_extra=ui(
            labels={
                "cpf": "CPF: ***.456.789-**",
                "cnpj": "CNPJ: **.345.678/****-**",
                "email": "E-mail: a***@empresa.com.br",
                "keep_last": "Mostrar só o fim",
                "keep_first": "Mostrar só o início",
                "fixed": "Trocar por um texto fixo",
                "code": "Trocar por um código estável",
            }
        ),
    )
    keep: int = Field(
        4,
        ge=0,
        le=50,
        title="Quantos caracteres mostrar",
        json_schema_extra=ui(show_if={"method": ["keep_last", "keep_first"]}),
    )
    text: str = Field(HIDDEN, title="Texto", json_schema_extra=ui(show_if={"method": ["fixed"]}))


def _alnum(value: str) -> str:
    return "".join(c for c in value if c.isalnum())


def mask_cpf(value: str) -> str:
    d = _alnum(value)
    return f"***.{d[3:6]}.{d[6:9]}-**" if len(d) == 11 and d.isdigit() else HIDDEN


def mask_cnpj(value: str) -> str:
    d = _alnum(value)  # o CNPJ novo aceita letras
    return f"**.{d[2:5]}.{d[5:8]}/****-**" if len(d) == 14 else HIDDEN


def mask_email(value: str) -> str:
    name, sep, domain = value.strip().partition("@")
    return f"{name[0]}***@{domain}" if sep and name and "." in domain else HIDDEN


def _masker(cfg: MaskConfig, key: Callable[[], bytes] | None) -> Callable[[str], str]:
    if cfg.method == "cpf":
        return mask_cpf
    if cfg.method == "cnpj":
        return mask_cnpj
    if cfg.method == "email":
        return mask_email
    if cfg.method == "keep_last":
        return lambda v: "*" * max(0, len(v) - cfg.keep) + (v[-cfg.keep :] if cfg.keep else "")
    if cfg.method == "keep_first":
        return lambda v: v[: cfg.keep] + "*" * max(0, len(v) - cfg.keep)
    if cfg.method == "fixed":
        return lambda _v: cfg.text
    if key is None:
        raise InvalidInputError("O código estável precisa do cofre do sistema, indisponível neste ambiente.")
    secret = key()
    # O mesmo valor dá sempre o mesmo código neste computador; sem a chave, não dá para voltar ao valor.
    return lambda v: hmac.new(secret, v.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:16]


@tool(
    type="prep.mask",
    explainer="mask",
    name="Mask",
    category="prep",
    icon="lock",
    description="Protege dados pessoais (LGPD): máscara de CPF, CNPJ e e-mail, só o início ou o fim, texto fixo ou código estável.",
    config=MaskConfig,
    annotate=lambda c: ", ".join(c.columns),
)
def mask(ctx: NodeContext, cfg: MaskConfig) -> NodeOutput:
    df = ctx.input()
    if not cfg.columns:
        raise InvalidInputError("Escolha as colunas.")
    if missing := [c for c in cfg.columns if c not in df.columns]:
        raise InvalidInputError(f"Coluna(s) inexistente(s) na entrada: {', '.join(missing)}")
    apply = _masker(cfg, ctx.secret_key)
    out = df
    for column in cfg.columns:
        text = df[column].cast(pl.String)
        # Calcula uma vez por valor diferente: CPF repetido em mil linhas é mascarado uma vez só.
        distinct = text.drop_nulls().unique().to_list()
        mapping = pl.DataFrame(
            {"__v": distinct, "__m": [apply(v) for v in distinct]},
            schema={"__v": pl.String, "__m": pl.String},
        )
        masked = text.to_frame("__v").join(mapping, on="__v", how="left", maintain_order="left")["__m"]
        out = out.with_columns(masked.alias(column))
    return NodeOutput(tables={"out": out})
