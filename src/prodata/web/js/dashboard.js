// Dashboard em página de tamanho fixo (spec 014): modo Visualizar e modo Editar (canvas com encaixe,
// guias, seleção múltipla), painel Formato, textos/imagens/formas, Organizar com layouts prontos e
// imagem PNG. Os cartões de visual também são usados pelo painel de insights.

import { api } from './api.js';
import { renderChart, withTooltip } from './charts.js';
import {
  biNodes, ensureLayout, GRID, growToFit, hintFor, PAGE_SIZES, PAGE_W, pageHeight, rectOf, restoreVisual, widgetsByNode,
} from './dash_model.js';
import { renderPng, savePng, stamp } from './dash_export.js';
import { button, debounce, fmt, h } from './dom.js';
import { renderFields } from './fields.js';
import { icon } from './icons.js';
import { inspect, mutate, on, select, store } from './store.js';
import { confirmDialog, openDialog, showMenu, toast, toastError } from './ui.js';

export const AGG_LABELS = {
  sum: 'Soma', mean: 'Média', count: 'Contagem', min: 'Mínimo', max: 'Máximo', n_unique: 'Distintos',
};

let root;
let handlers = {};
const tableMode = new Set();
const ui = { mode: 'view', zoom: null, selected: new Set(), scale: 1 };
let els = {};
let gesture = null;
let syncing = null;
let formats = null; // campos do painel Formato por tipo (GET /api/dashboard/formats)
let clip = { items: [], pastes: 0 };
const PANEL_W = 312;

