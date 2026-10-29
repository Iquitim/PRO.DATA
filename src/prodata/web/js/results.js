// Painel de resultados: dados paginados com perfil por coluna, perfil detalhado e log de execução.

import { addNode, connect } from './actions.js';
import { api } from './api.js';
import { button, debounce, fmt, h, persist, storage } from './dom.js';
import { isAreaFree } from './canvas.js';
import { cell } from './datasets.js';
import { describe, openFilterEditor, toExpression } from './explore.js';
import { icon } from './icons.js';
import { panelControls } from './layout.js';
import { inspect, node, nodeResult, on, select, store, toolOf } from './store.js';
import { showMenu, toast } from './ui.js';

const PAGE = 100;
const STATUS_ICONS = { executed: 'check-circle', cached: 'check-circle', error: 'alert', skipped: 'skip', disabled: 'power' };
const STATUS_LABELS = { executed: 'Executado', cached: 'Cache', error: 'Erro', skipped: 'Não executado', disabled: 'Desabilitado' };

const state = { tab: storage('prodata.results.tab', 'data'), offset: 0, search: '', sortCol: null, sortDesc: false, data: null, seq: 0 };
const els = {};

// Filtros exploratórios por saída inspecionada; cada saída lembra os seus durante a sessão.
const filtersByOutput = new Map();
const outputKey = () => `${store.workflow?.id}:${store.inspect.nodeId}:${store.inspect.anchor}`;
const currentFilters = () => filtersByOutput.get(outputKey()) || [];

function setFilters(list) {
  filtersByOutput.set(outputKey(), list);
  state.offset = 0;
  load();
}

function editFilter(x, y, index = null, preset = {}) {
  const columns = state.data?.profile?.columns || [];
  if (!columns.length) return;
  const list = currentFilters();
  openFilterEditor(x, y, {
    columns,
    initial: index === null ? preset : list[index],
    onApply: (cond) => setFilters(index === null ? [...list, cond] : list.map((f, i) => (i === index ? cond : f))),
  });
}

function filterAt(el, index = null, preset = {}) {
  const r = el.getBoundingClientRect();
  editFilter(r.left, r.bottom + 4, index, preset);
}

/** Exploração → fluxo: cria um Filter com os filtros ativos ligado à saída inspecionada. */
function createFilterNode() {
  const filters = currentFilters();
  // Guarda a origem antes: criar o nó muda a seleção e a saída inspecionada.
  const { nodeId, anchor } = store.inspect;
  const source = node(nodeId);
  if (!filters.length || !source) return;
  const expression = toExpression(filters, state.data.profile.columns);
  const { x, y } = freeSpotNear(source);
  const created = addNode('prep.filter', x, y, { mode: 'expression', expression, __label: 'Filtro explorado' });
  if (created && connect(source.id, anchor, created.id, 'in')) {
    toast('Nó Filter criado e conectado', { kind: 'success', detail: expression });
  }
}

/** Primeira posição livre (sem nós nem fios) à direita e abaixo do nó de origem. */
function freeSpotNear(source) {
  const x = source.x + 248;
  let y = source.y + 110;
  for (let i = 0; i < 30 && !isAreaFree(x, y); i += 1) y += 30;
  return { x, y };
}

function drawFilterBar() {
  const filters = currentFilters();
  els.filterBtn.querySelector('.count')?.remove();
  if (filters.length) els.filterBtn.append(h('span', { class: 'count' }, filters.length));
  els.filterBtn.classList.toggle('active', filters.length > 0);
  els.filterBar.hidden = !filters.length || state.tab === 'log';
  els.filterBar.replaceChildren(
    ...filters.map((f, i) => h('span', { class: 'filter-chip' },
      h('button', { type: 'button', class: 'filter-chip-main', title: 'Editar condição', onclick: (e) => filterAt(e.currentTarget, i) }, describe(f)),
      h('button', { type: 'button', class: 'chip-x', 'aria-label': 'Remover condição', onclick: () => setFilters(filters.filter((_, j) => j !== i)) }, icon('x', 12)))),
    button({ icon: 'plus', label: 'Condição', size: 'sm', variant: 'ghost', onClick: (e) => filterAt(e.currentTarget) }),
    h('div', { class: 'grow' }),
    button({ icon: 'workflow', label: 'Criar nó Filter', size: 'sm', variant: 'ghost', title: 'Levar estes filtros para o fluxo como um nó Filter', onClick: createFilterNode }),
    button({ icon: 'x', label: 'Limpar', size: 'sm', variant: 'ghost', onClick: () => setFilters([]) }),
  );
}

