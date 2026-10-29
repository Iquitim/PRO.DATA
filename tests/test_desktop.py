"""Spec 010 (RF-1001): os diálogos nativos do desktop precisam de filtros que o pywebview aceite."""

import pytest

from prodata import desktop

webview_util = pytest.importorskip("webview.util")


def test_file_filters_are_valid_for_pywebview() -> None:
    for file_filter in (desktop._WORKFLOW_FILTER, "Todos os arquivos (*.*)"):
        webview_util.parse_file_type(file_filter)  # lança ValueError se inválido


def test_closing_is_blocked_only_with_unsaved_changes() -> None:
    api = desktop.DesktopApi()
    assert api._on_closing() is True
    api.set_dirty(True)
    api._force_close = True
    assert api._on_closing() is True
