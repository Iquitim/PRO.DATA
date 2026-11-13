"""Capturas das caixas da 0.7.5: esquemas "Como funciona", biblioteca de modelos, tabela em tela cheia e linha de comando.

Usado por ``gerar_imagens.py``. Monta um trecho de fluxo com dados inventados, executa cada caixa e fotografa o
esquema dela no Configurar.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

DEMO = "demo_pipeline_360"
SUBFLOW = """async () => { await window.__API.saveWorkflow({ id: 'padroniza_cadastro', name: 'Padroniza cadastro', nodes: [
  { id: 'i', type: 'flow.input', label: 'Entra', x: 0, y: 0, config: { number: 1 } },
  { id: 'c', type: 'prep.cleanse', label: 'Limpeza', x: 200, y: 0, config: {} },
  { id: 'u', type: 'prep.unique', label: 'Sem repetidos', x: 400, y: 0, config: {} },
  { id: 'q', type: 'prep.data_quality', label: 'Regras do cadastro', x: 600, y: 0, config: {} },
  { id: 'o', type: 'flow.output', label: 'Sai', x: 800, y: 0, config: { number: 1 } }],
  edges: [{ id: 'a', source: 'i', sourceHandle: 'out', target: 'c', targetHandle: 'in' }, { id: 'b', source: 'c', sourceHandle: 'out', target: 'u', targetHandle: 'in' },
    { id: 'd', source: 'u', sourceHandle: 'U', target: 'o', targetHandle: 'in' }] }); }"""
NODES = """
const T = (id, label, y, columns, rows, x = 60) => ({ id, type: 'io.text_input', label, x, y, config: { table: { columns, rows } } });
const Y = 1500;
wf.nodes.push(
  { id: 'x_gen', type: 'io.generate_rows', label: 'Calendário', x: 360, y: Y, config: { start_date: '2026-10-01', end_date: '2026-10-31' } },
  T('x_a', 'Lançamentos', Y + 130, ['id', 'valor'], [[1, 1200.5], [2, 830], [3, 410.25], [4, 95]]),
  T('x_b', 'Relatório', Y + 230, ['id', 'valor'], [[1, 1200.5], [2, 830], [3, 410.25]]),
  { id: 'x_rec', type: 'control.reconcile', label: 'Fecha com o razão?', x: 360, y: Y + 180, config: { on_fail: 'warn', controls: [{ measure: 'count' }, { measure: 'sum', column_a: 'valor' }, { measure: 'n_unique', column_a: 'id' }] } },
  T('x_hoje', 'Carteira', Y + 330, ['id', 'valor', 'status'], [[1, 1200.5, 'ativo'], [2, 910, 'ativo'], [4, 95, 'novo'], [5, 300, 'novo']], 660),
  { id: 'x_cmp', type: 'control.compare_runs', label: 'O que mudou', x: 960, y: Y + 330, config: { keys: ['id'] } },
  T('x_crm', 'CRM', Y + 460, ['razao'], [['Padaria Pão Quente LTDA'], ['Mercado Bom Preço S.A.'], ['Transportadora Rápido Sul'], ['Oficina do Zé ME']]),
  T('x_erp', 'ERP', Y + 560, ['nome', 'codigo'], [['PADARIA PAO QUENTE', 1], ['Mercado Bom Preco', 2], ['Transportadora Rapdio Sul', 3], ['Farmácia Central', 4]]),
  { id: 'x_fuzzy', type: 'transform.fuzzy_match', label: 'Mesma empresa?', x: 360, y: Y + 510, config: { left: 'razao', right: 'nome' } },
  T('x_txt', 'Notas', Y + 690, ['ref', 'cliente', 'cidade', 'cpf'], [['NF 10/2026', ' ana souza ', ' recife', '123.456.789-09'], ['NF 03/2025', 'BRUNO LIMA', 'Natal ', '987.654.321-00'], ['sem data', 'carla dias', 'olinda', '111']]),
  { id: 'x_regex', type: 'prep.regex', label: 'Mês e ano', x: 360, y: Y + 660, config: { column: 'ref', pattern: '(\\\\d{2})/(\\\\d{4})', names: ['mes', 'ano'] } },
  { id: 'x_multi', type: 'prep.multi_field', label: 'Padroniza textos', x: 360, y: Y + 760, config: { columns: ['cliente', 'cidade'], expression: 'Trim(Uppercase([_Atual_]))' } },
  { id: 'x_mask', type: 'prep.mask', label: 'LGPD', x: 660, y: Y + 710, config: { columns: ['cpf'], method: 'cpf' } },
  { id: 'x_model', type: 'ml.model_input', label: 'Modelo de churn', x: 60, y: Y + 900, config: { model: 'churn_clientes' } },
  { id: 'x_sub', type: 'flow.subflow', label: 'Padroniza cadastro', x: 360, y: Y + 900, config: { workflow: 'padroniza_cadastro' } },
  T('x_ped', 'Pedidos', Y + 1030, ['id_cliente', 'valor'], [['C1', 100], ['C2', 250], ['C3', 80]]),
  T('x_cad', 'Cadastro', Y + 1130, ['id_cliente', 'vendedor'], [['C1', 'Ana'], ['C1', 'Bruno'], ['C2', 'Carla']]),
  { id: 'x_join', type: 'transform.join', label: 'Pedidos × cadastro', x: 360, y: Y + 1080, config: { keys: [{ left: 'id_cliente', right: 'id_cliente' }] } },
);
const E = (s, t, th, sh = 'out') => wf.edges.push({ id: `xe_${s}_${t}_${th}`, source: s, sourceHandle: sh, target: t, targetHandle: th });
E('x_a', 'x_rec', 'A'); E('x_b', 'x_rec', 'B'); E('x_hoje', 'x_cmp', 'in');
E('x_crm', 'x_fuzzy', 'L'); E('x_erp', 'x_fuzzy', 'R');
E('x_txt', 'x_regex', 'in'); E('x_txt', 'x_multi', 'in'); E('x_txt', 'x_mask', 'in'); E('x_txt', 'x_sub', 'in');
E('x_ped', 'x_join', 'L'); E('x_cad', 'x_join', 'R');
"""
SHOTS = {
    "x_gen": "explain-generate",
    "x_rec": "explain-reconcile",
    "x_cmp": "explain-compare",
    "x_fuzzy": "explain-fuzzy",
    "x_regex": "explain-regex",
    "x_multi": "explain-multifield",
    "x_mask": "explain-mask",
    "x_sub": "explain-subflow",
    "x_join": "explain-join-multiplica",
}


def _seed(tmp: Path) -> Path:
    """A pasta do mês e a execução "de ontem" do Compare Runs, para o esquema mostrar uma comparação de verdade."""
    folder = tmp / "fechamento_2026-10"
    folder.mkdir(exist_ok=True)
    for name, rows in (("norte", "PA;1200\nAM;830"), ("sul", "RS;2100\nSC;1740"), ("sudeste", "SP;9800\nRJ;4300")):
        (folder / f"vendas_{name}.csv").write_text("uf;valor\n" + rows + "\n", encoding="utf-8")
    state = tmp / "dados" / "estado" / DEMO / "x_cmp"
    state.mkdir(parents=True, exist_ok=True)
    before = pl.DataFrame({"id": [1, 2, 3], "valor": [1200.5, 830.0, 410.25], "status": ["ativo", "ativo", "ativo"]})
    before.write_parquet(state / f"{(date.today() - timedelta(days=1)).isoformat()}.parquet")
    return folder


def _run_to(pg: Any, node: str) -> None:
    pg.evaluate("id => { window.__S.select(id); window.__S.inspect(id); }", node)
    pg.wait_for_timeout(400)
    pg.keyboard.press("Control+Shift+Enter")
    pg.wait_for_timeout(700)
    pg.wait_for_function(
        "id => ['executed', 'cached', 'error'].includes(window.__S.store.execution?.node_results?.[id]?.status) && !window.__S.store.running",
        arg=node,
        timeout=120000,
    )
    pg.wait_for_timeout(1000)


def _explainer(pg: Any, shot: Callable[..., None], name: str) -> None:
    box = pg.locator("#leftPanel .explainer")
    box.scroll_into_view_if_needed()
    pg.wait_for_timeout(200)
    shot(box, name)


def part_new_tools(pg: Any, tmp: Path, shot: Callable[..., None]) -> None:
    folder = _seed(tmp)
    pg.set_viewport_size({"width": 1600, "height": 1500})
    pg.evaluate(SUBFLOW)
    trainer = pg.evaluate("() => window.__S.store.workflow.nodes.find(n => n.type === 'ml.automl_trainer').id")
    pg.evaluate("id => window.__S.mutate((wf) => { wf.nodes.find(n => n.id === id).config.publish_as = 'churn_clientes'; })", trainer)
    _run_to(pg, trainer)
    _explainer(pg, shot, "explain-model")

    pg.evaluate("code => window.__S.mutate((wf) => { new Function('wf', code)(wf); })", NODES.replace("FOLDER", repr(str(folder))))
    pg.wait_for_timeout(600)
    for node, name in SHOTS.items():
        _run_to(pg, node)
        _explainer(pg, shot, name)

    # Model Input: o campo com importar e exportar, e a ficha do modelo
    _run_to(pg, "x_model")
    # O campo do modelo, com a lista e os botões de importar e exportar. A ficha já aparece em explain-model.
    field = pg.locator("#leftPanel .field").filter(has=pg.locator("input[type=file]"))
    field.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    shot(field, "model-input")

    # tabela em tela cheia
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.evaluate("() => { window.__S.select('n_clientes'); window.__S.inspect('n_clientes'); }")
    pg.wait_for_timeout(900)
    pg.locator("#results button.results-focus").click()
    pg.wait_for_timeout(4500)  # a dica de como voltar some sozinha
    shot(pg, "tabela-cheia")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)

    # linha de comando
    pg.get_by_role("button", name="Arquivo").first.click()
    pg.wait_for_timeout(200)
    pg.get_by_text("Executar sem abrir o programa…", exact=True).click()
    pg.wait_for_selector("dialog[open]")
    pg.wait_for_timeout(300)
    shot(pg.locator("dialog[open]"), "cli-dialogo")
    pg.keyboard.press("Escape")

    # SQL para o Fabric
    pg.click("#viewSwitch .segment[data-view=sql]")
    pg.wait_for_selector(".sql-code .sql-part", timeout=30000)
    pg.locator("select.sql-dialect").select_option("tsql")
    pg.wait_for_function("() => !document.querySelector('.sql-unverified').hidden", timeout=20000)
    pg.wait_for_timeout(500)
    main = pg.locator(".sql-main").bounding_box()
    shot(pg, "sql-fabric", clip={"x": main["x"], "y": main["y"], "width": main["width"], "height": min(main["height"], 430)})