export function initResults(root) {
  els.root = root;
  els.title = h('div', { class: 'results-title' });
  els.anchors = h('div', { class: 'segmented small', role: 'tablist', 'aria-label': 'Saída' });
  els.search = h('input', {
    class: 'input input-search input-sm', type: 'search', placeholder: 'Buscar nas linhas', 'aria-label': 'Buscar nas linhas',
    oninput: debounce((e) => { state.search = e.target.value; state.offset = 0; load(); }, 300),
  });
  els.pager = h('div', { class: 'pager' });
  els.tabs = h('div', { class: 'tabs', role: 'tablist' },
    ['data', 'profile', 'log'].map((t) => h('button', {
      type: 'button', role: 'tab', class: 'tab', dataset: { tab: t },
      onclick: () => { state.tab = t; persist('prodata.results.tab', t); draw(); },
    }, { data: 'Dados', profile: 'Perfil', log: 'Log' }[t])));
  els.body = h('div', { class: 'results-body' });
  els.filterBtn = button({
    icon: 'filter', label: 'Filtros', size: 'sm', variant: 'ghost',
    title: 'Filtros exploratórios: só mudam esta visualização, não o fluxo',
    onClick: (e) => filterAt(e.currentTarget),
  });
  els.filterBar = h('div', { class: 'results-row filter-bar', hidden: true });

  root.replaceChildren(
    h('div', { class: 'results-toolbar' },
      h('div', { class: 'results-row' }, els.tabs, h('div', { class: 'grow' }), els.pager, panelControls('results')),
      h('div', { class: 'results-row' }, els.title, els.anchors, h('div', { class: 'grow' }), els.filterBtn, els.search),
      els.filterBar),
    els.body);

  on('inspect', () => { state.offset = 0; state.sortCol = null; load(); });
  on('execution', () => load());
  on('workflow:loaded', () => { state.data = null; draw(); });
  draw();
}

async function load() {
  const { nodeId, anchor } = store.inspect;
  const res = nodeResult(nodeId);
  const port = res?.anchors?.[anchor];
  state.data = null;
  if (!nodeId || !anchor || !port || port.kind === 'model' || !['executed', 'cached'].includes(res.status)) {
    draw();
    return;
  }
  const seq = ++state.seq;
  els.body.classList.add('loading');
  try {
    const filters = currentFilters();
    const data = await api.results(store.workflow.id, nodeId, anchor, {
      offset: state.offset, limit: PAGE, search: state.search,
      ...(state.sortCol ? { sort_col: state.sortCol, sort_desc: state.sortDesc } : {}),
      ...(filters.length ? { filters: JSON.stringify(filters) } : {}),
    });
    if (seq === state.seq) state.data = data;
  } catch (err) {
    if (seq === state.seq) state.data = { error: err.message };
  } finally {
    els.body.classList.remove('loading');
  }
  if (seq === state.seq) draw();
}

function draw() {
  for (const t of els.tabs.children) t.setAttribute('aria-selected', String(t.dataset.tab === state.tab));
  drawHeader();
  drawFilterBar();
  if (state.tab === 'log') els.body.replaceChildren(logView());
  else els.body.replaceChildren(state.tab === 'profile' ? profileView() : dataView());
}

