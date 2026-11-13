"""Refaz as capturas do guia e do Manual, no tema claro e no escuro (spec 029, RF-2983).

    uv run --with playwright --with pillow python docs/guia/imagens/gerar_imagens.py [claro|escuro]

Sobe o programa num servidor próprio, com a pasta de dados zerada, e usa o fluxo de demonstração. Precisa do Chrome e
de internet (o exemplo do IBGE). As imagens vão para src/prodata/web/manual/img (claro) e img-escuro. Rodar depois de
qualquer mudança de tela; a última etapa é `docs/guia/gerar_pdf.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from novas_075 import part_new_tools  # noqa: E402
from organizar_dados import part_organize as organize  # noqa: E402

PORT = 8796
FAKE_JIRA = 8797
URL = f"http://127.0.0.1:{PORT}/"
Pg = Page

done: list[str] = []
errors: list[str] = []
OUT = ROOT / "src/prodata/web/manual/img"


def shot(target: Any, name: str, **kw: Any) -> None:
    # Aviso de um passo anterior (ex.: "Imagem salva") não pode aparecer no print.
    getattr(target, "page", target).evaluate("() => document.querySelectorAll('.toast').forEach((t) => t.remove())")
    target.screenshot(path=str(OUT / f"{name}.png"), **kw)
    done.append(name)


def crop(name: str, src: str, box: tuple[float, float, float, float]) -> None:
    """Recorte de uma captura de página inteira; box em pixels CSS (a imagem está em 2x)."""
    x, y, w, h = (round(v * 2) for v in box)
    Image.open(OUT / f"{src}.png").crop((x, y, x + w, y + h)).save(OUT / f"{name}.png")
    done.append(name)


def wait_run(pg: Pg) -> None:
    pg.wait_for_function("() => !window.__S.store.running", timeout=120000)
    pg.wait_for_timeout(500)


def execute(pg: Pg) -> None:
    pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(600)
    if pg.locator("dialog[open] .export-ask").count():
        pg.locator("dialog[open] button:has-text('Executar')").last.click()
    wait_run(pg)


def inspect(pg: Pg, node: str, port: str | None = None) -> None:
    extra = f", {port!r}" if port else ""
    pg.evaluate(f"() => {{ window.__S.select('{node}'); window.__S.inspect('{node}'{extra}); }}")
    pg.wait_for_timeout(900)


def layout(pg: Pg, code: str) -> None:
    pg.evaluate(f"async () => {{ const L = await import('/static/js/layout.js'); {code} }}")
    pg.wait_for_timeout(500)


def ready(pg: Pg) -> None:
    pg.wait_for_function("() => document.querySelectorAll('.node').length > 15", timeout=60000)
    pg.evaluate("async () => { window.__S = await import('/static/js/store.js'); window.__A = await import('/static/js/actions.js'); window.__API = (await import('/static/js/api.js')).api; window.__C = await import('/static/js/constants.js'); }")
    pg.wait_for_function("() => window.__S.store.execution && !window.__S.store.running", timeout=120000)
    pg.wait_for_timeout(800)


def open_export_menu(pg: Pg) -> None:
    pg.evaluate("() => { document.querySelector('.dash-export-menu').hidden = false; }")


# ---------------------------------------------------------------- tela, resultados, dashboard e SQL


def part_screen(pg: Pg) -> None:
    # Só a caixa Clientes inspecionada, sem nada selecionado: a tela como quem acabou de abrir o programa.
    inspect(pg, "n_clientes")
    pg.evaluate("() => window.__S.select(null)")
    pg.locator("#leftPanel .tab[data-tab=tools]").click()
    pg.wait_for_timeout(500)
    shot(pg, "overview")

    layout(pg, "['explorer','results','insights'].forEach(L.hidePanel);")
    pg.keyboard.press("Escape")
    pg.keyboard.press("f")
    pg.wait_for_timeout(700)
    shot(pg, "_flow")
    vp = pg.locator("#canvas").bounding_box()
    nodes = pg.evaluate("() => { const r = [...document.querySelectorAll('.node, .container-box')].map(e => e.getBoundingClientRect()); return [Math.min(...r.map(x => x.top)), Math.max(...r.map(x => x.bottom))]; }")
    top = max(vp["y"], nodes[0] - 14)
    crop("flow-crop", "_flow", (vp["x"] + 30, top, min(1540, vp["width"] - 60), min(425, nodes[1] - top + 14)))
    layout(pg, "L.resetLayout();")

    layout(pg, "L.movePanel('results', 'bottom'); L.movePanel('insights', 'right');")
    inspect(pg, "n_clientes")
    pg.mouse.click(700, 500)
    shot(pg, "layoutAlt")
    layout(pg, "L.resetLayout();")

    box = pg.locator(".node[data-id='n_clientes']").bounding_box()
    pg.locator(".node[data-id='n_clientes']").click(button="right")
    pg.wait_for_selector(".menu")
    pg.wait_for_timeout(300)
    menu = pg.locator(".menu").bounding_box()
    shot(pg, "menu-crop", clip={"x": box["x"] - 20, "y": box["y"] - 15, "width": menu["x"] + menu["width"] - box["x"] + 30, "height": menu["y"] + menu["height"] - box["y"] + 30})
    pg.keyboard.press("Escape")
    pg.mouse.click(700, 600)

    pg.evaluate("() => { window.__S.select(null, null, 'c_prep'); window.__S.inspect(null); }")
    pg.wait_for_timeout(800)
    shot(pg, "_container")
    panel = pg.locator("#leftPanel").bounding_box()
    crop("container-crop", "_container", (panel["x"], panel["y"] + 40, 300, 752))
    pg.locator("[data-container='c_prep'] .container-toggle").first.click()
    pg.wait_for_timeout(600)
    pg.mouse.click(900, 700)
    pg.wait_for_timeout(400)
    shot(pg, "_containerOff")
    cbox = pg.locator("[data-container='c_prep']").first.bounding_box()
    crop("containerOff-crop", "_containerOff", (cbox["x"] - 10, cbox["y"] - 10, min(840, cbox["width"] + 20), 160))
    pg.locator("[data-container='c_prep'] .container-toggle").first.click()
    pg.wait_for_timeout(400)
    execute(pg)

    inspect(pg, "n_clientes")
    for col, op, val in (("uf", "eq", "SP"), ("mrr_mensal", "ge", "3000")):
        pg.locator("#results button:has-text('Filtros')").click()
        ed = pg.locator(".filter-editor")
        ed.locator("select").nth(0).select_option(col)
        ed.locator("select").nth(1).select_option(op)
        ed.locator("input").fill(val)
        ed.locator("button:has-text('Aplicar')").click()
        pg.wait_for_timeout(900)
    shot(pg, "_filters")
    res = pg.locator("#results").bounding_box()
    crop("filters-crop", "_filters", (res["x"], res["y"], 460, 608))
    pg.locator("#results button:has-text('Limpar')").first.click()
    pg.wait_for_timeout(500)

    inspect(pg, "n_join", "J")
    pg.locator("#results .tab[data-tab=profile]").click()
    pg.wait_for_timeout(1200)
    shot(pg, "_profile")
    res = pg.locator("#results").bounding_box()
    crop("profile-crop", "_profile", (res["x"], res["y"], 460, 608))
    pg.locator("#results .tab[data-tab=data]").click()

    inspect(pg, "n_join", "J")
    pg.wait_for_selector(".explainer table")
    shot(pg, "join")
    shot(pg.locator(".explainer"), "explain-join")
    pg.evaluate("() => document.documentElement.style.setProperty('--left-w', '460px')")
    pg.wait_for_timeout(400)
    table = pg.locator(".inspector .select-tools").locator("xpath=ancestor::*[contains(@class,'field')][1]")
    table.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    shot(table, "join-select")
    pg.evaluate("() => document.documentElement.style.removeProperty('--left-w')")
    pg.wait_for_timeout(300)

    inspect(pg, "n_sum_uf")
    pg.wait_for_selector(".explainer table")
    pg.wait_for_timeout(500)
    pg.locator(".explainer td[data-link^='g:']").first.hover()
    pg.wait_for_timeout(200)
    shot(pg.locator(".explainer"), "explain-summarize")
    cross = pg.evaluate("""() => { const S = window.__S, A = window.__A; const n = A.addNode('transform.crosstab', 300, 1100);
      S.mutate((wf) => { Object.assign(wf.nodes.find((k) => k.id === n.id).config, { group_by: ['uf'], header: 'segmento', value: 'mrr_mensal' }); });
      A.connect('n_join', 'J', n.id, 'in'); return n.id; }""")
    execute(pg)
    inspect(pg, cross)
    pg.wait_for_selector(".explainer table")
    pg.locator(".explainer td[data-link^='c:']").nth(1).hover()
    pg.wait_for_timeout(200)
    shot(pg.locator(".explainer"), "explain-crosstab")
    pg.evaluate("() => { window.__S.undo(); window.__S.undo(); window.__S.undo(); }")

    inspect(pg, "n_formula")
    area = pg.locator(".inspector .fx-input").nth(1)
    area.scroll_into_view_if_needed()
    area.click()
    pg.keyboard.press("Control+a")
    area.type("IF [mrr_mensal] >= 6000 AND [segmento] != 'Startup' THEN 'Diamond' ELSE Rou", delay=5)
    pg.wait_for_selector(".fx-suggest .fx-item-doc", timeout=5000)
    pg.wait_for_timeout(500)
    abox = area.bounding_box()
    shot(pg, "formula-crop", clip={"x": abox["x"] - 12, "y": abox["y"] - 300, "width": 540, "height": 450})
    pg.keyboard.press("Escape")
    pg.evaluate("() => { for (let i = 0; i < 5; i++) window.__S.undo(); }")
    pg.mouse.click(900, 700)

    pg.evaluate("async () => { const D = await import('/static/js/datasets.js'); D.openPreview('metas_regionais_br.csv', { applyLabel: 'Adicionar ao fluxo', onApply: () => {} }); }")
    pg.wait_for_selector("dialog[open] .data-table")
    pg.wait_for_timeout(800)
    shot(pg.locator("dialog[open]"), "preview-crop")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(400)

    pg.evaluate("async () => { const C = await import('/static/js/connections.js'); C.openConnectionDialog(); }")
    pg.wait_for_selector("dialog[open]")
    dlg = pg.locator("dialog[open]")
    for label, value in (("Nome", "Data Warehouse"), ("Servidor (host)", "dw.empresa.local"), ("Database", "vendas"), ("Usuário", "analista_leitura")):
        dlg.locator(f".field:has(.field-label:text-is('{label}')) input, label:has-text('{label}') input").first.fill(value)
    pg.mouse.move(5, 5)
    pg.wait_for_timeout(300)
    shot(dlg, "connection-crop")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)


def part_cache_dashboard(pg: Pg) -> None:
    pg.locator(".node[data-id='n_join']").click(button="right", force=True)
    pg.locator(".menu .menu-item", has_text="Cachear").first.click()
    wait_run(pg)
    execute(pg)
    pg.locator(".node[data-id='n_join']").click(force=True)
    pg.wait_for_timeout(700)
    box = pg.locator("#canvas").bounding_box()
    shot(pg, "cache-crop", clip={"x": box["x"], "y": box["y"] + 60, "width": min(832, box["width"]), "height": 380})

    pg.click("#viewSwitch .segment[data-view=dashboard]")
    pg.wait_for_selector(".dash-page .venn")
    pg.wait_for_timeout(900)
    for item, name in (("d_n_pareto", "dash-pareto"), ("d_n_venn", "dash-venn"), ("d_n_kpi_mes", "dash-kpi"), ("d_n_stacked", "dash-stacked")):
        shot(pg.locator(f".dash-item[data-id='{item}']"), name)

    open_export_menu(pg)
    with pg.expect_download() as dl:
        pg.click(".dash-actions button:has-text('Baixar imagem')")
        pg.wait_for_timeout(500)
        if pg.locator("dialog[open] button:has-text('Baixar assim mesmo')").count():
            pg.locator("dialog[open] button:has-text('Baixar assim mesmo')").click()
    tmp = OUT / "_export.png"
    dl.value.save_as(tmp)
    img = Image.open(tmp)
    img.resize((2000, round(img.height * 2000 / img.width)), Image.Resampling.LANCZOS).save(OUT / "dash-export.png")
    img.close()
    tmp.unlink()
    done.append("dash-export")

    pg.click("text=Editar layout")
    pg.wait_for_selector(".dash-page.editing")
    pg.wait_for_timeout(500)
    pg.locator(".dash-item[data-id='d_n_pareto']").click()
    pg.wait_for_selector(".dash-panel >> text=Gráfico")
    pg.wait_for_timeout(400)
    shot(pg, "dash-edit")
    box = pg.locator(".dash-item[data-id='d_n_chart_uf']").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(box["x"] + box["width"] / 2 - 9, box["y"] + box["height"] / 2 + 3, steps=6)
    pg.wait_for_timeout(200)
    shot(pg.locator(".dash-stage"), "dash-guides")
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=3)
    pg.mouse.up()
    pg.keyboard.press("Escape")
    pg.click(".dash-actions button:has-text('Organizar')")
    pg.wait_for_selector(".organize-option")
    pg.wait_for_timeout(300)
    shot(pg.locator("dialog[open]"), "dash-organize")


def part_sql(pg: Pg) -> None:
    pg.evaluate("""() => window.__S.mutate((wf) => {
      const template = wf.edges[0];
      for (const [id, source, port, x, y, name] of [['out_a', 'n_join', 'J', 1528, 215, 'Clientes ativos com vendas'], ['out_b', 'n_atingimento', 'out', 2024, 200, 'Atingimento por UF']]) {
        wf.nodes.push({ id, type: 'io.output_data', label: name, x, y, config: { filename: name, format: 'csv', if_exists: 'replace' } });
        wf.edges.push({ ...template, id: 'e_' + id, source, sourceHandle: port, target: id, targetHandle: 'in' });
      }
    })""")
    execute(pg)
    pg.evaluate("() => window.__S.markSaved()")  # o selo "não salvo" não interessa nas capturas
    pg.click("#viewSwitch .segment[data-view=sql]")
    pg.wait_for_selector(".sql-out")
    pg.locator(".sql-out-pick", has_text="Clientes ativos").click()
    pg.wait_for_function("() => document.querySelector('.sql-state')?.innerText.includes('Conferido')", timeout=60000, polling=200)
    pg.wait_for_timeout(300)
    shot(pg, "sql")
    pg.locator(".sql-out-pick", has_text="Exportar").click()
    pg.wait_for_function("() => document.querySelector('.sql-state')?.innerText.includes('Parcial')", timeout=30000, polling=200)
    pg.locator(".sql-trail-wrap").evaluate("(e) => { e.scrollTop = e.scrollHeight; }")
    pg.wait_for_timeout(300)
    shot(pg.locator(".sql-left"), "sql-parcial")
    pg.locator(".sql-actions button", has_text="Fluxo completo").click()
    pg.wait_for_timeout(400)
    shot(pg.locator(".sql-map-body"), "sql-fluxo")


# ---------------------------------------------------------------- Excel, Multi-Row, APIs, filtros e primeiro fluxo


def panel_until(pg: Pg, name: str, selector: str) -> None:
    """Só o começo do painel, até o campo que interessa: a captura inteira é alta demais para o guia."""
    box = pg.evaluate("""(sel) => {
      const pads = [...document.querySelectorAll('#leftPanel .pad')].filter((e) => e.offsetParent && e.getBoundingClientRect().height > 20);
      const first = pads[0].getBoundingClientRect();
      const el = document.querySelector('#leftPanel ' + sel);
      const last = (el.closest('.field') || el).getBoundingClientRect();
      return { x: first.left, y: first.top, width: first.width, height: last.bottom - first.top + 10 };
    }""", selector)
    shot(pg, name, clip=box)


def part_tools(pg: Pg) -> None:
    nid = pg.evaluate("""() => { const n = window.__A.addNode('io.output_data', 300, 1200, { filename: 'relatorio', format: 'excel', __label: 'Relatório' });
      window.__A.connect('n_clientes', 'out', n.id, 'in'); window.__A.connect('n_join', 'J', n.id, 'in2'); window.__S.select(n.id); window.__S.inspect(n.id); return n.id; }""")
    pg.wait_for_timeout(700)
    field = pg.locator(".sheet-port input").first
    field.fill("Cruzamento")
    field.dispatch_event("change")
    pg.wait_for_timeout(300)
    pg.set_viewport_size({"width": 1600, "height": 1500})
    pg.wait_for_timeout(300)
    panel_until(pg, "excel-sheets", ".sheet-port")
    pg.evaluate(f"() => window.__A.removeNodes(['{nid}'])")

    nid = pg.evaluate("""() => { const n = window.__A.addNode('prep.multirow', 300, 1200, { recipe: 'diff', base: 'mrr_mensal', distance: 1, target: 'new', column: 'mrr_mensal_diferenca', expression: '[mrr_mensal] - [Row-1:mrr_mensal]', group_by: ['uf'], order_by: 'id_cliente', __label: 'Multi-Row Formula' });
      window.__A.connect('n_clientes', 'out', n.id, 'in'); window.__S.select(n.id); window.__S.inspect(n.id); return n.id; }""")
    pg.wait_for_timeout(1200)
    panel_until(pg, "multirow", ".mr-formula")
    shot(pg.locator("#leftPanel .explainer"), "explain-multirow")
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.wait_for_timeout(300)
    pg.evaluate(f"() => window.__A.removeNodes(['{nid}'])")

    # APIs: o cadastro fica na vista Dados
    pg.click("#viewSwitch .segment[data-view=data]")
    pg.wait_for_selector(".dv-card-item")
    pg.set_viewport_size({"width": 1600, "height": 1500})
    pg.locator(".dv-card-item:has-text('Municípios')").click()
    pg.wait_for_selector(".api-vars")
    pg.wait_for_timeout(500)
    shot(pg.locator(".api-form"), "api-vars")
    pg.locator(".dv-list-head button:has-text('Adicionar')").click()
    pg.locator(".menu-item:has-text('Nova API')").first.click()
    pg.wait_for_selector(".api-example")
    pg.wait_for_timeout(300)
    pg.locator(".api-example:has-text('Lista simples')").click()
    pg.wait_for_timeout(500)
    pg.locator(".dv-editor button:has-text('Testar')").click()
    pg.wait_for_selector(".dv-editor .tree", timeout=30000)
    pg.wait_for_timeout(300)
    pg.locator(".dv-editor .tree-row[data-link]").nth(1).hover()
    pg.wait_for_timeout(150)
    shot(pg.locator(".dv-editor .api-form"), "api-editor")
    pg.locator(".dv-editor-actions button:has-text('Cancelar')").click()
    pg.wait_for_timeout(300)

    pg.click("#viewSwitch .segment[data-view=designer]")
    pg.wait_for_timeout(300)
    execute(pg)
    inspect(pg, "n_api_municipios")
    pg.wait_for_selector("#leftPanel .explainer .x-call", timeout=8000)
    pg.wait_for_timeout(600)
    pg.locator("#leftPanel .explainer .x-value").first.hover()
    pg.wait_for_timeout(150)
    shot(pg.locator("#leftPanel .explainer"), "api-loop")
    shot(pg.locator("#leftPanel .field:has(.api-param)"), "api-params")
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.wait_for_timeout(300)

    pg.click("#viewSwitch .segment[data-view=dashboard]")
    pg.wait_for_selector(".dash-page .venn", timeout=30000)
    pg.wait_for_timeout(600)
    pg.locator(".dash-filters button:has-text('Adicionar filtro')").click()
    pg.wait_for_selector("[role=menuitem]")
    pg.locator("[role=menuitem]:has-text('uf')").first.click()
    pg.wait_for_selector(".dash-pill")
    for uf in ("SP", "RJ", "MG"):
        pg.locator(f".dash-pill:text-is('{uf}')").click()
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(1300)
    shot(pg, "dash-filters", clip={"x": 0, "y": 80, "width": 1600, "height": 620})
    pg.mouse.click(5, 500)
    pg.wait_for_timeout(200)
    open_export_menu(pg)
    pg.locator(".dash-actions button:has-text('Baixar HTML')").click()
    dlg = pg.locator("dialog[open]")
    dlg.wait_for()
    pg.wait_for_timeout(200)
    shot(dlg, "dash-html")
    dlg.locator("button:has-text('Cancelar')").click()
    pg.wait_for_timeout(300)

    pg.click("#viewSwitch .segment[data-view=designer]")
    pg.wait_for_timeout(300)
    pg.locator("button[aria-label='Novo fluxo em outra aba'], button[title='Novo fluxo em outra aba']").first.click()
    pg.wait_for_timeout(500)
    pg.evaluate("""() => { const A = window.__A;
      const a = A.addNode('io.input_data', 60, 120, { dataset: 'clientes_enterprise.csv', __label: 'Clientes' });
      const s = A.addNode('transform.summarize', 340, 120, { group_by: ['uf'], aggregations: [{ column: 'mrr_mensal', agg: 'sum', alias: 'mrr_total' }], __label: 'MRR por UF' });
      const c = A.addNode('bi.chart', 620, 120, { title: 'MRR por UF', x_column: 'uf', y_column: 'mrr_total', agg: 'sum', chart_type: 'bar', __label: 'Gráfico' });
      A.connect(a.id, 'out', s.id, 'in'); A.connect(s.id, 'out', c.id, 'in'); window.__S.select(s.id); window.__S.inspect(s.id); }""")
    pg.wait_for_timeout(400)
    execute(pg)
    pg.wait_for_timeout(900)
    shot(pg, "primeiro-fluxo")


# ---------------------------------------------------------------- Data Quality


def part_quality_lists(pg: Pg) -> None:
    pg.set_viewport_size({"width": 1600, "height": 2400})  # a regra inteira à vista, sem rolagem
    nid = pg.evaluate("""() => { const n = window.__A.addNode('prep.data_quality', 1180, 600, { __label: 'UF válida' });
      window.__A.connect('n_clientes', 'out', n.id, 'in');
      window.__A.updateConfig(n.id, ['rules'], [{ kind: 'allowed', column: 'uf', values_from: 'list', values: [], list_column: '', ignore_case: true }]);
      window.__S.select(n.id); window.__S.inspect(n.id); return n.id; }""")
    pg.wait_for_timeout(900)
    pg.locator("#leftPanel .dq-values-input").fill("SP\nRJ")
    pg.wait_for_timeout(200)
    pg.locator("#leftPanel button:has-text('Trazer os valores de [uf]')").click()
    pg.wait_for_timeout(1200)

    def rule_clip(last: str) -> dict[str, float]:
        return pg.evaluate("""(last) => { const rule = document.querySelector('#leftPanel .dq-rule');
          const first = [...rule.querySelectorAll('.field')].find((f) => f.textContent.includes('De onde vem a lista')).getBoundingClientRect();
          const end = [...rule.querySelectorAll(last)].pop().getBoundingClientRect(); const r = rule.getBoundingClientRect();
          return { x: r.left, y: first.top - 4, width: r.width, height: end.bottom - first.top + 12 }; }""", last)

    shot(pg, "dq-lista", clip=rule_clip(".dq-values"))
    pg.evaluate(f"""() => {{ const t = window.__A.addNode('io.text_input', 900, 760, {{ __label: 'UFs atendidas' }});
      window.__A.updateConfig(t.id, ['table'], {{ columns: ['sigla', 'estado'], rows: [['SP', 'São Paulo'], ['RJ', 'Rio de Janeiro']] }});
      window.__A.connect(t.id, 'out', '{nid}', 'L'); window.__S.select('{nid}'); window.__S.inspect('{nid}'); }}""")
    pg.wait_for_timeout(700)
    pg.locator("#leftPanel .dq-rule select").filter(has=pg.locator("option[value=table]")).select_option("table")
    pg.wait_for_timeout(500)
    pg.locator("#leftPanel button[title='Executar até aqui'], #leftPanel button[aria-label='Executar até aqui']").first.click()
    pg.wait_for_timeout(600)
    wait_run(pg)
    pg.locator("#leftPanel .dq-rule select").filter(has=pg.locator("option[value=sigla]")).select_option("sigla")
    pg.wait_for_timeout(500)
    shot(pg, "dq-lista-tabela", clip=rule_clip(".field:has(option[value=sigla])"))


def part_data_trust(pg: Pg, tmp: Path) -> None:
    received = tmp / "relatorio_recebido.prodata.json"
    received.write_text(json.dumps({
        "id": "relatorio_recebido", "name": "Relatório recebido por e-mail",
        "nodes": [
            {"id": "i", "type": "io.input_data", "label": "Clientes", "x": 60, "y": 80, "config": {"dataset": "clientes_enterprise.csv"}},
            {"id": "f", "type": "prep.formula", "label": "Faixa de MRR", "x": 320, "y": 80, "config": {"formulas": [{"target": "new", "column": "faixa", "type": "Auto", "expression": "IF [mrr_mensal] > 50000 THEN 'alto' ELSE 'normal' ENDIF"}]}},
            {"id": "o", "type": "io.output_data", "label": "relatorio.xlsx", "x": 580, "y": 80, "config": {"filename": "relatorio", "format": "excel"}},
        ],
        "edges": [{"id": "e1", "source": "i", "target": "f"}, {"id": "e2", "source": "f", "target": "o"}],
    }, ensure_ascii=False), encoding="utf-8")

    pg.evaluate("""async () => {
      await window.__API.saveConstant({ name: 'mes_referencia', type: 'text', value: '2026-10', description: 'Competência que os relatórios fecham, no formato AAAA-MM.' });
      await window.__C.refreshConstants();
      const n = window.__A.addNode('prep.formula', 1180, 470, { __label: 'Vendas do mês' });
      window.__A.connect('n_vendas', 'out', n.id, 'in');
      window.__A.updateConfig(n.id, ['formulas'], [{ target: 'new', column: 'no_mes', type: 'Auto', expression: "IF [competencia] = [#mes_referencia] THEN 'no mês' ELSE 'antes' ENDIF" }]);
      await window.__API.saveWorkflow(window.__S.store.workflow);
      window.__S.markSaved();
      window.__NID = n.id;
    }""")
    pg.wait_for_timeout(500)
    pg.click("#viewSwitch .segment[data-view=data]")
    pg.wait_for_selector(".dv-welcome", timeout=10000)
    pg.locator(".dv-card-item[data-key='file:clientes_enterprise.csv']").click()
    pg.wait_for_selector(".dv-quality", timeout=15000)
    pg.wait_for_timeout(600)
    shot(pg, "dados-vista")
    pg.locator(".dv-tab[data-tab=usage]").click()
    pg.wait_for_timeout(500)
    main = pg.locator(".dv-main").bounding_box()
    shot(pg, "dados-mapa", clip={**main, "height": min(main["height"], 560)})
    pg.locator(".dv-card-item[data-key='const:mes_referencia']").click()
    pg.wait_for_selector(".cst-form")
    pg.wait_for_timeout(400)
    main = pg.locator(".dv-main").bounding_box()
    shot(pg, "constante", clip={**main, "height": min(main["height"], 760)})

    pg.click("#viewSwitch .segment[data-view=designer]")
    pg.wait_for_timeout(400)
    pg.evaluate("() => { window.__S.select(window.__NID); window.__S.inspect(window.__NID); }")
    pg.wait_for_timeout(800)
    pg.locator("#leftPanel .fx-cst-tool").first.click()
    pg.wait_for_timeout(300)
    r = pg.locator("#leftPanel .fx").first.bounding_box()
    m = pg.locator(".menu").last.bounding_box()
    shot(pg, "constante-formula", clip={"x": r["x"] - 8, "y": r["y"] - 8, "width": max(r["width"], m["x"] + m["width"] - r["x"]) + 16, "height": max(r["height"], m["y"] + m["height"] - r["y"]) + 16})
    pg.keyboard.press("Escape")

    pg.evaluate("""() => { const n = window.__A.addNode('prep.data_quality', 1180, 600, { __label: 'Clientes válidos' }); window.__A.connect('n_clientes', 'out', n.id, 'in');
      window.__A.updateConfig(n.id, ['rules'], [{ kind: 'not_empty', column: 'setor' }, { kind: 'number_range', column: 'nps', min: 3, max: 10 }, { kind: 'allowed', column: 'uf', values: ['SP', 'RJ', 'MG', 'PR', 'RS', 'SC', 'BA', 'DF'] }]);
      window.__S.select(n.id); window.__S.inspect(n.id); }""")
    pg.wait_for_timeout(900)
    pg.set_viewport_size({"width": 1600, "height": 2200})
    pg.wait_for_timeout(500)
    field = pg.locator("#leftPanel .dq-cards").first.locator("xpath=ancestor::div[contains(concat(' ', @class, ' '), ' field ')][1]")
    field.scroll_into_view_if_needed()
    # Só o título e os cartões: as regras escolhidas ficam abaixo e deixariam a imagem alta demais para o guia.
    top = field.bounding_box()
    cards = pg.locator("#leftPanel .dq-cards").first.bounding_box()
    shot(pg, "dq-regras", clip={"x": top["x"], "y": top["y"], "width": top["width"], "height": cards["y"] + cards["height"] - top["y"] + 4})
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.wait_for_timeout(400)
    pg.locator("#leftPanel button[title='Executar até aqui'], #leftPanel button[aria-label='Executar até aqui']").first.click()
    pg.wait_for_timeout(600)
    wait_run(pg)
    pg.wait_for_timeout(900)
    box = pg.locator("#leftPanel .explainer").bounding_box()
    shot(pg, "dq-resultado", clip={"x": max(0, box["x"] - 6), "y": box["y"] - 6, "width": box["width"] + 12, "height": box["height"] + 12})

    pg.keyboard.press("Control+o")
    pg.locator("dialog[open] button:has-text('Abrir arquivo')").click()
    entry = pg.locator("dialog[open] input.input")
    entry.wait_for()
    entry.fill(str(received))
    entry.press("Enter")
    pg.wait_for_selector(".trust-banner", timeout=10000)
    pg.wait_for_timeout(700)
    canvas = pg.locator("#canvas").bounding_box()
    shot(pg, "abertura-protegida", clip={**canvas, "height": min(canvas["height"], 620)})


def part_075(pg: Pg, tmp: Path) -> None:
    part_new_tools(pg, tmp, shot)


def part_organize(pg: Pg) -> None:
    organize(pg, shot)


def PARTS(tmp):  # noqa: N802
    every = ((part_screen, ()), (part_cache_dashboard, ()), (part_sql, ()), (part_tools, ()), (part_quality_lists, ()), (part_data_trust, (tmp,)), (part_manual, ()))
    every = (*every, (part_jira, ()), (part_replay, ()), (part_075, (tmp,)), (part_organize, ()))
    only = os.environ.get("IMAGENS_SO")
    return [e for e in every if not only or e[0].__name__ in only.split(",")]


def part_manual(pg: Pg) -> None:
    pg.locator("#topActions button[title^='Manual']").click()
    pg.wait_for_selector(".manual:not([hidden]) .manual-chapter")
    pg.locator(".manual-find").fill("Constantes: um valor")
    pg.wait_for_timeout(250)
    pg.locator(".manual-hit").first.click()
    pg.wait_for_timeout(1200)
    pg.locator(".manual-text [data-show=constantes]").click()
    pg.wait_for_selector(".manual-ring")
    pg.wait_for_timeout(300)
    shot(pg, "manual")


def part_jira(pg: Pg) -> None:
    pg.click("#viewSwitch .segment[data-view=data]")
    pg.wait_for_selector(".dv-list")
    pg.locator(".dv-list-head button").click()
    pg.wait_for_timeout(150)
    pg.get_by_text("Conectar ao Jira", exact=True).first.click()
    pg.wait_for_selector(".jira-steps")
    pg.get_by_label("Endereço do Jira").fill("empresa.atlassian.net")
    pg.locator(".jira-form input[type=email]").fill("ana@exemplo.com")
    pg.locator(".jira-form input[type=password]").fill("token-comum")
    pg.get_by_role("button", name="Testar", exact=True).click()
    pg.wait_for_selector(".jira-ok")
    pg.wait_for_timeout(300)
    shot(pg, "jira-conexao")
    pg.get_by_role("button", name="Salvar", exact=True).click()
    pg.wait_for_function("() => window.__S.store.jiraConnections.length === 1")
    pg.wait_for_timeout(500)
    pg.locator(".dv-list-head button").click()
    pg.wait_for_timeout(150)
    pg.get_by_text("Nova consulta do Jira", exact=True).first.click()
    pg.wait_for_selector(".jira-tables")
    pg.locator(".jira-projects .value-chip", has_text="DEMO").first.click()
    pg.wait_for_selector(".jira-status-group")
    pg.get_by_placeholder("Ex.: Demandas do time de Dados").fill("Demandas do time")
    pg.wait_for_selector(".jira-grid table")
    pg.wait_for_timeout(500)
    shot(pg, "jira-consulta")


def part_replay(pg: Pg) -> None:
    pg.evaluate("async () => { const m = await import('/static/js/manual.js'); await m.tryExample('replay'); }")
    pg.wait_for_function("() => window.__S.store.workflow.id === 'exemplo_replay'")
    pg.wait_for_function("() => window.__S.store.execution && !window.__S.store.running && Object.keys(window.__S.store.execution.node_results).length >= 10", timeout=60000)
    pg.click("#viewSwitch .segment[data-view=dashboard]")
    pg.wait_for_selector(".replay-bar", timeout=15000)
    pg.locator(".replay-bar input[type=range]").evaluate("(el) => { el.value = 6; el.dispatchEvent(new Event('input', {bubbles: true})); }")
    pg.wait_for_timeout(700)
    shot(pg, "replay-dash")
    pg.locator(".dash-item[data-id=v_c2] button[title='Baixar GIF deste gráfico']").click()
    pg.wait_for_selector("dialog[open] .replay-gif-grid")
    pg.wait_for_timeout(300)
    shot(pg.locator("dialog[open]"), "replay-gif")
    pg.locator("dialog[open] .dialog-footer button", has_text="Cancelar").click()
    pg.wait_for_timeout(200)
    pg.locator(".replay-bar button", has_text="Guardar cena").click()
    pg.wait_for_selector("dialog[open] input[aria-label='Título da cena']")
    pg.fill("dialog[open] input[aria-label='Título da cena']", "O andamento virou o gargalo")
    pg.fill("dialog[open] textarea", "Em julho, as demandas em andamento passaram de 70 dias paradas, em média.")
    pg.locator("dialog[open] select").select_option("v_c2")
    pg.locator("dialog[open] .dialog-footer button", has_text="Salvar").click()
    pg.wait_for_timeout(5200)  # o aviso some
    pg.locator(".replay-bar button", has_text="Cenas (1)").click()
    pg.wait_for_selector("dialog[open] .story-list li")
    pg.locator("dialog[open] .dialog-footer button", has_text="Apresentar").click()
    pg.wait_for_selector(".story .dash-page")
    pg.wait_for_timeout(500)
    shot(pg, "replay-historia")


def run_part(browser: Any, theme: str, part: Callable[..., None], *args: Any) -> None:
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=2, color_scheme="dark" if theme == "escuro" else "light", accept_downloads=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL)
    ready(pg)
    part(pg, *args)
    ctx.close()


def generate(theme: str) -> None:
    global OUT
    OUT = ROOT / "src/prodata/web/manual" / ("img-escuro" if theme == "escuro" else "img")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prodata-imagens-") as folder:
        tmp = Path(folder)
        env = {**os.environ, "PRODATA_PORT": str(PORT), "PRODATA_STORAGE_DIR": str(tmp / "dados"), "PRODATA_SECRETS_BACKEND": "memory", "PRODATA_JIRA_TEST_BASE": f"http://127.0.0.1:{FAKE_JIRA}"}
        uv = shutil.which("uv") or "uv"
        server = subprocess.Popen([uv, "run", "prodata"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        fake = subprocess.Popen([sys.executable, str(ROOT / "tests/jira_fake.py"), str(FAKE_JIRA), "40"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        try:
            for _ in range(90):
                try:
                    urllib.request.urlopen(URL + "api/health")  # noqa: S310
                    break
                except OSError:
                    time.sleep(1)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True)
                for part, args in PARTS(tmp):
                    run_part(browser, theme, part, *args)
                browser.close()
        finally:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(server.pid)], capture_output=True, check=False)  # noqa: S603, S607
            fake.terminate()
    for leftover in OUT.glob("_*.png"):
        leftover.unlink()


def main() -> None:
    themes = sys.argv[1:] or ["claro", "escuro"]
    for theme in themes:
        done.clear()
        generate(theme)
        print(f"{theme}: {len(set(done))} imagens")
    print("erros de página:", errors or "nenhum")


if __name__ == "__main__":
    main()
