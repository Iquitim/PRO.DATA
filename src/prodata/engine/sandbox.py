"""Conexão DuckDB para o que vem escrito num fluxo: fórmulas e a caixa SQL (spec 027).

O DuckDB lê arquivos e endereços da internet por funções comuns de consulta, como ``read_text``. Um fluxo recebido
de outra pessoa executa ao abrir, então sem esta trava ele poderia ler um arquivo do computador e enviá-lo para
fora. Aqui, a consulta só enxerga as tabelas registradas pelo próprio programa.
"""

from __future__ import annotations

import duckdb

BLOCKED_MESSAGE = (
    "Fórmulas e a caixa SQL não acessam arquivos nem a internet: use as caixas de entrada de dados."
)
_BLOCKED_ERRORS = ("disabled by configuration", "file system operations are disabled")


def sandboxed_connection() -> duckdb.DuckDBPyConnection:
    """Base em memória, sem acesso externo. Quem precisar de macros cria antes de chamar :func:`lock`."""
    return duckdb.connect(
        ":memory:",
        config={
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        },
    )


def lock(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Depois disto, nenhuma consulta consegue religar o acesso externo com ``SET``."""
    con.execute("SET python_enable_replacements = false")  # variáveis do Python não viram tabelas
    con.execute("SET lock_configuration = true")
    return con


def is_blocked(exc: Exception) -> bool:
    """O erro veio desta trava? Quem mostra o erro troca o texto do DuckDB por :data:`BLOCKED_MESSAGE`."""
    text = str(exc)
    return any(piece in text for piece in _BLOCKED_ERRORS)
