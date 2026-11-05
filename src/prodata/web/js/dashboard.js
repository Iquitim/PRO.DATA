// Dashboard em página de tamanho fixo (spec 014): modo Visualizar e modo Editar (canvas com encaixe,
// guias, seleção múltipla), painel Formato, textos/imagens/formas, Organizar com layouts prontos e
// imagem PNG. Os cartões de visual também são usados pelo painel de insights.

import { api } from './api.js';
import { chartChrome, freeEl, placeItem, setCardEnv, visualCard } from './dash_cards.js';
import { clickedValues, filterBar, isFilterActive, noFilterBadge, selectedIn } from './dash_filters.js';
import { exportHtml } from './dash_html.js';
import { guardBadge, hideLabelTip, labelPicker, withLabelTip } from './label_picker.js';
import { biNodes, ensureLayout, GRID, PAGE_SIZES, PAGE_W, pageHeight, rectOf, restoreVisual, widgetsByNode } from './dash_model.js';
import { button, debounce, fmt, h } from './dom.js';
import { renderFields } from './fields.js';
import { icon } from './icons.js';
import { inspect, mutate, on, select, store } from './store.js';
import { showMenu, toast, toastError } from './ui.js';
import { commitLayout, dash, els, itemById, newId, nodeLabel, nodeOf, page as dashPage, ui } from './dash_state.js';
import { bbox, drawGuides, overlaps, resizeRect, snapBox } from './dash_snap.js';
import { insertItems, logoImage, pickImage } from './dash_insert.js';
import { openOrganize } from './dash_organize.js';
import { exportPage, exportVisual } from './dash_png.js';

export { AGG_LABELS, chartCard, kpiTile, tableCard, visualCard } from './dash_cards.js';

let root;
let handlers = {};
let gesture = null;
let syncing = null;
let formats = null; // campos do painel Formato por tipo (GET /api/dashboard/formats)
let loadingFormats = null;
let clip = { items: [], pastes: 0 };
const PANEL_W = 312;

export function initDashboard(el, opts) {
  root = el;
  handlers = opts;
  Object.assign(dashPage, { root: el, render, pageEl, itemEl, shownWidgets });
  setCardEnv({
    open: goToNode,
    clickable: () => ui.mode === 'view',
    canFilter: (w) => ui.mode === 'view' && ((dash()?.filters || []).some((f) => f.kind === 'list' && f.column === w.x_column)
      || options.list.some((o) => o.kind === 'list' && o.column === w.x_column)),
    selectedFor: (w) => selectedIn(dash()?.filters, w.x_column),
    onCategory: filterByCategory,
  });
  const refresh = () => store.view === 'dashboard' && render();
  on('execution', refresh);
  on('workflow:loaded', () => { ui.selected.clear(); ui.mode = 'view'; refresh(); });
  on('workflow:changed', refresh);
  new ResizeObserver(debounce(refresh, 120)).observe(root);
}

export function goToNode(id) {
  handlers.showDesigner?.();
  select(id);
  inspect(id);
}

// ------------------------------------------------------------------ página

function visualEl(item, w, { editing, exporting }) {
  const node = nodeOf(item.node_id);
  const f = item.format || {};
  if (!w) {
    if (!editing) return null;
    return h('article', { class: 'dash-placeholder' }, icon(store.tools[node?.type]?.icon || 'chart', 22),
      h('strong', {}, nodeLabel(item.node_id)),
      h('span', {}, node?.disabled ? 'Caixa desativada no fluxo' : 'Execute o fluxo para ver este visual'));
  }
  const actions = exporting || editing || w.widget_type === 'kpi' ? [] : [button({ icon: 'download', title: 'Baixar imagem deste visual (PNG)', size: 'sm', variant: 'ghost', onClick: () => exportVisual(item) })];
  return visualCard(w, { width: item.w, height: Math.max(80, item.h - chartChrome(f)), className: 'fill', actions, fmt: f, cross: true });
}

const HANDLES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

function itemEl(item, widgets, opts) {
  const content = item.kind === 'visual' ? visualEl(item, widgets[item.node_id], opts) : freeEl(item, opts);
  if (!content) return null;
  const absent = item.kind === 'visual' ? filtered.noColumn[item.node_id] : null;
  return placeItem(item, content,
    [absent?.length && !opts.exporting ? noFilterBadge(absent) : null,
      ...(opts.editing ? HANDLES.map((d) => h('span', { class: `dash-handle h-${d}`, dataset: { dir: d } })) : [])],
    { class: opts.editing && ui.selected.has(item.id) && 'selected' });
}

// ------------------------------------------------------------------ filtros da página (spec 021)

/** Resultado do servidor para os filtros de agora. */
const filtered = { key: '', widgets: {}, noColumn: {}, busy: false, token: 0 };
const options = { execution: undefined, list: [], loading: false };

