// Editor de expressões (spec 010): cores de sintaxe, autocompletar, dica de assinatura e
// assistente de inserção. Um <textarea> transparente fica sobre um <pre> colorido com a mesma
// fonte, padding e quebra de linha, então o cursor e a seleção continuam nativos.

import { knownConstants } from './constants.js';
import { h } from './dom.js';
import { formulaToolbar } from './formula_toolbar.js';
import { store } from './store.js';

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
  const constants = knownConstants();
  const classes = tokens.map(() => '');
  const stack = [];
  tokens.forEach((t, i) => {
    switch (t.kind) {
      case 'col': {
        const closed = t.text.endsWith(']') && t.text.length > 1;
        const name = t.text.slice(1, closed ? -1 : undefined);
        // [#nome]: constante (spec 028), com cor própria para nunca parecer coluna.
        if (name.startsWith('#')) {
          classes[i] = `fx-cst${!closed || !constants.has(name.slice(1)) ? ' fx-bad' : ''}`;
          break;
        }
        // [Row-1:coluna] pode citar a própria coluna nova: quem confere esse caso é a validação do servidor.
        const rowRef = /^Row[+-]\d+:/i.test(name);
        classes[i] = `fx-col${!closed || (!rowRef && known.size && !known.has(name)) ? ' fx-bad' : ''}`;
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

const KIND_LABEL = { function: 'ƒ', column: '[ ]', keyword: 'if', logical: '&' };

/** Ponto na tela logo abaixo do cursor, medido num espelho invisível do texto. */
function caretPoint(ed) {
  const pos = ed.area.selectionStart;
  ed.mirror.innerHTML = `${escapeHtml(ed.area.value.slice(0, pos))}<span class="fx-caret">​</span>`;
  const mark = ed.mirror.querySelector('.fx-caret');
  const r = ed.area.getBoundingClientRect();
  return { x: r.left + mark.offsetLeft, y: r.top + mark.offsetTop - ed.area.scrollTop + mark.offsetHeight + 4 };
}

/** Lista de sugestões do autocompletar. Vive no body enquanto está aberta, para não ser cortada pelo painel. */
function suggestPopup(ed) {
  const el = h('div', { class: 'fx-suggest', role: 'listbox' });
  const pop = { el, items: [], active: 0, ctx: null };
  pop.close = () => { el.remove(); pop.items = []; };
  pop.draw = () => {
    const { items, active } = pop;
    if (!items.length) { pop.close(); return; }
    el.replaceChildren(
      ...items.map((it, i) => h('div', {
        class: ['fx-item', i === active && 'active', `fx-item-${it.kind}`], role: 'option', 'aria-selected': String(i === active),
        onmousedown: (e) => { e.preventDefault(); pop.accept(it); },
        onmousemove: () => { if (pop.active !== i) { pop.active = i; pop.draw(); } },
      }, h('span', { class: 'fx-item-kind' }, KIND_LABEL[it.kind]), h('span', { class: 'fx-item-label' }, it.label),
      h('span', { class: 'fx-item-detail' }, it.detail || ''))),
      items[active]?.doc ? h('div', { class: 'fx-item-doc' }, items[active].doc.description, h('code', {}, items[active].doc.example)) : null,
    );
    if (!el.isConnected) {
      document.body.append(el);
      const p = caretPoint(ed);
      const w = Math.min(380, innerWidth - 16);
      el.style.left = `${Math.max(8, Math.min(p.x, innerWidth - w - 8))}px`;
      el.style.top = `${p.y + 260 > innerHeight ? p.y - 280 : p.y}px`;
    }
    el.querySelector('.fx-item.active')?.scrollIntoView({ block: 'nearest' });
  };
  pop.suggest = (force = false) => {
    const caret = ed.area.selectionStart;
    let ctx = contextAt(ed.area.value, caret);
    if (force && ctx.kind === 'none') ctx = { kind: 'all', prefix: '', start: caret };
    pop.ctx = ctx;
    pop.items = suggestions(ctx, ed.columns());
    // Palavra-chave já completa (ex.: THEN): não atrapalha o Enter.
    if (!force && pop.items.length && ctx.kind === 'word' && pop.items[0].kind === 'keyword'
      && pop.items[0].label.toLowerCase() === ctx.prefix.toLowerCase()) pop.items = [];
    pop.active = 0;
    pop.draw();
  };
  pop.move = (step) => { pop.active = (pop.active + step + pop.items.length) % pop.items.length; pop.draw(); };
  pop.accept = (it) => {
    const { area } = ed;
    const caret = area.selectionStart;
    const start = pop.ctx?.start ?? caret;
    let end = caret;
    const after = area.value.slice(caret);
    if (it.kind === 'column') {
      const rest = after.match(/^[^\]\n]*\]/);
      if (rest) end += rest[0].length;
      ed.replaceRange(start, end, it.insert);
    } else if (it.kind === 'function') {
      end += (after.match(/^\w*/) || [''])[0].length;
      if (area.value.slice(end).startsWith('(')) ed.replaceRange(start, end + 1, `${it.insert}(`);
      else ed.replaceRange(start, end, `${it.insert}()`, it.insert.length + 1);
    } else {
      end += (after.match(/^\w*/) || [''])[0].length;
      ed.replaceRange(start, end, `${it.insert} `);
    }
    pop.close();
    ed.updateHint();
  };
  return pop;
}

/** Dica da função em que o cursor está, com o argumento atual destacado. */
function drawSignature(hint, area) {
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
}

function bindKeys(ed, pop) {
  const { area } = ed;
  area.addEventListener('input', () => { ed.changed(); pop.suggest(); ed.updateHint(); });
  area.addEventListener('scroll', () => { ed.hl.scrollTop = area.scrollTop; });
  area.addEventListener('blur', () => setTimeout(pop.close, 120));
  area.addEventListener('click', () => { ed.paint(); ed.updateHint(); pop.close(); });
  area.addEventListener('keyup', (e) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key) || (!pop.el.isConnected && ['ArrowUp', 'ArrowDown'].includes(e.key))) {
      ed.paint();
      ed.updateHint();
    }
  });
  area.addEventListener('keydown', (e) => {
    if (e.key === ' ' && e.ctrlKey) { e.preventDefault(); pop.suggest(true); return; }
    if (!pop.el.isConnected) return;
    if (e.key === 'ArrowDown') { pop.move(1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { pop.move(-1); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pop.accept(pop.items[pop.active]); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); pop.close(); }
  });
}