function drawHeader() {
  const n = node(store.inspect.nodeId);
  const spec = toolOf(n);
  const res = nodeResult(n?.id);
  const via = store.inspect.via;
  const target = via && node(via.nodeId);
  if (target) {
    // Entrada de uma caixa (spec 012): mostra o que chega pela porta, vindo da caixa de origem.
    const tSpec = toolOf(target);
    const port = tSpec?.inputs.find((p) => p.id === via.port);
    els.title.replaceChildren(h('span', { class: 'results-via' }, icon('arrow-down', 14),
      `Entrada [${port?.label || via.port}] de ${target.label || tSpec?.name}`,
      h('span', { class: 'muted' }, ` ← ${n?.label || spec?.name || ''}`)));
  } else {
    els.title.replaceChildren(n ? h('span', {}, icon(spec.icon, 14), n.label || spec.name) : h('span', { class: 'muted' }, 'Nenhum nó selecionado'));
  }
  els.anchors.replaceChildren(...(!target && (spec?.outputs.length > 1 || spec?.outputs[0]?.kind === 'model') ? spec.outputs : []).map((o) => {
    const count = res?.anchors?.[o.id];
    return h('button', {
      type: 'button', role: 'tab', class: 'segment', 'aria-selected': String(store.inspect.anchor === o.id),
      title: o.title, onclick: () => inspect(n.id, o.id),
    }, h('b', {}, o.label), count ? h('span', { class: 'muted' }, count.kind === 'model' ? 'modelo' : fmt.compact(count.row_count)) : null);
  }));
  const d = state.data;
  const showPager = state.tab === 'data' && d?.rows;
  els.search.hidden = state.tab === 'log';
  els.filterBtn.hidden = state.tab === 'log';
  const narrowed = d && d.filtered_count !== d.row_count;
  els.pager.replaceChildren(...(showPager ? [
    h('span', { class: 'muted', title: narrowed ? `${fmt.int(d.filtered_count)} de ${fmt.int(d.row_count)} linhas após filtros/busca` : null },
      d.filtered_count
        ? `${fmt.int(d.offset + 1)}–${fmt.int(Math.min(d.offset + PAGE, d.filtered_count))} de ${fmt.int(d.filtered_count)}${narrowed ? ` (de ${fmt.compact(d.row_count)})` : ''}`
        : '0 linhas'),
    button({ icon: 'chevron-left', title: 'Página anterior', size: 'sm', variant: 'ghost', disabled: d.offset === 0,
      onClick: () => { state.offset = Math.max(0, state.offset - PAGE); load(); } }),
    button({ icon: 'chevron-right', title: 'Próxima página', size: 'sm', variant: 'ghost', disabled: d.offset + PAGE >= d.filtered_count,
      onClick: () => { state.offset += PAGE; load(); } }),
  ] : []));
}

function empty(iconName, title, detail) {
  return h('div', { class: 'empty' }, icon(iconName, 22), h('strong', {}, title), detail ? h('span', {}, detail) : null);
}

function guard() {
  const { nodeId, anchor } = store.inspect;
  if (!nodeId) return empty('table', 'Selecione um nó', 'Clique em um nó ou em uma de suas saídas para ver os dados.');
  const res = nodeResult(nodeId);
  if (!res) return empty('play', 'Nó ainda não executado', 'Execute o fluxo (Ctrl+Enter) para ver os dados.');
  if (res.status === 'error') return empty('alert', 'Este nó falhou', res.error);
  if (res.status === 'skipped' || res.status === 'disabled') return empty('skip', STATUS_LABELS[res.status], res.error);
  const port = res.anchors?.[anchor];
  if (port?.kind === 'model') return modelCard(port.metrics);
  if (state.data?.error) return empty('alert', 'Não foi possível carregar', state.data.error);
  if (!state.data) return h('div', { class: 'empty' }, 'Carregando…');
  return null;
}

function modelCard(m) {
  const rows = m.task === 'classification'
    ? [['Acurácia (validação)', `${fmt.number(m.accuracy_pct)}%`], ['F1 ponderado (validação)', `${fmt.number(m.f1_pct)}%`]]
    : [['R² (validação)', fmt.number(m.r2, 3)], ['Erro absoluto médio', fmt.number(m.mae)]];
  return h('div', { class: 'model-card' },
    h('div', { class: 'model-head' }, icon('brain', 18), h('strong', {}, 'Modelo treinado'),
      h('span', { class: 'badge' }, m.algorithm), h('span', { class: 'badge' }, m.task === 'classification' ? 'Classificação' : 'Regressão')),
    h('dl', { class: 'stats' }, rows.map(([k, v]) => h('div', { class: 'stat' }, h('dt', {}, k), h('dd', {}, v))),
      h('div', { class: 'stat' }, h('dt', {}, 'Treino / validação'), h('dd', {}, `${fmt.int(m.train_rows)} / ${fmt.int(m.validation_rows)}`))),
    h('p', { class: 'muted' }, 'Conecte a saída [M] a um nó Predictor para aplicar o modelo. A saída [I] mostra a importância das variáveis.'));
}