const shownWidgets = () => ({ ...widgetsByNode(), ...filtered.widgets });

/** Pede de novo os visuais quando os filtros ou a execução mudam. Nada disso executa o fluxo. */
const requestFiltered = debounce(async () => {
  filtered.token += 1;
  const { token } = filtered;
  filtered.busy = true;
  drawFilterBar();
  try {
    const res = await api.dashboardFiltered(store.workflow);
    if (token !== filtered.token) return;
    filtered.widgets = res.widgets;
    filtered.noColumn = res.no_column;
  } catch (err) {
    if (token === filtered.token) toastError(err, 'Não foi possível aplicar os filtros');
  } finally {
    if (token === filtered.token) {
      filtered.busy = false;
      filtered.pulse = true;
      if (store.view === 'dashboard') render();
    }
  }
}, 180);

function syncFilters() {
  const d = dash();
  const active = (d?.filters || []).filter(isFilterActive);
  if (!active.length) {
    filtered.token += 1;
    Object.assign(filtered, { key: '', widgets: {}, noColumn: {}, busy: false });
  } else {
    const key = JSON.stringify([active, store.execution?.total_elapsed_ms, store.workflow.id]);
    if (key !== filtered.key) {
      filtered.key = key;
      requestFiltered();
    }
  }
  if (d && store.execution && options.execution !== store.execution && !options.loading) {
    options.loading = true;
    const running = store.execution;
    api.dashboardFilterOptions(store.workflow)
      .then((list) => { options.list = list; options.execution = running; })
      .catch((err) => { options.execution = running; toastError(err, 'Não foi possível listar os valores dos filtros'); })
      .finally(() => { options.loading = false; drawFilterBar(); });
  }
}

/** Clique numa barra ou fatia: usa o filtro daquela coluna ou cria um. */
function filterByCategory(w, value, adding) {
  changeFilters((list) => {
    const found = list.find((f) => f.kind === 'list' && f.column === w.x_column);
    if (found) return list.map((f) => (f === found ? { ...f, selected: clickedValues(f.selected, value, adding) } : f));
    return [...list, { id: newId(), column: w.x_column, kind: 'list', label: '', selected: [value], min: null, max: null }];
  });
}

const changeFilters = (fn, key) => commitLayout((d) => { d.filters = fn(structuredClone(d.filters || [])); }, key ? { key } : {});

function addFilterMenu(e) {
  const taken = new Set((dash().filters || []).map((f) => f.column));
  const total = dash().items.filter((i) => i.kind === 'visual').length;
  const items = options.list.filter((o) => !taken.has(o.column)).map((o) => ({
    label: `${o.column} · ${o.visuals} de ${total} visuais`,
    icon: 'filter',
    onSelect: () => changeFilters((list) => [...list, { id: newId(), column: o.column, kind: o.kind, label: '', selected: [], min: null, max: null }]),
  }));
  const r = e.currentTarget.getBoundingClientRect();
  showMenu(r.left, r.bottom + 4, items.length ? items : [{ label: store.execution ? 'Nenhuma coluna disponível' : 'Execute o fluxo para ver as colunas', disabled: true, onSelect: () => {} }]);
}

function filterBarEl() {
  const d = dash();
  if (!d) return null;
  return h('div', { class: 'dash-filters-slot' }, filterBar({
    filters: d.filters || [],
    options: options.list,
    busy: filtered.busy,
    onChange: (id, patch) => changeFilters((list) => list.map((f) => (f.id === id ? { ...f, ...patch } : f)), `filter:${id}`),
    onClear: () => changeFilters((list) => list.map((f) => ({ ...f, selected: [], min: null, max: null }))),
    onAdd: addFilterMenu,
    onRemove: (id) => changeFilters((list) => list.filter((f) => f.id !== id)),
  }));
}

function drawFilterBar() {
  const slot = root?.querySelector('.dash-filters-slot');
  const next = slot && filterBarEl();
  if (next) slot.replaceWith(next);
}

function pageEl({ editing = false, exporting = false } = {}) {
  const d = dash();
  const widgets = shownWidgets();
  const pulse = filtered.pulse && !exporting && !editing;
  if (!exporting) filtered.pulse = false;
  return h('div', {
    class: ['dash-page', editing && 'editing', exporting && 'dash-export', pulse && 'dash-refresh'],
    style: { width: `${PAGE_W}px`, height: `${pageHeight(d.page)}px`, backgroundColor: d.page.background || null },
  }, d.items.map((item) => itemEl(item, widgets, { editing, exporting })));
}

