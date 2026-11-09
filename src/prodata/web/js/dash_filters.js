// Barra de filtros da página (spec 021): a mesma no programa e no HTML exportado.

import { button, h } from './dom.js';
import { icon } from './icons.js';

const SHOWN_VALUES = 200;
const MAX_PILLS = 12; // acima disso, os valores ficam na caixa com busca
const EMPTY_VALUE = '(vazio)'; // o mesmo de filters.py
const CROSS_CHARTS = ['bar', 'hbar', 'donut', 'pareto'];
const CLICK_ONLY_CHARTS = ['stacked', 'grouped', 'stacked100'];

/** Gráficos que não se filtram pela própria categoria: apagam as de fora (filters.py faz o mesmo). */
export const isCrossChart = (w) => w.widget_type !== 'venn' && CROSS_CHARTS.includes(w.chart_type);
/** Gráficos em que clicar numa categoria filtra a página. Os empilhados têm cores por série, e por isso só ficam com a categoria escolhida. */
export const isClickChart = (w) => isCrossChart(w) || (w.widget_type !== 'venn' && CLICK_ONLY_CHARTS.includes(w.chart_type));

/** Filtros que valem para o visual de uma caixa: o gráfico da própria coluna mantém todas as categorias. */
export function filtersFor(config, filters) {
  if (!CROSS_CHARTS.includes(config?.chart_type)) return filters;
  return filters.filter((f) => !(f.kind === 'list' && f.column === config.x_column));
}

/** Valores escolhidos na coluna da categoria, ou null se não há filtro ativo nela. */
export function selectedIn(filters, column) {
  const f = (filters || []).find((x) => x.kind === 'list' && x.column === column && x.selected?.length);
  return f ? new Set(f.selected) : null;
}

/** Clique: só aquele valor (de novo, tira). Ctrl+clique: soma ou tira da escolha. */
export function clickedValues(selected, value, adding) {
  const now = new Set(selected || []);
  if (adding) {
    if (now.has(value)) now.delete(value); else now.add(value);
    return [...now];
  }
  return now.size === 1 && now.has(value) ? [] : [value];
}

export function isFilterActive(f) {
  if (f.kind === 'list') return Boolean(f.selected?.length);
  return (f.min !== null && f.min !== undefined) || (f.max !== null && f.max !== undefined);
}

const dateText = (iso) => (iso ? String(iso).split('-').reverse().join('/') : '');
const numberText = (v) => (v === null || v === undefined ? '' : Number(v).toLocaleString('pt-BR'));

/** Resumo do que está escolhido: aparece no botão e no topo das imagens exportadas. */
export function filterSummary(f) {
  if (!isFilterActive(f)) return 'Todos';
  if (f.kind === 'list') return f.selected.length === 1 ? f.selected[0] : `${f.selected.length} valores`;
  const show = f.kind === 'date' ? dateText : numberText;
  if (f.min === null || f.min === undefined) return `até ${show(f.max)}`;
  if (f.max === null || f.max === undefined) return `desde ${show(f.min)}`;
  return `${show(f.min)} a ${show(f.max)}`;
}

export const filterName = (f) => f.label || f.column;

/** Texto dos filtros ativos, para o que for exportado dizer de que recorte se trata. */
export function activeFiltersText(filters) {
  return (filters || []).filter(isFilterActive).map((f) => `${filterName(f)}: ${filterSummary(f)}`).join(' · ');
}

let openPopover = null;

function closePopover() {
  openPopover?.remove();
  openPopover = null;
  document.removeEventListener('pointerdown', closeOutside, true);
}

function closeOutside(e) {
  if (openPopover && !openPopover.contains(e.target)) closePopover();
}

