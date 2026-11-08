// Editor de fórmula grande (spec 029, RF-2941): o mesmo editor, numa janela larga, com colunas, funções e
// constantes ao lado. O que se escreve aqui já vale no painel, então basta Concluir; Ctrl+Z desfaz.

import { showValue } from './constants.js';
import { button, h } from './dom.js';
import { formulaEditor } from './formula_editor.js';
import { SCOPE_LABEL, sortedConstants } from './formula_toolbar.js';
import { store } from './store.js';
import { typeLabel } from './types.js';
import { openDialog } from './ui.js';

const TABS = { columns: ['Colunas', 'Buscar coluna…'], functions: ['Funções', 'Buscar função…'], constants: ['Constantes', 'Buscar constante…'] };
const keepCaret = (e) => e.preventDefault(); // clicar na lista não tira o cursor da fórmula

function item({ name, right, detail, title, onPick }) {
  return h('button', { type: 'button', class: 'fx-large-item', title, onmousedown: keepCaret, onclick: onPick },
    h('span', { class: 'fx-large-line' }, h('span', { class: 'ellipsis' }, name), right ? h('small', {}, right) : null),
    detail ? h('span', { class: 'fx-large-detail' }, detail) : null);
}

function functionRows(query, insert) {
  const groups = new Map();
  for (const f of store.catalog?.formula_functions || []) {
    if (query && !`${f.name} ${f.description} ${f.category}`.toLowerCase().includes(query)) continue;
    if (!groups.has(f.category)) groups.set(f.category, []);
    groups.get(f.category).push(f);
  }
  return [...groups].flatMap(([category, list]) => [
    h('div', { class: 'fx-large-group' }, category),
    ...list.map((f) => item({ name: f.signature, detail: f.description, title: `Exemplo: ${f.example}`, onPick: () => insert(`${f.name}(|)`) })),
  ]);
}

function rowsFor(tab, query, columns, insert) {
  if (tab === 'functions') return functionRows(query, insert);
  if (tab === 'constants') {
    return sortedConstants().filter((c) => c.name.toLowerCase().includes(query)).map((c) => item({
      name: `[#${c.name}]`, right: `${showValue(c)} · ${SCOPE_LABEL[c.scope]}`, title: c.description, onPick: () => insert(`[#${c.name}]`),
    }));
  }
  return columns.filter((c) => c.name.toLowerCase().includes(query)).map((c) => item({
    name: `[${c.name}]`, right: typeLabel(c.type), onPick: () => insert(`[${c.name}]`),
  }));
}

function sidePane(columns, insert) {
  let tab = 'columns';
  const search = h('input', { class: 'input input-sm input-search', type: 'search', 'aria-label': 'Buscar' });
  const list = h('div', { class: 'fx-large-list' });
  const buttons = Object.entries(TABS).map(([id, [label]]) => h('button', {
    type: 'button', class: 'tab', role: 'tab', dataset: { tab: id },
    onclick: () => { tab = id; search.value = ''; draw(); },
  }, label));
  function draw() {
    for (const b of buttons) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    search.placeholder = TABS[tab][1];
    const rows = rowsFor(tab, search.value.trim().toLowerCase(), columns, insert);
    const nothing = tab === 'columns' && !columns.length ? 'Execute o fluxo para ver as colunas.' : 'Nada encontrado.';
    list.replaceChildren(...(rows.length ? rows : [h('p', { class: 'muted pad' }, nothing)]));
  }
  search.addEventListener('input', draw);
  draw();
  return h('aside', { class: 'fx-large-side' }, h('div', { class: 'tabs full', role: 'tablist' }, buttons), h('div', { class: 'fx-large-search' }, search), list);
}

/** `makeValidate(el)` devolve a função que confere a fórmula e escreve o resultado em `el`. */
export function openLargeFormula({ subtitle, value, columns, rowRefs, makeValidate, onChange }) {
  const status = h('div', { class: 'expr-status muted' }, ' ');
  const validate = makeValidate(status);
  const editor = formulaEditor({
    value, rows: 15, maxHeight: 460, columns: () => columns, rowRefs,
    onChange: (text) => { onChange(text); validate(text); },
  });
  const dialog = openDialog({
    title: subtitle ? `Editar fórmula · ${subtitle}` : 'Editar fórmula',
    size: 'formula',
    body: h('div', { class: 'fx-large' },
      h('div', { class: 'fx-large-main' }, h('span', { class: 'field-label' }, 'Expressão'), editor, status),
      sidePane(columns, editor.fx.insert)),
    actions: [
      h('p', { class: 'fx-large-note' }, 'Clique num item para inserir. O que você escreve aqui já vale no painel.'),
      button({ label: 'Concluir', variant: 'primary', onClick: () => dialog.close() }),
    ],
  });
  if (value) validate(value);
  requestAnimationFrame(() => editor.fx.focus());
}
