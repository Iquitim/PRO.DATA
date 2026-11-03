"""Funções do PRO.DATA em SQL: o código copiado precisa rodar sozinho num DuckDB limpo (RF-2005).

O preâmbulo traz só o que é usado. Conversões espelham ``engine/convert.py``, com as mesmas listas de palavras e de
formatos; os testes de equivalência comparam as duas implementações.
"""

from __future__ import annotations

import re
import threading

import duckdb

from prodata.engine.convert import DATE_FORMATS, DATETIME_FORMATS, FALSE_WORDS, TRUE_WORDS
from prodata.engine.formula import ALTERYX_FUNCTIONS


def _words(words: list[str]) -> str:
    return ", ".join("'" + w + "'" for w in words)


_FORMATS = ", ".join("'" + f + "'" for f in [*DATE_FORMATS, *DATETIME_FORMATS])

# Em ordem de dependência. O nome é a parte antes do parêntese.
PRODATA_MACROS: tuple[str, ...] = (
    r"pd_limpo(x) AS regexp_replace(CAST(x AS VARCHAR), '^\s+|\s+$', '', 'g')",
    r"pd_so_numero(x) AS regexp_replace(pd_limpo(x), '(?i)r\$|\s', '', 'g')",
    r"""pd_numero_br(n) AS CASE
      WHEN regexp_matches(n, ',\d*$') AND NOT regexp_matches(n, '\.\d{1,2}$') THEN replace(replace(n, '.', ''), ',', '.')
      WHEN regexp_matches(n, '^-?\d{1,3}(\.\d{3}){2,}$') THEN replace(n, '.', '')
      ELSE replace(n, ',', '')
    END""",
    "pd_para_decimal(x) AS TRY_CAST(pd_numero_br(pd_so_numero(x)) AS DOUBLE)",
    "pd_para_inteiro(x) AS TRY_CAST(trunc(pd_para_decimal(x)) AS BIGINT)",
    f"""pd_para_booleano(x) AS CASE
      WHEN lower(pd_limpo(x)) IN ({_words(TRUE_WORDS)}) THEN TRUE
      WHEN lower(pd_limpo(x)) IN ({_words(FALSE_WORDS)}) THEN FALSE
    END""",
    f"""pd_para_data(x) AS COALESCE(
      CAST(try_strptime(pd_limpo(x), [{_FORMATS}]) AS DATE),
      CAST(try_strptime(pd_limpo(x) || '-01', '%Y-%m-%d') AS DATE)
    )""",
    "pd_texto_decimal(x) AS CASE WHEN isnan(CAST(x AS DOUBLE)) THEN 'NaN' ELSE CAST(x AS VARCHAR) END",
    "pd_data_excel(x) AS DATE '1899-12-30' + CAST(trunc(x) AS INTEGER)",
    "pd_titulo(x) AS array_to_string(list_transform(string_split(lower(x), ' '), lambda w: upper(w[1:1]) || w[2:]), ' ')",
    "pd_distintos(l) AS list_filter(l, lambda x, i: list_position(l, x) = i)",
    # Mais frequente; no empate, o menor (como o Summarize).
    "pd_moda(h) AS list_sort(list_transform(map_entries(h), lambda e: {'n': -CAST(e.value AS BIGINT), 'v': e.key}))[1].v",
)


def _macro_table() -> dict[str, str]:
    table = {definition.split("(", 1)[0]: definition for definition in PRODATA_MACROS}
    for name, definition in ALTERYX_FUNCTIONS.values():
        table[name] = definition
    return table


MACROS = _macro_table()
_NAME = re.compile(r"\b(pd_[a-z_]+|ax_[a-z_0-9]+)\s*\(", re.IGNORECASE)


def macros_used(sql: str) -> list[str]:
    """Macros citadas e as que elas usam, cada uma depois das suas dependências."""
    ordered: list[str] = []

    def visit(text: str) -> None:
        for match in _NAME.finditer(text):
            name = match.group(1).lower()
            if name in MACROS and name not in ordered:
                visit(MACROS[name].split(" AS ", 1)[1])
                ordered.append(name)

    visit(sql)
    return ordered


def preamble(sql: str) -> str:
    """Comandos que criam as macros usadas (vazio se não há nenhuma)."""
    return "\n".join(f"CREATE OR REPLACE TEMPORARY MACRO {MACROS[name]};" for name in macros_used(sql))


_base: duckdb.DuckDBPyConnection | None = None
_base_lock = threading.Lock()


def macro_cursor() -> duckdb.DuckDBPyConnection:
    """Cursor isolado sobre uma base que já tem as macros: criá-las a cada geração custava mais que o resto."""
    global _base
    with _base_lock:
        if _base is None:
            base = duckdb.connect(":memory:")
            install_all(base, temporary=False)
            _base = base
        return _base.cursor()


def install_all(con: object, *, temporary: bool = True) -> None:
    """Cria todas as macros numa conexão, em ordem de dependência."""
    kind = "TEMPORARY MACRO" if temporary else "MACRO"
    for name in macros_used(" ".join(f"{n}(" for n in MACROS)):
        con.execute(f"CREATE OR REPLACE {kind} {MACROS[name]}")  # type: ignore[attr-defined]