function listEditor(f, option, onChange) {
  const chosen = new Set(f.selected || []);
  const all = option?.values || [...chosen];
  const box = h('div', { class: 'dash-filter-values' });
  const search = h('input', { class: 'input input-sm', placeholder: 'Buscar', 'aria-label': `Buscar em ${filterName(f)}` });
  const emit = () => onChange({ selected: [...chosen] });
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    const shown = all.filter((v) => !q || v.toLowerCase().includes(q));
    box.replaceChildren(...shown.slice(0, SHOWN_VALUES).map((v) => h('label', { class: 'dash-filter-value' },
      h('input', { type: 'checkbox', checked: chosen.has(v), onchange: (e) => { if (e.target.checked) chosen.add(v); else chosen.delete(v); emit(); } }),
      h('span', { class: 'ellipsis', title: v }, v))),
    ...(shown.length > SHOWN_VALUES ? [h('p', { class: 'field-help' }, `Mostrando ${SHOWN_VALUES} de ${shown.length}: use a busca.`)] : []),
    ...(!shown.length ? [h('p', { class: 'field-help' }, 'Nenhum valor.')] : []));
  };
  search.addEventListener('input', draw);
  draw();
  return h('div', { class: 'stack-xs' }, search,
    h('div', { class: 'row space-between' },
      button({ label: 'Marcar os visíveis', size: 'sm', variant: 'ghost', onClick: () => {
        const q = search.value.trim().toLowerCase();
        for (const v of all) if (!q || v.toLowerCase().includes(q)) chosen.add(v);
        emit(); draw();
      } }),
      all.includes(EMPTY_VALUE) && !option?.truncated ? button({ label: 'Só preenchidos', size: 'sm', variant: 'ghost', onClick: () => {
        chosen.clear();
        for (const v of all) if (v !== EMPTY_VALUE) chosen.add(v);
        emit(); draw();
      } }) : null,
      button({ label: 'Limpar', size: 'sm', variant: 'ghost', onClick: () => { chosen.clear(); emit(); draw(); } })),
    box,
    option?.truncated ? h('p', { class: 'field-help' }, 'Muitos valores: a lista traz só os primeiros.') : null);
}

function rangeEditor(f, option, onChange) {
  const type = f.kind === 'date' ? 'date' : 'number';
  const parse = (v) => (v === '' ? null : type === 'number' ? Number(v) : v);
  const input = (key, label) => h('label', { class: 'field' }, h('span', { class: 'field-label' }, label),
    h('input', {
      class: 'input input-sm', type, value: f[key] ?? '', step: 'any', placeholder: option?.[key] ?? '',
      min: type === 'date' ? option?.min ?? null : null, max: type === 'date' ? option?.max ?? null : null,
      onchange: (e) => onChange({ [key]: parse(e.target.value) }),
    }));
  return h('div', { class: 'stack-xs' }, input('min', 'De'), input('max', 'Até'),
    option && option.min !== null && option.min !== undefined
      ? h('p', { class: 'field-help' }, `Nos dados: ${f.kind === 'date' ? dateText(option.min) : numberText(option.min)} a ${f.kind === 'date' ? dateText(option.max) : numberText(option.max)}`) : null);
}

