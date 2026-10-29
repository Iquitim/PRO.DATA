// Editor de expressões (spec 010): cores de sintaxe, autocompletar, dica de assinatura e
// assistente de inserção. Um <textarea> transparente fica sobre um <pre> colorido com a mesma
// fonte, padding e quebra de linha, então o cursor e a seleção continuam nativos.

import { h } from './dom.js';
import { icon } from './icons.js';
import { store } from './store.js';
import { showMenu } from './ui.js';

// ------------------------------------------------------------------ tokens

const TOKEN = /(\[[^\]\n]*\]?)|('(?:[^']|'')*'?|"(?:[^"]|"")*"?)|(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(==|!=|<>|>=|<=|[=<>+\-*/%!])|([(),])|(\s+)|([\s\S])/g;
const COMPARISON = new Set(['==', '!=', '<>', '>=', '<=', '=', '<', '>']);

const keywords = () => store.catalog?.formula_keywords || { control: [], logical: [] };
const functions = () => store.catalog?.formula_functions || [];
const functionByName = (name) => functions().find((f) => f.name.toLowerCase() === name.toLowerCase()) || null;

/** Quebra o texto em tokens { text, start, kind } (kind: col, str, num, word, op, paren, comma, space, other). */
export function tokenize(text) {
  const out = [];
  for (const m of text.matchAll(TOKEN)) {
    const [raw, col, str, num, word, op, punct, space] = m;
    let kind = 'other';
    if (col !== undefined) kind = 'col';
    else if (str !== undefined) kind = 'str';
    else if (num !== undefined) kind = 'num';
    else if (word !== undefined) kind = 'word';
    else if (op !== undefined) kind = 'op';
    else if (punct !== undefined) kind = punct === ',' ? 'comma' : 'paren';
    else if (space !== undefined) kind = 'space';
    out.push({ text: raw, start: m.index, kind });
  }
  return out;
}

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Classe de cor de cada token (com parênteses sem par e colunas inexistentes marcados). */
function classify(tokens, columns, caret) {
  const control = new Set(keywords().control.map((k) => k.toUpperCase()));
  const logical = new Set(keywords().logical.map((k) => k.toUpperCase()));
  const known = new Set(columns.map((c) => c.name));
  const classes = tokens.map(() => '');
  const stack = [];
  tokens.forEach((t, i) => {
    switch (t.kind) {
      case 'col': {
        const closed = t.text.endsWith(']') && t.text.length > 1;
        const name = t.text.slice(1, closed ? -1 : undefined);
        classes[i] = `fx-col${!closed || (known.size && !known.has(name)) ? ' fx-bad' : ''}`;
        break;
      }
      case 'str': classes[i] = 'fx-str'; break;
      case 'num': classes[i] = 'fx-num'; break;
      case 'word': {
        const upper = t.text.toUpperCase();
        const next = tokens.slice(i + 1).find((x) => x.kind !== 'space');
        if (control.has(upper)) classes[i] = 'fx-kw';
        else if (['TRUE', 'FALSE', 'NULL'].includes(upper)) classes[i] = 'fx-const';
        else if (logical.has(upper)) classes[i] = 'fx-logic';
        else if (next?.text === '(') classes[i] = functionByName(t.text) ? 'fx-fn' : 'fx-fn fx-fn-other';
        else classes[i] = 'fx-word';
        break;
      }
      case 'op':
        classes[i] = t.text === '!' ? 'fx-logic' : COMPARISON.has(t.text) ? 'fx-cmp' : 'fx-op';
        break;
      case 'paren':
        if (t.text === '(') {
          classes[i] = `fx-paren fx-d${stack.length % 3}`;
          stack.push(i);
        } else if (stack.length) {
          const open = stack.pop();
          classes[i] = `fx-paren fx-d${stack.length % 3}`;
          // Par de parênteses junto ao cursor fica destacado.
          const touches = (k) => caret === tokens[k].start || caret === tokens[k].start + 1;
          if (touches(open) || touches(i)) {
            classes[open] += ' fx-match';
            classes[i] += ' fx-match';
          }
        } else {
          classes[i] = 'fx-paren fx-bad';
        }
        break;
      case 'comma': classes[i] = 'fx-op'; break;
      default: break;
    }
  });
  for (const i of stack) classes[i] = 'fx-paren fx-bad'; // abertos sem fechamento
  return classes;
}

