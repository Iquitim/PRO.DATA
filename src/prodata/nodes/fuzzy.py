"""Fuzzy Match (spec 033): casa textos parecidos entre duas tabelas, como razão social e endereço."""

from __future__ import annotations

from typing import Literal

import duckdb
import polars as pl
from pydantic import Field

from prodata.engine import sandbox
from prodata.errors import InvalidInputError
from prodata.forms import ui
from prodata.nodes.base import NodeContext, NodeOutput, Port, ToolConfig, tool

MAX_PAIRS = 25_000_000
_SUFFIXES = r"(\s+(ltda|limitada|eireli|epp|me|mei|sa|s a|cia|companhia))+$"


class FuzzyConfig(ToolConfig):
    left: str = Field("", title="Texto em [L]", json_schema_extra=ui(widget="column", port="L"))
    right: str = Field("", title="Texto em [R]", json_schema_extra=ui(widget="column", port="R"))
    threshold: int = Field(
        88,
        ge=50,
        le=100,
        title="Nota mínima (0 a 100)",
        description="100 = igual depois de limpar. Abaixo de 85 começam a aparecer casamentos errados: confira a saída J.",
    )
    method: Literal["jaro", "words"] = Field(
        "jaro",
        title="Como comparar",
        json_schema_extra=ui(
            labels={
                "jaro": "Letra a letra (erros de digitação)",
                "words": "Por palavras (ordem trocada)",
            }
        ),
    )
    company: bool = Field(
        True,
        title="Ignorar LTDA, S.A., ME, EIRELI no fim",
        description="Para razão social. Desligue para endereços e nomes de pessoas.",
    )
    block_left: str = Field(
        "",
        title="Só comparar quando for igual em [L]",
        description="Opcional. Ex.: UF ou cidade. Reduz muito o tempo e os casamentos errados.",
        json_schema_extra=ui(widget="column", port="L", group="Avançado"),
    )
    block_right: str = Field(
        "", title="e em [R]", json_schema_extra=ui(widget="column", port="R", group="Avançado")
    )
    score_column: str = Field("nota", title="Coluna da nota", json_schema_extra=ui(group="Avançado"))
    right_prefix: str = Field(
        "r_", title="Prefixo para colunas repetidas da direita", json_schema_extra=ui(group="Avançado")
    )


def clean(column: str, cfg: FuzzyConfig) -> pl.Expr:
    """Caixa, acentos, pontuação e espaços; sufixos de empresa e ordem das palavras conforme a configuração."""
    text = (
        pl.col(column)
        .cast(pl.String)
        .str.to_lowercase()
        .str.normalize("NFKD")
        .str.replace_all(r"\p{M}", "")
        .str.replace_all(r"[^a-z0-9]+", " ")
        .str.strip_chars()
    )
    if cfg.company:
        text = text.str.replace(_SUFFIXES, "").str.strip_chars()
    if cfg.method == "words":
        text = text.str.split(" ").list.sort().list.join(" ")
    return pl.when(text == "").then(None).otherwise(text)


def _require(df: pl.DataFrame, column: str, side: str, what: str = "o texto") -> None:
    if column not in df.columns:
        raise InvalidInputError(
            f"Coluna '{column}' não existe em [{side}]." if column else f"Escolha {what} em [{side}]."
        )


def _pairs(lk: pl.DataFrame, rk: pl.DataFrame, blocked: bool) -> int:
    if not blocked:
        return lk.height * rk.height
    counts = lk.group_by("b").len("nl").join(rk.group_by("b").len("nr"), on="b")
    return int((counts["nl"] * counts["nr"]).sum() or 0)