/** Botão de exportar com selo e dica do que o rótulo faz naquela saída. */
function exportButton({ icon: name, label, kind, onClick }) {
  const level = () => dash().confidentiality || 'interno';
  const el = button({ icon: name, label, onClick: (e) => { hideLabelTip(); onClick(e); } });
  el.removeAttribute('title'); // a dica já explica; o título nativo apareceria por cima dela
  const badge = guardBadge(level(), kind);
  if (badge) el.append(badge);
  return withLabelTip(el, level, 'dash');
}

const menuAt = (items) => (e) => { const r = e.currentTarget.getBoundingClientRect(); showMenu(r.left, r.bottom + 4, items()); };

function headEl() {
  const editing = ui.mode === 'edit';
  const d = dash();
  const count = d ? d.items.filter((i) => i.kind === 'visual').length : 0;
  const status = store.execution
    ? `${count} visual(is) na página · execução em ${fmt.ms(store.execution.total_elapsed_ms)}`
    : 'Execute o fluxo para gerar os visuais.';
  const brand = h('div', { class: 'dash-brand' },
    h('img', { class: 'dash-logo', src: '/static/brand/protege-escudo.svg', alt: 'Grupo Protege' }),
    h('div', {}, h('div', { class: 'dash-org' }, 'Grupo Protege'), h('h1', {}, store.workflow?.name || 'Dashboard'),
      h('p', { class: 'muted' }, editing ? 'Editando o layout · arraste, redimensione, formate e use Organizar' : status)));
  if (!d) return h('header', { class: 'dash-head' }, brand);
  const actions = editing ? [
    button({ icon: 'plus', label: 'Inserir', title: 'Texto, imagem, logo ou forma', onClick: menuAt(insertItems) }),
    button({ icon: 'wand', label: 'Organizar', title: 'Organizar automaticamente ou escolher um layout pronto', onClick: openOrganize }),
    button({ icon: 'columns', label: 'Alinhar', title: 'Alinhar e distribuir as selecionadas', disabled: ui.selected.size < 2, onClick: menuAt(alignItems) }),
    button({ icon: 'eye', label: `Fora da página (${d.hidden.length})`, title: 'Visuais removidos da página', disabled: !d.hidden.length, onClick: menuAt(hiddenItems) }),
    h('div', { class: 'divider-v' }),
    button({ icon: 'zoom-out', title: 'Diminuir zoom', variant: 'ghost', onClick: () => setZoom(ui.scale / 1.2) }),
    h('span', { class: 'dash-zoom muted' }, `${Math.round(ui.scale * 100)}%`),
    button({ icon: 'zoom-in', title: 'Aumentar zoom', variant: 'ghost', onClick: () => setZoom(ui.scale * 1.2) }),
    button({ icon: 'fit', title: 'Ajustar à largura', variant: 'ghost', onClick: () => setZoom(null) }),
    h('div', { class: 'divider-v' }),
    button({ icon: 'check', label: 'Concluir', variant: 'primary', onClick: () => setMode('view') }),
  ] : [
    button({ icon: 'edit', label: 'Editar layout', title: 'Mover, redimensionar, formatar e organizar os visuais', onClick: () => setMode('edit') }),
    h('div', { class: 'dash-label-pick' }, h('span', { class: 'dash-label-title' }, 'Rótulo'),
      labelPicker({ value: d.confidentiality || 'interno', place: 'dash', onChange: (level) => commitLayout((dd) => { dd.confidentiality = level; }) })),
    exportButton({ icon: 'download', label: 'Baixar imagem', kind: 'image', onClick: () => exportPage().catch((err) => toastError(err, 'Não foi possível gerar a imagem')) }),
    exportButton({ icon: 'globe', label: 'Baixar HTML', kind: 'html', onClick: () => exportHtml(shownWidgets()) }),
    button({ icon: 'refresh', label: 'Atualizar dados', variant: 'primary', onClick: () => handlers.run() }),
  ];
  return h('header', { class: 'dash-head' }, brand, h('div', { class: 'dash-actions' }, actions));
}

function setMode(mode) {
  ui.mode = mode;
  ui.selected.clear();
  ui.zoom = null;
  render();
}

function setZoom(scale) {
  ui.zoom = scale && Math.min(2, Math.max(0.25, scale));
  render();
}

