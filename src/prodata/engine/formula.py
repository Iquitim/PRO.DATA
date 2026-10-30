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

# Unidade de data em inglês ou português ('dia', 'mês', 'ano'...), normalizada para o DuckDB.
_UNIT = (
    "CASE WHEN lower(u) IN ('day', 'days', 'dia', 'dias', 'd') THEN 'day' "
    "WHEN lower(u) IN ('week', 'weeks', 'semana', 'semanas') THEN 'week' "
    "WHEN lower(u) IN ('month', 'months', 'mes', 'mês', 'meses') THEN 'month' "
    "WHEN lower(u) IN ('quarter', 'quarters', 'trimestre', 'trimestres') THEN 'quarter' "
    "WHEN lower(u) IN ('year', 'years', 'ano', 'anos') THEN 'year' ELSE lower(u) END"
)

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
    # Spec 015: funções comuns no Alteryx e no KNIME, com unidades de data também em português.
    "trimleft": ("ax_trimleft", "ax_trimleft(s) AS ltrim(CAST(s AS VARCHAR))"),
    "trimright": ("ax_trimright", "ax_trimright(s) AS rtrim(CAST(s AS VARCHAR))"),
    "padleft": ("ax_padleft", "ax_padleft(s, n, c) AS lpad(CAST(s AS VARCHAR), n, c)"),
    "padright": ("ax_padright", "ax_padright(s, n, c) AS rpad(CAST(s AS VARCHAR), n, c)"),
    "findstring": ("ax_findstring", "ax_findstring(s, t) AS instr(CAST(s AS VARCHAR), t)"),
    "getword": (
        "ax_getword",
        "ax_getword(s, n) AS split_part(regexp_replace(trim(CAST(s AS VARCHAR)), '\\s+', ' ', 'g'), ' ', n)",
    ),
    "splitpart": ("ax_splitpart", "ax_splitpart(s, sep, n) AS split_part(CAST(s AS VARCHAR), sep, n)"),
    "countwords": (
        "ax_countwords",
        "ax_countwords(s) AS CASE WHEN s IS NULL THEN NULL WHEN trim(CAST(s AS VARCHAR)) = '' THEN 0 "
        "ELSE len(string_split(regexp_replace(trim(CAST(s AS VARCHAR)), '\\s+', ' ', 'g'), ' ')) END",
    ),
    "reverse": ("ax_reverse", "ax_reverse(s) AS reverse(CAST(s AS VARCHAR))"),
    "removeaccents": ("ax_removeaccents", "ax_removeaccents(s) AS strip_accents(CAST(s AS VARCHAR))"),
    "digitsonly": (
        "ax_digitsonly",
        "ax_digitsonly(s) AS regexp_replace(CAST(s AS VARCHAR), '[^0-9]', '', 'g')",
    ),
    "regexmatch": ("ax_regexmatch", "ax_regexmatch(s, p) AS regexp_matches(CAST(s AS VARCHAR), p)"),
    "regexreplace": (
        "ax_regexreplace",
        "ax_regexreplace(s, p, r) AS regexp_replace(CAST(s AS VARCHAR), p, r, 'g')",
    ),
    "regexextract": (
        "ax_regexextract",
        "ax_regexextract(s, p, g) AS regexp_extract(CAST(s AS VARCHAR), p, g)",
    ),
    "mod": ("ax_mod", "ax_mod(a, b) AS (a % b)"),
    "divide": ("ax_divide", "ax_divide(a, b) AS CASE WHEN b = 0 THEN NULL ELSE a / b END"),
    "between": ("ax_between", "ax_between(x, a, b) AS (x BETWEEN a AND b)"),
    "formatnumber": (
        "ax_formatnumber",
        "ax_formatnumber(x, n) AS translate(printf('%,.' || CAST(n AS VARCHAR) || 'f', CAST(x AS DOUBLE)), ',.', '.,')",
    ),
    "tointeger": ("ax_tointeger", "ax_tointeger(x) AS CAST(trunc(TRY_CAST(x AS DOUBLE)) AS BIGINT)"),
    "tonumberbr": (
        "ax_tonumberbr",
        "ax_tonumberbr(x) AS TRY_CAST(replace(replace(trim(CAST(x AS VARCHAR)), '.', ''), ',', '.') AS DOUBLE)",
    ),
    "isnumber": (
        "ax_isnumber",
        "ax_isnumber(x) AS (TRY_CAST(x AS DOUBLE) IS NOT NULL "
        "OR TRY_CAST(replace(replace(trim(CAST(x AS VARCHAR)), '.', ''), ',', '.') AS DOUBLE) IS NOT NULL)",
    ),
    "dateparse": (
        "ax_dateparse",
        "ax_dateparse(x, f) AS CAST(TRY_STRPTIME(trim(CAST(x AS VARCHAR)), f) AS DATE)",
    ),
    "now": ("ax_now", "ax_now() AS CAST(now() AS TIMESTAMP)"),
    "dateadd": (
        "ax_dateadd",
        f"ax_dateadd(d, n, u) AS CAST(date_add(CAST(d AS TIMESTAMP), CASE {_UNIT} "
        "WHEN 'day' THEN to_days(CAST(n AS INTEGER)) WHEN 'week' THEN to_days(7 * CAST(n AS INTEGER)) "
        "WHEN 'month' THEN to_months(CAST(n AS INTEGER)) WHEN 'quarter' THEN to_months(3 * CAST(n AS INTEGER)) "
        "WHEN 'year' THEN to_years(CAST(n AS INTEGER)) END) AS DATE)",
    ),
    "datetrunc": (
        "ax_datetrunc",
        f"ax_datetrunc(u, d) AS CAST(date_trunc({_UNIT}, CAST(d AS TIMESTAMP)) AS DATE)",
    ),
    "date_diff": (
        "ax_datediff",
        f"ax_datediff(u, a, b) AS date_diff({_UNIT}, CAST(a AS TIMESTAMP), CAST(b AS TIMESTAMP))",
    ),
    "startofmonth": (
        "ax_startofmonth",
        "ax_startofmonth(d) AS CAST(date_trunc('month', CAST(d AS DATE)) AS DATE)",
    ),
    "endofmonth": ("ax_endofmonth", "ax_endofmonth(d) AS last_day(CAST(d AS DATE))"),
    "weekday": ("ax_weekday", "ax_weekday(d) AS isodow(CAST(d AS DATE))"),
    "weekdayname": (
        "ax_weekdayname",
        "ax_weekdayname(d) AS ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', "
        "'sábado', 'domingo'][isodow(CAST(d AS DATE))]",
    ),
    "monthname": (
        "ax_monthname",
        "ax_monthname(d) AS ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', "
        "'setembro', 'outubro', 'novembro', 'dezembro'][month(CAST(d AS DATE))]",
    ),
    "isweekend": ("ax_isweekend", "ax_isweekend(d) AS (isodow(CAST(d AS DATE)) >= 6)"),
    "dateformat": ("ax_dateformat", "ax_dateformat(d, f) AS strftime(CAST(d AS TIMESTAMP), f)"),
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
    FunctionDoc("Date_Diff", "Date_Diff('dia', início, fim)", "Datas",
                "Diferença entre datas na unidade pedida ('dia', 'semana', 'mês', 'ano' ou em inglês).",
                "Date_Diff('dia', [data], Today())"),
    # Spec 015 -------------------------------------------------------------------------------
    FunctionDoc("NullIf", "NullIf(valor, valor_a_anular)", "Condicional",
                "Nulo quando o valor é igual ao segundo (ex.: zero vira nulo).", "NullIf([valor], 0)"),
    FunctionDoc("Between", "Between(valor, mínimo, máximo)", "Condicional",
                "Verdadeiro se o valor está entre os limites (inclusive).", "Between([valor], 100, 500)"),
    FunctionDoc("TrimLeft", "TrimLeft(texto)", "Texto", "Remove espaços do início.", "TrimLeft([nome])"),
    FunctionDoc("TrimRight", "TrimRight(texto)", "Texto", "Remove espaços do fim.", "TrimRight([nome])"),
    FunctionDoc("PadLeft", "PadLeft(texto, tamanho, caractere)", "Texto",
                "Completa à esquerda até o tamanho (ex.: zeros em códigos).", "PadLeft([codigo], 8, '0')"),
    FunctionDoc("PadRight", "PadRight(texto, tamanho, caractere)", "Texto",
                "Completa à direita até o tamanho.", "PadRight([codigo], 10, ' ')"),
    FunctionDoc("FindString", "FindString(texto, trecho)", "Texto",
                "Posição do trecho no texto (começa em 1; 0 se não achar).", "FindString([email], '@')"),
    FunctionDoc("GetWord", "GetWord(texto, n)", "Texto",
                "A n-ésima palavra do texto (começa em 1).", "GetWord([nome], 1)"),
    FunctionDoc("SplitPart", "SplitPart(texto, separador, n)", "Texto",
                "O n-ésimo pedaço do texto, dividido pelo separador.", "SplitPart([email], '@', 2)"),
    FunctionDoc("CountWords", "CountWords(texto)", "Texto", "Quantidade de palavras.", "CountWords([nome])"),
    FunctionDoc("Reverse", "Reverse(texto)", "Texto", "Texto de trás para frente.", "Reverse([codigo])"),
    FunctionDoc("RemoveAccents", "RemoveAccents(texto)", "Texto",
                "Tira acentos e cedilha (São Paulo → Sao Paulo).", "RemoveAccents([cidade])"),
    FunctionDoc("DigitsOnly", "DigitsOnly(texto)", "Texto",
                "Só os dígitos (útil para CPF, CNPJ, CEP e telefone).", "DigitsOnly([documento])"),
    FunctionDoc("RegexMatch", "RegexMatch(texto, padrão)", "Texto",
                "Verdadeiro se o texto contém o padrão (expressão regular).", "RegexMatch([email], '^[^@]+@[^@]+$')"),
    FunctionDoc("RegexReplace", "RegexReplace(texto, padrão, trocar_por)", "Texto",
                "Troca tudo o que casa com o padrão.", "RegexReplace([telefone], '[^0-9]', '')"),
    FunctionDoc("RegexExtract", "RegexExtract(texto, padrão, grupo)", "Texto",
                "Trecho que casa com o grupo do padrão (0 = tudo).", "RegexExtract([codigo], '([A-Z]+)', 1)"),
    FunctionDoc("Mod", "Mod(número, divisor)", "Números", "Resto da divisão.", "Mod(Year([data]), 4)"),
    FunctionDoc("Divide", "Divide(número, divisor)", "Números",
                "Divisão que dá nulo (em vez de erro) quando o divisor é zero.", "Divide([valor], [saldo])"),
    FunctionDoc("Trunc", "Trunc(número)", "Números", "Corta as casas decimais, sem arredondar.", "Trunc([valor])"),
    FunctionDoc("Sign", "Sign(número)", "Números", "-1, 0 ou 1 conforme o sinal.", "Sign([saldo])"),
    FunctionDoc("Ln", "Ln(número)", "Números", "Logaritmo natural.", "Ln([valor])"),
    FunctionDoc("Log10", "Log10(número)", "Números", "Logaritmo na base 10.", "Log10([valor])"),
    FunctionDoc("Exp", "Exp(número)", "Números", "Exponencial (e elevado ao número).", "Exp(1)"),
    FunctionDoc("FormatNumber", "FormatNumber(número, casas)", "Números",
                "Texto no padrão brasileiro: 1.234,56.", "FormatNumber([valor], 2)"),
    FunctionDoc("ToInteger", "ToInteger(valor)", "Conversão",
                "Converte para inteiro, cortando as casas decimais.", "ToInteger([valor])"),
    FunctionDoc("ToNumberBR", "ToNumberBR(texto)", "Conversão",
                "Lê números no padrão brasileiro ('1.234,56' → 1234.56).", "ToNumberBR([valor_br])"),
    FunctionDoc("IsNumber", "IsNumber(valor)", "Conversão",
                "Verdadeiro se o valor pode ser lido como número (12.5 ou 12,5).", "IsNumber([valor_br])"),
    FunctionDoc("DateParse", "DateParse(texto, formato)", "Conversão",
                "Lê uma data no formato indicado (%d dia, %m mês, %Y ano).", "DateParse([data_texto], '%d/%m/%Y')"),
    FunctionDoc("Now", "Now()", "Datas", "Data e hora de agora.", "Now()"),
    FunctionDoc("DateAdd", "DateAdd(data, quantidade, unidade)", "Datas",
                "Soma dias, semanas, meses, trimestres ou anos (negativo subtrai).", "DateAdd([data], 30, 'dia')"),
    FunctionDoc("DateTrunc", "DateTrunc(unidade, data)", "Datas",
                "Início do período: 'semana', 'mês', 'trimestre' ou 'ano'.", "DateTrunc('mês', [data])"),
    FunctionDoc("StartOfMonth", "StartOfMonth(data)", "Datas", "Primeiro dia do mês.", "StartOfMonth([data])"),
    FunctionDoc("EndOfMonth", "EndOfMonth(data)", "Datas", "Último dia do mês.", "EndOfMonth([data])"),
    FunctionDoc("Quarter", "Quarter(data)", "Datas", "Trimestre (1 a 4).", "Quarter([data])"),
    FunctionDoc("Week", "Week(data)", "Datas", "Semana do ano (ISO).", "Week([data])"),
    FunctionDoc("Weekday", "Weekday(data)", "Datas", "Dia da semana: 1 = segunda … 7 = domingo.", "Weekday([data])"),
    FunctionDoc("WeekdayName", "WeekdayName(data)", "Datas", "Nome do dia da semana.", "WeekdayName([data])"),
    FunctionDoc("MonthName", "MonthName(data)", "Datas", "Nome do mês.", "MonthName([data])"),
    FunctionDoc("IsWeekend", "IsWeekend(data)", "Datas", "Verdadeiro em sábados e domingos.", "IsWeekend([data])"),
    FunctionDoc("DateFormat", "DateFormat(data, formato)", "Datas",
                "Data como texto no formato pedido.", "DateFormat([data], '%d/%m/%Y')"),
    FunctionDoc("Hour", "Hour(data_hora)", "Datas", "Hora (0 a 23).", "Hour([data_hora])"),
    FunctionDoc("Minute", "Minute(data_hora)", "Datas", "Minuto (0 a 59).", "Minute([data_hora])"),
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
        ("data_texto", "String"), ("data", "Date"), ("documento", "String"), ("valor_br", "String"),
        ("data_hora", "Datetime"),
    ]
]  # fmt: skip

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_COLUMN_REF = re.compile(r"\[([^\[\]]+)\]")
_PLACEHOLDER = "\x00{}\x00"