@tool(
    type="transform.fuzzy_match",
    explainer="fuzzy",
    name="Fuzzy Match",
    category="transform",
    icon="fingerprint",
    description="Junta [L] e [R] por texto parecido (razão social, endereço), com nota de 0 a 100. Saídas: [L] sem par, [J] casados, [R] sem par.",
    config=FuzzyConfig,
    inputs=[Port("L", "L", "Esquerda"), Port("R", "R", "Direita")],
    outputs=[
        Port("L", "L", "Sem par na esquerda"),
        Port("J", "J", "Casados"),
        Port("R", "R", "Sem par na direita"),
    ],
    annotate=lambda c: f"{c.left} ≈ {c.right} · ≥ {c.threshold}" if c.left else "",
)
def fuzzy_match(ctx: NodeContext, cfg: FuzzyConfig) -> NodeOutput:
    left, right = ctx.input("L"), ctx.input("R")
    _require(left, cfg.left, "L")
    _require(right, cfg.right, "R")
    blocked = bool(cfg.block_left or cfg.block_right)
    if blocked:
        _require(left, cfg.block_left, "L", "a coluna de bloco")
        _require(right, cfg.block_right, "R", "a coluna de bloco")
    block_l = pl.col(cfg.block_left).cast(pl.String) if blocked else pl.lit("")
    block_r = pl.col(cfg.block_right).cast(pl.String) if blocked else pl.lit("")
    lrows = left.with_row_index("__i").with_columns(clean(cfg.left, cfg).alias("__k"), block_l.alias("__b"))
    rrows = right.with_row_index("__j").with_columns(clean(cfg.right, cfg).alias("__k"), block_r.alias("__b"))
    # Compara cada texto diferente uma vez só: nomes repetidos não aumentam o trabalho.
    lk = lrows.filter(pl.col("__k").is_not_null()).select(k="__k", b="__b").unique()
    rk = rrows.filter(pl.col("__k").is_not_null()).select(k="__k", b="__b").unique()
    pairs = _pairs(lk, rk, blocked)
    if pairs > MAX_PAIRS:
        raise InvalidInputError(
            f"Seriam {pairs:,} comparações (limite de {MAX_PAIRS:,}). ".replace(",", ".")
            + "Em Avançado, escolha uma coluna de bloco, como UF ou cidade, para comparar só dentro dela."
        )
    ctx.report(f"{pairs:,} comparações".replace(",", "."))
    with sandbox.sandboxed_connection() as con:
        con.register("lk", lk)
        con.register("rk", rk)
        sandbox.lock(con)
        try:
            best = con.sql(
                "SELECT lk.k AS lkey, lk.b AS b, rk.k AS rkey, "
                "round(jaro_winkler_similarity(lk.k, rk.k) * 100, 1) AS s "
                "FROM lk JOIN rk ON lk.b = rk.b "
                f"WHERE jaro_winkler_similarity(lk.k, rk.k) * 100 >= {int(cfg.threshold)} "
                "QUALIFY row_number() OVER (PARTITION BY lk.k, lk.b ORDER BY s DESC, rk.k) = 1"
            ).pl()
        except duckdb.Error as exc:
            raise InvalidInputError(str(exc).split("\n\nLINE")[0]) from exc

    score = cfg.score_column.strip() or "nota"
    matched = lrows.join(best, left_on=["__k", "__b"], right_on=["lkey", "b"], how="inner")
    clashes = {c: f"{cfg.right_prefix}{c}" for c in right.columns if c in left.columns or c == score}
    joined = matched.join(
        rrows.rename(clashes), left_on=["rkey", "__b"], right_on=["__k", "__b"], how="inner"
    ).sort("__i", "__j")
    used = joined["__j"].unique()
    helpers = ["__i", "__j", "__k", "__b", "rkey", "s"]
    result = joined.with_columns(pl.col("s").alias(score)).drop([c for c in helpers if c in joined.columns])
    return NodeOutput(
        tables={
            "L": lrows.join(matched.select("__i"), on="__i", how="anti").drop("__i", "__k", "__b"),
            "J": result,
            "R": rrows.filter(~pl.col("__j").is_in(used.implode())).drop("__j", "__k", "__b"),
        },
        extra={"fuzzy_pairs": pairs, "fuzzy_matched": result.height},
    )