export function highlight(text, columns = [], caret = -1) {
  const tokens = tokenize(text);
  const classes = classify(tokens, columns, caret);
  const html = tokens.map((t, i) => (classes[i] ? `<span class="${classes[i]}">${escapeHtml(t.text)}</span>` : escapeHtml(t.text))).join('');
  return `${html}\n`; // a linha final vazia mantém a altura igual à do textarea
}

// ------------------------------------------------------------------ contexto do cursor

/** O que está sendo digitado no cursor: coluna `[pre`, palavra `Rou`, ou nada (dentro de texto). */
function contextAt(text, caret) {
  const tokens = tokenize(text.slice(0, caret));
  const last = tokens.at(-1);
  if (!last) return { kind: 'none', prefix: '', start: caret };
  if (last.kind === 'str' && !/^(['"]).*\1$/s.test(last.text)) return { kind: 'string' };
  if (last.kind === 'col' && !last.text.endsWith(']')) return { kind: 'column', prefix: last.text.slice(1), start: last.start };
  if (last.kind === 'word') return { kind: 'word', prefix: last.text, start: last.start };
  return { kind: 'none', prefix: '', start: caret };
}

/** Função cujos parênteses envolvem o cursor e o índice do argumento atual. */
function callAt(text, caret) {
  const stack = [];
  let prevWord = null;
  for (const t of tokenize(text.slice(0, caret))) {
    if (t.kind === 'space') continue;
    if (t.text === '(') stack.push({ name: prevWord, arg: 0 });
    else if (t.text === ')') stack.pop();
    else if (t.kind === 'comma' && stack.length) stack.at(-1).arg += 1;
    prevWord = t.kind === 'word' ? t.text : null;
  }
  const top = stack.at(-1);
  return top?.name ? { doc: functionByName(top.name), arg: top.arg } : null;
}

function suggestions(ctx, columns) {
  const q = (ctx.prefix || '').toLowerCase();
  const rank = (name) => (name.toLowerCase().startsWith(q) ? 0 : 1);
  if (ctx.kind === 'column') {
    return columns.filter((c) => c.name.toLowerCase().includes(q))
      .sort((a, b) => rank(a.name) - rank(b.name))
      .slice(0, 10).map((c) => ({ kind: 'column', label: c.name, detail: c.type, insert: `[${c.name}]` }));
  }
  if (ctx.kind !== 'word' && ctx.kind !== 'all') return [];
  const fns = functions().filter((f) => f.name.toLowerCase().includes(q))
    .map((f) => ({ kind: 'function', label: f.name, detail: f.signature, doc: f, insert: f.name }));
  const kws = [...keywords().control, ...keywords().logical].filter((k) => k.toLowerCase().startsWith(q))
    .map((k) => ({ kind: 'keyword', label: k, detail: keywords().control.includes(k) ? 'controle' : 'lógico', insert: k }));
  const cols = ctx.kind === 'all' ? columns.map((c) => ({ kind: 'column', label: c.name, detail: c.type, insert: `[${c.name}]` })) : [];
  return [...kws, ...fns, ...cols].sort((a, b) => rank(a.label) - rank(b.label)).slice(0, 10);
}

// ------------------------------------------------------------------ editor

const OPERATORS = [
  ['=', 'igual a'], ['!=', 'diferente de'], ['>', 'maior que'], ['>=', 'maior ou igual'], ['<', 'menor que'], ['<=', 'menor ou igual'],
];
const ARITHMETIC = [['+', 'soma (ou junta textos com Concat)'], ['-', 'subtração'], ['*', 'multiplicação'], ['/', 'divisão']];
const LOGIC = [['AND', 'e: as duas condições'], ['OR', 'ou: pelo menos uma'], ['NOT', 'não: inverte a condição']];
const KIND_LABEL = { function: 'ƒ', column: '[ ]', keyword: 'if', logical: '&' };

/**
 * Cria o editor. `columns()` devolve as colunas da entrada; `onChange(texto)` a cada alteração.
 * Devolve o elemento raiz.
 */
export function formulaEditor({ id, value = '', placeholder = '', rows = 3, columns = () => [], onChange = () => {} }) {
  const hl = h('pre', { class: 'fx-hl', 'aria-hidden': 'true' });
  const mirror = h('div', { class: 'fx-hl fx-mirror', 'aria-hidden': 'true' });
  const area = h('textarea', {
    id, class: 'fx-input', rows, spellcheck: false, autocomplete: 'off', placeholder,
    'aria-autocomplete': 'list', 'aria-label': 'Expressão',
  }, value);
  const box = h('div', { class: 'fx-box' }, hl, mirror, area);
  const hint = h('div', { class: 'fx-hint', hidden: true });
  // O popup só fica no documento enquanto está visível (vive no body para não ser cortado pelo painel).
  const popup = h('div', { class: 'fx-suggest', role: 'listbox' });
  let items = [];
  let active = 0;
  let ctx = null;

  // O campo cresce com o conteúdo (até ~12 linhas), sem esconder o fim da fórmula.
  const fit = () => {
    area.style.height = 'auto';
    area.style.height = `${Math.min(area.scrollHeight + 2, 300)}px`;
  };

  const paint = () => {
    hl.innerHTML = highlight(area.value, columns(), area.selectionStart === area.selectionEnd ? area.selectionStart : -1);
    hl.scrollTop = area.scrollTop;
  };

  const caretPoint = () => {
    const pos = area.selectionStart;
    mirror.innerHTML = `${escapeHtml(area.value.slice(0, pos))}<span class="fx-caret">​</span>`;
    const mark = mirror.querySelector('.fx-caret');
    const r = area.getBoundingClientRect();
    return { x: r.left + mark.offsetLeft, y: r.top + mark.offsetTop - area.scrollTop + mark.offsetHeight + 4 };
  };

  const closePopup = () => { popup.remove(); items = []; };

  const drawPopup = () => {
    if (!items.length) { closePopup(); return; }
    popup.replaceChildren(
      ...items.map((it, i) => h('div', {
        class: ['fx-item', i === active && 'active', `fx-item-${it.kind}`], role: 'option', 'aria-selected': String(i === active),
        onmousedown: (e) => { e.preventDefault(); accept(it); },
        onmousemove: () => { if (active !== i) { active = i; drawPopup(); } },
      }, h('span', { class: 'fx-item-kind' }, KIND_LABEL[it.kind]), h('span', { class: 'fx-item-label' }, it.label),
      h('span', { class: 'fx-item-detail' }, it.detail || ''))),
      items[active]?.doc ? h('div', { class: 'fx-item-doc' }, items[active].doc.description,
        h('code', {}, items[active].doc.example)) : null,
    );
    if (!popup.isConnected) {
      document.body.append(popup);
      const p = caretPoint();
      const w = Math.min(380, innerWidth - 16);
      popup.style.left = `${Math.max(8, Math.min(p.x, innerWidth - w - 8))}px`;
      popup.style.top = `${p.y + 260 > innerHeight ? p.y - 280 : p.y}px`;
    }
    popup.querySelector('.fx-item.active')?.scrollIntoView({ block: 'nearest' });
  };

  const suggest = (force = false) => {
    const caret = area.selectionStart;
    ctx = contextAt(area.value, caret);
    if (force && ctx.kind === 'none') ctx = { kind: 'all', prefix: '', start: caret };
    if (force && ctx.kind === 'word') ctx = { ...ctx, kind: 'word' };
    items = suggestions(ctx, columns());
    // Palavra-chave já completa (ex.: THEN): não atrapalha o Enter.
    if (!force && items.length && ctx.kind === 'word' && items[0].kind === 'keyword'
      && items[0].label.toLowerCase() === ctx.prefix.toLowerCase()) items = [];
    active = 0;
    drawPopup();
  };

  const replaceRange = (start, end, text, caretOffset = text.length) => {
    area.setRangeText(text, start, end, 'end');
    area.selectionStart = area.selectionEnd = start + caretOffset;
    area.focus();
    changed();
  };

  function accept(it) {
    const caret = area.selectionStart;
    const start = ctx?.start ?? caret;
    let end = caret;
    const after = area.value.slice(caret);
    if (it.kind === 'column') {
      const rest = after.match(/^[^\]\n]*\]/);
      if (rest) end += rest[0].length;
      replaceRange(start, end, it.insert);
    } else if (it.kind === 'function') {
      end += (after.match(/^\w*/) || [''])[0].length;
      if (area.value.slice(end).startsWith('(')) replaceRange(start, end + 1, `${it.insert}(`);
      else replaceRange(start, end, `${it.insert}()`, it.insert.length + 1);
    } else {
      end += (after.match(/^\w*/) || [''])[0].length;
      replaceRange(start, end, `${it.insert} `);
    }
    closePopup();
    updateHint();
  }

  const updateHint = () => {
    const call = callAt(area.value, area.selectionStart);
    if (!call?.doc) { hint.hidden = true; return; }
    const sig = call.doc.signature;
    const open = sig.indexOf('(');
    const args = sig.slice(open + 1, sig.lastIndexOf(')')).split(', ').filter(Boolean);
    const current = Math.min(call.arg, args.length - 1);
    hint.hidden = false;
    hint.replaceChildren(
      h('span', { class: 'fx-hint-sig' }, h('b', { class: 'fx-fn' }, sig.slice(0, open)), '(',
        args.map((a, i) => [i ? ', ' : '', i === current ? h('span', { class: 'fx-hint-arg' }, a) : a]), ')'),
      h('span', { class: 'fx-hint-desc' }, call.doc.description));
  };

  function changed() {
    fit();
    paint();
    onChange(area.value);
  }

  /** Insere no cursor (assistente): `text` com `|` marcando onde o cursor deve ficar. */
  const insert = (text, { spaced = false } = {}) => {
    const s = area.selectionStart;
    const e = area.selectionEnd;
    let piece = text;
    if (spaced) {
      const before = area.value.slice(0, s);
      piece = `${before && !/\s$/.test(before) ? ' ' : ''}${text} `;
    }
    const mark = piece.indexOf('|');
    const clean = piece.replace('|', '');
    replaceRange(s, e, clean, mark >= 0 ? mark : clean.length);
    updateHint();
  };

  area.addEventListener('input', () => { changed(); suggest(); updateHint(); });
  area.addEventListener('scroll', () => { hl.scrollTop = area.scrollTop; });
  area.addEventListener('blur', () => setTimeout(closePopup, 120));
  area.addEventListener('click', () => { paint(); updateHint(); closePopup(); });
  area.addEventListener('keyup', (e) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key) || (!popup.isConnected && ['ArrowUp', 'ArrowDown'].includes(e.key))) {
      paint();
      updateHint();
    }
  });
  area.addEventListener('keydown', (e) => {
    if (e.key === ' ' && e.ctrlKey) { e.preventDefault(); suggest(true); return; }
    if (!popup.isConnected) return;
    if (e.key === 'ArrowDown') { active = (active + 1) % items.length; drawPopup(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; drawPopup(); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); accept(items[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePopup(); }
  });

  // ---- assistente de inserção
  const keepFocus = (e) => e.preventDefault(); // clicar no assistente não tira o foco do campo
  const columnButton = h('button', {
    type: 'button', class: 'fx-tool', title: 'Inserir coluna da entrada', onmousedown: keepFocus,
    onclick: (e) => {
      const cols = columns();
      const r = e.currentTarget.getBoundingClientRect();
      showMenu(r.left, r.bottom + 4, cols.length
        ? cols.map((c) => ({ label: `${c.name}`, icon: 'columns', shortcut: c.type, onSelect: () => insert(`[${c.name}]`) }))
        : [{ label: 'Execute o fluxo para ver as colunas', icon: 'info', disabled: true, onSelect: () => {} }]);
    },
  }, icon('columns', 13), 'Coluna', icon('chevron-down', 12));
  const fnButton = h('button', {
    type: 'button', class: 'fx-tool', title: 'Inserir função (com descrição e exemplo)', onmousedown: keepFocus,
    onclick: (e) => openCatalog(e.currentTarget, (doc) => insert(`${doc.name}(|)`)),
  }, h('i', { class: 'fx-fx' }, 'ƒx'), 'Função', icon('chevron-down', 12));
  const chip = ([op, title], opts) => h('button', {
    type: 'button', class: ['fx-chip', opts.cls], title, onmousedown: (e) => e.preventDefault(),
    onclick: () => insert(op, { spaced: true }),
  }, op);
  // Coluna e Função sempre visíveis; operadores aparecem enquanto o campo está em foco.
  const toolbar = h('div', { class: 'fx-toolbar' },
    columnButton, fnButton,
    h('span', { class: 'fx-hint-key' }, h('kbd', {}, 'Ctrl'), '+', h('kbd', {}, 'Espaço'), ' sugere'),
    h('div', { class: 'fx-ops' },
      OPERATORS.map((o) => chip(o, { cls: 'fx-cmp' })),
      h('span', { class: 'fx-sep' }),
      LOGIC.map((o) => chip(o, { cls: 'fx-logic' })),
      h('span', { class: 'fx-sep' }),
      ARITHMETIC.map((o) => chip(o, { cls: 'fx-op' })),
      h('span', { class: 'fx-sep' }),
      h('button', {
      type: 'button', class: 'fx-chip fx-kw', title: 'Condição: IF condição THEN valor ELSE outro ENDIF',
      onmousedown: (e) => e.preventDefault(), onclick: () => insert('IF | THEN  ELSE  ENDIF', { spaced: false }),
    }, 'IF…ENDIF')));

  const root = h('div', { class: 'fx' }, box, hint, toolbar);
  paint();
  requestAnimationFrame(fit); // altura certa só depois de entrar no documento
  return root;
}

// ------------------------------------------------------------------ catálogo de funções

let catalogEl = null;

function openCatalog(anchor, onPick) {
  catalogEl?.remove();
  const search = h('input', { class: 'input input-sm input-search', type: 'search', placeholder: 'Buscar função…', 'aria-label': 'Buscar função' });
  const list = h('div', { class: 'fx-cat-list' });
  const close = () => { catalogEl?.remove(); catalogEl = null; document.removeEventListener('pointerdown', outside, true); };
  const outside = (e) => { if (!catalogEl?.contains(e.target)) close(); };
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    const groups = new Map();
    for (const f of functions()) {
      if (q && !`${f.name} ${f.description} ${f.category}`.toLowerCase().includes(q)) continue;
      if (!groups.has(f.category)) groups.set(f.category, []);
      groups.get(f.category).push(f);
    }
    list.replaceChildren(...(groups.size ? [...groups].map(([cat, fns]) => h('section', {},
      h('div', { class: 'fx-cat-title' }, cat),
      fns.map((f) => h('button', {
        type: 'button', class: 'fx-cat-item', title: `Exemplo: ${f.example}`,
        onclick: () => { close(); onPick(f); },
      }, h('span', { class: 'fx-cat-sig' }, h('b', { class: 'fx-fn' }, f.name), f.signature.slice(f.name.length)),
      h('span', { class: 'fx-cat-desc' }, f.description), h('code', { class: 'fx-cat-ex' }, f.example)))))
      : [h('p', { class: 'muted pad' }, 'Nenhuma função encontrada.')]));
  };
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