export function render() {
  if (!root || !store.workflow) return;
  if (!syncing) {
    syncing = ensureLayout()
      .then((changed) => { syncing = null; if (changed && store.view === 'dashboard') render(); })
      .catch((err) => { syncing = null; toastError(err, 'Não foi possível montar o dashboard'); });
  }
  const d = dash();
  if (!d) {
    root.replaceChildren(headEl(), h('div', { class: 'empty big' }, 'Montando o dashboard…'));
    return;
  }
  syncFilters();
  const editing = ui.mode === 'edit';
  if (!d.items.length && !biNodes().length && !editing) {
    root.replaceChildren(headEl(), h('div', { class: 'empty big' }, icon('dashboard', 28),
      h('strong', {}, 'Nenhum visual publicado'),
      h('span', {}, 'Adicione nós Chart ou KPI Card (categoria BI e indicadores) ao fluxo e execute.')));
    return;
  }
  // Carrega o painel Formato já na primeira visita, para o modo Editar abrir pronto (sem redesenhar no meio).
  if (!formats && !loadingFormats) {
    loadingFormats = api.dashboardFormats()
      .then((f) => { formats = f; if (ui.mode === 'edit') render(); })
      .catch((err) => { loadingFormats = null; toastError(err, 'Não foi possível carregar o painel Formato'); });
  }
  const fit = Math.max(0.2, (root.clientWidth - 48 - (editing ? PANEL_W + 16 : 0)) / PAGE_W);
  ui.scale = editing && ui.zoom ? ui.zoom : Math.min(fit, 1.5);
  const page = pageEl({ editing });
  page.style.transform = `scale(${ui.scale})`;
  page.style.setProperty('--inv', String(1 / ui.scale)); // alças e guias com o mesmo tamanho em qualquer zoom
  const sheet = h('div', { class: 'dash-sheet', style: { width: `${PAGE_W * ui.scale}px`, height: `${pageHeight(d.page) * ui.scale}px` } }, page);
  const previous = els;
  Object.assign(els, { page, sheet, guides: [], marquee: null });
  if (editing) {
    page.addEventListener('pointerdown', onDown);
    page.addEventListener('pointermove', onMove);
    page.addEventListener('pointerup', onUp);
    page.addEventListener('pointercancel', () => { gesture = null; render(); });
    page.addEventListener('dblclick', onDoubleClick);
  }
  page.addEventListener('contextmenu', onContextMenu);
  const scroll = root.scrollTop;
  if (editing) {
    // Enquanto se digita no painel, só a página e o cabeçalho são refeitos: tirar o painel do lugar
    // (mesmo para recolocá-lo) tiraria o foco do campo a cada letra.
    const key = [...ui.selected].join(',');
    const keep = previous.panel?.isConnected && previous.panelKey === key && previous.panel.contains(document.activeElement);
    els.panelKey = key;
    if (keep) {
      Object.assign(els, { panel: previous.panel, stage: previous.stage });
      els.stage.replaceChildren(sheet);
      root.firstElementChild.replaceWith(headEl());
      drawFilterBar();
    } else {
      els.panel = panelEl();
      els.stage = h('div', { class: 'dash-stage' }, sheet);
      root.replaceChildren(...[headEl(), filterBarEl(), h('div', { class: 'dash-workspace' }, els.stage, els.panel)].filter(Boolean));
    }
  } else {
    root.replaceChildren(...[headEl(), filterBarEl(), sheet].filter(Boolean));
  }
  root.scrollTop = scroll;
}

// ------------------------------------------------------------------ painel Formato (RF-1410)

