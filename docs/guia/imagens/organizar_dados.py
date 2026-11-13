"""Capturas da organização da vista Dados (spec 034): pastas, nome de exibição, descrição e a janela de nova pasta.

Usado por ``gerar_imagens.py``, depois das outras partes (que já cadastraram ``mes_referencia``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

SETUP = """async () => {
  const api = window.__API;
  await api.saveConstant({ name: 'meta_trimestre', type: 'number', value: '1500000', description: 'Meta de MRR do trimestre, em reais.' });
  await window.__C.refreshConstants();
  await api.addFolder('Vendas', 'azul');
  await api.addFolder('Metas e indicadores', 'verde');
  const org = await api.addFolder('Referências públicas', 'roxo');
  const [vendas, metas, publicas] = org.folders.map((f) => f.id);
  await api.changeSources(['file:transacoes_vendas.csv', 'file:clientes_enterprise.csv'], { folder: vendas });
  await api.changeSources(['file:metas_regionais_br.csv', 'const:meta_trimestre', 'const:mes_referencia'], { folder: metas });
  await api.changeSources(['api:exemplo_ibge_estados', 'api:exemplo_ibge_municipios'], { folder: publicas });
  await api.changeSources(['file:transacoes_vendas.csv'], { label: 'Transações de vendas', pinned: true });
  await api.changeSources(['file:clientes_enterprise.csv'], { label: 'Carteira de clientes' });
  await api.changeSources(['file:metas_regionais_br.csv'], {
    label: 'Metas por região',
    description: 'Meta de MRR e margem-alvo de cada UF, definidas pela diretoria comercial no início do trimestre.\\nAtualizada uma vez por trimestre.',
    owner: 'Ana, Planejamento Comercial',
  });
  await (await import('/static/js/organization.js')).refreshOrganization();
}"""


def part_organize(pg: Any, shot: Callable[..., None]) -> None:
    pg.evaluate(SETUP)
    pg.click("#viewSwitch .segment[data-view=data]")
    pg.wait_for_selector(".org-folder-title.is-folder", timeout=10000)
    pg.locator(".dv-card-item[data-key='file:metas_regionais_br.csv']").click()
    pg.wait_for_selector(".dv-quality", timeout=15000)
    pg.wait_for_timeout(600)
    shot(pg, "dados-pastas")

    # Nome de exibição: o título vira campo, com a explicação de que os fluxos não mudam.
    pg.locator(".org-title-btn").click()
    pg.wait_for_selector(".org-title-input")
    pg.wait_for_timeout(200)
    head = pg.locator(".dv-head").bounding_box()
    about = pg.locator(".org-about").bounding_box()
    shot(pg, "dados-nome-exibicao", clip={"x": head["x"] - 12, "y": head["y"] - 12, "width": head["width"] + 24,
                                          "height": about["y"] + about["height"] - head["y"] + 24})
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)

    pg.locator("button.org-new-folder").click()
    dlg = pg.locator("dialog[open]")
    dlg.locator("input").fill("Fechamento do mês")
    dlg.locator(".org-swatch[aria-label='Âmbar']").click()
    pg.wait_for_timeout(200)
    shot(dlg, "dados-nova-pasta")
    dlg.locator(".dialog-footer button", has_text="Cancelar").click()
