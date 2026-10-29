"""Motor de expressões estilo Alteryx, transpilado para SQL vetorizado do DuckDB.

Sintaxe suportada:

- Colunas: ``[nome da coluna]``
- Literais: ``'texto'`` ou ``"texto"`` (ambos viram literais SQL)
- ``IF cond THEN a ELSEIF cond2 THEN b ELSE c ENDIF`` e ``IIF(cond, a, b)``
- Operadores: ``== != <> > >= < <= + - * / AND OR NOT !``
- Funções Alteryx (sem diferenciar maiúsculas): ver ``ALTERYX_FUNCTIONS``.
  Qualquer outra função escalar do DuckDB (``ROUND``, ``ABS``, ``COALESCE``...)
  é repassada como está.
"""

from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass
from typing import Any

import duckdb
import polars as pl

# nome Alteryx (minúsculo) -> (macro SQL, definição)
ALTERYX_FUNCTIONS: dict[str, tuple[str, str]] = {
    "iif": ("ax_iif", "ax_iif(c, a, b) AS CASE WHEN c THEN a ELSE b END"),
    "isnull": ("ax_isnull", "ax_isnull(x) AS (x IS NULL)"),
    "isempty": ("ax_isempty", "ax_isempty(x) AS (x IS NULL OR trim(CAST(x AS VARCHAR)) = '')"),
    "contains": ("ax_contains", "ax_contains(s, t) AS contains(CAST(s AS VARCHAR), t)"),
    "startswith": ("ax_startswith", "ax_startswith(s, t) AS starts_with(CAST(s AS VARCHAR), t)"),
    "endswith": ("ax_endswith", "ax_endswith(s, t) AS ends_with(CAST(s AS VARCHAR), t)"),
    "uppercase": ("ax_upper", "ax_upper(s) AS upper(CAST(s AS VARCHAR))"),
    "lowercase": ("ax_lower", "ax_lower(s) AS lower(CAST(s AS VARCHAR))"),
    "titlecase": (
        "ax_title",
        "ax_title(s) AS array_to_string(list_transform(string_split(lower(CAST(s AS VARCHAR)), ' '), "
        "lambda w: upper(w[1]) || w[2:]), ' ')",
    ),
    "length": ("ax_length", "ax_length(s) AS length(CAST(s AS VARCHAR))"),
    "tonumber": ("ax_tonumber", "ax_tonumber(x) AS TRY_CAST(x AS DOUBLE)"),
    "tostring": ("ax_tostring", "ax_tostring(x) AS CAST(x AS VARCHAR)"),
    "todate": ("ax_todate", "ax_todate(x) AS TRY_CAST(x AS DATE)"),
    "left": ("ax_left", "ax_left(s, n) AS left(CAST(s AS VARCHAR), n)"),
    "right": ("ax_right", "ax_right(s, n) AS right(CAST(s AS VARCHAR), n)"),
}


@dataclass(frozen=True)
class FunctionDoc:
    """Documentação de uma função para o editor (autocompletar e assistente)."""

    name: str
    signature: str
    category: str
    description: str
    example: str


