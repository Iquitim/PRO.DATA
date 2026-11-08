// Assistente de inserção do editor de fórmula (spec 010): Coluna, Função, Constante, linhas vizinhas da
// Multi-Row e os operadores, para montar a fórmula sem decorar a escrita. Saiu de formula_editor.js.

import { knownConstants, showValue } from './constants.js';
import { openFlowConstants } from './constants_ui.js';
import { h } from './dom.js';
import { icon } from './icons.js';
import { store } from './store.js';
import { typeLabel } from './types.js';
import { showMenu } from './ui.js';

const OPERATORS = [
  ['=', 'igual a'], ['!=', 'diferente de'], ['>', 'maior que'], ['>=', 'maior ou igual'], ['<', 'menor que'], ['<=', 'menor ou igual'],
];
const ARITHMETIC = [['+', 'soma (ou junta textos com Concat)'], ['-', 'subtração'], ['*', 'multiplicação'], ['/', 'divisão']];
const LOGIC = [['AND', 'e: as duas condições'], ['OR', 'ou: pelo menos uma'], ['NOT', 'não: inverte a condição']];
const NO_COLUMNS = [{ label: 'Execute o fluxo para ver as colunas', icon: 'info', disabled: true, onSelect: () => {} }];

const keepFocus = (e) => e.preventDefault(); // clicar no assistente não tira o foco do campo
const functions = () => store.catalog?.formula_functions || [];

/** Botão que abre um menu logo abaixo dele. `items()` monta a lista na hora do clique. */
function menuButton({ cls = '', title, iconName, label, items }) {
  return h('button', {
    type: 'button', class: ['fx-tool', cls], title, onmousedown: keepFocus,
    onclick: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      showMenu(r.left, r.bottom + 4, items());
    },
  }, icon(iconName, 13), label, icon('chevron-down', 12));
}

export const SCOPE_LABEL = { system: 'do sistema', shared: 'compartilhada', flow: 'do fluxo', conflict: 'do fluxo' };

/** As do sistema primeiro, depois as do fluxo e as compartilhadas em ordem de nome. */
export const sortedConstants = () => [...knownConstants().values()]
  .sort((a, b) => (b.scope === 'system') - (a.scope === 'system') || a.name.localeCompare(b.name));

function constantItems(insert) {
  const list = sortedConstants();
  return [
    ...list.map((c) => ({
      label: `[#${c.name}]`, icon: 'hash', shortcut: `${showValue(c)} · ${SCOPE_LABEL[c.scope]}`,
      onSelect: () => insert(`[#${c.name}]`),
    })),
    ...(list.length ? ['separator'] : []),
    { label: 'Nova constante do fluxo…', icon: 'plus', onSelect: () => openFlowConstants({ create: true }) },
  ];
}

