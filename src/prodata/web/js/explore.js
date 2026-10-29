// Filtros exploratórios da tabela de resultados (spec 007): só mudam a visualização,
// nunca o fluxo — a não ser que o usuário peça "Criar nó Filter".

import { button, h } from './dom.js';
import { icon } from './icons.js';

export const OPS = {
  eq: { label: 'igual a', short: '=' },
  ne: { label: 'diferente de', short: '≠' },
  gt: { label: 'maior que', short: '>' },
  ge: { label: 'maior ou igual a', short: '≥' },
  lt: { label: 'menor que', short: '<' },
  le: { label: 'menor ou igual a', short: '≤' },
  between: { label: 'entre', short: 'entre' },
  contains: { label: 'contém', short: 'contém' },
  not_contains: { label: 'não contém', short: 'não contém' },
  starts_with: { label: 'começa com', short: 'começa com' },
  ends_with: { label: 'termina com', short: 'termina com' },
  in: { label: 'está em (lista)', short: 'em' },
  is_null: { label: 'é nulo', short: 'é nulo', noValue: true },
  not_null: { label: 'não é nulo', short: 'não é nulo', noValue: true },
};

const NUMERIC = new Set(['Int64', 'Float64']);

export function opsFor(type) {
  if (NUMERIC.has(type) || type === 'Date') return ['eq', 'ne', 'gt', 'ge', 'lt', 'le', 'between', 'is_null', 'not_null'];
  if (type === 'Boolean') return ['eq', 'ne', 'is_null', 'not_null'];
  return ['eq', 'ne', 'contains', 'not_contains', 'starts_with', 'ends_with', 'in', 'is_null', 'not_null'];
}

export function describe(f) {
  const op = OPS[f.op];
  if (op.noValue) return `${f.column} ${op.short}`;
  if (f.op === 'between') return `${f.column} entre ${f.value} e ${f.value2}`;
  return `${f.column} ${op.short} ${f.value}`;
}

// ------------------------------------------------------------------ editor (popover)

let openEditor = null;

export function closeFilterEditor() {
  openEditor?.remove();
  openEditor = null;
}

/**
 * Popover para criar/editar uma condição.
 * columns: [{name, type, histogram}] (perfil); initial: condição parcial; onApply(cond).
 */