/**
 * Cria o editor. `columns()` devolve as colunas da entrada; `onChange(texto)` a cada alteração.
 * Devolve o elemento raiz.
 */
export function formulaEditor({ id, value = '', placeholder = '', rows = 3, columns = () => [], onChange = () => {}, rowRefs = false }) {
  const area = h('textarea', {
    id, class: 'fx-input', rows, spellcheck: false, autocomplete: 'off', placeholder,
    'aria-autocomplete': 'list', 'aria-label': 'Expressão',
  }, value);
  const hint = h('div', { class: 'fx-hint', hidden: true });
  const ed = { area, columns, hl: h('pre', { class: 'fx-hl', 'aria-hidden': 'true' }), mirror: h('div', { class: 'fx-hl fx-mirror', 'aria-hidden': 'true' }) };
  // O campo cresce com o conteúdo (até ~12 linhas), sem esconder o fim da fórmula.
  ed.fit = () => {
    area.style.height = 'auto';
    area.style.height = `${Math.min(area.scrollHeight + 2, 300)}px`;
  };
  ed.paint = () => {
    ed.hl.innerHTML = highlight(area.value, columns(), area.selectionStart === area.selectionEnd ? area.selectionStart : -1);
    ed.hl.scrollTop = area.scrollTop;
  };
  ed.changed = () => { ed.fit(); ed.paint(); onChange(area.value); };
  ed.updateHint = () => drawSignature(hint, area);
  ed.replaceRange = (start, end, text, caretOffset = text.length) => {
    area.setRangeText(text, start, end, 'end');
    area.selectionStart = area.selectionEnd = start + caretOffset;
    area.focus();
    ed.changed();
  };
  /** Insere no cursor (assistente): `text` com `|` marcando onde o cursor deve ficar. */
  const insert = (text, { spaced = false } = {}) => {
    const s = area.selectionStart;
    const before = area.value.slice(0, s);
    const piece = spaced ? `${before && !/\s$/.test(before) ? ' ' : ''}${text} ` : text;
    const mark = piece.indexOf('|');
    const clean = piece.replace('|', '');
    ed.replaceRange(s, area.selectionEnd, clean, mark >= 0 ? mark : clean.length);
    ed.updateHint();
  };
  bindKeys(ed, suggestPopup(ed));
  const root = h('div', { class: 'fx' }, h('div', { class: 'fx-box' }, ed.hl, ed.mirror, area), hint, formulaToolbar({ columns, insert, rowRefs }));
  ed.paint();
  requestAnimationFrame(ed.fit); // altura certa só depois de entrar no documento
  return root;
}
