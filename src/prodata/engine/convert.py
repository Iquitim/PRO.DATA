"""Conversão de tipos tolerante, com relatório do que não converteu (spec 018, RF-1804).

O ``cast`` do Polars é estrito demais para dados de planilha brasileira: "1.234,56", " 12 " ou "12.0"
viram vazio sem aviso, e texto → data/booleano nem existe. Aqui cada conversão entende os formatos
comuns e devolve quantos valores (e quais) não puderam ser convertidos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

TRUE_WORDS = ["true", "1", "sim", "s", "yes", "y", "verdadeiro", "v", "x"]
FALSE_WORDS = ["false", "0", "não", "nao", "n", "no", "falso", "f"]
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"]
DATETIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"]
# O Excel guarda datas como dias desde 30/12/1899.
EXCEL_EPOCH = pl.date(1899, 12, 30)


@dataclass
class Conversion:
    series: pl.Series
    failed: int = 0
    examples: list[str] = field(default_factory=list)


def _text(series: pl.Series) -> pl.Series:
    return series.cast(pl.String).str.strip_chars()


def parse_number(text: pl.Series) -> pl.Series:
    """Número a partir de texto: padrão brasileiro (1.234,56 · 12,5), padrão americano, "R$" e espaços."""
    s = text.str.replace_all(r"(?i)r\$|\s", "")
    br = s.str.contains(r",\d*$") & ~s.str.contains(r"\.\d{1,2}$")  # vírgula como separador decimal
    normalized = (
        pl.when(br)
        .then(s.str.replace_all(r"\.", "").str.replace(",", ".", literal=True))
        # "1.234.567": pontos de milhar sem casas decimais
        .when(s.str.contains(r"^-?\d{1,3}(\.\d{3}){2,}$"))
        .then(s.str.replace_all(r"\.", ""))
        .otherwise(s.str.replace_all(",", ""))
    )
    return pl.select(normalized.alias(text.name)).to_series().cast(pl.Float64, strict=False)


def parse_date(text: pl.Series) -> pl.Series:
    attempts = [text.str.to_date(fmt, strict=False) for fmt in DATE_FORMATS]
    attempts += [text.str.to_datetime(fmt, strict=False).dt.date() for fmt in DATETIME_FORMATS]
    attempts.append((text + "-01").str.to_date("%Y-%m-%d", strict=False))  # 2026-10
    return pl.select(pl.coalesce(attempts).alias(text.name)).to_series()


def _convert(series: pl.Series, target: pl.DataType | type[pl.DataType]) -> pl.Series:
    source = series.dtype
    if target == pl.String:
        return series.cast(pl.String)
    if source == pl.String:
        text = _text(series)
        if target in (pl.Float64, pl.Int64):
            number = parse_number(text)
            return number if target == pl.Float64 else number.cast(pl.Int64, strict=False)
        if target == pl.Boolean:
            lower = text.str.to_lowercase()
            out = pl.when(lower.is_in(TRUE_WORDS)).then(True).when(lower.is_in(FALSE_WORDS)).then(False)
            return pl.select(out.alias(series.name)).to_series()
        if target == pl.Date:
            return parse_date(text)
    if target == pl.Date and source.is_numeric():
        days = series.cast(pl.Int64, strict=False)
        return pl.select((EXCEL_EPOCH + pl.duration(days=pl.lit(days))).alias(series.name)).to_series()
    if target == pl.Date and isinstance(source, pl.Datetime):
        return series.dt.date()
    return series.cast(target, strict=False)


def convert(series: pl.Series, target: pl.DataType | type[pl.DataType]) -> Conversion:
    """Converte e conta o que se perdeu: valores preenchidos que viraram vazio."""
    out = _convert(series, target).alias(series.name)
    filled = series.is_not_null()
    if series.dtype == pl.String:
        filled = filled & (series.str.strip_chars() != "")
    lost = filled & out.is_null()
    failed = int(lost.sum())
    examples = (
        [str(v) for v in series.filter(lost).unique(maintain_order=True).head(3).to_list()] if failed else []
    )
    return Conversion(out, failed, examples)
