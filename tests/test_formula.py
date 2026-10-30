from datetime import date

import polars as pl
import pytest
from fastapi.testclient import TestClient

from prodata.engine import formula

DF = pl.DataFrame(
    {
        "nome": ["  Ana ", "Bruno", None, "carla"],
        "valor": [10.0, 3000.0, 7000.0, None],
        "status": ["ATIVO", "INATIVO", "ATIVO", "ATIVO"],
    }
)


def test_if_elseif_else() -> None:
    out = formula.evaluate_columns(
        DF,
        [
            {
                "column": "tier",
                "type": "String",
                "expression": "IF [valor] >= 6000 THEN 'A' ELSEIF [valor] >= 3000 THEN 'B' ELSE 'C' ENDIF",
            }
        ],
    )
    assert out["tier"].to_list() == ["C", "B", "A", "C"]


def test_double_quoted_strings_are_literals() -> None:
    mask = formula.evaluate_mask(DF, 'Contains([status], "INAT")')
    assert mask.to_list() == [False, True, False, False]


def test_nested_functions() -> None:
    out = formula.evaluate_columns(DF, [{"column": "n", "expression": "UpperCase(Trim([nome]))"}])
    assert out["n"].to_list() == ["ANA", "BRUNO", None, "CARLA"]


def test_negated_isnull_and_iif() -> None:
    out = formula.evaluate_columns(
        DF, [{"column": "tem_nome", "expression": "IIF(!IsNull([nome]), 'sim', 'nao')"}]
    )
    assert out["tem_nome"].to_list() == ["sim", "sim", "nao", "sim"]


def test_keywords_inside_strings_are_preserved() -> None:
    out = formula.evaluate_columns(DF, [{"column": "t", "expression": "'IF x THEN y == z!'"}])
    assert out["t"][0] == "IF x THEN y == z!"


def test_titlecase() -> None:
    out = formula.evaluate_columns(DF, [{"column": "t", "expression": "TitleCase('joão DA silva')"}])
    assert out["t"][0] == "João Da Silva"


def test_formula_can_use_previous_formula() -> None:
    out = formula.evaluate_columns(
        DF,
        [
            {"column": "anual", "type": "Float64", "expression": "[valor] * 12"},
            {"column": "dobro", "type": "Float64", "expression": "[anual] * 2"},
        ],
    )
    assert out["dobro"][0] == 240.0


def test_filter_mask_treats_null_as_false() -> None:
    mask = formula.evaluate_mask(DF, "[valor] > 100 AND [status] == 'ATIVO'")
    assert mask.to_list() == [False, False, True, False]


def test_unknown_column_is_reported() -> None:
    with pytest.raises(formula.FormulaError, match=r"\[inexistente\]"):
        formula.evaluate_mask(DF, "[inexistente] > 1")


def test_validate() -> None:
    cols = [{"name": "valor", "type": "Float64"}]
    assert formula.validate("Round([valor] * 12, 2)", cols)["valid"]
    result = formula.validate("[valor] +* 2", cols)
    assert not result["valid"] and result["error"]


def test_documented_examples_are_valid() -> None:
    """Spec 010 (RF-1011): o assistente só oferece exemplos que funcionam."""
    for doc in formula.FUNCTION_DOCS:
        result = formula.validate(doc.example, formula.SAMPLE_SCHEMA)
        assert result["valid"], (doc.name, result["error"])


def test_not_equal_operators() -> None:
    cols = [{"name": "uf", "type": "String"}]
    for op in ("!=", "<>"):
        assert formula.validate(f"[uf] {op} 'SP'", cols)["valid"]


def test_catalog_lists_documented_functions(client: TestClient) -> None:
    catalog = client.get("/api/catalog").json()
    names = {f["name"] for f in catalog["formula_functions"]}
    assert {"IIF", "Round", "Contains"} <= names
    assert "ENDIF" in catalog["formula_keywords"]["control"]


def test_incomplete_expression_has_friendly_message() -> None:
    cols = [{"name": "valor", "type": "Float64"}]
    assert "incompleta" in formula.validate("Round([valor], ", cols)["error"]
    assert "incompleta" in formula.validate("IF [valor] > 1 THEN 2", cols)["error"]
    assert "perto de" in formula.validate("[valor] > > 2", cols)["error"]


# ------------------------------------------------------------------ spec 015


def test_formula_can_change_an_existing_column_in_place() -> None:
    df = pl.DataFrame({"id": [1], "nome": ["  ana maria "], "uf": ["sp"]})
    out = formula.evaluate_columns(
        df, [{"target": "existing", "existing": "nome", "expression": "TitleCase(Trim([nome]))"}]
    )
    assert out.columns == ["id", "nome", "uf"] and out["nome"][0] == "Ana Maria"
    with pytest.raises(formula.FormulaError, match="não existe para ser alterada"):
        formula.evaluate_columns(df, [{"target": "existing", "existing": "sumiu", "expression": "1"}])


def test_brazilian_helpers() -> None:
    df = pl.DataFrame({"v": ["1.234,56"], "doc": ["123.456.789-00"], "d": [date(2026, 1, 31)]})
    out = formula.evaluate_columns(
        df,
        [
            {"column": "n", "expression": "ToNumberBR([v])"},
            {"column": "txt", "expression": "FormatNumber([n] * 1000, 2)"},
            {"column": "cpf", "expression": "DigitsOnly([doc])"},
            {"column": "venc", "expression": "DateAdd([d], 1, 'mês')"},
            {"column": "mes", "expression": "MonthName([d])"},
            {"column": "dias", "expression": "Date_Diff('dia', [d], DateAdd([d], 2, 'semana'))"},
        ],
    )
    row = out.row(0, named=True)
    assert row["n"] == 1234.56 and row["txt"] == "1.234.560,00" and row["cpf"] == "12345678900"
    assert row["venc"] == date(2026, 2, 28) and row["mes"] == "janeiro" and row["dias"] == 14


def test_plus_on_text_points_to_concat() -> None:
    result = formula.validate("[nome] + ' x'", [{"name": "nome", "type": "String"}])
    assert not result["valid"] and "Concat" in result["error"]
    assert "Candidate" not in formula.validate("Year([nome])", [{"name": "nome", "type": "String"}])["error"]