export function openFilterEditor(x, y, { columns, initial = {}, onApply }) {
  closeFilterEditor();
  const cond = { column: initial.column || columns[0]?.name, op: initial.op, value: initial.value ?? '', value2: initial.value2 ?? '' };
  const colInfo = () => columns.find((c) => c.name === cond.column) || columns[0];
  if (!cond.op || !opsFor(colInfo().type).includes(cond.op)) cond.op = opsFor(colInfo().type)[0];

  const body = h('div', { class: 'stack-sm' });
  const panel = h('div', { class: 'filter-editor', role: 'dialog', 'aria-label': 'Condição de filtro' },
    h('div', { class: 'filter-editor-title' }, icon('filter', 14), initial.column && initial.op ? 'Editar condição' : 'Nova condição'), body);

  const apply = () => {
    const op = OPS[cond.op];
    if (!op.noValue && String(cond.value).trim() === '') return;
    if (cond.op === 'between' && String(cond.value2).trim() === '') return;
    closeFilterEditor();
    onApply({ column: cond.column, op: cond.op, ...(op.noValue ? {} : { value: cond.value }), ...(cond.op === 'between' ? { value2: cond.value2 } : {}) });
  };

  const draw = () => {
    const info = colInfo();
    const listId = `vals_${Math.random().toString(36).slice(2, 7)}`;
    const suggestions = !NUMERIC.has(info.type) ? (info.histogram || []).map((b) => b.label) : [];
    const valueInput = (key, placeholder) => h('input', {
      class: 'input input-sm', value: cond[key], placeholder, list: suggestions.length ? listId : null,
      oninput: (e) => { cond[key] = e.target.value; },
      onkeydown: (e) => { if (e.key === 'Enter') apply(); },
    });
    const op = OPS[cond.op];
    body.replaceChildren(
      h('select', { class: 'input input-sm', 'aria-label': 'Coluna', onchange: (e) => {
        cond.column = e.target.value;
        if (!opsFor(colInfo().type).includes(cond.op)) cond.op = opsFor(colInfo().type)[0];
        draw();
      } }, columns.map((c) => h('option', { value: c.name, selected: c.name === cond.column }, `${c.name}  ·  ${c.type}`))),
      h('select', { class: 'input input-sm', 'aria-label': 'Operador', onchange: (e) => { cond.op = e.target.value; draw(); } },
        opsFor(info.type).map((k) => h('option', { value: k, selected: k === cond.op }, OPS[k].label))),
      op.noValue ? null : cond.op === 'between'
        ? h('div', { class: 'row' }, valueInput('value', 'de'), valueInput('value2', 'até'))
        : valueInput('value', cond.op === 'in' ? 'valores separados por vírgula' : 'valor'),
      suggestions.length ? h('datalist', { id: listId }, suggestions.map((s) => h('option', { value: s }))) : null,
      h('div', { class: 'row end' },
        button({ label: 'Cancelar', size: 'sm', variant: 'ghost', onClick: closeFilterEditor }),
        button({ label: 'Aplicar', size: 'sm', variant: 'primary', onClick: apply })),
    );
    body.querySelector('input')?.focus();
  };

  document.body.append(panel);
  draw();
  const r = panel.getBoundingClientRect();
  panel.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
  panel.style.top = `${Math.max(8, Math.min(y, innerHeight - r.height - 8))}px`;
  openEditor = panel;
  setTimeout(() => {
    const outside = (e) => {
      if (!panel.contains(e.target)) {
        closeFilterEditor();
        document.removeEventListener('pointerdown', outside, true);
      }
    };
    document.addEventListener('pointerdown', outside, true);
  });
  panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeFilterEditor(); });
}

// ------------------------------------------------------------------ exploração → fluxo

const quote = (v) => `'${String(v).replace(/'/g, "''")}'`;

/** Converte os filtros na sintaxe de expressão do nó Filter (mesma semântica, sem diferenciar maiúsculas). */
export function toExpression(filters, columns) {
  const typeOf = (name) => columns.find((c) => c.name === name)?.type;
  return filters.map((f) => {
    const col = `[${f.column}]`;
    const numeric = NUMERIC.has(typeOf(f.column));
    const lit = (v) => (numeric ? String(v).replace(',', '.') : quote(v));
    const lower = `LowerCase(${col})`;
    const needle = quote(String(f.value ?? '').toLowerCase());
    switch (f.op) {
      case 'eq': return `${col} == ${lit(f.value)}`;
      case 'ne': return `${col} != ${lit(f.value)}`;
      case 'gt': return `${col} > ${lit(f.value)}`;
      case 'ge': return `${col} >= ${lit(f.value)}`;
      case 'lt': return `${col} < ${lit(f.value)}`;
      case 'le': return `${col} <= ${lit(f.value)}`;
      case 'between': return `(${col} >= ${lit(f.value)} AND ${col} <= ${lit(f.value2)})`;
      case 'contains': return `Contains(${lower}, ${needle})`;
      case 'not_contains': return `!Contains(${lower}, ${needle})`;
      case 'starts_with': return `StartsWith(${lower}, ${needle})`;
      case 'ends_with': return `EndsWith(${lower}, ${needle})`;
      case 'in': {
        const items = String(f.value).split(',').map((v) => v.trim()).filter(Boolean);
        return `(${items.map((v) => `${col} == ${quote(v)}`).join(' OR ')})`;
      }
      case 'is_null': return `IsNull(${col})`;
      default: return `!IsNull(${col})`;
    }
  }).join(' AND ');
}