export function initDashboard(el, opts) {
  root = el;
  handlers = opts;
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

// ------------------------------------------------------------------ cartões (formato: RF-1411..RF-1413)

/** Fundo, borda, cantos e sombra do cartão. */
function cardStyle(f = {}) {
  return {
    background: f.background || null,
    border: f.border === false ? '0' : null,
    borderColor: f.border !== false && f.border_color ? f.border_color : null,
    borderRadius: f.radius !== undefined ? `${f.radius}px` : null,
    boxShadow: f.shadow ? 'var(--shadow-md)' : null,
  };
}

const titleStyle = (f) => ({ fontSize: f.title_size ? `${f.title_size}px` : null, textAlign: f.title_align === 'center' ? 'center' : null });

export function kpiTile(w, { compact = false, className = '', fmt: f = {} } = {}) {
  const exact = `${w.prefix || ''}${fmt.number(w.value, w.decimals ?? 0)}${w.suffix || ''}`;
  const shown = Math.abs(w.value) >= 1e6 ? `${w.prefix || ''}${fmt.compact(w.value)}${w.suffix || ''}` : exact;
  return h('article', {
    class: ['kpi', compact && 'compact', className, f.align === 'center' && 'centered'], tabindex: 0, style: cardStyle(f),
    onclick: () => ui.mode === 'view' && goToNode(w.node_id),
  },
  f.show_title === false ? null : h('div', { class: 'kpi-label', style: titleStyle(f) }, f.title || w.title),
  h('div', { class: 'kpi-value', title: exact, style: { fontSize: f.value_size ? `${f.value_size}px` : null, color: f.value_color || null } }, shown),
  f.show_footer === false ? null : h('div', { class: 'kpi-foot' },
    `${AGG_LABELS[w.metric] || w.metric}${w.column && w.metric !== 'count' ? ` de ${w.column}` : ''} · ${fmt.int(w.row_count)} linhas`));
}

/**
 * Cartão de gráfico. `w`: {node_id, title, subtitle?, chart_type, series, x_column, y_column, agg}.
 * Clicar no título leva ao nó de origem. `actions`: botões extras no cabeçalho; `fmt`: formato do visual.
 */
export function chartCard(w, { width, height = 260, className = '', actions = [], fmt: f = {} } = {}) {
  const card = h('article', { class: ['chart-card', className], style: cardStyle(f) });
  const asTable = tableMode.has(w.node_id);
  const subtitle = w.subtitle || (w.agg === 'count'
    ? `Contagem por ${w.x_column}` : `${AGG_LABELS[w.agg] || w.agg} de ${w.y_column} por ${w.x_column}`);
  const redraw = () => card.replaceWith(chartCard(w, { width, height, className, actions, fmt: f }));
  const showTitle = f.show_title !== false;
  const showSub = f.show_subtitle !== false;
  card.append(h('header', { class: ['chart-head', !showTitle && !showSub && 'bare'] },
    showTitle || showSub ? h('button', { type: 'button', class: 'chart-title', title: 'Ir para o nó', style: titleStyle(f), onclick: () => goToNode(w.node_id) },
      showTitle ? h('h3', { style: { fontSize: f.title_size ? `${f.title_size}px` : null } }, f.title || w.title) : null,
      showSub ? h('p', { class: 'muted' }, subtitle) : null) : h('span', { class: 'grow' }),
    h('div', { class: 'chart-actions' }, actions,
      button({ icon: asTable ? 'chart' : 'table', title: asTable ? 'Ver gráfico' : 'Ver tabela', size: 'sm', variant: 'ghost',
        onClick: () => { if (asTable) tableMode.delete(w.node_id); else tableMode.add(w.node_id); redraw(); } }))));

  if (!w.series.length) {
    card.append(h('div', { class: 'empty' }, 'Sem dados para exibir.'));
  } else if (asTable) {
    card.append(h('div', { class: 'chart-body table-wrap' }, h('table', { class: 'data-table compact' },
      h('thead', {}, h('tr', {}, h('th', {}, w.x_column), h('th', { class: 'num' }, w.y_column || 'contagem'))),
      h('tbody', {}, w.series.map((s) => h('tr', {}, h('td', {}, s.label), h('td', { class: 'num' }, fmt.number(s.value))))))));
  } else {
    const body = h('div', { class: 'chart-body' }, renderChart(w.chart_type, w.series, Math.max(220, width - 34), height, f));
    card.append(body);
    withTooltip(card, body);
  }
  return card;
}

// ------------------------------------------------------------------ página

const dash = () => store.workflow?.dashboard;
const itemById = (id) => dash()?.items.find((i) => i.id === id);
const nodeOf = (nodeId) => store.workflow.nodes.find((k) => k.id === nodeId);
const nodeLabel = (nodeId) => {
  const n = nodeOf(nodeId);
  return n?.label || store.tools[n?.type]?.name || nodeId;
};
const newId = () => `d_${Math.random().toString(36).slice(2, 8)}`;

/** Altura do cabeçalho do cartão: o resto da altura do item é do gráfico. */
function chartChrome(f) {
  const title = f.show_title === false ? 0 : Math.round((f.title_size || 14) * 1.45);
  const sub = f.show_subtitle === false ? 0 : 18;
  return 30 + (title || sub ? title + sub + 12 : 24);
}

function visualEl(item, w, { editing, exporting }) {
  const node = nodeOf(item.node_id);
  const f = item.format || {};
  if (!w) {
    if (!editing) return null;
    return h('article', { class: 'dash-placeholder' }, icon(node?.type === 'bi.kpi_card' ? 'gauge' : 'chart', 22),
      h('strong', {}, nodeLabel(item.node_id)),
      h('span', {}, node?.disabled ? 'Caixa desativada no fluxo' : 'Execute o fluxo para ver este visual'));
  }
  if (w.widget_type === 'kpi') return kpiTile(w, { className: 'fill', fmt: f });
  const actions = exporting || editing ? [] : [button({ icon: 'download', title: 'Baixar imagem deste visual (PNG)', size: 'sm', variant: 'ghost', onClick: () => exportVisual(item) })];
  return chartCard(w, { width: item.w, height: Math.max(80, item.h - chartChrome(f)), className: 'fill', actions, fmt: f });
}

/** Texto, imagem e forma (RF-1440..RF-1442). O texto entra como texto puro, nunca como HTML. */
function freeEl(item, { editing }) {
  const f = item.format || {};
  if (item.kind === 'text') {
    return h('div', {
      class: 'dash-text',
      style: {
        fontSize: `${f.size || 16}px`, fontWeight: f.bold ? '700' : null, fontStyle: f.italic ? 'italic' : null,
        color: f.color || null, textAlign: f.align || null, background: f.background || null,
        justifyContent: { middle: 'center', bottom: 'flex-end' }[f.vertical] || null,
      },
    }, h('span', {}, item.content || (editing ? 'Texto vazio' : '')));
  }
  if (item.kind === 'image') {
    if (!item.content) return editing ? h('div', { class: 'dash-placeholder' }, icon('file', 22), h('span', {}, 'Escolha uma imagem no painel Formato')) : null;
    return h('img', {
      class: 'dash-image', src: item.content, alt: '', draggable: false,
      style: { objectFit: f.fit || 'contain', opacity: f.opacity !== undefined ? f.opacity / 100 : null, borderRadius: f.radius ? `${f.radius}px` : null },
    });
  }
  if (item.kind === 'shape') {
    const opacity = f.opacity !== undefined ? f.opacity / 100 : null;
    if (f.shape === 'line') {
      const horizontal = item.w >= item.h;
      return h('div', { class: ['dash-line', horizontal ? 'h' : 'v'], style: { opacity } },
        h('span', { style: { [horizontal ? 'borderTopWidth' : 'borderLeftWidth']: `${f.stroke_width ?? 1}px`, borderColor: f.stroke || null } }));
    }
    return h('div', {
      class: 'dash-shape',
      style: {
        background: f.fill || null, opacity, borderRadius: `${f.radius ?? 12}px`,
        borderWidth: `${f.stroke_width ?? 1}px`, borderColor: f.stroke || null,
      },
    });
  }
  return null;
}

const HANDLES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

function itemEl(item, widgets, opts) {
  const content = item.kind === 'visual' ? visualEl(item, widgets[item.node_id], opts) : freeEl(item, opts);
  if (!content) return null;
  return h('div', {
    class: ['dash-item', `kind-${item.kind}`, opts.editing && ui.selected.has(item.id) && 'selected'],
    dataset: { id: item.id },
    style: { left: `${item.x}px`, top: `${item.y}px`, width: `${item.w}px`, height: `${item.h}px` },
  }, content, opts.editing ? HANDLES.map((d) => h('span', { class: `dash-handle h-${d}`, dataset: { dir: d } })) : null);
}

function pageEl({ editing = false, exporting = false } = {}) {
  const d = dash();
  const widgets = widgetsByNode();
  return h('div', {
    class: ['dash-page', editing && 'editing', exporting && 'dash-export'],
    style: { width: `${PAGE_W}px`, height: `${pageHeight(d.page)}px`, backgroundColor: d.page.background || null },
  }, d.items.map((item) => itemEl(item, widgets, { editing, exporting })));
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
    button({ icon: 'download', label: 'Baixar imagem', title: 'Baixar o dashboard em PNG', onClick: () => exportPage().catch((err) => toastError(err, 'Não foi possível gerar a imagem')) }),
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
  const editing = ui.mode === 'edit';
  if (!d.items.length && !biNodes().length && !editing) {
    root.replaceChildren(headEl(), h('div', { class: 'empty big' }, icon('dashboard', 28),
      h('strong', {}, 'Nenhum visual publicado'),
      h('span', {}, 'Adicione nós Chart ou KPI Card (categoria BI e indicadores) ao fluxo e execute.')));
    return;
  }
  if (editing && !formats) {
    api.dashboardFormats().then((f) => { formats = f; render(); }).catch((err) => toastError(err, 'Não foi possível carregar o painel Formato'));
  }
  const fit = Math.max(0.2, (root.clientWidth - 48 - (editing ? PANEL_W + 16 : 0)) / PAGE_W);
  ui.scale = editing && ui.zoom ? ui.zoom : Math.min(fit, 1.5);
  const page = pageEl({ editing });
  page.style.transform = `scale(${ui.scale})`;
  page.style.setProperty('--inv', String(1 / ui.scale)); // alças e guias com o mesmo tamanho em qualquer zoom
  const sheet = h('div', { class: 'dash-sheet', style: { width: `${PAGE_W * ui.scale}px`, height: `${pageHeight(d.page) * ui.scale}px` } }, page);
  const previous = els;
  els = { page, sheet, guides: [], marquee: null };
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
    } else {
      els.panel = panelEl();
      els.stage = h('div', { class: 'dash-stage' }, sheet);
      root.replaceChildren(headEl(), h('div', { class: 'dash-workspace' }, els.stage, els.panel));
    }
  } else {
    root.replaceChildren(headEl(), sheet);
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
  return widgetsByNode()[item.node_id]?.widget_type === 'kpi' || nodeOf(item.node_id)?.type === 'bi.kpi_card' ? 'kpi' : 'chart';
}

