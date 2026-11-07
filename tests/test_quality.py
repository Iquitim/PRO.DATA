"""Data Quality (spec 028, RF-2831..2837): cada regra separa P e F certos, inclusive nos casos de borda."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from prodata.ingestion import DatasetStore
from prodata.nodes import REGISTRY, NodeContext
from prodata.nodes.quality import QualityRule, check_quality, valid_cnpj, valid_cpf


def run(df: pl.DataFrame, *rules: dict[str, Any]) -> tuple[pl.DataFrame, pl.DataFrame]:
    passed, failed, _ = check_quality(df, [QualityRule.model_validate(r) for r in rules])
    return passed, failed


@pytest.mark.parametrize("cpf", ["529.982.247-25", "52998224725", " 529.982.247-25 ", "390.533.447-05"])
def test_valid_cpf_with_or_without_mask(cpf: str) -> None:
    assert valid_cpf(cpf)


@pytest.mark.parametrize(
    "cpf", ["111.111.111-11", "123.456.789-00", "529.982.247-2", "529.982.247-25a", "abc"]
)
def test_invalid_cpf(cpf: str) -> None:
    assert not valid_cpf(cpf)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-81", "11222333000181", "12.ABC.345/01DE-35"])
def test_valid_cnpj_numeric_and_alphanumeric(cnpj: str) -> None:
    assert valid_cnpj(cnpj)


@pytest.mark.parametrize(
    "cnpj", ["11.222.333/0001-80", "00.000.000/0000-00", "1122233300018", "12.ABC.345/01DE-36"]
)
def test_invalid_cnpj(cnpj: str) -> None:
    assert not valid_cnpj(cnpj)


def test_not_empty_counts_spaces_as_empty() -> None:
    df = pl.DataFrame({"nome": ["Ana", "", "  ", None]})
    passed, failed = run(df, {"kind": "not_empty", "column": "nome"})
    assert passed["nome"].to_list() == ["Ana"]
    assert failed["motivo"].to_list() == ["Vazio em [nome]"] * 3


def test_format_rules_let_empty_pass_so_each_failure_has_one_reason() -> None:
    df = pl.DataFrame({"cpf": ["529.982.247-25", "", None, "111.111.111-11"]})
    passed, failed = run(df, {"kind": "cpf", "column": "cpf"})
    assert passed.height == 3 and failed["cpf"].to_list() == ["111.111.111-11"]


def test_unique_flags_every_copy_and_combines_columns() -> None:
    df = pl.DataFrame({"id": [1, 1, 2, 2], "mes": ["jan", "jan", "jan", "fev"]})
    _, failed = run(df, {"kind": "unique", "column": "id"})
    assert failed.height == 4
    _, failed = run(df, {"kind": "unique", "column": "id", "also": ["mes"]})
    assert failed["mes"].to_list() == ["jan", "jan"] and failed["motivo"][0] == "Repetido em [id], [mes]"


def test_email() -> None:
    df = pl.DataFrame({"email": ["ana@empresa.com", "ana@empresa", "ana empresa.com", "a@b.co", ""]})
    passed, failed = run(df, {"kind": "email", "column": "email"})
    assert failed["email"].to_list() == ["ana@empresa", "ana empresa.com"]
    assert passed.height == 3


def test_number_range() -> None:
    df = pl.DataFrame({"idade": [35, -4, 130, None]})
    passed, failed = run(df, {"kind": "number_range", "column": "idade", "min": 0, "max": 120})
    assert failed["idade"].to_list() == [-4, 130]
    assert failed["motivo"][0] == "Fora da faixa de 0 a 120 em [idade]"
    assert passed["idade"].to_list() == [35, None]


def test_number_range_refuses_text_column() -> None:
    with pytest.raises(ValueError, match="colunas de número"):
        run(pl.DataFrame({"x": ["1"]}), {"kind": "number_range", "column": "x", "min": 0})


def test_date_rule_reads_text_and_limits() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    df = pl.DataFrame({"d": ["12/03/2025", "2025-03-12", "31/02/2025", tomorrow, "", "2019-12-31"]})
    passed, failed = run(df, {"kind": "date", "column": "d", "not_future": True, "date_min": "2020-01-01"})
    assert failed["d"].to_list() == ["31/02/2025", tomorrow, "2019-12-31"]
    assert passed.height == 3


def test_allowed_values_ignore_case_and_spaces() -> None:
    df = pl.DataFrame({"uf": ["SP", " rj ", "XX", None]})
    passed, failed = run(df, {"kind": "allowed", "column": "uf", "values": ["SP", "RJ"]})
    assert failed["uf"].to_list() == ["XX"] and passed.height == 3


def test_formula_rule_with_custom_message() -> None:
    df = pl.DataFrame({"idade": [17, 30]})
    _, failed = run(df, {"kind": "formula", "expression": "[idade] >= 18", "message": "Menor de idade"})
    assert failed["motivo"].to_list() == ["Menor de idade"]


def test_several_failures_in_one_row_are_joined() -> None:
    df = pl.DataFrame({"cpf": ["111.111.111-11", "529.982.247-25"], "email": ["", "ana@empresa.com"]})
    _, failed = run(df, {"kind": "cpf", "column": "cpf"}, {"kind": "not_empty", "column": "email"})
    assert failed["regra"].to_list() == ["CPF válido · Não vazio"]
    assert failed["motivo"].to_list() == ["CPF inválido em [cpf] · Vazio em [email]"]


def test_output_keeps_order_and_avoids_name_clash() -> None:
    df = pl.DataFrame({"regra": ["a", "b"], "v": ["", "x"]})
    passed, failed = run(df, {"kind": "not_empty", "column": "v"})
    assert "regra_dq" in failed.columns and failed["regra"].to_list() == ["a"]
    assert passed.columns == ["regra", "v"]


def test_missing_column_and_no_rules_explain() -> None:
    with pytest.raises(ValueError, match="Escolha ao menos uma regra"):
        run(pl.DataFrame({"a": [1]}))
    with pytest.raises(ValueError, match=r"\[b\]"):
        run(pl.DataFrame({"a": [1]}), {"kind": "not_empty", "column": "b"})


def test_tool_reports_counts_for_the_canvas(store: DatasetStore, tmp_path: Path) -> None:
    spec = REGISTRY["prep.data_quality"]
    df = pl.DataFrame({"email": ["a@b.com", "", "x"]})
    cfg = spec.config.model_validate(
        {"rules": [{"kind": "not_empty", "column": "email"}, {"kind": "email", "column": "email"}]}
    )
    out = spec.run(NodeContext({"in": df}, {}, store, tmp_path), cfg)
    assert out.extra["dq_failed"] == 2 and out.extra["dq_passed"] == 1
    assert [r["failed"] for r in out.extra["dq_rules"]] == [1, 1]


def test_big_table_is_fast() -> None:
    import time

    n = 500_000
    df = pl.DataFrame({"cpf": ["529.982.247-25", "111.111.111-11"] * (n // 2), "email": ["a@b.com"] * n})
    start = time.perf_counter()
    run(
        df,
        {"kind": "cpf", "column": "cpf"},
        {"kind": "email", "column": "email"},
        {"kind": "unique", "column": "cpf"},
    )
    assert time.perf_counter() - start < 3


# ------------------------------------------------------------------ tradução para SQL (RF-2836)

SQL_DF = pl.DataFrame(
    {
        "id": [1, 2, 2, 3, 4, 5],
        "nome": ["Ana", "", "Caio", None, "Duda", "Eva"],
        "email": ["a@b.com", "ruim", "c@d.com", "", "e@f.org", "x@y"],
        "idade": [30, -1, 45, None, 130, 18],
        "uf": ["SP", "rj", "XX", None, " sp ", "MG"],
    }
)
SQL_RULES: list[list[dict[str, Any]]] = [
    [{"kind": "not_empty", "column": "nome"}],
    [{"kind": "unique", "column": "id"}],
    [{"kind": "email", "column": "email"}],
    [{"kind": "number_range", "column": "idade", "min": 0, "max": 120}],
    [{"kind": "allowed", "column": "uf", "values": ["SP", "RJ"]}],
    [{"kind": "formula", "expression": "[idade] >= 18", "message": "Menor"}],
    [
        {"kind": "not_empty", "column": "nome"},
        {"kind": "email", "column": "email"},
        {"kind": "unique", "column": "id"},
    ],
]


@pytest.mark.parametrize("rules", SQL_RULES, ids=str)
def test_sql_matches_engine(rules: list[dict[str, Any]], store: DatasetStore, tmp_path: Path) -> None:
    import duckdb

    from prodata.engine.sql.fragment import SQL_REGISTRY, SqlContext, SqlInput, kind_of
    from prodata.engine.sql.macros import install_all
    from prodata.engine.sql.verify import SAME, compare

    spec = REGISTRY["prep.data_quality"]
    cfg = spec.config.model_validate({"rules": rules})
    engine = spec.run(NodeContext({"in": SQL_DF}, {}, store, tmp_path), cfg).tables
    con = duckdb.connect(":memory:")
    install_all(con)
    con.register("entrada", SQL_DF)
    described = con.execute('DESCRIBE "entrada"').fetchall()
    source = SqlInput(
        "entrada", [str(r[0]) for r in described], {str(r[0]): kind_of(str(r[1])) for r in described}
    )
    fragments = SQL_REGISTRY["prep.data_quality"](SqlContext({"in": source}, sample=lambda _p: SQL_DF), cfg)
    for port in ("P", "F"):
        check = compare(con.sql(fragments[port].sql).pl(), engine[port])
        assert check.state == SAME, (port, check.detail, check.examples, fragments[port].sql)
    con.close()


@pytest.mark.parametrize("kind", ["cpf", "cnpj", "date"])
def test_rules_without_sql_say_so(kind: str) -> None:
    from prodata.engine.sql.fragment import SQL_REGISTRY, NoTranslationError, SqlContext, SqlInput

    cfg = REGISTRY["prep.data_quality"].config.model_validate({"rules": [{"kind": kind, "column": "x"}]})
    with pytest.raises(NoTranslationError, match="ainda não tem tradução"):
        SQL_REGISTRY["prep.data_quality"](SqlContext({"in": SqlInput("e", ["x"], {"x": "String"})}), cfg)


# ------------------------------------------------------------------ lista permitida de outra tabela (RF-2840)

UFS = pl.DataFrame({"sigla": ["SP", " rj ", None, "", "SP"], "nome": ["São Paulo", "Rio", "x", "y", "z"]})


def test_allowed_values_from_table_ignore_blanks_and_repeats() -> None:
    df = pl.DataFrame({"uf": ["SP", "RJ", "XX", None, "mg"]})
    rule = {"kind": "allowed", "column": "uf", "values_from": "table", "list_column": "sigla"}
    passed, failed, counts = check_quality(df, [QualityRule.model_validate(rule)], UFS)
    assert failed["uf"].to_list() == ["XX", "mg"] and passed.height == 3
    assert counts[0]["failed"] == 2


def test_allowed_values_from_table_explain_what_is_missing() -> None:
    df = pl.DataFrame({"uf": ["SP"]})
    rule = QualityRule.model_validate({"kind": "allowed", "column": "uf", "values_from": "table"})
    with pytest.raises(ValueError, match=r"Conecte na entrada \[L\]"):
        check_quality(df, [rule])
    with pytest.raises(ValueError, match=r"Escolha a coluna de \[L\]"):
        check_quality(df, [rule], UFS)
    with pytest.raises(ValueError, match=r"\[sig\] não existe"):
        check_quality(df, [rule.model_copy(update={"list_column": "sig"})], UFS)
    empty = pl.DataFrame({"sigla": [None, " "]}, schema={"sigla": pl.String})
    with pytest.raises(ValueError, match="está vazia"):
        check_quality(df, [rule.model_copy(update={"list_column": "sigla"})], empty)


def test_list_port_only_when_a_rule_asks() -> None:
    port = next(p for p in REGISTRY["prep.data_quality"].inputs if p.id == "L")
    assert not port.required and port.when == {"rules[].values_from": ["table"]}


@pytest.mark.parametrize("ignore_case", [True, False])
def test_sql_with_list_from_table_matches_engine(
    ignore_case: bool, store: DatasetStore, tmp_path: Path
) -> None:
    import duckdb

    from prodata.engine.sql.fragment import SQL_REGISTRY, SqlContext, SqlInput
    from prodata.engine.sql.verify import SAME, compare

    rule = {
        "kind": "allowed",
        "column": "uf",
        "values_from": "table",
        "list_column": "sigla",
        "ignore_case": ignore_case,
    }
    cfg = REGISTRY["prep.data_quality"].config.model_validate({"rules": [rule]})
    engine = (
        REGISTRY["prep.data_quality"]
        .run(NodeContext({"in": SQL_DF, "L": UFS}, {}, store, tmp_path), cfg)
        .tables
    )
    con = duckdb.connect(":memory:")
    con.register("entrada", SQL_DF)
    con.register("ufs", UFS)
    kinds = {"id": "number", "nome": "text", "email": "text", "idade": "number", "uf": "text"}
    ctx = SqlContext(
        {"in": SqlInput("entrada", list(SQL_DF.columns), kinds), "L": SqlInput("ufs", ["sigla", "nome"], {})}
    )
    fragments = SQL_REGISTRY["prep.data_quality"](ctx, cfg)
    assert "NOT IN (SELECT" in fragments["F"].sql
    for port in ("P", "F"):
        check = compare(con.sql(fragments[port].sql).pl(), engine[port])
        assert check.state == SAME, (port, check.detail, fragments[port].sql)
    con.close()
