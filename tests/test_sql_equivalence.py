"""O SQL gerado precisa dar o mesmo resultado que o motor (spec 020). Este teste é a definição de "pronto".

Cada caso roda a ferramenta de verdade e o SQL dela no DuckDB, sobre os mesmos dados, com valores incômodos: vazios,
espaços, acentos, repetições, tabela vazia e nomes de coluna estranhos.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from prodata.engine import formula
from prodata.engine.sql.fragment import SQL_REGISTRY, SqlContext, SqlInput, kind_of, q
from prodata.engine.sql.macros import install_all
from prodata.engine.sql.verify import DIFFERENT, SAME, compare
from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext

MESSY = pl.DataFrame(
    {
        "id": [1, 2, 2, 3, 4, 5, None],
        "uf": ["SP", "RJ", "RJ", None, " MG ", "São Paulo", "SP"],
        "valor": [10.5, None, 3.25, 7.0, 0.0, -2.5, 10.5],
        "qtd": [1, 2, None, 4, 5, 6, 7],
        "ativo": [True, False, None, True, True, False, True],
        "texto": ["a,b", "c", None, "", " d , e ", "f,g,h", "ação"],
        "numero": ["1.234,56", " 12 ", "12,5", "R$ 1.500,00", "abc", "", None],
        "sim": ["sim", "NÃO", "1", "false", "talvez", None, "x"],
        "data": ["2026-10-29", "29/10/2026", "2026-10", "abc", None, "31/12/2025", "2025.12.31"],
        "coluna estranha": ["x", "y", "x", 'as"pas', "o'clock", None, "x"],
        "select": [1, 2, 3, 4, 5, 6, 7],
    }
)
EMPTY = MESSY.clear()
OTHER = pl.DataFrame(
    {"id": [2, 3, None, 9, 2], "uf": ["RJ", "X", "SP", "Y", "Z"], "extra": [1.5, None, 3.0, 4.0, 5.0]}
)


def _inputs(con: duckdb.DuckDBPyConnection, tables: dict[str, pl.DataFrame]) -> dict[str, SqlInput]:
    found = {}
    for port, table in tables.items():
        name = f"entrada_{port}"
        con.register(name, table)
        rows = con.execute(f'DESCRIBE "{name}"').fetchall()
        found[port] = SqlInput(name, [str(r[0]) for r in rows], {str(r[0]): kind_of(str(r[1])) for r in rows})
    return found


def run_both(
    tool: str, tables: dict[str, pl.DataFrame], store: DatasetStore, tmp_path: Path, **config: Any
) -> dict[str, tuple[pl.DataFrame, pl.DataFrame]]:
    spec = REGISTRY[tool]
    cfg = spec.config.model_validate(config)
    engine = spec.run(NodeContext(tables, {}, store, tmp_path), cfg).tables
    con = duckdb.connect(":memory:")
    install_all(con)
    try:
        ctx = SqlContext(_inputs(con, tables), sample=lambda port: tables.get(port))
        fragments = SQL_REGISTRY[tool](ctx, cfg)
        return {port: (con.sql(f.sql).pl(), engine[port]) for port, f in fragments.items()}
    finally:
        con.close()


def assert_same(results: dict[str, tuple[pl.DataFrame, pl.DataFrame]]) -> None:
    for port, (sql, engine) in results.items():
        check = compare(sql, engine)
        assert check.state == SAME, (port, check.detail, check.examples, sql.columns, engine.columns)


CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("select_keep", "prep.select", {"fields": [{"name": "uf", "keep": False}]}),
    ("select_rename_reserved", "prep.select", {"fields": [{"name": "uf", "rename": "from"}]}),
    ("select_order", "prep.select", {"order": ["qtd", "coluna estranha"]}),
    ("select_to_decimal", "prep.select", {"fields": [{"name": "numero", "cast": "Float64"}]}),
    ("select_to_int", "prep.select", {"fields": [{"name": "numero", "cast": "Int64"}]}),
    ("select_to_bool", "prep.select", {"fields": [{"name": "sim", "cast": "Boolean"}]}),
    ("select_to_date", "prep.select", {"fields": [{"name": "data", "cast": "Date"}]}),
    ("select_float_to_int", "prep.select", {"fields": [{"name": "valor", "cast": "Int64"}]}),
    ("select_int_to_text", "prep.select", {"fields": [{"name": "qtd", "cast": "String"}]}),
    ("select_number_to_date", "prep.select", {"fields": [{"name": "select", "cast": "Date"}]}),
    (
        "filter_expression",
        "prep.filter",
        {"mode": "expression", "expression": "[valor] > 1 AND [uf] != 'SP'"},
    ),
    ("filter_null_in_condition", "prep.filter", {"mode": "expression", "expression": "[valor] > 5"}),
    ("filter_equal_text", "prep.filter", {"mode": "simple", "column": "uf", "operator": "==", "value": "SP"}),
    (
        "filter_number",
        "prep.filter",
        {"mode": "simple", "column": "valor", "operator": ">=", "value": "3,25"},
    ),
    (
        "filter_contains",
        "prep.filter",
        {"mode": "simple", "column": "uf", "operator": "contains", "value": "SÃO"},
    ),
    (
        "filter_starts",
        "prep.filter",
        {"mode": "simple", "column": "uf", "operator": "starts_with", "value": "s"},
    ),
    ("filter_is_null", "prep.filter", {"mode": "simple", "column": "valor", "operator": "is_null"}),
    ("filter_bool", "prep.filter", {"mode": "simple", "column": "ativo", "operator": "==", "value": "sim"}),
    (
        "formula_new",
        "prep.formula",
        {"formulas": [{"column": "dobro", "type": "Float64", "expression": "[valor] * 2"}]},
    ),
    (
        "formula_chain",
        "prep.formula",
        {
            "formulas": [
                {"column": "a", "type": "Float64", "expression": "[valor] + 1"},
                {"column": "b", "type": "Float64", "expression": "[a] * 2"},
                {"column": "c", "type": "String", "expression": "Concat([uf], '-x')"},
            ]
        },
    ),
    (
        "formula_existing",
        "prep.formula",
        {
            "formulas": [
                {"target": "existing", "existing": "valor", "type": "Float64", "expression": "[valor] * 10"}
            ]
        },
    ),
    (
        "formula_rewrites_column",
        "prep.formula",
        {
            "formulas": [
                {"column": "a", "type": "Int64", "expression": "1"},
                {"column": "a", "type": "Int64", "expression": "[a] + 1"},
            ]
        },
    ),
    (
        "formula_row_functions",
        "prep.formula",
        {
            "formulas": [
                {"column": "m", "type": "Float64", "expression": "Average([valor], [qtd], 1)"},
                {"column": "n", "type": "Float64", "expression": "StdDev([valor], [qtd], 1)"},
            ]
        },
    ),
    (
        "formula_if",
        "prep.formula",
        {
            "formulas": [
                {
                    "column": "t",
                    "type": "String",
                    "expression": "IF [valor] > 5 THEN 'A' ELSEIF [valor] > 1 THEN 'B' ELSE 'C' ENDIF",
                }
            ]
        },
    ),
    ("cleanse_default", "prep.cleanse", {}),
    (
        "cleanse_upper",
        "prep.cleanse",
        {"columns": ["uf", "texto"], "case_mode": "upper", "replace_null_string": True},
    ),
    (
        "cleanse_lower_numbers",
        "prep.cleanse",
        {"case_mode": "lower", "replace_null_numeric": True, "numeric_default": 9},
    ),
    (
        "cleanse_collapse",
        "prep.cleanse",
        {"collapse_whitespace": True, "trim_whitespace": False, "empty_as_null": False},
    ),
    ("unique_keys", "prep.unique", {"keys": ["uf"]}),
    ("unique_row", "prep.unique", {}),
    ("sort", "prep.sort", {"sorts": [{"column": "uf"}, {"column": "valor", "descending": True}]}),
    ("sample_first", "prep.sample", {"mode": "first", "n": 3}),
    ("sample_last", "prep.sample", {"mode": "last", "n": 2}),
    (
        "summarize_numbers",
        "transform.summarize",
        {
            "group_by": ["uf"],
            "aggregations": [
                {"column": "valor", "agg": "sum"},
                {"column": "valor", "agg": "mean"},
                {"column": "valor", "agg": "median"},
                {"column": "valor", "agg": "min"},
                {"column": "valor", "agg": "max"},
                {"column": "valor", "agg": "std"},
            ],
        },
    ),
    (
        "summarize_counts",
        "transform.summarize",
        {
            "group_by": ["uf", "ativo"],
            "aggregations": [
                {"column": "qtd", "agg": "count"},
                {"agg": "count_all"},
                {"column": "uf", "agg": "n_unique"},
                {"column": "valor", "agg": "n_unique", "alias": "distintos"},
            ],
        },
    ),
    (
        "summarize_mode",
        "transform.summarize",
        {
            "group_by": ["ativo"],
            "aggregations": [{"column": "uf", "agg": "mode"}, {"column": "qtd", "agg": "mode"}],
        },
    ),
    (
        "summarize_positional",
        "transform.summarize",
        {
            "group_by": ["ativo"],
            "aggregations": [
                {"column": "uf", "agg": "first"},
                {"column": "uf", "agg": "last"},
                {"column": "uf", "agg": "concat"},
            ],
        },
    ),
    (
        "summarize_total",
        "transform.summarize",
        {"aggregations": [{"column": "valor", "agg": "sum"}, {"agg": "count_all"}]},
    ),
    ("summarize_no_aggregation", "transform.summarize", {"group_by": ["uf"], "aggregations": []}),
    (
        "crosstab_sum",
        "transform.crosstab",
        {"group_by": ["ativo"], "header": "uf", "value": "valor", "agg": "sum"},
    ),
    (
        "crosstab_count",
        "transform.crosstab",
        {"group_by": ["ativo"], "header": "uf", "value": "valor", "agg": "count"},
    ),
    ("crosstab_mean_no_group", "transform.crosstab", {"header": "uf", "value": "valor", "agg": "mean"}),
    (
        "crosstab_first",
        "transform.crosstab",
        {"group_by": ["ativo"], "header": "uf", "value": "qtd", "agg": "first"},
    ),
    (
        "crosstab_concat",
        "transform.crosstab",
        {"group_by": ["ativo"], "header": "uf", "value": "texto", "agg": "concat"},
    ),
    (
        "transpose_same_type",
        "transform.transpose",
        {"keys": ["id"], "columns": ["valor", "qtd"], "value_column": "conteudo"},
    ),
    (
        "transpose_mixed",
        "transform.transpose",
        {"keys": ["id"], "columns": ["uf", "qtd"], "name_column": "campo", "value_column": "conteudo"},
    ),
    ("text_columns", "prep.text_to_columns", {"column": "texto"}),
    (
        "text_columns_keep",
        "prep.text_to_columns",
        {"column": "texto", "keep_original": True, "max_parts": 2, "trim": False},
    ),
    ("text_rows", "prep.text_to_columns", {"column": "texto", "mode": "rows"}),
    ("record_id_first", "prep.record_id", {"column": "n", "start": 10}),
    ("record_id_last", "prep.record_id", {"column": "n", "position": "last"}),
    ("running_total", "prep.running_total", {"columns": ["valor", "qtd"]}),
    (
        "running_total_groups",
        "prep.running_total",
        {"columns": ["valor"], "group_by": ["uf"], "prefix": "ac_"},
    ),
    ("browse", "io.browse", {}),
]


@pytest.mark.parametrize(("case", "tool", "config"), CASES, ids=[c[0] for c in CASES])
def test_tool_matches_engine(
    case: str, tool: str, config: dict[str, Any], store: DatasetStore, tmp_path: Path
) -> None:
    assert_same(run_both(tool, {"in": MESSY}, store, tmp_path, **config))


NOT_ON_EMPTY = {
    "crosstab_sum",
    "crosstab_count",
    "crosstab_mean_no_group",
    "crosstab_first",
    "crosstab_concat",
}


@pytest.mark.parametrize(
    ("case", "tool", "config"),
    [c for c in CASES if c[0] not in NOT_ON_EMPTY],
    ids=[c[0] for c in CASES if c[0] not in NOT_ON_EMPTY],
)
def test_tool_matches_engine_on_empty_table(
    case: str, tool: str, config: dict[str, Any], store: DatasetStore, tmp_path: Path
) -> None:
    assert_same(run_both(tool, {"in": EMPTY}, store, tmp_path, **config))


@pytest.mark.parametrize(
    "config",
    [
        {"keys": [{"left": "id", "right": "id"}]},
        {"keys": [{"left": "id", "right": "id"}], "keys_mode": "left"},
        {"keys": [{"left": "id", "right": "id"}], "keys_mode": "right"},
        {"keys": [{"left": "id", "right": "id"}, {"left": "uf", "right": "uf"}]},
        {
            "keys": [{"left": "id", "right": "id"}],
            "right_prefix": "direita_",
            "fields": [
                {"name": "qtd", "keep": False},
                {"name": "direita_uf", "rename": "uf2"},
                {"name": "numero", "cast": "Float64"},
            ],
            "order": ["direita_uf", "id"],
        },
    ],
    ids=["both", "left", "right", "two_keys", "select"],
)
def test_join_matches_engine(config: dict[str, Any], store: DatasetStore, tmp_path: Path) -> None:
    assert_same(run_both("transform.join", {"L": MESSY, "R": OTHER}, store, tmp_path, **config))


def test_join_with_different_key_names(store: DatasetStore, tmp_path: Path) -> None:
    right = OTHER.rename({"id": "codigo"})
    for mode in ("both", "left", "right"):
        config = {"keys": [{"left": "id", "right": "codigo"}], "keys_mode": mode}
        assert_same(run_both("transform.join", {"L": MESSY, "R": right}, store, tmp_path, **config))


@pytest.mark.parametrize(
    "config",
    [{"mode": "by_name"}, {"mode": "by_name", "source_column": "origem"}, {"mode": "by_position"}],
    ids=["name", "source", "position"],
)
def test_union_matches_engine(config: dict[str, Any], store: DatasetStore, tmp_path: Path) -> None:
    second = (
        OTHER
        if config["mode"] == "by_name"
        else OTHER.select(pl.col("id") + 1, pl.col("uf").alias("outra"), "extra")
    )
    assert_same(run_both("transform.union", {"in1": OTHER, "in2": second}, store, tmp_path, **config))


def test_union_adds_missing_columns(store: DatasetStore, tmp_path: Path) -> None:
    assert_same(run_both("transform.union", {"in1": MESSY.select("id", "uf"), "in2": OTHER}, store, tmp_path))


def test_append_fields_matches_engine(store: DatasetStore, tmp_path: Path) -> None:
    assert_same(
        run_both("transform.append_fields", {"T": MESSY.head(3), "S": OTHER.head(2)}, store, tmp_path)
    )


def test_sql_tool_matches_engine(store: DatasetStore, tmp_path: Path) -> None:
    assert_same(
        run_both(
            "transform.sql_query",
            {"in": MESSY},
            store,
            tmp_path,
            sql="SELECT uf, count(*) AS n FROM input_1 GROUP BY uf",
        )
    )
    second = {"in": OTHER, "in2": OTHER}
    assert_same(
        run_both(
            "transform.sql_query",
            second,
            store,
            tmp_path,
            sql="WITH a AS (SELECT id FROM input_1) SELECT * FROM a, input_2 LIMIT 3;",
        )
    )


def test_text_input_matches_engine(store: DatasetStore, tmp_path: Path) -> None:
    table = {
        "columns": ["nome", "n", "v", "ok", "vazia"],
        "rows": [["O'Neil", "1", "1,5", "sim", ""], ["", "2", "3", "não", ""], ["Ção", "", "", "", ""]],
    }
    assert_same(run_both("io.text_input", {}, store, tmp_path, table=table))


@pytest.mark.parametrize("doc", formula.FUNCTION_DOCS, ids=lambda d: d.name)
def test_documented_function_runs_with_only_the_preamble(doc: formula.FunctionDoc) -> None:
    """Toda função documentada precisa rodar num DuckDB limpo, só com o preâmbulo do código gerado."""
    from prodata.engine.sql.macros import preamble

    sql = formula.transpile(doc.example)
    source = pl.DataFrame({c["name"]: pl.Series([], dtype=_type(c["type"])) for c in formula.SAMPLE_SCHEMA})
    con = duckdb.connect(":memory:")
    try:
        if macros := preamble(sql):
            con.execute(macros)
        con.register("t", source)
        con.sql(f"SELECT {sql} AS v FROM t").fetchall()
    finally:
        con.close()


def _type(name: str) -> type[pl.DataType]:
    return {
        "Int64": pl.Int64,
        "Float64": pl.Float64,
        "Boolean": pl.Boolean,
        "Date": pl.Date,
        "Datetime": pl.Datetime,
    }.get(name, pl.String)


DATES = pl.DataFrame(
    {
        "d": [date(2026, 1, 5), None, date(2025, 3, 1), date(2026, 1, 5)],
        "h": [datetime(2026, 1, 5, 10, 30), datetime(2025, 1, 1), None, datetime(2026, 1, 5, 10, 30)],
        "b": [True, False, None, True],
        "n": [1, 2, 3, 1],
        "v": [1.5, float("nan"), None, 2.5],
        "s": ["a", "b", None, "a"],
    }
)
DATE_CASES: list[tuple[str, dict[str, Any]]] = [
    ("prep.select", {"fields": [{"name": "d", "cast": "String"}]}),
    ("prep.select", {"fields": [{"name": "h", "cast": "Date"}]}),
    ("prep.select", {"fields": [{"name": "h", "cast": "String"}]}),
    ("prep.select", {"fields": [{"name": "b", "cast": "Int64"}]}),
    ("prep.select", {"fields": [{"name": "n", "cast": "Boolean"}]}),
    ("prep.select", {"fields": [{"name": "v", "cast": "String"}]}),
    ("prep.filter", {"mode": "simple", "column": "d", "operator": ">=", "value": "2026-01-01"}),
    ("prep.filter", {"mode": "simple", "column": "h", "operator": "==", "value": "2026-01-05 10:30:00.000000"}),
    ("prep.filter", {"mode": "simple", "column": "b", "operator": "!=", "value": "true"}),
    ("prep.filter", {"mode": "simple", "column": "n", "operator": "contains", "value": "1"}),
    ("prep.sort", {"sorts": [{"column": "d", "descending": True}]}),
    ("prep.unique", {"keys": ["d", "n"]}),
    ("transform.summarize", {"group_by": ["d"], "aggregations": [
        {"column": "h", "agg": "max"}, {"column": "h", "agg": "min"}, {"column": "h", "agg": "mode"},
        {"column": "b", "agg": "sum", "alias": "sb"}, {"column": "v", "agg": "sum", "alias": "sv"}, {"column": "n", "agg": "concat"},
    ]}),
    ("transform.summarize", {"aggregations": [{"column": "d", "agg": "first"}, {"column": "v", "agg": "mean"}, {"column": "v", "agg": "n_unique"}]}),
    ("transform.crosstab", {"group_by": ["s"], "header": "d", "value": "n", "agg": "sum"}),
    ("transform.crosstab", {"group_by": ["s"], "header": "b", "value": "s", "agg": "first"}),
    ("transform.transpose", {"keys": ["s"], "columns": ["d", "n"]}),
    ("transform.transpose", {"columns": ["n", "v"]}),
    ("prep.text_to_columns", {"column": "n"}),
    ("prep.running_total", {"columns": ["v"]}),
    ("prep.formula", {"formulas": [{"column": "y", "type": "Date", "expression": "[d]"}, {"column": "z", "type": "String", "expression": "[h]"}]}),
]  # fmt: skip


@pytest.mark.parametrize(
    ("tool", "config"), DATE_CASES, ids=[f"{t}-{i}" for i, (t, _) in enumerate(DATE_CASES)]
)
def test_tool_matches_engine_with_dates_and_nan(
    tool: str, config: dict[str, Any], store: DatasetStore, tmp_path: Path
) -> None:
    assert_same(run_both(tool, {"in": DATES}, store, tmp_path, **config))


@pytest.mark.parametrize(
    "word", ["left", "right", "join", "is", "like", "by", "full", "inner", "order", "group", "select", "end"]
)
def test_columns_named_as_reserved_words(word: str, store: DatasetStore, tmp_path: Path) -> None:
    df = pl.DataFrame({word: [1, 2, 2], "outra": ["a", "b", "b"]})
    assert_same(
        run_both(
            "prep.select", {"in": df}, store, tmp_path, fields=[{"name": "outra", "rename": word + "_x"}]
        )
    )
    assert_same(
        run_both(
            "transform.summarize",
            {"in": df},
            store,
            tmp_path,
            group_by=[word],
            aggregations=[{"column": word, "agg": "sum", "alias": "t"}],
        )
    )
    assert_same(run_both("prep.sort", {"in": df}, store, tmp_path, sorts=[{"column": word}]))


def test_every_reserved_word_is_quoted() -> None:
    rows = duckdb.sql(
        "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category IN ('reserved', 'type_function')"
    ).fetchall()
    for (word,) in rows:
        duckdb.sql(f'SELECT {q(word)} FROM (SELECT 1 AS "{word}")').fetchall()


# ------------------------------------------------------------------ a própria comparação precisa ser honesta


def test_compare_detects_differences() -> None:
    base = pl.DataFrame({"a": [1, 2, 2], "b": ["x", None, "y"]})
    assert compare(base, base).state == SAME
    assert compare(base.reverse(), base).state == SAME  # a ordem só conta quando faz parte do resultado
    assert compare(base.reverse(), base, ["a"]).state == DIFFERENT
    assert compare(base.head(2), base).state == DIFFERENT
    assert compare(base.select("a"), base).state == DIFFERENT
    assert compare(base.select("b", "a"), base).state == DIFFERENT
    assert compare(base.with_columns(pl.col("a").cast(pl.String)), base).state == DIFFERENT
    assert compare(pl.DataFrame({"a": [1, 2, 2, 2], "b": ["x", None, "y", "y"]}).head(3), base).state == SAME
    changed = compare(base.with_columns(pl.lit("z").alias("b")), base)
    assert changed.state == DIFFERENT and changed.examples


def test_compare_tolerates_decimal_noise_and_int_vs_float() -> None:
    a = pl.DataFrame({"v": [0.1 + 0.2, 1.0]})
    b = pl.DataFrame({"v": [0.3, 1.0]})
    assert compare(a, b).state == SAME
    assert compare(pl.DataFrame({"v": [1, 2]}), pl.DataFrame({"v": [1.0, 2.0]})).state == SAME


def test_quoting_is_safe() -> None:
    assert q("nome") == "nome"
    assert q("Nome") == '"Nome"'
    assert q("select") == '"select"'
    assert q('a"b') == '"a""b"'
    assert q("coluna estranha") == '"coluna estranha"'