function itemPanel(item) {
  const kind = formatKind(item);
  const fields = formats[kind] || [];
  const ctrl = controlling(fields);
  const widget = widgetsByNode()[item.node_id];
  const f = item.format || {};
  const surface = hex(f.background) || hex(cssVar('--surface'));
  const onChange = ([name], value) => {
    if (ctrl.has(name)) els.panelKey = null;
    commitLayout((dd) => {
      const it = dd.items.find((i) => i.id === item.id);
      if (it) it.format = { ...it.format, [name]: value };
    }, { key: `fmt:${item.id}:${name}` });
  };
  const ctx = {
    categories: widget?.series?.map((s) => s.label) || [],
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

function insertItems() {
  return [
    { label: 'Título', icon: 'edit', onSelect: () => insert({ kind: 'text', w: 800, h: 64, content: store.workflow.name || 'Título', format: { size: 30, bold: true } }, { header: true }) },
    { label: 'Texto', icon: 'list', onSelect: () => insert({ kind: 'text', w: 480, h: 120, content: 'Escreva aqui', format: {} }) },
    'separator',
    { label: 'Imagem…', icon: 'upload', onSelect: () => pickImage().then((img) => img && insert({ kind: 'image', ...fitBox(img, 360), content: img.data, format: {} })) },
    { label: 'Logo do Grupo Protege', icon: 'image', onSelect: () => logoImage().then((img) => insert({ kind: 'image', ...fitBox(img, 120), content: img.data, format: {} })) },
    'separator',
    { label: 'Retângulo (fundo de seção)', icon: 'group', onSelect: () => insert({ kind: 'shape', w: 760, h: 400, format: { shape: 'rect' } }, { back: true }) },
    { label: 'Linha divisória', icon: 'columns', onSelect: () => insert({ kind: 'shape', w: 1520, h: 16, format: { shape: 'line' } }) },
  ];
}

const fitBox = (img, max) => {
  const k = Math.min(1, max / Math.max(img.width, img.height));
  return { w: Math.max(48, Math.round((img.width * k) / GRID) * GRID), h: Math.max(48, Math.round((img.height * k) / GRID) * GRID) };
};

/** Primeiro espaço livre a partir de `top` (de cima para baixo, da esquerda para a direita). */
function freeSpot(w, h, top) {
  const taken = dash().items;
  const fits = (x, y) => !taken.some((o) => overlaps({ x: x - 16, y: y - 16, w: w + 32, h: h + 32 }, o));
  for (let y = top; y < top + 4000; y += GRID) {
    for (let x = 40; x + w <= PAGE_W - 40; x += GRID) if (fits(x, y)) return { x, y };
  }
  return { x: Math.round((PAGE_W - w) / 2 / GRID) * GRID, y: top };
}

/**
 * Novo item no primeiro espaço livre perto do topo visível, selecionado. Formas de fundo vão para trás,
 * no topo visível, porque costumam ficar atrás de outros itens. Um título (`header`) entra no topo
 * visível e empurra para baixo o que estiver dali em diante, abrindo espaço.
 */
function insert(item, { back = false, header = false } = {}) {
  const top = els.sheet ? Math.max(0, (root.getBoundingClientRect().top - els.sheet.getBoundingClientRect().top) / ui.scale) : 0;
  const start = Math.round((top + 40) / GRID) * GRID;
  const spot = back || header ? { x: 40, y: start } : freeSpot(item.w, item.h, start);
  const placed = { id: newId(), node_id: null, ...item, ...spot };
  commitLayout((d) => {
    if (header) for (const i of d.items) if (i.y + i.h > start) i.y += item.h + 16;
    if (back) d.items.unshift(placed); else d.items.push(placed);
  });
  ui.selected = new Set([placed.id]);
  render();
}

const SVG_FORBIDDEN = /<\s*script|<\s*foreignObject|<\s*iframe|<\s*object|<\s*embed|\son\w+\s*=|javascript:|(?:xlink:)?href\s*=\s*["']\s*(?!#|data:image\/)/i;

const readAsDataUrl = (blob) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(blob);
});

const naturalSize = (src) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => resolve({ width: img.naturalWidth || 320, height: img.naturalHeight || 240 });
  img.onerror = () => resolve({ width: 320, height: 240 });
  img.src = src;
});