const KIND_LABELS = { text: 'Texto', image: 'Imagem', shape: 'Forma' };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const hex = (v) => (/^#[0-9a-f]{6}$/i.test(v) ? v : null);

/** Campos que mostram/escondem outros (show_if): mudar um deles refaz o painel. */
const controlling = (fields) => new Set(fields.flatMap((f) => Object.keys(f.show_if || {})));

function panelEl() {
  const d = dash();
  const sel = d.items.filter((i) => ui.selected.has(i.id));
  const body = !formats ? h('p', { class: 'muted' }, 'Carregando…')
    : sel.length === 1 ? itemPanel(sel[0])
      : sel.length > 1 ? multiPanel(sel)
        : pagePanel(d);
  return h('aside', { class: 'dash-panel', style: { width: `${PANEL_W}px` } }, body);
}

function formatKind(item) {
  if (item.kind !== 'visual') return item.kind;
  const type = widgetsByNode()[item.node_id]?.widget_type || { 'bi.kpi_card': 'kpi', 'bi.table': 'table' }[nodeOf(item.node_id)?.type];
  return type === 'kpi' || type === 'table' ? type : 'chart';
}

function itemPanel(item) {
  const kind = formatKind(item);
  const fields = formats[kind] || [];
  const ctrl = controlling(fields);
  const widget = widgetsByNode()[item.node_id];
  const f = item.format || {};
  const surface = hex(f.background) || hex(cssVar('--surface'));
  // `path` vem do formulário: [campo] ou, em listas (regras de cor), [campo, índice, subcampo].
  const onChange = (path, value) => {
    const [name] = path;
    // Mudou o que aparece no painel (campo que controla outros, ou item adicionado/removido): refaz o painel.
    if (ctrl.has(name) || (path.length === 1 && Array.isArray(value))) els.panelKey = null;
    commitLayout((dd) => {
      const it = dd.items.find((i) => i.id === item.id);
      if (it) it.format = setIn(structuredClone(it.format || {}), path, value);
    }, { key: `fmt:${item.id}:${path.join('.')}` });
  };
  // "Cor por categoria" pinta o que tem cor no visual: séries, conjuntos do Venn ou categorias.
  const colored = widget?.widget_type === 'venn' ? widget.sets.map((s) => s.name)
    : widget?.series_names?.length ? widget.series_names
      : widget?.chart_type === 'scatter' ? [...new Set((widget.points || []).map((p) => p.s).filter((s) => s !== undefined))]
        : widget?.series?.map((s) => s.label) || [];
  const ctx = {
    categories: colored,
    columns: () => (widget?.columns || []).filter((c) => c.numeric).map((c) => ({ name: c.name, type: 'Float64' })),
    contrastFor: (name) => {
      if (['color', 'category_colors'].includes(name) && kind === 'chart') return { against: surface, min: 3, what: 'o fundo do cartão' };
      if (name === 'value_color') return { against: surface, min: 4.5, what: 'o fundo do cartão' };
      if (name === 'color' && kind === 'text') return { against: hex(f.background) || hex(dash().page.background) || hex(cssVar('--bg')), min: 4.5, what: 'o fundo' };
      return null;
    },
    defaultColor: (name, i = 0) => {
      if (['color', 'category_colors'].includes(name) && kind === 'chart') return hex(cssVar(`--series-${(i % 8) + 1}`));
      if (['color', 'value_color'].includes(name)) return hex(cssVar('--text'));
      if (['background', 'fill'].includes(name)) return hex(cssVar('--surface'));
      return hex(cssVar('--border-strong'));
    },
  };
  const title = item.kind === 'visual' ? (widget?.title || nodeLabel(item.node_id)) : KIND_LABELS[item.kind];
  return h('div', {},
    h('header', { class: 'dash-panel-head' },
      h('span', { class: 'dash-panel-kicker' }, item.kind === 'visual' ? (kind === 'kpi' ? 'KPI' : 'Gráfico') : 'Elemento'),
      h('strong', {}, title)),
    item.kind === 'visual' ? h('div', { class: 'dash-panel-note' },
      h('span', { class: 'muted' }, 'Dados, ordenação e limite de categorias ficam na caixa do fluxo.'),
      button({ icon: 'workflow', label: 'Editar dados', size: 'sm', onClick: () => goToNode(item.node_id) })) : null,
    item.kind === 'text' ? textContentField(item) : null,
    item.kind === 'image' ? imageField(item) : null,
    renderFields(fields, f, onChange, ctx));
}

/** Atribui `value` no caminho dentro de `obj` (cria listas e objetos no caminho) e devolve `obj`. */
function setIn(obj, path, value) {
  let cur = obj;
  path.slice(0, -1).forEach((key, i) => {
    if (cur[key] === undefined || cur[key] === null) cur[key] = typeof path[i + 1] === 'number' ? [] : {};
    cur = cur[key];
  });
  cur[path.at(-1)] = value;
  return obj;
}

function textContentField(item) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label', for: 'dash-text' }, 'Texto'),
    h('textarea', {
      id: 'dash-text', class: 'input', rows: 4,
      oninput: (e) => commitLayout((d) => { d.items.find((i) => i.id === item.id).content = e.target.value; }, { key: `txt:${item.id}` }),
    }, item.content || ''));
}

function imageField(item) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Imagem'),
    h('div', { class: 'color-row' },
      button({ icon: 'upload', label: item.content ? 'Trocar imagem' : 'Escolher imagem', size: 'sm', onClick: () => pickImage().then((img) => {
        if (img) commitLayout((d) => { d.items.find((i) => i.id === item.id).content = img.data; });
      }) }),
      button({ icon: 'image', label: 'Logo Protege', size: 'sm', variant: 'ghost', onClick: () => logoImage().then((img) => {
        commitLayout((d) => { d.items.find((i) => i.id === item.id).content = img.data; });
      }) })),
    h('p', { class: 'field-help' }, 'PNG, JPG ou SVG até 1 MB. A imagem fica dentro do arquivo do fluxo.'));
}

function multiPanel(sel) {
  return h('div', {},
    h('header', { class: 'dash-panel-head' }, h('span', { class: 'dash-panel-kicker' }, 'Seleção'), h('strong', {}, `${sel.length} itens selecionados`)),
    h('div', { class: 'dash-panel-actions' }, alignItems().map((a) => button({ icon: a.icon, label: a.label, size: 'sm', variant: 'ghost', disabled: a.disabled, onClick: a.onSelect }))),
    h('p', { class: 'muted' }, 'Ctrl+C / Ctrl+V copiam textos, imagens e formas. Delete tira da página.'));
}