# Ordem = ordem no assistente. Todo ``example`` é validado em teste contra SAMPLE_SCHEMA.
FUNCTION_DOCS: list[FunctionDoc] = [
    FunctionDoc("IIF", "IIF(condição, se_verdadeiro, se_falso)", "Condicional",
                "Escolhe um de dois valores conforme a condição.", "IIF([valor] > 100, 'alto', 'baixo')"),
    FunctionDoc("IsNull", "IsNull(valor)", "Condicional",
                "Verdadeiro quando o valor é nulo.", "IsNull([cidade])"),
    FunctionDoc("IsEmpty", "IsEmpty(valor)", "Condicional",
                "Verdadeiro quando o valor é nulo ou texto em branco.", "IsEmpty([cidade])"),
    FunctionDoc("Coalesce", "Coalesce(valor1, valor2, …)", "Condicional",
                "Primeiro valor não nulo da lista.", "Coalesce([cidade], 'sem cidade')"),
    FunctionDoc("Contains", "Contains(texto, trecho)", "Texto",
                "Verdadeiro se o texto contém o trecho (diferencia maiúsculas).", "Contains([nome], 'Ltda')"),
    FunctionDoc("StartsWith", "StartsWith(texto, início)", "Texto",
                "Verdadeiro se o texto começa com o trecho.", "StartsWith([codigo], 'BR')"),
    FunctionDoc("EndsWith", "EndsWith(texto, fim)", "Texto",
                "Verdadeiro se o texto termina com o trecho.", "EndsWith([email], '.com.br')"),
    FunctionDoc("Uppercase", "Uppercase(texto)", "Texto", "Texto em MAIÚSCULAS.", "Uppercase([nome])"),
    FunctionDoc("Lowercase", "Lowercase(texto)", "Texto", "Texto em minúsculas.", "Lowercase([email])"),
    FunctionDoc("TitleCase", "TitleCase(texto)", "Texto",
                "Primeira letra de cada palavra em maiúscula.", "TitleCase([nome])"),
    FunctionDoc("Trim", "Trim(texto)", "Texto", "Remove espaços do início e do fim.", "Trim([nome])"),
    FunctionDoc("Length", "Length(texto)", "Texto", "Quantidade de caracteres.", "Length([nome])"),
    FunctionDoc("Left", "Left(texto, n)", "Texto", "Os n primeiros caracteres.", "Left([codigo], 2)"),
    FunctionDoc("Right", "Right(texto, n)", "Texto", "Os n últimos caracteres.", "Right([codigo], 4)"),
    FunctionDoc("Substring", "Substring(texto, início, tamanho)", "Texto",
                "Trecho do texto a partir da posição (começa em 1).", "Substring([codigo], 3, 4)"),
    FunctionDoc("Replace", "Replace(texto, procurar, trocar_por)", "Texto",
                "Troca todas as ocorrências de um trecho.", "Replace([telefone], '-', '')"),
    FunctionDoc("Concat", "Concat(texto1, texto2, …)", "Texto",
                "Junta textos (nulos viram vazio).", "Concat([cidade], ' - ', [uf])"),
    FunctionDoc("Round", "Round(número, casas)", "Números",
                "Arredonda para o número de casas decimais.", "Round([valor] * 1.07, 2)"),
    FunctionDoc("Abs", "Abs(número)", "Números", "Valor absoluto (sem sinal).", "Abs([saldo])"),
    FunctionDoc("Ceil", "Ceil(número)", "Números", "Arredonda para cima.", "Ceil([valor])"),
    FunctionDoc("Floor", "Floor(número)", "Números", "Arredonda para baixo.", "Floor([valor])"),
    FunctionDoc("Sqrt", "Sqrt(número)", "Números", "Raiz quadrada.", "Sqrt([valor])"),
    FunctionDoc("Power", "Power(base, expoente)", "Números", "Potência.", "Power([valor], 2)"),
    FunctionDoc("Greatest", "Greatest(valor1, valor2, …)", "Números",
                "Maior valor entre os informados.", "Greatest([valor], 0)"),
    FunctionDoc("Least", "Least(valor1, valor2, …)", "Números",
                "Menor valor entre os informados.", "Least([valor], 1000)"),
    FunctionDoc("ToNumber", "ToNumber(valor)", "Conversão",
                "Converte para número (inválido vira nulo).", "ToNumber([codigo])"),
    FunctionDoc("ToString", "ToString(valor)", "Conversão", "Converte para texto.", "ToString([valor])"),
    FunctionDoc("ToDate", "ToDate(valor)", "Conversão",
                "Converte para data (AAAA-MM-DD; inválido vira nulo).", "ToDate([data_texto])"),
    FunctionDoc("Today", "Today()", "Datas", "Data de hoje.", "Today()"),
    FunctionDoc("Year", "Year(data)", "Datas", "Ano da data.", "Year([data])"),
    FunctionDoc("Month", "Month(data)", "Datas", "Mês da data (1 a 12).", "Month([data])"),
    FunctionDoc("Day", "Day(data)", "Datas", "Dia do mês.", "Day([data])"),
    FunctionDoc("Date_Diff", "Date_Diff('day', início, fim)", "Datas",
                "Diferença entre datas na unidade pedida ('day', 'month', 'year').",
                "Date_Diff('day', [data], Today())"),
]  # fmt: skip