/** Escolhe uma imagem do computador. Mesmas regras do servidor: PNG/JPG/SVG sem código, até 1 MB. */
function pickImage() {
  return new Promise((resolve) => {
    const input = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/svg+xml', hidden: true });
    input.addEventListener('change', async () => {
      const file = input.files[0];
      input.remove();
      if (!file) { resolve(null); return; }
      try {
        if (!['image/png', 'image/jpeg', 'image/svg+xml'].includes(file.type)) throw new Error('Use uma imagem PNG, JPG ou SVG.');
        if (file.size > 1024 * 1024) throw new Error('A imagem passa de 1 MB. Reduza o tamanho antes de inserir.');
        if (file.type === 'image/svg+xml' && SVG_FORBIDDEN.test(await file.text())) throw new Error('O SVG contém scripts ou links externos e não pode ser usado.');
        const data = await readAsDataUrl(file);
        resolve({ data, ...(await naturalSize(data)) });
      } catch (err) {
        toastError(err, 'Imagem não aceita');
        resolve(null);
      }
    });
    document.body.append(input);
    input.click();
  });
}

async function logoImage() {
  const blob = await (await fetch('/static/brand/protege-escudo.svg')).blob();
  const data = await readAsDataUrl(new Blob([blob], { type: 'image/svg+xml' }));
  return { data, width: 191, height: 241 };
}

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
function commitLayout(fn, opts = {}) {
  let grew = false;
  mutate((wf) => { fn(wf.dashboard); grew = growToFit(wf.dashboard); }, opts);
  if (grew) toast('Os itens passaram do fim da página: a altura passou a ser livre.');
}