function showPopover(anchor, f, option, { onChange, onRemove }) {
  const same = openPopover?.dataset.filter === f.id;
  closePopover();
  if (same) return;
  // Guarda a escolha aqui: a barra é refeita a cada mudança, mas a caixa continua aberta.
  const current = { ...f };
  const change = (patch) => { Object.assign(current, patch); onChange(f.id, patch); };
  const pop = h('div', { class: 'dash-filter-pop', role: 'dialog', 'aria-label': `Filtro ${filterName(f)}`, dataset: { filter: f.id } },
    h('strong', {}, filterName(f)),
    f.kind === 'list' ? listEditor(current, option, change) : rangeEditor(current, option, change),
    onRemove ? button({ icon: 'trash', label: 'Tirar este filtro', size: 'sm', variant: 'ghost', onClick: () => { closePopover(); onRemove(f.id); } }) : null);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8))}px`;
  pop.style.top = `${Math.min(r.bottom + 4, Math.max(8, window.innerHeight - pop.offsetHeight - 8))}px`;
  openPopover = pop;
  document.addEventListener('pointerdown', closeOutside, true);
}

/** Valores à mostra, como botões: um clique liga ou desliga. */
function pills(f, option, onChange) {
  const chosen = new Set(f.selected || []);
  const all = option?.values || [...chosen];
  // Muitos valores não cabem: ficam só os escolhidos, e a lista completa continua na caixa com busca.
  const shown = all.length > MAX_PILLS ? [...chosen] : all;
  if (!shown.length) return null;
  return h('div', { class: 'dash-pills', role: 'group', 'aria-label': `Valores de ${filterName(f)}` }, shown.map((v) => h('button', {
    type: 'button', class: ['dash-pill', chosen.has(v) && 'on'], 'aria-pressed': chosen.has(v) ? 'true' : 'false', title: v,
    onclick: () => onChange(f.id, { selected: chosen.has(v) ? [...chosen].filter((x) => x !== v) : [...chosen, v] }),
  }, v)));
}

const dayOf = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / 86400000);
const isoOf = (day) => new Date(day * 86400000).toISOString().slice(0, 10);

/** Dois marcadores no mesmo trilho, para número e data. Só aplica ao soltar: filtrar a cada pixel pesaria. */
function rangeSlider(f, option, onChange) {
  if (option?.min === null || option?.min === undefined || option.max === null || option.max === undefined || option.min === option.max) return null;
  const isDate = f.kind === 'date';
  const toScale = (v) => (isDate ? dayOf(v) : Number(v));
  const low = toScale(option.min);
  const high = toScale(option.max);
  const whole = !isDate && Number.isInteger(low) && Number.isInteger(high) && high - low <= 400;
  const step = isDate || whole ? 1 : (high - low) / 200;
  const fromScale = (v) => (isDate ? isoOf(Math.round(Number(v))) : whole ? Number(v) : Number(Number(v).toFixed(2)));
  const text = (v) => (isDate ? dateText(isoOf(Math.round(Number(v)))) : numberText(fromScale(v)));
  const track = h('span', { class: 'dash-range-fill' });
  const values = h('span', { class: 'dash-range-values' });
  const thumb = (key, edge, label) => h('input', {
    type: 'range', class: 'dash-range-thumb', min: low, max: high, step, 'aria-label': `${filterName(f)}: ${label}`,
    value: f[key] === null || f[key] === undefined ? edge : toScale(f[key]),
    oninput: () => paint(key),
    onchange: (e) => {
      const at = Number(e.target.value);
      onChange(f.id, { [key]: at === edge ? null : fromScale(at) });
    },
  });
  const from = thumb('min', low, 'de');
  const to = thumb('max', high, 'até');
  function paint(moved) {
    if (Number(from.value) > Number(to.value)) {
      if (moved === 'min') from.value = to.value; else to.value = from.value;
    }
    const pct = (v) => ((Number(v) - low) / (high - low)) * 100;
    track.style.left = `${pct(from.value)}%`;
    track.style.right = `${100 - pct(to.value)}%`;
    values.textContent = `${text(from.value)} a ${text(to.value)}`;
  }
  paint();
  return h('div', { class: 'dash-range' }, h('div', { class: 'dash-range-track' }, track, from, to), values);
}

/**
 * `filters`: filtros da página; `options`: valores por coluna; `onChange(id, patch)`, `onClear()`;
 * `onAdd(event)` e `onRemove(id)` só existem onde o filtro pode ser criado ou tirado.
 */
export function filterBar({ filters, options, onChange, onClear, onAdd = null, onRemove = null, busy = false }) {
  const byColumn = new Map((options || []).map((o) => [o.column, o]));
  const anyActive = filters.some(isFilterActive);
  if (!filters.length && !onAdd) return null;
  const activeCount = filters.filter(isFilterActive).length;
  return h('div', { class: ['dash-filters', anyActive && 'has-active'], role: 'group', 'aria-label': 'Filtros da página' },
    h('div', { class: 'dash-filters-head' },
      h('span', { class: 'dash-filters-mark' }, icon('filter', 15)),
      h('strong', {}, 'Filtros'),
      activeCount ? h('span', { class: 'dash-filters-count' }, activeCount === 1 ? '1 ativo' : `${activeCount} ativos`) : null,
      h('span', { class: 'dash-filters-tip muted' }, filters.length ? 'Clique num valor aqui, ou numa barra ou fatia dos gráficos.' : 'Escolha uma coluna, ou clique numa barra ou fatia de um gráfico.'),
      busy ? h('span', { class: 'dash-filter-busy muted' }, 'Calculando…') : null,
      h('span', { class: 'grow' }),
      anyActive ? button({ icon: 'x', label: 'Limpar filtros', size: 'sm', variant: 'ghost', onClick: () => { closePopover(); onClear(); } }) : null,
      onAdd ? button({ icon: 'plus', label: 'Adicionar filtro', title: 'Adicionar filtro', size: 'sm', onClick: onAdd }) : null),
    filters.length ? h('div', { class: 'dash-slicers' }, filters.map((f) => h('div', { class: ['dash-slicer', isFilterActive(f) && 'active'] },
      h('button', {
        type: 'button', class: ['dash-filter', isFilterActive(f) && 'active'], dataset: { filterId: f.id }, 'aria-haspopup': 'dialog',
        onclick: (e) => showPopover(e.currentTarget, f, byColumn.get(f.column), { onChange, onRemove }),
      }, h('span', { class: 'dash-filter-name' }, filterName(f)), h('span', { class: 'dash-filter-state' }, filterSummary(f)), icon('chevron-down', 12)),
      f.kind === 'list' ? pills(f, byColumn.get(f.column), onChange) : rangeSlider(f, byColumn.get(f.column), onChange)))) : null);
}

/** Aviso discreto no canto do visual que não tem a coluna do filtro. */
export function noFilterBadge(columns) {
  return h('span', { class: 'dash-nofilter', title: `Este visual não tem a coluna ${columns.join(', ')}: mostra todos os dados.` },
    icon('filter', 11), 'Sem filtro');
}
