"""Gravação de Excel do Output Data: várias planilhas no mesmo arquivo e rótulo de confidencialidade."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import xlsxwriter

from prodata.domain.labels import (
    DEFAULT_LABEL,
    EXCEL_PROPERTY,
    LABEL_COLORS,
    LABEL_NAMES,
    level_from_name,
    most_restrictive,
)
from prodata.errors import InvalidInputError

_BAD_SHEET_CHARS = set("[]:*?/\\")

if TYPE_CHECKING:
    from prodata.nodes.io import OutputDataConfig


MAX_SHEETS = 8


def sheet_title(raw: str) -> str:
    """Nome de planilha aceito pelo Excel: 1 a 31 caracteres, sem colchetes, : * ? / ou barra invertida."""
    name = raw.strip() or "Dados"
    bad = sorted(set(name) & _BAD_SHEET_CHARS)
    if bad:
        raise InvalidInputError(f"O nome da planilha não pode ter {' '.join(bad)}.")
    if len(name) > 31:
        raise InvalidInputError("O nome da planilha tem no máximo 31 caracteres.")
    return name


def write_excel_sheet(
    df: pl.DataFrame, path: Path, sheet: str, add: bool, label: str = DEFAULT_LABEL
) -> None:
    """Grava a planilha. Com ``add`` e arquivo existente, mantém as outras planilhas (e a posição desta)."""
    if not (add and path.exists()):
        write_excel_book([(sheet, df)], path, False, label)
        return
    from openpyxl import load_workbook
    from openpyxl.packaging.custom import StringProperty

    try:
        book = load_workbook(path)
    except Exception as exc:  # arquivo corrompido ou que não é xlsx: mensagem acionável
        raise InvalidInputError(
            f"Não foi possível abrir {path.name} para adicionar a planilha: {exc}"
        ) from exc
    position = len(book.sheetnames)
    if sheet in book.sheetnames:
        position = book.sheetnames.index(sheet)
        del book[sheet]
    ws = book.create_sheet(sheet, position)
    ws.append(df.columns)
    for row in df.iter_rows():
        ws.append(list(row))
    for i, col in enumerate(df.columns, start=1):  # largura aproximada, como o autofit do write_excel
        sample = [len(str(v)) for v in df[col].head(200).to_list() if v is not None]
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max([len(col), *sample]) + 2)
    # O arquivo fica com o nível mais restrito entre o que já tinha e o da planilha nova.
    current = next((p.value for p in book.custom_doc_props.props if p.name == EXCEL_PROPERTY), None)
    level = most_restrictive(level_from_name(current) or label, label)
    title = LABEL_NAMES[level]
    book.custom_doc_props.props = [p for p in book.custom_doc_props.props if p.name != EXCEL_PROPERTY]
    book.custom_doc_props.append(StringProperty(name=EXCEL_PROPERTY, value=title))
    book.properties.category = title
    book.properties.keywords = f"Classificação: {title}"
    ws.sheet_properties.tabColor = LABEL_COLORS[label].lstrip("#")
    ws.oddHeader.center.text = LABEL_NAMES[label]
    ws.oddFooter.center.text = LABEL_NAMES[label]
    tmp = path.with_name(path.name + ".tmp")
    book.save(tmp)
    os.replace(tmp, path)


def _sheet_list(
    df: pl.DataFrame, extras: dict[str, pl.DataFrame], cfg: OutputDataConfig
) -> list[tuple[str, pl.DataFrame]]:
    """Planilhas do arquivo, na ordem das entradas. Nomes são conferidos antes de gravar qualquer coisa."""
    ordered = sorted(extras, key=lambda p: int(p[2:]))
    sheets = [(sheet_title(cfg.sheet_name), df)]
    sheets += [(sheet_title(cfg.sheet_names.get(p) or f"Planilha {p[2:]}"), extras[p]) for p in ordered]
    seen: set[str] = set()
    for name, _ in sheets:
        if name.casefold() in seen:  # o Excel não diferencia maiúsculas
            raise InvalidInputError(
                f'Duas planilhas com o nome "{name}": cada entrada precisa de um nome próprio.'
            )
        seen.add(name.casefold())
    return sheets


def _label_new_sheet(sheet: Any, label: str) -> None:
    name = LABEL_NAMES[label]
    sheet.set_tab_color(LABEL_COLORS[label])
    sheet.set_header(f"&C{name}")
    sheet.set_footer(f"&C{name}")


def write_excel_book(
    sheets: list[tuple[str, pl.DataFrame]], path: Path, add: bool, label: str = DEFAULT_LABEL
) -> None:
    """Grava as planilhas com o rótulo, sem tocar nas células. Sem ``add``, o arquivo é criado de uma vez."""
    if add and path.exists():
        for name, table in sheets:
            write_excel_sheet(table, path, name, True, label)
        return
    tmp = path.with_name(path.name + ".tmp.xlsx")
    name = LABEL_NAMES[label]
    with xlsxwriter.Workbook(tmp) as book:
        book.set_properties({"category": name, "keywords": f"Classificação: {name}"})
        book.set_custom_property(EXCEL_PROPERTY, name)
        for sheet_name, table in sheets:
            table.write_excel(book, worksheet=sheet_name, autofit=True)
            _label_new_sheet(book.get_worksheet_by_name(sheet_name), label)
    os.replace(tmp, path)
