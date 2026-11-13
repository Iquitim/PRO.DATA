"""Capturas da pasta de arquivos na vista Dados (spec 035): o detalhe da fonte e o cadastro com a lista ao vivo.

Usado por ``gerar_imagens.py``. Monta uma pasta de fechamento com quatro filiais, uma delas com uma coluna a mais.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

BRANCHES = {
    "vendas_filial_centro.csv": "uf;valor;vendedor\nSP;9800;Ana\nSP;4100;Bruno\n",
    "vendas_filial_norte.csv": "uf;valor;vendedor\nPA;1200;Carla\nAM;830;Davi\n",
    "vendas_filial_sul.csv": "uf;valor;vendedor;canal\nRS;2100;Elisa;loja\nSC;1740;Fábio;site\n",
    "vendas_filial_leste.csv": "uf;valor;vendedor\nRJ;4300;Gabi\nES;960;Hugo\n",
}


def _seed(tmp: Path) -> Path:
    folder = tmp / "Fechamento" / "2026-10"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in BRANCHES.items():
        (folder / name).write_text(text, encoding="utf-8")
    (folder / "leia-me.txt").write_text("Pasta do fechamento de outubro.", encoding="utf-8")
    return folder


def part_folder_source(pg: Any, tmp: Path, shot: Callable[..., None]) -> None:
    folder = _seed(tmp)
    pg.evaluate(
        """async (folder) => {
          await window.__API.createFolderSource({ name: 'Vendas das filiais', folder, pattern: 'vendas_filial_*.csv', file_column: 'arquivo' });
          await (await import('/static/js/folder_sources.js')).refreshFolderSources();
        }""",
        str(folder),
    )
    pg.click("#viewSwitch .segment[data-view=data]")
    card = pg.locator(".dv-card-item[data-key^='folder:']")
    card.wait_for(timeout=10000)
    card.click()
    pg.wait_for_selector(".fd-overview .dv-quality", timeout=15000)
    pg.wait_for_timeout(600)
    main = pg.locator(".dv-main").bounding_box()
    shot(pg, "dados-pasta", clip={**main, "height": min(main["height"], 900)})

    pg.locator(".dv-list-head button").click()
    pg.locator(".menu .menu-item", has_text="Pasta de arquivos").click()
    pg.wait_for_selector(".fd-editor")
    form = pg.locator(".fd-form")
    form.locator("input").nth(0).fill("Vendas das filiais")
    form.locator("input").nth(1).fill(str(folder))
    form.locator("input").nth(2).fill("vendas_filial_*.csv")
    pg.wait_for_selector(".fd-live .fd-file.odd", timeout=8000)
    pg.wait_for_timeout(500)
    main = pg.locator(".dv-main").bounding_box()
    shot(pg, "dados-pasta-cadastro", clip={**main, "height": min(main["height"], 700)})

    # Um por arquivo: cada arquivo vira uma fonte, agrupadas numa pasta da organização.
    pg.locator(".fd-mode[data-mode=each]").click()
    pg.wait_for_selector(".fd-live h3:has-text('Fontes que serão criadas')", timeout=8000)
    pg.wait_for_timeout(500)
    main = pg.locator(".dv-main").bounding_box()
    shot(pg, "dados-pasta-separados", clip={**main, "height": min(main["height"], 700)})
    pg.locator(".dv-editor-actions button", has_text="Cancelar").click()