function qualityBar(c) {
  return h('div', {
    class: 'quality', title: `${c.ok_pct}% preenchido · ${c.empty_pct}% vazio · ${c.null_pct}% nulo`,
  }, h('span', { class: 'q-ok', style: { width: `${c.ok_pct}%` } }), h('span', { class: 'q-empty', style: { width: `${c.empty_pct}%` } }),
  h('span', { class: 'q-null', style: { width: `${c.null_pct}%` } }));
}

function sparkline(c) {
  return h('div', { class: 'spark' }, c.histogram.map((b) => h('span', {
    style: { height: `${Math.max(6, b.pct)}%` }, title: `${b.label}: ${fmt.int(b.count)}`,
  })));
}

function dataView() {
  const blocked = guard();
  if (blocked) return blocked;
  const { profile, rows } = state.data;
  const cols = profile.columns;
  if (!cols.length) return empty('table', 'Tabela sem colunas');
  const sortIcon = (name) => (state.sortCol === name ? icon(state.sortDesc ? 'arrow-down' : 'arrow-up', 12) : null);
  const sortBy = (name, desc) => { state.sortCol = name; state.sortDesc = desc; state.offset = 0; load(); };
  const filtered = new Set(currentFilters().map((f) => f.column));
  const head = h('tr', {}, h('th', { class: 'rownum' }, '#'), cols.map((c) => h('th', {
    class: ['sortable', state.sortCol === c.name && 'sorted', filtered.has(c.name) && 'filtered'],
    title: 'Clique para ordenar · botão direito para mais opções',
    onclick: () => {
      if (state.sortCol !== c.name) sortBy(c.name, false);
      else if (!state.sortDesc) sortBy(c.name, true);
      else { state.sortCol = null; state.offset = 0; load(); }
    },
    oncontextmenu: (e) => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, [
        { label: 'Filtrar esta coluna…', icon: 'filter', onSelect: () => editFilter(e.clientX, e.clientY, null, { column: c.name }) },
        'separator',
        { label: 'Ordenar crescente', icon: 'arrow-up', onSelect: () => sortBy(c.name, false) },
        { label: 'Ordenar decrescente', icon: 'arrow-down', onSelect: () => sortBy(c.name, true) },
      ]);
    },
  },
  h('div', { class: 'th-top' }, h('span', { class: 'th-name' }, c.name), sortIcon(c.name),
    h('button', {
      type: 'button', class: 'th-filter', title: `Filtrar ${c.name}`, 'aria-label': `Filtrar ${c.name}`,
      onclick: (e) => { e.stopPropagation(); filterAt(e.currentTarget, null, { column: c.name }); },
    }, icon('filter', 12)),
    h('span', { class: 'th-type' }, c.type)),
  qualityBar(c), sparkline(c))));
  const body = rows.length
    ? rows.map((r, i) => h('tr', {}, h('td', { class: 'rownum' }, state.data.offset + i + 1), cols.map((c, ci) => {
      const td = cell(r[c.name], c.type);
      td.dataset.ci = ci;
      return td;
    })))
    : [h('tr', {}, h('td', { colspan: cols.length + 1, class: 'muted pad' }, 'Nenhuma linha corresponde aos filtros ou à busca.'))];
  const tbody = h('tbody', {}, body);
  // Clique direito numa célula: filtrar por aquele valor (ou excluí-lo).
  tbody.addEventListener('contextmenu', (e) => {
    const td = e.target.closest('td[data-ci]');
    if (!td) return;
    e.preventDefault();
    const c = cols[Number(td.dataset.ci)];
    const value = rows[td.parentElement.rowIndex - 1]?.[c.name];
    const add = (cond) => setFilters([...currentFilters(), cond]);
    const shown = value === null || value === undefined ? null : String(value);
    showMenu(e.clientX, e.clientY, shown === null ? [
      { label: `Somente ${c.name} nulo`, icon: 'filter', onSelect: () => add({ column: c.name, op: 'is_null' }) },
      { label: `Excluir ${c.name} nulo`, icon: 'x', onSelect: () => add({ column: c.name, op: 'not_null' }) },
    ] : [
      { label: `Filtrar ${c.name} = ${shown.slice(0, 40)}`, icon: 'filter', onSelect: () => add({ column: c.name, op: 'eq', value: shown }) },
      { label: `Excluir ${shown.slice(0, 40)}`, icon: 'x', onSelect: () => add({ column: c.name, op: 'ne', value: shown }) },
      'separator',
      { label: 'Filtrar esta coluna…', icon: 'plus', onSelect: () => editFilter(e.clientX, e.clientY, null, { column: c.name, value: shown }) },
    ]);
  });
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data-table' }, h('thead', {}, head), tbody));
}

