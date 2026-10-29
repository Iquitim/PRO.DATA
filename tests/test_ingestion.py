import io
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter

from prodata.errors import ConflictError, InvalidInputError, TooLargeError
from prodata.ingestion import DatasetStore, ReadOptions, inspect_file, read_table
from prodata.ingestion.datasets import resolve_inside, sanitize_filename
from prodata.ingestion.readers import resolve_options


def test_brazilian_csv_is_autodetected(tmp_path: Path) -> None:
    path = tmp_path / "br.csv"
    path.write_bytes("nome;valor;cidade\nJoão;1234,56;São Paulo\nMárcia;-7,5;Brasília\n".encode("cp1252"))

    opts = resolve_options(path, ReadOptions())
    assert (opts.encoding, opts.delimiter, opts.decimal) == ("cp1252", ";", ",")

    df = read_table(path, ReadOptions())
    assert df["nome"].to_list() == ["João", "Márcia"]
    assert df["valor"].dtype == pl.Float64
    assert df["valor"].to_list() == [1234.56, -7.5]


def test_utf8_bom_and_tab_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "t.tsv"
    path.write_bytes("﻿a\tb\n1\tx\n".encode())
    df = read_table(path, ReadOptions())
    assert df.columns == ["a", "b"]


def test_explicit_options_override_detection(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("cabecalho lixo\na,b\n1,2\n", encoding="utf-8")
    df = read_table(path, ReadOptions(delimiter=",", skip_rows=1))
    assert df.columns == ["a", "b"]


def test_null_values(tmp_path: Path) -> None:
    path = tmp_path / "n.csv"
    path.write_text("a,b\n1,NA\n2,x\n", encoding="utf-8")
    df = read_table(path, ReadOptions(null_values="NA"))
    assert df["b"].null_count() == 1


def test_json_vs_ndjson(tmp_path: Path) -> None:
    array = tmp_path / "a.json"
    array.write_text('[{"a": 1}, {"a": 2}]', encoding="utf-8")
    lines = tmp_path / "l.json"
    lines.write_text('{"a": 1}\n{"a": 2}\n{"a": 3}\n', encoding="utf-8")
    assert resolve_options(array, ReadOptions()).format == "json"
    assert resolve_options(lines, ReadOptions()).format == "ndjson"
    assert read_table(lines, ReadOptions()).height == 3


def test_excel_sheets_and_preview(tmp_path: Path) -> None:
    path = tmp_path / "p.xlsx"
    with xlsxwriter.Workbook(path) as wb:
        for name, rows in (("Vendas", [["a", "b"], [1, "x"], [2, "y"]]), ("Metas", [["m"], [10]])):
            ws = wb.add_worksheet(name)
            for r, row in enumerate(rows):
                ws.write_row(r, 0, row)
    info = inspect_file(path, ReadOptions(sheet="Metas"))
    assert info["sheets"] == ["Vendas", "Metas"]
    assert [c["name"] for c in info["columns"]] == ["m"]
    assert info["row_count"] == 1
    assert read_table(path, ReadOptions()).height == 2


def test_parquet_row_count(tmp_path: Path) -> None:
    path = tmp_path / "x.parquet"
    pl.DataFrame({"a": range(1000)}).write_parquet(path)
    info = inspect_file(path, ReadOptions(), rows=5)
    assert info["row_count"] == 1000
    assert len(info["rows"]) == 5


def test_preview_rows_are_json_safe(tmp_path: Path) -> None:
    path = tmp_path / "x.parquet"
    pl.DataFrame({"a": [float("nan"), 1.0]}).write_parquet(path)
    assert inspect_file(path, ReadOptions())["rows"][0]["a"] is None


@pytest.mark.parametrize("name", ["../evil.csv", "..\\..\\evil.csv", "/etc/passwd", "sub/dir.csv"])
def test_resolve_inside_blocks_traversal(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidInputError):
        resolve_inside(tmp_path, name)


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../relatório final (v2).CSV") == "relatório_final_v2.csv"


def test_upload_rules(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path, max_bytes=100)
    info = store.save("../dados.csv", io.BytesIO(b"a,b\n1,2\n"))
    assert info.name == "dados.csv" and (tmp_path / "dados.csv").exists()
    with pytest.raises(ConflictError):
        store.save("dados.csv", io.BytesIO(b"a\n1\n"))
    with pytest.raises(InvalidInputError):
        store.save("script.py", io.BytesIO(b"print(1)"))
    with pytest.raises(TooLargeError):
        store.save("grande.csv", io.BytesIO(b"x" * 101))
    assert not any(p.suffix == ".part" for p in tmp_path.iterdir())


def test_excel_table_below_title_and_right_of_columns(tmp_path: Path) -> None:
    """Spec 011: tabela que não começa em A1 (título acima, coluna de apoio à esquerda)."""
    path = tmp_path / "relatorio.xlsx"
    with xlsxwriter.Workbook(path) as wb:
        wb.add_worksheet("Capa").write("A1", "Relatório mensal")
        ws = wb.add_worksheet("Dados")
        ws.write("A1", "Vendas por região - Outubro")
        ws.write_row("A4", ["uso interno", "regiao", "vendas"])
        ws.write_row("A5", ["x", "Sul", 100])
        ws.write_row("A6", ["y", "Norte", 80])
    df = read_table(path, ReadOptions(sheet="Dados", skip_rows=3, skip_columns=1))
    assert df.columns == ["regiao", "vendas"]
    assert df.rows() == [("Sul", 100.0), ("Norte", 80.0)]
    info = inspect_file(path, ReadOptions(sheet="Dados", skip_rows=3))
    assert info["sheets"] == ["Capa", "Dados"]
    assert info["columns"][0]["name"] == "uso interno"


def test_csv_skip_rows_and_columns(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text("Exportado em 01/10\n\nlixo;regiao;vendas\n;Sul;10\n;Norte;8\n", encoding="utf-8")
    df = read_table(path, ReadOptions(skip_rows=2, skip_columns=1))
    assert df.columns == ["regiao", "vendas"] and df.height == 2


def test_skipping_every_column_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    path.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="não deixa nada"):
        read_table(path, ReadOptions(skip_columns=2))