/** `insert(texto, { spaced })` escreve no cursor; `|` no texto marca onde o cursor fica. */
export function formulaToolbar({ columns, insert, rowRefs = false, onExpand = null }) {
  const columnItems = (prefix, iconName) => {
    const cols = columns();
    return cols.length
      ? cols.map((c) => ({ label: c.name, icon: iconName, shortcut: typeLabel(c.type), onSelect: () => insert(prefix ? `[${prefix}:${c.name}]` : `[${c.name}]`) }))
      : NO_COLUMNS;
  };
  const fnButton = h('button', {
    type: 'button', class: 'fx-tool', title: 'Inserir função (com descrição e exemplo)', onmousedown: keepFocus,
    onclick: (e) => openCatalog(e.currentTarget, (doc) => insert(`${doc.name}(|)`)),
  }, h('i', { class: 'fx-fx' }, 'ƒx'), 'Função', icon('chevron-down', 12));
  // Multi-Row: as referências a outras linhas, sem precisar decorar a escrita.
  const rowButton = (label, title, prefix, iconName) => menuButton({ cls: 'fx-row-ref', title, iconName, label, items: () => columnItems(prefix, iconName) });
  const chip = ([op, title], cls) => h('button', {
    type: 'button', class: ['fx-chip', cls], title, onmousedown: keepFocus, onclick: () => insert(op, { spaced: true }),
  }, op);
  // Coluna, Função e Constante sempre visíveis; operadores aparecem enquanto o campo está em foco.
  return h('div', { class: 'fx-toolbar' },
    menuButton({ title: 'Inserir coluna da entrada', iconName: 'columns', label: 'Coluna', items: () => columnItems('', 'columns') }),
    fnButton,
    menuButton({ cls: 'fx-cst-tool', title: 'Inserir constante: um valor com nome, como o mês de referência', iconName: 'hash', label: 'Constante', items: () => constantItems(insert) }),
    rowRefs ? rowButton('Linha anterior', 'Inserir o valor da linha de cima: [Row-1:coluna]', 'Row-1', 'arrow-up') : null,
    rowRefs ? rowButton('Linha seguinte', 'Inserir o valor da linha de baixo: [Row+1:coluna]', 'Row+1', 'arrow-down') : null,
    onExpand ? h('button', { type: 'button', class: 'fx-tool fx-expand', title: 'Editar numa janela larga, com colunas e funções ao lado', onclick: onExpand },
      icon('maximize', 13), 'Abrir grande') : null,
    h('span', { class: 'fx-hint-key' }, h('kbd', {}, 'Ctrl'), '+', h('kbd', {}, 'Espaço'), ' sugere'),
    h('div', { class: 'fx-ops' },
      OPERATORS.map((o) => chip(o, 'fx-cmp')),
      h('span', { class: 'fx-sep' }),
      LOGIC.map((o) => chip(o, 'fx-logic')),
      h('span', { class: 'fx-sep' }),
      ARITHMETIC.map((o) => chip(o, 'fx-op')),
      h('span', { class: 'fx-sep' }),
      h('button', {
        type: 'button', class: 'fx-chip fx-kw', title: 'Condição: IF condição THEN valor ELSE outro ENDIF',
        onmousedown: keepFocus, onclick: () => insert('IF | THEN  ELSE  ENDIF', { spaced: false }),
      }, 'IF…ENDIF')));
}

// ------------------------------------------------------------------ catálogo de funções

let catalogEl = null;

function catalogGroups(query, onPick, close) {
  const groups = new Map();
  for (const f of functions()) {
    if (query && !`${f.name} ${f.description} ${f.category}`.toLowerCase().includes(query)) continue;
    if (!groups.has(f.category)) groups.set(f.category, []);
    groups.get(f.category).push(f);
  }
  if (!groups.size) return [h('p', { class: 'muted pad' }, 'Nenhuma função encontrada.')];
  return [...groups].map(([cat, fns]) => h('section', {},
    h('div', { class: 'fx-cat-title' }, cat),
    fns.map((f) => h('button', {
      type: 'button', class: 'fx-cat-item', title: `Exemplo: ${f.example}`,
      onclick: () => { close(); onPick(f); },
    }, h('span', { class: 'fx-cat-sig' }, h('b', { class: 'fx-fn' }, f.name), f.signature.slice(f.name.length)),
    h('span', { class: 'fx-cat-desc' }, f.description), h('code', { class: 'fx-cat-ex' }, f.example)))));
}

function openCatalog(anchor, onPick) {
  catalogEl?.remove();
  const search = h('input', { class: 'input input-sm input-search', type: 'search', placeholder: 'Buscar função…', 'aria-label': 'Buscar função' });
  const list = h('div', { class: 'fx-cat-list' });
  const close = () => { catalogEl?.remove(); catalogEl = null; document.removeEventListener('pointerdown', outside, true); };
  const outside = (e) => { if (!catalogEl?.contains(e.target)) close(); };
  const draw = () => list.replaceChildren(...catalogGroups(search.value.trim().toLowerCase(), onPick, close));
  search.addEventListener('input', draw);
  search.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
  catalogEl = h('div', { class: 'fx-catalog' }, search, list);
  document.body.append(catalogEl);
  const r = anchor.getBoundingClientRect();
  const w = Math.min(420, innerWidth - 16);
  catalogEl.style.left = `${Math.max(8, Math.min(r.left, innerWidth - w - 8))}px`;
  catalogEl.style.top = `${Math.min(r.bottom + 4, innerHeight - 420)}px`;
  document.addEventListener('pointerdown', outside, true);
  draw();
  search.focus();
}