// ------------------------------------------------------------------ encaixe e guias

const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function bbox(rects) {
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  return { x, y, w: Math.max(...rects.map((r) => r.x + r.w)) - x, h: Math.max(...rects.map((r) => r.y + r.h)) - y };
}

/** Linhas de referência: bordas e centro da página, margens e bordas/centros dos outros itens. */
function targets(others) {
  const ph = pageHeight(dash().page);
  const xs = [0, 40, PAGE_W / 2, PAGE_W - 40, PAGE_W];
  const ys = [0, 40, ph / 2, ph - 40, ph];
  for (const o of others) {
    xs.push(o.x, o.x + o.w / 2, o.x + o.w);
    ys.push(o.y, o.y + o.h / 2, o.y + o.h);
  }
  return { xs, ys };
}

/** Melhor encaixe de um conjunto de arestas numa lista de alvos: { offset, at } ou null. */
function nearest(edges, values, threshold) {
  let best = null;
  for (const edge of edges) {
    for (const v of values) {
      const d = v - edge;
      if (Math.abs(d) <= threshold && (!best || Math.abs(d) < Math.abs(best.offset))) best = { offset: d, at: v };
    }
  }
  return best;
}

const toGrid = (v) => Math.round(v / GRID) * GRID;

function snapBox(box, others, free) {
  if (free) return { dx: 0, dy: 0, guides: [] };
  const t = targets(others);
  const threshold = 6 / ui.scale;
  const sx = nearest([box.x, box.x + box.w / 2, box.x + box.w], t.xs, threshold);
  const sy = nearest([box.y, box.y + box.h / 2, box.y + box.h], t.ys, threshold);
  const guides = [];
  if (sx) guides.push({ axis: 'x', at: sx.at });
  if (sy) guides.push({ axis: 'y', at: sy.at });
  return {
    dx: sx ? sx.offset : toGrid(box.x) - box.x,
    dy: sy ? sy.offset : toGrid(box.y) - box.y,
    guides,
  };
}

