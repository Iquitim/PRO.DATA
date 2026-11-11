"""Output Data num modelo de Excel (spec 033): grava só os valores numa cópia da planilha já formatada."""

from __future__ import annotations

import os
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from prodata.domain.labels import (
    DEFAULT_LABEL,
    EXCEL_PROPERTY,
    LABEL_COLORS,
    LABEL_NAMES,
    level_from_name,
    most_restrictive,
)
from prodata.errors import InvalidInputError

MAX_TEMPLATE_ROWS = 200_000
_PLAIN = (str, int, float, bool, date, datetime, time)


def template_path(raw: str) -> Path:
    """Modelo escolhido pelo usuário: caminho completo, existente, .xlsx. Só é lido."""
    path = Path(raw.strip())
    if not path.is_absolute():
        raise InvalidInputError("O modelo precisa do caminho completo, como D:\\Modelos\\fechamento.xlsx.")
    if path.suffix.lower() != ".xlsx":
        raise InvalidInputError("O modelo precisa ser um arquivo .xlsx.")
    if not path.is_file():
        raise InvalidInputError(f"O modelo não existe: {path}")
    return path.resolve()


def drawing_warning(path: Path) -> str | None:
    """Gráficos e imagens são reescritos pela biblioteca e podem mudar: melhor avisar antes de alguém confiar."""
    try:
        with zipfile.ZipFile(path) as book:
            names = book.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise InvalidInputError(f"O modelo não é um arquivo .xlsx válido: {exc}") from exc
    kinds = [
        label
        for prefix, label in (
            ("xl/charts/", "gráficos"),
            ("xl/media/", "imagens"),
            ("xl/pivotTables/", "tabelas dinâmicas"),
        )
        if any(n.startswith(prefix) for n in names)
    ]
    if not kinds:
        return None
    return f"O modelo tem {' e '.join(kinds)}: confira no arquivo gerado, porque nem sempre são preservados."


def _value(v: Any) -> Any:
    if v is None or isinstance(v, _PLAIN):
        return v
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


def _fill(ws: Any, df: pl.DataFrame, first_row: int, first_col: int, header: bool, clear: bool) -> int:
    """Grava cabeçalho e linhas mudando só o valor das células. Devolve a última linha gravada."""
    row = first_row
    if header:
        for i, column in enumerate(df.columns):
            ws.cell(row=row, column=first_col + i, value=column)
        row += 1
    for record in df.iter_rows():
        for i, v in enumerate(record):
            ws.cell(row=row, column=first_col + i, value=_value(v))
        row += 1
    if clear:
        for old in range(row, ws.max_row + 1):
            for col in range(first_col, first_col + max(df.width, 1)):
                ws.cell(row=old, column=col).value = None
    return row - 1


def write_template(
    df: pl.DataFrame,
    template: Path,
    target: Path,
    *,
    sheet: str,
    cell: str,
    header: bool,
    clear: bool,
    label: str = DEFAULT_LABEL,
) -> None:
    from openpyxl import load_workbook
    from openpyxl.packaging.custom import StringProperty
    from openpyxl.utils import get_column_letter, range_boundaries
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
    from openpyxl.utils.exceptions import CellCoordinatesException

    if target.resolve() == template:
        raise InvalidInputError("O arquivo de destino é o próprio modelo: escolha outro nome ou outra pasta.")
    if df.height > MAX_TEMPLATE_ROWS:
        raise InvalidInputError(
            f"O modelo aceita até {MAX_TEMPLATE_ROWS:,} linhas. Para mais, grave sem modelo.".replace(
                ",", "."
            )
        )
    try:
        letters, first_row = coordinate_from_string(cell.strip().upper() or "A1")
        first_col = column_index_from_string(letters)
    except (ValueError, CellCoordinatesException) as exc:
        raise InvalidInputError(f"'{cell}' não é uma célula: use algo como A2.") from exc
    try:
        book = load_workbook(template)
    except Exception as exc:  # arquivo corrompido ou protegido: mensagem acionável
        raise InvalidInputError(f"Não foi possível abrir o modelo {template.name}: {exc}") from exc
    name = sheet.strip()
    if name and name not in book.sheetnames:
        raise InvalidInputError(
            f"O modelo não tem a planilha '{name}'. Planilhas: {', '.join(book.sheetnames)}."
        )
    ws = book[name] if name else book.active
    if ws is None:
        raise InvalidInputError("O modelo não tem planilha.")

    last_row = _fill(ws, df, first_row, first_col, header, clear)
    last_col = first_col + max(df.width, 1) - 1
    # Tabela do Excel que começa na célula inicial acompanha o tamanho dos dados.
    for table in ws.tables.values():
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        if min_row == first_row and min_col == first_col and header:
            end = max(last_row, first_row + 1)  # o Excel exige ao menos uma linha de dados
            table.ref = (
                f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max(max_col or 0, last_col))}{end}"
            )

    current = next((p.value for p in book.custom_doc_props.props if p.name == EXCEL_PROPERTY), None)
    title = LABEL_NAMES[most_restrictive(level_from_name(current) or label, label)]
    book.custom_doc_props.props = [p for p in book.custom_doc_props.props if p.name != EXCEL_PROPERTY]
    book.custom_doc_props.append(StringProperty(name=EXCEL_PROPERTY, value=title))
    book.properties.category = title
    book.properties.keywords = f"Classificação: {title}"
    ws.sheet_properties.tabColor = LABEL_COLORS[label].lstrip("#")
    ws.oddHeader.center.text = LABEL_NAMES[label]
    ws.oddFooter.center.text = LABEL_NAMES[label]
    tmp = target.with_name(target.name + ".tmp")
    book.save(tmp)
    os.replace(tmp, target)
