// Painel Formato do dashboard (RF-1410): do visual selecionado, da seleção múltipla ou da página.

import { api } from './api.js';
import { logoImage, pickImage } from './dash_insert.js';
import { PAGE_SIZES, PAGE_W, pageHeight, widgetsByNode } from './dash_model.js';
import { commitLayout, dash, els, nodeLabel, nodeOf, page as dashPage, ui } from './dash_state.js';
import { button, h } from './dom.js';
import { renderFields } from './fields.js';
import { toastError } from './ui.js';

export const PANEL_W = 312;
let formats = null; // campos do painel Formato por tipo (GET /api/dashboard/formats)
let loadingFormats = null;

/** Carrega os campos já na primeira visita, para o modo Editar abrir pronto. */
export function loadFormats(ready) {
  if (formats || loadingFormats) return;
  loadingFormats = api.dashboardFormats()
    .then((f) => { formats = f; ready(); })
    .catch((err) => { loadingFormats = null; toastError(err, 'Não foi possível carregar o painel Formato'); });
}

const KIND_LABELS = { text: 'Texto', image: 'Imagem', shape: 'Forma' };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const hex = (v) => (/^#[0-9a-f]{6}$/i.test(v) ? v : null);

/** Campos que mostram/escondem outros (show_if): mudar um deles refaz o painel. */
const controlling = (fields) => new Set(fields.flatMap((f) => Object.keys(f.show_if || {})));

export function panelEl() {
  const d = dash();
  const sel = d.items.filter((i) => ui.selected.has(i.id));
  const body = !formats ? h('p', { class: 'muted' }, 'Carregando…')
    : sel.length === 1 ? itemPanel(sel[0])
      : sel.length > 1 ? multiPanel(sel)
        : pagePanel(d);
  return h('aside', { class: 'dash-panel', style: { width: `${PANEL_W}px` } }, body);
}

export const formatFields = (kind) => formats?.[kind] || [];

export function formatKind(item) {
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
      if (!it) return;
      it.format = setIn(structuredClone(it.format || {}), path, value);
      if (name === 'category_colors') keepOtherColors(it.format);
    }, { key: `fmt:${item.id}:${path.join('.')}` });
  };
  // "Cor por categoria" pinta o que tem cor no visual: séries, conjuntos do Venn ou categorias.
  const oneColor = !widget?.series_names?.length && ['line', 'area'].includes(widget?.chart_type);
  const colored = widget?.widget_type === 'venn' ? widget.sets.map((s) => s.name)
    : widget?.series_names?.length ? widget.series_names
      : oneColor ? []
      : widget?.chart_type === 'bubble' ? (widget.points || []).map((p) => p.label)
      : widget?.chart_type === 'sankey' ? [...new Set((widget.links || []).flatMap((l) => [l.source, l.target]))]
      : widget?.chart_type === 'scatter' ? [...new Set((widget.points || []).map((p) => p.s).filter((s) => s !== undefined))]
        : widget?.series?.map((s) => s.label) || [];
  const ctx = {
    categories: colored,
    noCategories: oneColor ? 'Este gráfico tem uma série só. Mude a cor dele em Uma cor só.' : '',
    columns: () => (widget?.columns || []).filter((c) => c.numeric).map((c) => ({ name: c.name, type: 'Float64' })),
    contrastFor: (name) => {
      if (['color', 'category_colors'].includes(name) && kind === 'chart') return { against: surface, min: 3, what: 'o fundo do cartão' };
      if (name === 'value_color') return { against: surface, min: 4.5, what: 'o fundo do cartão' };
      if (name === 'color' && kind === 'text') return { against: hex(f.background) || hex(dash().page.background) || hex(cssVar('--bg')), min: 4.5, what: 'o fundo' };
      return null;
    },
    defaultColor: (name, i = 0) => {
      if (name === 'category_colors') return colorInUse(i, widget, item.format || {});
      if (name === 'color' && kind === 'chart') return hex(cssVar('--series-1'));
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
    h('div', { class: 'dash-panel-tools' }, button({
      icon: 'paintbrush', label: ui.paint ? 'Parar de copiar' : 'Copiar formato', size: 'sm', title: 'Levar este formato para outras caixas',
      onClick: () => (ui.paint ? dashPage.stopPaint() : dashPage.startPaint(item)),
    })),
    item.kind === 'visual' ? h('div', { class: 'dash-panel-note' },
      h('span', { class: 'muted' }, 'Dados, ordenação e limite de categorias ficam na caixa do fluxo.'),
      button({ icon: 'workflow', label: 'Editar dados', size: 'sm', onClick: () => dashPage.goToNode(item.node_id) })) : null,
    item.kind === 'text' ? textContentField(item) : null,
    item.kind === 'image' ? imageField(item) : null,
    renderFields(fields, f, onChange, ctx));
}

/** Barras, funil e Pareto usam uma cor para todas as categorias; os demais, uma por posição. */
function colorInUse(i, widget, f) {
  const base = f.palette === 'custom' ? (f.other_palette || 'brand') : (f.palette || 'brand');
  if (base === 'single' && f.color) return f.color;
  const shared = !widget?.series_names?.length && ['bar', 'hbar', 'funnel', 'pareto'].includes(widget?.chart_type);
  return hex(cssVar(`--${base === 'alt' ? 'alt' : 'series'}-${shared ? 1 : (i % 8) + 1}`));
}

/** Quem muda a cor de uma categoria passa a usar cor por categoria, sem mexer nas outras. */
function keepOtherColors(f) {
  if (f.palette === 'custom') return;
  if (f.palette && f.palette !== 'brand') f.other_palette = f.palette;
  f.palette = 'custom';
  const select = els.panel?.querySelector('[id^="f_palette_"]');
  if (select) select.value = 'custom';
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
    h('div', { class: 'dash-panel-actions' }, dashPage.alignItems().map((a) => button({ icon: a.icon, label: a.label, size: 'sm', variant: 'ghost', disabled: a.disabled, onClick: a.onSelect }))),
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
    h('p', { class: 'muted' }, 'Clique num visual para formatá-lo. Arrastar no vazio seleciona vários; Alt solta o encaixe.'));
}