# Palavras de controle e operadores lógicos (para cores e sugestões no editor).
KEYWORDS: list[str] = ["IF", "THEN", "ELSEIF", "ELSE", "ENDIF"]
LOGICAL: list[str] = ["AND", "OR", "NOT", "IN", "TRUE", "FALSE", "NULL"]

# Esquema usado pelo teste que valida os exemplos de FUNCTION_DOCS.
SAMPLE_SCHEMA: list[dict[str, str]] = [
    {"name": n, "type": t}
    for n, t in [
        ("valor", "Float64"), ("saldo", "Float64"), ("cidade", "String"), ("nome", "String"),
        ("codigo", "String"), ("email", "String"), ("telefone", "String"), ("uf", "String"),
        ("data_texto", "String"), ("data", "Date"),
    ]
]  # fmt: skip

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_COLUMN_REF = re.compile(r"\[([^\[\]]+)\]")
_PLACEHOLDER = "\x00{}\x00"

_DUCK_TYPES = {"Int64": "BIGINT", "Float64": "DOUBLE", "Boolean": "BOOLEAN", "Date": "DATE"}
_CASTS = {
    "Int64": "TRY_CAST(({}) AS BIGINT)",
    "Float64": "TRY_CAST(({}) AS DOUBLE)",
    "String": "CAST(({}) AS VARCHAR)",
    "Boolean": "TRY_CAST(({}) AS BOOLEAN)",
    "Date": "TRY_CAST(({}) AS DATE)",
}


class FormulaError(ValueError):
    """Expressão inválida."""


def referenced_columns(expression: str) -> list[str]:
    masked = _STRING_LITERAL.sub("''", expression or "")
    return list(dict.fromkeys(_COLUMN_REF.findall(masked)))


