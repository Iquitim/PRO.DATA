"""Spec 010 (RF-1001): os diálogos nativos do desktop precisam de filtros que o pywebview aceite."""

import base64
from pathlib import Path

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


def test_png_filter_and_names() -> None:
    webview_util.parse_file_type(desktop._PNG_FILTER)
    webview_util.parse_file_type(desktop._DATA_FILTER)
    assert desktop.png_name("Vendas 2026 - 29/10") == "10.png"  # barra separa pasta: fica só o nome
    assert desktop.png_name('Vendas: "jan"?') == "Vendas jan.png"
    assert desktop.png_name("relatorio.PNG") == "relatorio.png"
    assert desktop.png_name("...") == "dashboard.png"


def test_write_png_only_valid_images(tmp_path: Path) -> None:
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
    path = desktop.write_png(str(tmp_path / "painel.txt"), f"data:image/png;base64,{png}")
    assert path.name == "painel.txt.png" and path.read_bytes().startswith(b"\x89PNG")
    with pytest.raises(ValueError, match="inválida"):
        desktop.write_png(str(tmp_path / "x.png"), base64.b64encode(b"<html>").decode())
    with pytest.raises(ValueError, match="não existe"):
        desktop.write_png(str(tmp_path / "nada" / "x.png"), png)
    with pytest.raises(ValueError, match="pasta e o nome"):
        desktop.write_png("x.png", png)


def test_port_is_stable_with_fallback() -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        busy = probe.getsockname()[1]
        probe.listen()
        # Porta ocupada: usa outra. Porta livre: usa sempre a mesma.
        assert desktop.choose_port(busy) != busy
    free = desktop._free_port()
    assert desktop.choose_port(free) == free