function pagePanel(d) {
  const fields = [
    { name: 'size', title: 'Tamanho', widget: 'select', default: '16:9', options: PAGE_SIZES.map(([value, label]) => ({ value, label: value === 'free' ? label : `${label} · ${PAGE_W}×${pageHeight({ size: value })}` })) },
    { name: 'height', title: 'Altura (px)', widget: 'number', default: 900, min: 400, max: 20000, step: 8, show_if: { size: ['free'] } },
    { name: 'background', title: 'Fundo', widget: 'color', default: '' },
  ];
  return h('div', {},
    h('header', { class: 'dash-panel-head' }, h('span', { class: 'dash-panel-kicker' }, 'Página'), h('strong', {}, 'Nada selecionado')),
    renderFields(fields, d.page, ([name], value) => {
      if (name === 'size') els.panelKey = null;
      commitLayout((dd) => {
        dd.page = { ...dd.page, [name]: value };
        if (name === 'size' && value === 'free') dd.page.height = pageHeight(d.page);
      }, { key: `page:${name}` });
    }, { defaultColor: () => hex(cssVar('--bg')) }),
    h('p', { class: 'muted' }, 'Clique num visual para formatá-lo. Shift+arrastar seleciona vários; Alt solta o encaixe.'));
}

// ------------------------------------------------------------------ inserir (RF-1440..RF-1442)

// ------------------------------------------------------------------ copiar, colar, duplicar (RF-1404)

function copySelection() {
  const free = dash().items.filter((i) => ui.selected.has(i.id) && i.kind !== 'visual');
  if (!free.length) {
    if (ui.selected.size) toast('Visuais vêm das caixas de BI: para repetir um, duplique a caixa no fluxo.');
    return false;
  }
  clip = { items: free.map((i) => structuredClone(i)), pastes: 0 };
  return true;
}

function pasteClip() {
  if (!clip.items.length) return;
  clip.pastes += 1;
  const shift = GRID * 2 * clip.pastes;
  const copies = clip.items.map((i) => ({ ...structuredClone(i), id: newId(), x: i.x + shift, y: i.y + shift }));
  commitLayout((d) => { d.items.push(...copies); });
  ui.selected = new Set(copies.map((c) => c.id));
  render();
}

// ------------------------------------------------------------------ edição: gestos

const toPage = (e) => {
  const r = els.page.getBoundingClientRect();
  return { x: (e.clientX - r.left) / ui.scale, y: (e.clientY - r.top) / ui.scale };
};
const elOf = (id) => els.page.querySelector(`.dash-item[data-id="${id}"]`);

/** Seleção mudou: destaca os itens e troca o painel Formato. */
function refreshSelection() {
  for (const el of els.page.querySelectorAll('.dash-item')) el.classList.toggle('selected', ui.selected.has(el.dataset.id));
  const align = root.querySelector('.dash-actions [aria-label^="Alinhar"]');
  if (align) align.disabled = ui.selected.size < 2;
  const key = [...ui.selected].join(',');
  if (els.panel && els.panelKey !== key) {
    const panel = panelEl();
    els.panel.replaceWith(panel);
    els.panel = panel;
    els.panelKey = key;
  }
}

function onDown(e) {
  if (e.button !== 0) return;
  const p = toPage(e);
  const handle = e.target.closest('.dash-handle');
  const el = e.target.closest('.dash-item');
  const additive = e.shiftKey || e.ctrlKey || e.metaKey;
  if (handle) {
    const item = itemById(el.dataset.id);
    ui.selected = new Set([item.id]);
    gesture = { type: 'resize', id: item.id, dir: handle.dataset.dir, start: p, rect: rectOf(item), moved: false };
  } else if (el) {
    const id = el.dataset.id;
    if (additive) {
      if (ui.selected.has(id)) ui.selected.delete(id); else ui.selected.add(id);
      refreshSelection();
      return;
    }
    if (!ui.selected.has(id)) ui.selected = new Set([id]);
    gesture = { type: 'move', start: p, moved: false, members: [...ui.selected].map(itemById).filter(Boolean).map((i) => ({ id: i.id, rect: rectOf(i) })) };
  } else {
    if (!additive) ui.selected.clear();
    els.marquee = h('div', { class: 'dash-marquee' });
    els.page.append(els.marquee);
    gesture = { type: 'marquee', start: p, base: new Set(ui.selected), moved: false };
  }
  refreshSelection();
  document.activeElement?.blur?.();
  els.page.setPointerCapture(e.pointerId);
  e.preventDefault();
}