_DUCK_TYPES = {
    "Int64": "BIGINT",
    "Float64": "DOUBLE",
    "Boolean": "BOOLEAN",
    "Date": "DATE",
    "Datetime": "TIMESTAMP",
}
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
    """Aplica, em sequência, uma lista de fórmulas ``{column, expression, type, target?, existing?}``.

    ``target="existing"`` grava em ``existing`` (uma coluna que já existe), mantendo a posição dela.
    """
    with connect() as con:
        current = df
        for rule in formulas:
            replace = rule.get("target") == "existing"
            column = (rule.get("existing" if replace else "column") or "").strip()
            expression = (rule.get("expression") or "").strip()
            if not column or not expression:
                continue
            if replace and column not in current.columns:
                raise FormulaError(f"A coluna [{column}] não existe para ser alterada.")
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
    message = str(exc).split("\n\nLINE")[0].split("\n\tCandidate functions")[0].strip()
    message = re.sub(r"\s*You might need to add explicit type casts\.?", "", message)
    if "No function matches" in message:
        # Quem vem do Alteryx junta textos com "+": aqui isso é soma de números.
        if (
            re.search(r"'\+\((?:VARCHAR|STRING_LITERAL)|, (?:VARCHAR|STRING_LITERAL)\)'", message)
            and "'+(" in message
        ):
            return "Texto não se soma com +. Para juntar textos, use Concat([a], ' - ', [b])."
        found = re.search(r"given name and argument types '([^(']+)\(", message)
        name = found.group(1) if found else ""
        what = f"A função {name}" if name[:1].isalpha() else f"A operação {name}".rstrip()
        return (
            f"{what} não aceita esses tipos de valor. Confira se as colunas são texto, número ou data "
            "e converta com ToNumber, ToString ou ToDate."
        )
    if "syntax error" not in message.lower():
        return message
    # A expressão vai embutida em "SELECT <expr> FROM t": parar em FROM ou no fim = expressão incompleta.
    near = re.search(r'at or near "([^"]*)"', message)
    if not near or near.group(1).upper() == "FROM" or "end of input" in message.lower():
        return "Expressão incompleta: falta um valor, fechar um parêntese ou terminar o IF com ENDIF."
    return f'Erro de sintaxe perto de "{near.group(1)}". Confira operadores, vírgulas e aspas.'


def function_catalog() -> list[dict[str, str]]:
    return [asdict(doc) for doc in FUNCTION_DOCS]
