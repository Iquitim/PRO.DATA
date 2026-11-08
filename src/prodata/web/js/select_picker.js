// Listas de opção do Configurar no estilo do programa (spec 029, RF-2942). O <select> continua sendo a fonte da
// verdade: valor, `onchange` e rótulo não mudam, então cada campo segue igual. Só a lista aberta é nossa.

import { h } from './dom.js';
import { icon } from './icons.js';

const SEARCH_FROM = 11; // com mais de 10 opções, a lista ganha busca
const TAG_SEPARATOR = '  ·  '; // "uf  ·  abc": o tipo vai para a direita
const OPEN_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', ' ', 'F4']);
const fold = (text) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

let current = null;

function closePicker({ refocus = true } = {}) {
  if (!current) return;
  const { el, sel, cleanup } = current;
  current = null;
  cleanup();
  el.remove();
  if (refocus && sel.isConnected) sel.focus();
}

/** As opções do <select> como uma lista simples, com o título do grupo em cada uma. */
function readOptions(sel) {
  return [...sel.options].filter((o) => !o.hidden).map((o) => {
    const [label, tag] = o.textContent.split(TAG_SEPARATOR);
    return { value: o.value, label, tag: tag || '', disabled: o.disabled, group: o.parentElement.tagName === 'OPTGROUP' ? o.parentElement.label : '' };
  });
}

function place(el, sel) {
  const r = sel.getBoundingClientRect();
  const width = Math.min(Math.max(r.width, 240), innerWidth - 16);
  const below = innerHeight - r.bottom - 12;
  const above = r.top - 12;
  const up = below < 200 && above > below;
  Object.assign(el.style, {
    left: `${Math.max(8, Math.min(r.left, innerWidth - width - 8))}px`,
    width: `${width}px`,
    maxHeight: `${Math.min(360, up ? above : below)}px`,
    ...(up ? { bottom: `${innerHeight - r.top + 4}px` } : { top: `${r.bottom + 4}px` }),
  });
}

function openPicker(sel, root) {
  closePicker({ refocus: false });
  const options = readOptions(sel);
  const search = options.length >= SEARCH_FROM
    ? h('input', { class: 'input input-sm select-find', type: 'search', placeholder: 'Buscar…', 'aria-label': 'Buscar na lista' })
    : null;
  const list = h('div', { class: 'select-list', role: 'listbox', tabindex: -1, 'aria-label': sel.getAttribute('aria-label') || 'Opções' });
  const el = h('div', { class: 'select-pop' }, search, list);
  let shown = options;
  let active = Math.max(0, options.findIndex((o) => o.value === sel.value));
  let typed = '';
  let typedAt = 0;

  const usable = () => shown.flatMap((o, i) => (o.disabled ? [] : [i]));
  const pick = (o) => {
    closePicker();
    if (sel.value === o.value) return;
    sel.value = o.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const mark = () => {
    list.querySelectorAll('.select-opt').forEach((row) => {
      const on = Number(row.dataset.i) === active;
      row.classList.toggle('active', on);
      if (on) { list.setAttribute('aria-activedescendant', row.id); row.scrollIntoView({ block: 'nearest' }); }
    });
  };
  const draw = () => {
    const query = fold(search?.value.trim() || '');
    shown = query ? options.filter((o) => fold(`${o.label} ${o.group}`).includes(query)) : options;
    if (!usable().includes(active)) active = usable()[0] ?? 0;
    let group = '';
    const rows = [];
    shown.forEach((o, i) => {
      if (o.group && o.group !== group) rows.push(h('div', { class: 'select-group', role: 'presentation' }, o.group));
      group = o.group;
      rows.push(h('div', {
        id: `select-opt-${i}`, class: ['select-opt', o.disabled && 'disabled', !o.value && 'placeholder'], role: 'option', 'aria-selected': String(o.value === sel.value), dataset: { i },
        onmousedown: (e) => e.preventDefault(), // clicar não tira o foco da busca
        onclick: () => { if (!o.disabled) pick(o); },
        onmousemove: () => { if (!o.disabled && active !== i) { active = i; mark(); } },
      }, h('span', { class: 'select-check' }, o.value === sel.value ? icon('check', 13) : null),
      h('span', { class: 'ellipsis', title: o.label }, o.label), o.tag ? h('small', {}, o.tag) : null));
    });
    list.replaceChildren(...(rows.length ? rows : [h('p', { class: 'select-none' }, 'Nada encontrado.')]));
    mark();
  };
  const step = (delta) => {
    const ids = usable();
    if (!ids.length) return;
    const at = ids.indexOf(active);
    active = ids[Math.max(0, Math.min(ids.length - 1, (at < 0 ? 0 : at) + delta))];
    mark();
  };
  const typeAhead = (char) => {
    const now = Date.now();
    typed = now - typedAt > 700 ? char : typed + char;
    typedAt = now;
    const hit = usable().find((i) => fold(shown[i].label).startsWith(fold(typed)));
    if (hit !== undefined) { active = hit; mark(); }
  };
  el.addEventListener('keydown', (e) => {
    const moves = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 };
    e.stopPropagation(); // Esc e as setas são da lista: não mexem no canvas
    if (moves[e.key]) { e.preventDefault(); step(moves[e.key]); }
    else if (e.key === 'Home' && !search) { e.preventDefault(); step(-shown.length); }
    else if (e.key === 'End' && !search) { e.preventDefault(); step(shown.length); }
    else if (e.key === 'Enter' || (e.key === ' ' && !search)) { e.preventDefault(); if (shown[active] && !shown[active].disabled) pick(shown[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); closePicker(); }
    else if (e.key === 'Tab') closePicker();
    else if (!search && e.key.length === 1 && !e.ctrlKey && !e.altKey) typeAhead(e.key);
  });
  search?.addEventListener('input', draw);

  const outside = (e) => { if (!el.contains(e.target) && e.target !== sel) closePicker({ refocus: false }); };
  const dismiss = () => closePicker({ refocus: false });
  document.addEventListener('pointerdown', outside, true);
  window.addEventListener('resize', dismiss);
  root.addEventListener('scroll', dismiss, true);
  const cleanup = () => {
    document.removeEventListener('pointerdown', outside, true);
    window.removeEventListener('resize', dismiss);
    root.removeEventListener('scroll', dismiss, true);
  };
  current = { el, sel, cleanup };
  document.body.append(el);
  place(el, sel);
  draw();
  (search || list).focus();
}

/** Liga a lista própria em todos os <select> de `root`, inclusive os que forem desenhados depois. */
export function initSelectPicker(root) {
  const selectOf = (target) => {
    const sel = target.closest?.('select');
    return sel && !sel.disabled && !sel.multiple ? sel : null;
  };
  root.addEventListener('mousedown', (e) => {
    const sel = selectOf(e.target);
    if (!sel || e.button !== 0) return;
    e.preventDefault(); // não abre a lista do Windows
    if (current?.sel === sel) { closePicker(); return; }
    sel.focus();
    openPicker(sel, root);
  });
  root.addEventListener('keydown', (e) => {
    const sel = selectOf(e.target);
    if (!sel || current || !OPEN_KEYS.has(e.key)) return;
    e.preventDefault();
    e.stopPropagation();
    openPicker(sel, root);
  });
}