function onMove(e) {
  if (!gesture) return;
  const p = toPage(e);
  const dx = p.x - gesture.start.x;
  const dy = p.y - gesture.start.y;
  if (!gesture.moved && Math.hypot(dx, dy) * ui.scale < 3) return;
  gesture.moved = true;
  if (gesture.type === 'marquee') {
    const box = { x: Math.min(p.x, gesture.start.x), y: Math.min(p.y, gesture.start.y), w: Math.abs(dx), h: Math.abs(dy) };
    Object.assign(els.marquee.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` });
    ui.selected = new Set(gesture.base);
    for (const i of dash().items) if (overlaps(box, i) && elOf(i.id)) ui.selected.add(i.id);
    refreshSelection();
    return;
  }
  const others = dash().items.filter((i) => !(gesture.members || [{ id: gesture.id }]).some((m) => m.id === i.id));
  if (gesture.type === 'move') {
    const box = bbox(gesture.members.map((m) => m.rect));
    const snap = snapBox({ ...box, x: box.x + dx, y: box.y + dy }, others, e.altKey);
    gesture.dx = box.x + dx + snap.dx - box.x;
    gesture.dy = box.y + dy + snap.dy - box.y;
    for (const m of gesture.members) {
      const el = elOf(m.id);
      if (el) { el.style.left = `${m.rect.x + gesture.dx}px`; el.style.top = `${m.rect.y + gesture.dy}px`; }
    }
    drawGuides(snap.guides);
  } else if (gesture.type === 'resize') {
    const { rect, guides } = resizeRect(gesture.rect, gesture.dir, dx, dy, others, e.altKey);
    gesture.next = rect;
    Object.assign(elOf(gesture.id).style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.w}px`, height: `${rect.h}px` });
    drawGuides(guides);
  }
}

function onUp() {
  const g = gesture;
  gesture = null;
  drawGuides([]);
  els.marquee?.remove();
  if (!g?.moved) return;
  if (g.type === 'move' && (g.dx || g.dy)) {
    commitLayout((d) => {
      for (const m of g.members) {
        const it = d.items.find((i) => i.id === m.id);
        if (it) { it.x = Math.max(0, Math.round(m.rect.x + g.dx)); it.y = Math.max(0, Math.round(m.rect.y + g.dy)); }
      }
    });
  } else if (g.type === 'resize' && g.next) {
    commitLayout((d) => Object.assign(d.items.find((i) => i.id === g.id), g.next));
  }
}

/** Duplo clique num texto leva ao campo de texto do painel. */
function onDoubleClick(e) {
  const el = e.target.closest('.dash-item.kind-text');
  if (!el) return;
  ui.selected = new Set([el.dataset.id]);
  refreshSelection();
  const area = els.panel?.querySelector('#dash-text');
  area?.focus();
  area?.select();
}

/** Uma alteração de layout = um passo de desfazer; a página cresce se algo passou do fim (RF-1463). */

// ------------------------------------------------------------------ encaixe e guias

// ------------------------------------------------------------------ menus e ações

function onContextMenu(e) {
  const el = e.target.closest('.dash-item');
  if (!el) return;
  e.preventDefault();
  const item = itemById(el.dataset.id);
  if (ui.mode === 'edit' && !ui.selected.has(item.id)) { ui.selected = new Set([item.id]); refreshSelection(); }
  const visual = item.kind === 'visual';
  const items = [
    visual ? { label: 'Ir para a caixa no fluxo', icon: 'workflow', onSelect: () => goToNode(item.node_id) } : null,
    visual ? { label: 'Baixar imagem (PNG)', icon: 'download', onSelect: () => exportVisual(item) } : null,
  ];
  if (ui.mode === 'edit') {
    const free = !visual;
    items.push('separator',
      free ? { label: 'Copiar', icon: 'copy', shortcut: 'Ctrl+C', onSelect: copySelection } : null,
      free ? { label: 'Duplicar', icon: 'copy', shortcut: 'Ctrl+D', onSelect: () => copySelection() && pasteClip() } : null,
      clip.items.length ? { label: 'Colar', icon: 'clipboard', shortcut: 'Ctrl+V', onSelect: pasteClip } : null,
      { label: 'Trazer para frente', icon: 'arrow-up', onSelect: () => reorder(true) },
      { label: 'Enviar para trás', icon: 'arrow-down', onSelect: () => reorder(false) });
    if (ui.selected.size > 1) items.push('separator', ...alignItems());
    items.push('separator', {
      label: visual || ui.selected.size > 1 ? 'Remover da página' : 'Excluir', icon: 'trash', danger: true, shortcut: 'Del', onSelect: removeSelected,
    });
  }
  showMenu(e.clientX, e.clientY, items.filter(Boolean));
}

