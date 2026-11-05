// Barra de filtros da página (spec 021): a mesma no programa e no HTML exportado.

import { button, h } from './dom.js';
import { icon } from './icons.js';

const SHOWN_VALUES = 200;

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

/**
 * `filters`: filtros da página; `options`: valores por coluna; `onChange(id, patch)`, `onClear()`;
 * `onAdd(event)` e `onRemove(id)` só existem onde o filtro pode ser criado ou tirado.
 */
export function filterBar({ filters, options, onChange, onClear, onAdd = null, onRemove = null, busy = false }) {
  const byColumn = new Map((options || []).map((o) => [o.column, o]));
  const anyActive = filters.some(isFilterActive);
  if (!filters.length && !onAdd) return null;
  return h('div', { class: 'dash-filters', role: 'group', 'aria-label': 'Filtros da página' },
    icon('filter', 14),
    filters.map((f) => h('button', {
      type: 'button', class: ['dash-filter', isFilterActive(f) && 'active'], dataset: { filterId: f.id }, 'aria-haspopup': 'dialog',
      onclick: (e) => showPopover(e.currentTarget, f, byColumn.get(f.column), { onChange, onRemove }),
    }, h('span', { class: 'dash-filter-name' }, filterName(f)), h('span', { class: 'dash-filter-state' }, filterSummary(f)), icon('chevron-down', 12))),
    onAdd ? button({ icon: 'plus', label: filters.length ? null : 'Adicionar filtro', title: 'Adicionar filtro', size: 'sm', variant: 'ghost', onClick: onAdd }) : null,
    anyActive ? button({ label: 'Limpar filtros', size: 'sm', variant: 'ghost', onClick: () => { closePopover(); onClear(); } }) : null,
    busy ? h('span', { class: 'dash-filter-busy muted' }, 'Calculando…') : null);
}

/** Aviso discreto no canto do visual que não tem a coluna do filtro. */
export function noFilterBadge(columns) {
  return h('span', { class: 'dash-nofilter', title: `Este visual não tem a coluna ${columns.join(', ')}: mostra todos os dados.` },
    icon('filter', 11), 'Sem filtro');
}