function profileView() {
  const blocked = guard();
  if (blocked) return blocked;
  const note = state.data.profile_scope === 'filtered'
    ? h('div', { class: 'profile-note' }, icon('filter', 13),
      `Perfil das ${fmt.int(state.data.filtered_count)} linhas filtradas (de ${fmt.int(state.data.row_count)}).`)
    : null;
  return h('div', {}, note, h('div', { class: 'profile-grid' }, state.data.profile.columns.map((c) => {
    const s = c.stats || {};
    const numeric = s.mean !== undefined;
    const facts = numeric
      ? [['Mín', s.min], ['Média', s.mean], ['Mediana', s.median], ['Máx', s.max], ['Desvio', s.std], ['Soma', s.sum]]
      : [['Distintos', c.unique_count], ['Mais comum', s.top ?? '—'], ['Ocorrências', s.top_count ?? 0]];
    return h('section', { class: 'profile-card' },
      h('header', {}, h('strong', { class: 'mono ellipsis' }, c.name), h('span', { class: 'th-type' }, c.raw_type)),
      qualityBar(c),
      h('div', { class: 'q-legend' }, h('span', {}, h('i', { class: 'q-ok' }), `${c.ok_pct}% ok`),
        h('span', {}, h('i', { class: 'q-empty' }), `${c.empty_pct}% vazio`), h('span', {}, h('i', { class: 'q-null' }), `${c.null_pct}% nulo`)),
      h('dl', { class: 'facts' }, facts.map(([k, v]) => h('div', {}, h('dt', {}, k),
        h('dd', { class: 'ellipsis', title: String(v) }, typeof v === 'number' ? fmt.number(v) : v)))),
      c.histogram.length ? h('div', { class: 'hist' }, c.histogram.map((b) => h('div', { class: 'hist-row', title: `${b.label}: ${fmt.int(b.count)}` },
        h('span', { class: 'hist-label ellipsis' }, b.label), h('span', { class: 'hist-bar' }, h('i', { style: { width: `${b.pct}%` } })),
        h('span', { class: 'hist-count' }, fmt.compact(b.count))))) : null);
  })));
}

function logView() {
  const logs = store.execution?.logs || [];
  if (!logs.length) return empty('list', 'Sem execuções', 'O log da última execução aparece aqui.');
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data-table log-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Status'), h('th', {}, 'Nó'), h('th', {}, 'Mensagem'), h('th', { class: 'num' }, 'Tempo'))),
    h('tbody', {}, logs.map((l) => h('tr', {
      class: ['clickable', `log-${l.status}`],
      onclick: () => { select(l.node_id); inspect(l.node_id); state.tab = 'data'; draw(); },
    }, h('td', {}, h('span', { class: `status-chip ${l.status}` }, icon(STATUS_ICONS[l.status] || 'info', 13), STATUS_LABELS[l.status] || l.status)),
    h('td', {}, l.node_name), h('td', { class: 'wrap' }, l.message), h('td', { class: 'num' }, fmt.ms(l.elapsed_ms)))))));
}

export function showLog() {
  state.tab = 'log';
  draw();
}