def transpile(expression: str) -> str:
    """Converte uma expressão estilo Alteryx em uma expressão SQL do DuckDB."""
    if not expression or not expression.strip():
        raise FormulaError("Expressão vazia.")

    literals: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        raw = match.group(0)
        body = raw[1:-1].replace(raw[0] * 2, raw[0])
        literals.append("'" + body.replace("'", "''") + "'")
        return _PLACEHOLDER.format(len(literals) - 1)

    def _stash_column(match: re.Match[str]) -> str:
        literals.append('"' + match.group(1).replace('"', '""') + '"')
        return _PLACEHOLDER.format(len(literals) - 1)

    sql = _STRING_LITERAL.sub(_stash, expression.strip())
    sql = _COLUMN_REF.sub(_stash_column, sql)

    sql = re.sub(r"\bELSEIF\b", "WHEN", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bENDIF\b", "END", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bIF\b(?!\s*\()", "CASE WHEN", sql, flags=re.IGNORECASE)
    sql = sql.replace("==", "=")
    sql = re.sub(r"!(?!=)", " NOT ", sql)

    def _function(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        return ALTERYX_FUNCTIONS[name][0] + "(" if name in ALTERYX_FUNCTIONS else match.group(0)

    sql = re.sub(r"\b([A-Za-z_]\w*)\s*\(", _function, sql)

    for idx, lit in enumerate(literals):
        sql = sql.replace(_PLACEHOLDER.format(idx), lit)
    return sql


_base: duckdb.DuckDBPyConnection | None = None
_base_lock = threading.Lock()


def connect() -> duckdb.DuckDBPyConnection:
    """Cursor isolado sobre uma base em memória que já tem as macros Alteryx.

    Criar conexão + 15 macros a cada nó custava ~30 ms; a base é criada uma vez e
    cada chamada recebe o próprio cursor (tabelas registradas não vazam entre threads).
    """
    global _base
    with _base_lock:
        if _base is None:
            base = duckdb.connect(":memory:")
            for _, definition in ALTERYX_FUNCTIONS.values():
                base.execute(f"CREATE MACRO {definition}")
            _base = base
        return _base.cursor()


def _check_columns(expression: str, columns: list[str]) -> None:
    missing = [c for c in referenced_columns(expression) if c not in columns]
    if missing:
        raise FormulaError("Coluna(s) inexistente(s): " + ", ".join(f"[{c}]" for c in missing))


def evaluate_columns(df: pl.DataFrame, formulas: list[dict[str, Any]]) -> pl.DataFrame:
    """Aplica, em sequência, uma lista de fórmulas ``{column, expression, type}``."""
    with connect() as con:
        current = df
        for rule in formulas:
            column = (rule.get("column") or "").strip()
            expression = (rule.get("expression") or "").strip()
            if not column or not expression:
                continue
            _check_columns(expression, current.columns)
            sql = transpile(expression)
            cast = _CASTS.get(rule.get("type") or "Auto")
            if cast:
                sql = cast.format(sql)
            try:
                con.register("t", current)
                value = con.sql(f"SELECT {sql} AS v FROM t").pl().to_series().alias(column)
            except duckdb.Error as exc:
                raise FormulaError(f"Fórmula de [{column}]: {_clean(exc)}") from exc
            finally:
                con.unregister("t")
            current = current.with_columns(value)
        return current


def evaluate_mask(df: pl.DataFrame, expression: str) -> pl.Series:
    """Avalia uma condição e devolve uma máscara booleana sem nulos."""
    _check_columns(expression, df.columns)
    sql = transpile(expression)
    with connect() as con:
        con.register("t", df)
        try:
            return con.sql(f"SELECT COALESCE(CAST(({sql}) AS BOOLEAN), FALSE) AS m FROM t").pl().to_series()
        except duckdb.Error as exc:
            raise FormulaError(_clean(exc)) from exc


def validate(expression: str, columns: list[dict[str, str]]) -> dict[str, Any]:
    """Valida a expressão contra um esquema, sem executar sobre dados."""
    try:
        _check_columns(expression, [c["name"] for c in columns])
        sql = transpile(expression)
        defs = [
            f'NULL::{_DUCK_TYPES.get(c.get("type", "String"), "VARCHAR")} AS "{c["name"].replace('"', '""')}"'
            for c in columns
        ] or ["1 AS _dummy"]
        with connect() as con:
            con.execute(f"WITH t AS (SELECT {', '.join(defs)}) SELECT {sql} FROM t")
        return {"valid": True, "error": None, "sql": sql}
    except (FormulaError, duckdb.Error) as exc:
        return {"valid": False, "error": _clean(exc), "sql": None}


def _clean(exc: Exception) -> str:
    """Remove o ruído de contexto do DuckDB e traduz erros de sintaxe para algo acionável."""
    message = str(exc).split("\n\nLINE")[0].strip()
    if "syntax error" not in message.lower():
        return message
    # A expressão vai embutida em "SELECT <expr> FROM t": parar em FROM ou no fim = expressão incompleta.
    near = re.search(r'at or near "([^"]*)"', message)
    if not near or near.group(1).upper() == "FROM" or "end of input" in message.lower():
        return "Expressão incompleta: falta um valor, fechar um parêntese ou terminar o IF com ENDIF."
    return f'Erro de sintaxe perto de "{near.group(1)}". Confira operadores, vírgulas e aspas.'


def function_catalog() -> list[dict[str, str]]:
    return [asdict(doc) for doc in FUNCTION_DOCS]