const MIN_W = 48;
const MIN_H = 16;

function resizeRect(r, dir, dx, dy, others, free) {
  const t = targets(others);
  const threshold = 6 / ui.scale;
  const guides = [];
  const snap = (v, list, axis) => {
    if (free) return v;
    const s = nearest([v], list, threshold);
    if (s) { guides.push({ axis, at: s.at }); return s.at; }
    return toGrid(v);
  };
  let { x, y } = r;
  let right = r.x + r.w;
  let bottom = r.y + r.h;
  if (dir.includes('e')) right = Math.max(x + MIN_W, snap(right + dx, t.xs, 'x'));
  if (dir.includes('w')) x = Math.min(right - MIN_W, Math.max(0, snap(r.x + dx, t.xs, 'x')));
  if (dir.includes('s')) bottom = Math.max(y + MIN_H, snap(bottom + dy, t.ys, 'y'));
  if (dir.includes('n')) y = Math.min(bottom - MIN_H, Math.max(0, snap(r.y + dy, t.ys, 'y')));
  right = Math.min(right, PAGE_W);
  return { rect: { x: Math.round(x), y: Math.round(y), w: Math.round(right - x), h: Math.round(bottom - y) }, guides };
}

function drawGuides(guides) {
  for (const g of els.guides || []) g.remove();
  els.guides = guides.map((g) => h('div', {
    class: ['dash-guide', g.axis === 'x' ? 'v' : 'h'],
    style: g.axis === 'x' ? { left: `${g.at}px` } : { top: `${g.at}px` },
  }));
  els.page?.append(...els.guides);
}

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

const TEMPLATE_INFO = {
  auto: ['Automático', 'Tamanho pelo tipo de visual, na ordem atual, sem buracos'],
  'kpis-top-2': ['KPIs no topo + 2 colunas', 'Indicadores em faixa, gráficos lado a lado'],
  'kpis-top-3': ['KPIs no topo + 3 colunas', 'Mais visuais por linha, para telas largas'],
  highlight: ['Destaque', 'Um gráfico grande e os demais ao lado'],
  'kpis-side': ['KPIs na lateral', 'Indicadores em coluna à esquerda'],
  report: ['Relatório', 'Um visual por linha, em largura total'],
};

