// Página do HTML exportado (spec 021): mostra o dashboard e recalcula os visuais quando um filtro muda.
// Roda sozinha, sem servidor: tudo o que precisa está no próprio arquivo.

import { chartChrome, freeEl, placeItem, setCardEnv, visualCard } from './dash_cards.js';
import { computeWidget, makeTable, applyFilters } from './dash_compute.js';
import { activeFiltersText, filterBar, isFilterActive, noFilterBadge } from './dash_filters.js';
import { h } from './dom.js';

const PAGE_W = 1600;
const data = JSON.parse(document.getElementById('prodata-dados').textContent);
const filters = (data.filters || []).map((f) => ({ ...f }));

function tableOf(node) {
  const columns = {};
  for (const [name, key] of Object.entries(node.columns)) columns[name] = data.columns[key];
  return makeTable(columns, node.types, node.rows);
}

const tables = Object.fromEntries(Object.entries(data.nodes || {}).map(([id, node]) => [id, tableOf(node)]));

function widgets() {
  const out = { ...data.widgets };
  const missing = {};
  for (const [id, node] of Object.entries(data.nodes || {})) {
    const { table, missing: absent } = applyFilters(tables[id], filters);
    if (absent.length) missing[id] = absent;
    try {
      out[id] = { ...computeWidget(node.tool, node.config, table), node_id: id };
    } catch (err) {
      out[id] = { widget_type: 'message', title: node.title, message: err.message, node_id: id };
    }
  }
  for (const item of data.items) {
    if (item.kind !== 'visual' || data.nodes?.[item.node_id]) continue;
    const absent = filters.filter(isFilterActive).map((f) => f.column);
    if (absent.length) missing[item.node_id] = [...new Set(absent)];
  }
  return { out, missing };
}

function page() {
  const { out, missing } = widgets();
  return h('div', {
    class: 'dash-page dash-viewer-page',
    style: { width: `${PAGE_W}px`, height: `${data.height}px`, backgroundColor: data.page.background || null },
  }, data.items.map((item) => {
    const f = item.format || {};
    const w = out[item.node_id];
    if (item.kind === 'visual' && !w) return null;
    const content = item.kind === 'visual'
      ? visualCard(w, { width: item.w, height: Math.max(80, item.h - chartChrome(f)), className: 'fill', fmt: f })
      : freeEl(item, { editing: false });
    if (!content) return null;
    return placeItem(item, content, missing[item.node_id] ? noFilterBadge(missing[item.node_id]) : null);
  }));
}

const root = document.getElementById('prodata-pagina');

function draw() {
  const available = Math.max(320, document.documentElement.clientWidth - 32);
  const scale = Math.min(available / PAGE_W, 1.5);
  const sheet = h('div', { class: 'dash-sheet', style: { width: `${PAGE_W * scale}px`, height: `${data.height * scale}px` } }, page());
  sheet.firstChild.style.transform = `scale(${scale})`;
  const note = data.fixed_filters ? h('p', { class: 'dash-viewer-fixed' }, `Recorte aplicado ao gerar este arquivo: ${data.fixed_filters}`) : null;
  const bar = filterBar({
    filters,
    options: data.options,
    onChange: (id, patch) => { Object.assign(filters.find((f) => f.id === id), patch); schedule(); },
    onClear: () => { for (const f of filters) { f.selected = []; f.min = null; f.max = null; } schedule(); },
  });
  const head = h('header', { class: 'dash-head' }, h('div', { class: 'dash-brand' },
    data.logo ? h('img', { class: 'dash-logo', src: data.logo, alt: 'Grupo Protege' }) : null,
    h('div', {}, h('div', { class: 'dash-org' }, 'Grupo Protege'), h('h1', {}, data.name),
      h('p', { class: 'muted' }, `Dados de ${data.exported_at} · ${activeFiltersText(filters) || 'sem filtros aplicados'}`))));
  root.replaceChildren(...[head, note, bar, sheet].filter(Boolean));
}

let pending = 0;
function schedule() {
  cancelAnimationFrame(pending);
  pending = requestAnimationFrame(draw);
}

setCardEnv({ open: null, clickable: () => false });
let resizing = 0;
window.addEventListener('resize', () => { clearTimeout(resizing); resizing = setTimeout(draw, 120); });
document.title = data.name;
draw();