function alignItems() {
  const n = ui.selected.size;
  return [
    { label: 'Alinhar à esquerda', icon: 'chevron-left', disabled: n < 2, onSelect: () => align('left') },
    { label: 'Centralizar na horizontal', icon: 'columns', disabled: n < 2, onSelect: () => align('hcenter') },
    { label: 'Alinhar à direita', icon: 'chevron-right', disabled: n < 2, onSelect: () => align('right') },
    { label: 'Alinhar ao topo', icon: 'chevron-up', disabled: n < 2, onSelect: () => align('top') },
    { label: 'Centralizar na vertical', icon: 'columns', disabled: n < 2, onSelect: () => align('vmiddle') },
    { label: 'Alinhar à base', icon: 'chevron-down', disabled: n < 2, onSelect: () => align('bottom') },
    { label: 'Mesma largura e altura', icon: 'fit', disabled: n < 2, onSelect: () => align('size') },
    { label: 'Distribuir na horizontal', icon: 'columns', disabled: n < 3, onSelect: () => distribute('x') },
    { label: 'Distribuir na vertical', icon: 'list', disabled: n < 3, onSelect: () => distribute('y') },
  ];
}

const selectedItems = (d = dash()) => d.items.filter((i) => ui.selected.has(i.id));

function align(kind) {
  commitLayout((d) => {
    const sel = selectedItems(d);
    const b = bbox(sel.map(rectOf));
    const first = sel[0];
    for (const i of sel) {
      if (kind === 'left') i.x = b.x;
      else if (kind === 'right') i.x = b.x + b.w - i.w;
      else if (kind === 'hcenter') i.x = Math.round(b.x + (b.w - i.w) / 2);
      else if (kind === 'top') i.y = b.y;
      else if (kind === 'bottom') i.y = b.y + b.h - i.h;
      else if (kind === 'vmiddle') i.y = Math.round(b.y + (b.h - i.h) / 2);
      else if (kind === 'size') { i.w = first.w; i.h = first.h; }
    }
  });
}

function distribute(axis) {
  commitLayout((d) => {
    const size = axis === 'x' ? 'w' : 'h';
    const sel = selectedItems(d).sort((a, b) => a[axis] - b[axis]);
    const start = sel[0][axis];
    const end = Math.max(...sel.map((i) => i[axis] + i[size]));
    const gap = (end - start - sel.reduce((acc, i) => acc + i[size], 0)) / (sel.length - 1);
    let pos = start;
    for (const i of sel) { i[axis] = Math.round(pos); pos += i[size] + gap; }
  });
}

function reorder(front) {
  commitLayout((d) => {
    const moving = d.items.filter((i) => ui.selected.has(i.id));
    const rest = d.items.filter((i) => !ui.selected.has(i.id));
    d.items = front ? [...rest, ...moving] : [...moving, ...rest];
  });
}

/** Visuais saem da página mas a caixa continua no fluxo (RF-1407); textos, imagens e formas são excluídos. */
function removeSelected() {
  if (!ui.selected.size) return;
  commitLayout((d) => {
    for (const i of selectedItems(d)) if (i.kind === 'visual' && !d.hidden.includes(i.node_id)) d.hidden.push(i.node_id);
    d.items = d.items.filter((i) => !ui.selected.has(i.id));
  });
  ui.selected.clear();
  render();
}

function hiddenItems() {
  return dash().hidden.map((nodeId) => ({
    label: nodeLabel(nodeId),
    icon: 'plus',
    onSelect: () => restoreVisual(nodeId, mutate)
      .then((grew) => grew && toast('O visual não coube na página: a altura passou a ser livre.'))
      .catch((err) => toastError(err, 'Não foi possível devolver o visual')),
  }));
}

/** Atalhos do modo Editar. Devolve true se tratou a tecla. */
export function handleDashboardKey(e) {
  if (store.view !== 'dashboard' || ui.mode !== 'edit' || !dash()) return false;
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  if (mod && key === 'a') {
    ui.selected = new Set(dash().items.map((i) => i.id));
    refreshSelection();
    return true;
  }
  if (mod && key === 'c') return copySelection() || true;
  if (mod && key === 'x') { if (copySelection()) removeSelected(); return true; }
  if (mod && key === 'v') { pasteClip(); return true; }
  if (mod && key === 'd') { if (copySelection()) pasteClip(); return true; }
  if (mod) return false;
  if (e.key === 'Escape') { ui.selected.clear(); refreshSelection(); return true; }
  if (!ui.selected.size) return false;
  if (e.key === 'Delete' || e.key === 'Backspace') { removeSelected(); return true; }
  const step = e.shiftKey ? GRID : 1;
  const move = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (!move) return false;
  commitLayout((d) => {
    for (const i of selectedItems(d)) { i.x = Math.max(0, i.x + move[0]); i.y = Math.max(0, i.y + move[1]); }
  }, { key: 'dash:nudge' });
  return true;
}

// ------------------------------------------------------------------ Organizar (RF-1460..RF-1463)

// ------------------------------------------------------------------ imagem PNG (RF-1450..RF-1453)