async function openOrganize() {
  const d = dash();
  const visuals = d.items.filter((i) => i.kind === 'visual');
  const picked = visuals.filter((i) => ui.selected.has(i.id));
  const chosen = picked.length ? picked : visuals;
  if (!chosen.length) { toast('Selecione visuais ou adicione caixas de BI ao fluxo.'); return; }
  const obstacles = d.items.filter((i) => !chosen.includes(i)).map(rectOf);
  let result;
  try {
    result = await api.arrangeDashboard({
      page: d.page,
      items: chosen.map((i) => ({ id: i.id, hint: hintFor(i.node_id), rect: rectOf(i) })),
      obstacles,
    });
  } catch (err) {
    toastError(err, 'Não foi possível organizar');
    return;
  }
  const kinds = Object.fromEntries(chosen.map((i) => [i.id, hintFor(i.node_id).kind]));
  const { close } = openDialog({
    title: picked.length ? `Organizar ${chosen.length} visual(is) selecionado(s)` : 'Organizar o dashboard',
    size: 'lg',
    body: h('div', {},
      h('p', { class: 'muted organize-help' }, 'Escolha um layout. Textos, imagens, formas e visuais não selecionados ficam onde estão. Ctrl+Z desfaz.'),
      h('div', { class: 'organize-grid' }, Object.entries(TEMPLATE_INFO).map(([key, [label, desc]]) => h('button', {
        type: 'button', class: 'organize-option',
        onclick: () => { close(); applyArrangement(result[key]); },
      }, thumbnail(result[key], obstacles, kinds), h('strong', {}, label), h('span', { class: 'muted' }, desc),
      result[key].grew ? h('span', { class: 'organize-warn' }, 'Não cabe: a página vira altura livre') : null)))),
  });
}

function thumbnail(arr, obstacles, kinds) {
  const H = pageHeight(arr.page);
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const svgEl = el('svg', { viewBox: `0 0 ${PAGE_W} ${H}`, class: 'organize-thumb', 'aria-hidden': 'true' });
  svgEl.append(el('rect', { class: 'thumb-page', x: 0, y: 0, width: PAGE_W, height: H }));
  for (const o of obstacles) svgEl.append(el('rect', { class: 'thumb-fixed', x: o.x, y: o.y, width: o.w, height: o.h, rx: 12 }));
  for (const [id, r] of Object.entries(arr.positions)) {
    svgEl.append(el('rect', { class: `thumb-${kinds[id]}`, x: r.x, y: r.y, width: r.w, height: r.h, rx: 12 }));
  }
  return svgEl;
}

function applyArrangement(arr) {
  commitLayout((d) => {
    for (const i of d.items) if (arr.positions[i.id]) Object.assign(i, arr.positions[i.id]);
    d.page = { ...arr.page };
  });
  if (arr.grew) toast('Os visuais não couberam na página: a altura passou a ser livre.');
}

// ------------------------------------------------------------------ imagem PNG (RF-1450..RF-1453)

async function exportPage() {
  const d = dash();
  if (!d) return;
  const widgets = widgetsByNode();
  const missing = d.items.filter((i) => i.kind === 'visual' && !widgets[i.node_id]).length;
  if (!store.execution || missing) {
    const ok = await confirmDialog({
      title: 'Baixar imagem',
      message: store.execution
        ? `${missing} visual(is) sem dados (com erro, desativados ou não executados) vão ficar de fora da imagem.`
        : 'O fluxo ainda não foi executado: a imagem vai sair sem os visuais. Execute antes com "Atualizar dados".',
      confirm: 'Baixar assim mesmo',
    });
    if (!ok) return;
  }
  const data = await renderPng(pageEl({ exporting: true }), PAGE_W, pageHeight(d.page), { background: d.page.background || 'var(--bg)' });
  const saved = await savePng(`${store.workflow.name || 'Dashboard'} - ${stamp()}`, data);
  if (saved) toast(`Imagem salva: ${saved}`, { kind: 'success' });
}

async function exportVisual(item) {
  const w = widgetsByNode()[item.node_id];
  if (!w) { toast('Execute o fluxo antes de baixar este visual.'); return; }
  try {
    const wrap = h('div', { class: 'dash-page dash-export', style: { width: `${item.w}px`, height: `${item.h}px`, backgroundColor: 'transparent' } },
      itemEl({ ...item, x: 0, y: 0 }, { [item.node_id]: w }, { exporting: true }));
    const data = await renderPng(wrap, item.w, item.h, { background: 'transparent' });
    const saved = await savePng(`${w.title || nodeLabel(item.node_id)} - ${stamp()}`, data);
    if (saved) toast(`Imagem salva: ${saved}`, { kind: 'success' });
  } catch (err) {
    toastError(err, 'Não foi possível gerar a imagem');
  }
}
