// Formulários gerados a partir de `config_fields` (ver prodata.nodes.base.describe_fields).
//
// renderFields(fields, values, onChange, ctx)
//   onChange(path, value) – path é uma lista de chaves a partir da raiz da configuração.
//   ctx: { columns(port) → [{name,type}], format, sheets, datasets, errorField, validate(expr, port) }

import { api } from './api.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { formulaEditor } from './formula_editor.js';
import { QUERY_PREFIX } from './store.js';

const TYPE_LABEL = { Int64: '123', Float64: '1.2', String: 'abc', Boolean: 'v/f', Date: 'data' };

function visible(field, values, ctx, fields) {
  // Fonte que não é arquivo (consulta de banco): opções de leitura de arquivo não se aplicam.
  if (ctx.fileOptions === false && field.group) return false;
  if (!field.show_if) return true;
  return Object.entries(field.show_if).every(([key, allowed]) => {
    const current = key === '$format' ? ctx.format : values?.[key] ?? fields.find((f) => f.name === key)?.default;
    return allowed.includes(current);
  });
}

export function renderFields(fields, values, onChange, ctx = {}) {
  const root = h('div', { class: 'form' });
  const groups = new Map();
  for (const field of fields) {
    if (field.widget === 'hidden' || !visible(field, values, ctx, fields)) continue;
    const group = field.group || '';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(field);
  }
  // Campos sem grupo primeiro; "Avançado" sempre por último.
  const rank = (g) => (g === '' ? 0 : g === 'Avançado' ? 2 : 1);
  const ordered = [...groups].sort(([a], [b]) => rank(a) - rank(b));
  for (const [group, items] of ordered) {
    // `update`: um widget pode gravar outro campo da mesma configuração (ex.: a ordem do Select).
    const local = { ...ctx, update: (name, v) => onChange([name], v) };
    const rows = items.map((f) => fieldRow(f, values?.[f.name] ?? f.default, (v, sub = []) => onChange([f.name, ...sub], v), local, values));
    if (!group) {
      root.append(...rows);
    } else {
      root.append(h('details', { class: 'form-section', open: group !== 'Avançado' },
        h('summary', {}, icon('chevron-right', 14), group), ...rows));
    }
  }
  return root;
}

function fieldRow(field, value, set, ctx, values) {
  const widget = WIDGETS[field.widget] || WIDGETS.text;
  const id = `f_${field.name}_${Math.random().toString(36).slice(2, 6)}`;
  const control = widget(field, value, set, ctx, id, values);
  if (field.widget === 'toggle') {
    return h('div', { class: ['field', 'field-toggle', ctx.errorField === field.name && 'has-error'] },
      control, field.help ? h('p', { class: 'field-help' }, field.help) : null);
  }
  return h('div', { class: ['field', ctx.errorField === field.name && 'has-error'] },
    h('label', { class: 'field-label', for: id }, field.title),
    control,
    field.help ? h('p', { class: 'field-help' }, field.help) : null);
}

// ------------------------------------------------------------------ widgets simples

function text(field, value, set, _ctx, id) {
  return h('input', {
    id, class: 'input', value: value ?? '', placeholder: field.placeholder || '',
    oninput: (e) => set(e.target.value),
  });
}

function textarea(field, value, set, _ctx, id) {
  return h('textarea', { id, class: 'input', rows: 3, oninput: (e) => set(e.target.value) }, value ?? '');
}

function number(field, value, set, _ctx, id) {
  return h('input', {
    id, class: 'input', type: 'number', value: value ?? 0, step: field.step ?? 'any',
    min: field.min, max: field.max,
    onchange: (e) => set(e.target.value === '' ? field.default : Number(e.target.value)),
  });
}

function toggle(field, value, set, _ctx, id) {
  return h('label', { class: 'switch', for: id },
    h('input', { id, type: 'checkbox', checked: Boolean(value), onchange: (e) => set(e.target.checked) }),
    h('span', { class: 'switch-track' }), h('span', {}, field.title));
}

function select(field, value, set, _ctx, id) {
  return h('select', { id, class: 'input', onchange: (e) => set(coerce(field, e.target.value)) },
    field.options.map((o) => h('option', { value: o.value, selected: o.value === value }, o.label)));
}

function coerce(field, raw) {
  const opt = field.options.find((o) => String(o.value) === raw);
  return opt ? opt.value : raw;
}

// ------------------------------------------------------------------ colunas

function columnOptions(cols, value, emptyLabel) {
  const names = cols.map((c) => c.name);
  const options = [h('option', { value: '' }, emptyLabel)];
  for (const c of cols) {
    options.push(h('option', { value: c.name, selected: c.name === value }, `${c.name}  ·  ${TYPE_LABEL[c.type] || c.type}`));
  }
  if (value && !names.includes(value)) {
    options.push(h('option', { value, selected: true }, `${value}  (não encontrada)`));
  }
  return options;
}

function column(field, value, set, ctx, id) {
  const cols = ctx.columns?.(field.port) || [];
  if (!cols.length) {
    return h('div', { class: 'stack-xs' },
      h('input', { id, class: 'input mono', value: value ?? '', placeholder: 'nome_da_coluna', oninput: (e) => set(e.target.value) }),
      h('p', { class: 'field-help' }, 'Execute o fluxo para escolher a coluna em uma lista.'));
  }
  return h('select', { id, class: ['input', value && !cols.some((c) => c.name === value) && 'invalid'], onchange: (e) => set(e.target.value) },
    columnOptions(cols, value, 'Escolha uma coluna…'));
}

function columns(field, value, set, ctx, id) {
  const selected = Array.isArray(value) ? value : [];
  const cols = ctx.columns?.(field.port) || [];
  const chips = h('div', { class: 'chips' }, selected.map((name) => h('span', {
    class: ['chip', cols.length && !cols.some((c) => c.name === name) && 'invalid'],
  }, name, h('button', {
    type: 'button', class: 'chip-x', 'aria-label': `Remover ${name}`,
    onclick: () => set(selected.filter((x) => x !== name)),
  }, icon('x', 12)))));
  const remaining = cols.filter((c) => !selected.includes(c.name));
  const adder = cols.length
    ? h('select', {
      id, class: 'input',
      onchange: (e) => e.target.value && set([...selected, e.target.value]),
    }, columnOptions(remaining, '', selected.length ? '+ Adicionar coluna' : 'Escolha colunas…'))
    : h('input', {
      id, class: 'input mono', placeholder: 'Digite e pressione Enter',
      onkeydown: (e) => {
        if (e.key === 'Enter' && e.target.value.trim()) set([...selected, e.target.value.trim()]);
      },
    });
  const extra = cols.length && remaining.length
    ? button({ label: 'Todas', size: 'sm', variant: 'ghost', onClick: () => set(cols.map((c) => c.name)) })
    : null;
  return h('div', { class: 'stack-xs' }, selected.length ? chips : null, h('div', { class: 'row' }, adder, extra));
}

function tags(field, value, set, ctx, id) {
  return columns(field, value, set, { ...ctx, columns: () => [] }, id);
}

// ------------------------------------------------------------------ editores de código

function insertAtCursor(area, token) {
  const { selectionStart: s, selectionEnd: e, value } = area;
  area.value = value.slice(0, s) + token + value.slice(e);
  area.selectionStart = area.selectionEnd = s + token.length;
  area.focus();
  area.dispatchEvent(new Event('input'));
}

function columnInserter(area, cols, wrap) {
  if (!cols.length) return null;
  return h('select', {
    class: 'input input-sm', 'aria-label': 'Inserir coluna',
    onchange: (e) => {
      if (e.target.value) insertAtCursor(area, wrap(e.target.value));
      e.target.value = '';
    },
  }, h('option', { value: '' }, 'Inserir coluna…'), cols.map((c) => h('option', { value: c.name }, c.name)));
}

function expression(field, value, set, ctx, id) {
  const status = h('div', { class: 'expr-status muted' }, ' ');
  const cols = ctx.columns?.(field.port) || [];
  const validate = debounce(async (expr) => {
    if (!expr.trim()) {
      status.className = 'expr-status muted';
      status.textContent = ' ';
      return;
    }
    try {
      const res = await api.validateFormula(expr, cols.map(({ name, type }) => ({ name, type })));
      status.className = `expr-status ${res.valid ? 'ok' : 'err'}`;
      status.replaceChildren(icon(res.valid ? 'check' : 'alert', 13), res.valid ? 'Expressão válida' : res.error);
    } catch {
      status.textContent = '';
    }
  }, 250);
  // Editor com cores, autocompletar e assistente (spec 010).
  const editor = formulaEditor({
    id, value: value ?? '', rows: 3, placeholder: field.placeholder || '[coluna] * 2  ·  Ctrl+Espaço sugere',
    columns: () => cols,
    onChange: (text) => { set(text); validate(text); },
  });
  if (value) validate(value);
  return h('div', { class: 'stack-xs' }, editor, status);
}

function sql(field, value, set, ctx, id) {
  const cols = ctx.columns?.('in') || [];
  const area = h('textarea', { id, class: 'input code', rows: 8, spellcheck: false, oninput: (e) => set(e.target.value) }, value ?? '');
  return h('div', { class: 'stack-xs' }, area,
    h('div', { class: 'row space-between' },
      h('span', { class: 'field-help' }, 'Tabelas: input_1, input_2'),
      columnInserter(area, cols, (c) => `"${c}"`)));
}

function template(field, value, set, ctx, id) {
  const cols = ctx.columns?.() || [];
  const area = h('textarea', { id, class: 'input', rows: 4, oninput: (e) => set(e.target.value) }, value ?? '');
  return h('div', { class: 'stack-xs' }, area, h('div', { class: 'row end' }, columnInserter(area, cols, (c) => `{{${c}}}`)));
}

// ------------------------------------------------------------------ arquivos

function dataset(field, value, set, ctx, id) {
  const files = ctx.datasets || [];
  const queries = ctx.queries || [];
  const known = files.some((d) => d.name === value) || queries.some((q) => `${QUERY_PREFIX}${q.id}` === value);
  return h('div', { class: 'row' },
    h('select', { id, class: ['input', value && !known && 'invalid'], onchange: (e) => set(e.target.value) },
      h('option', { value: '' }, files.length || queries.length ? 'Escolha uma fonte…' : 'Nenhuma fonte na aba Dados'),
      files.length ? h('optgroup', { label: 'Arquivos' },
        files.map((d) => h('option', { value: d.name, selected: d.name === value }, d.name))) : null,
      queries.length ? h('optgroup', { label: 'Consultas de banco' },
        queries.map((q) => h('option', { value: `${QUERY_PREFIX}${q.id}`, selected: `${QUERY_PREFIX}${q.id}` === value }, q.name))) : null,
      value && !known ? h('option', { value, selected: true }, `${value} (não encontrado)`) : null),
    ctx.onPreview ? button({ icon: ctx.isQuery ? 'edit' : 'eye', title: ctx.isQuery ? 'Editar consulta e ver prévia' : 'Pré-visualizar e ajustar leitura', disabled: !known, onClick: ctx.onPreview }) : null,
    ctx.onNewQuery ? button({ icon: 'plus', title: 'Nova consulta de banco', onClick: ctx.onNewQuery }) : null);
}

function folder(field, value, set, ctx, id) {
  const input = h('input', {
    id, class: 'input mono', value: value ?? '', placeholder: 'Pasta padrão de exportações', spellcheck: false,
    oninput: (e) => set(e.target.value),
  });
  return h('div', { class: 'row' }, input,
    ctx.chooseFolder ? button({
      icon: 'directory', title: 'Escolher pasta…',
      onClick: async () => {
        const chosen = await ctx.chooseFolder(input.value);
        if (chosen) { input.value = chosen; set(chosen); }
      },
    }) : null,
    value ? button({ icon: 'x', title: 'Voltar para a pasta padrão', onClick: () => { input.value = ''; set(''); } }) : null);
}

function sheet(field, value, set, ctx, id) {
  const sheets = ctx.sheets || [];
  if (!sheets.length) return text(field, value, set, ctx, id);
  return h('select', { id, class: 'input', onchange: (e) => set(e.target.value) },
    h('option', { value: '' }, `Primeira aba (${sheets[0]})`),
    sheets.map((s) => h('option', { value: s, selected: s === value }, s)));
}

// ------------------------------------------------------------------ bancos de dados (spec 005)

function connectionField(field, value, set, ctx, id) {
  const items = ctx.connections || [];
  const known = items.some((c) => c.id === value);
  return h('div', { class: 'row' },
    h('select', { id, class: ['input', value && !known && 'invalid'], onchange: (e) => set(e.target.value) },
      h('option', { value: '' }, items.length ? 'Escolha uma conexão…' : 'Nenhuma conexão cadastrada'),
      items.map((c) => h('option', { value: c.id, selected: c.id === value }, c.name)),
      value && !known ? h('option', { value, selected: true }, `${value} (não encontrada)`) : null),
    button({ icon: 'plus', title: 'Nova conexão', onClick: ctx.onNewConnection }),
    button({ icon: 'eye', title: 'Explorar tabelas e pré-visualizar', disabled: !known, onClick: ctx.onExplore }));
}

function dbTable(field, value, set, ctx, id) {
  const tables = ctx.tables;
  if (!Array.isArray(tables) || !tables.length) {
    const help = tables?.error ? h('p', { class: 'field-help text-error' }, icon('alert', 12), tables.error)
      : h('p', { class: 'field-help' }, ctx.connectionChosen ? 'Carregando tabelas…' : 'Escolha a conexão primeiro.');
    return h('div', { class: 'stack-xs' },
      h('input', { id, class: 'input mono', value: value ?? '', placeholder: 'esquema.tabela', oninput: (e) => set(e.target.value) }), help);
  }
  const bySchema = new Map();
  for (const t of tables) {
    if (!bySchema.has(t.schema)) bySchema.set(t.schema, []);
    bySchema.get(t.schema).push(t);
  }
  return h('select', { id, class: ['input', value && !tables.some((t) => t.qualified === value) && 'invalid'], onchange: (e) => set(e.target.value) },
    h('option', { value: '' }, `Escolha entre ${tables.length} tabelas…`),
    [...bySchema].map(([schema, items]) => h('optgroup', { label: schema },
      items.map((t) => h('option', { value: t.qualified, selected: t.qualified === value }, `${t.name}${t.type === 'view' ? '  (view)' : ''}`)))),
    value && !tables.some((t) => t.qualified === value) ? h('option', { value, selected: true }, `${value} (não encontrada)`) : null);
}

function dbQuery(field, value, set, ctx, id) {
  const area = h('textarea', {
    id, class: 'input code', rows: 7, spellcheck: false, placeholder: 'SELECT * FROM vendas WHERE ...',
    oninput: (e) => set(e.target.value),
  }, value ?? '');
  return h('div', { class: 'stack-xs' }, area,
    h('div', { class: 'row space-between' },
      h('span', { class: 'field-help' }, icon('lock', 12), ' Somente SELECT/WITH'),
      button({ icon: 'play', label: 'Pré-visualizar', size: 'sm', disabled: !ctx.connectionChosen, onClick: () => ctx.onExplore?.({ query: area.value }) })));
}

// ------------------------------------------------------------------ lista de itens

function list(field, value, set, ctx) {
  const items = Array.isArray(value) ? value : [];
  const update = (next) => set(next);
  const wrap = h('div', { class: 'list-field' });
  items.forEach((item, i) => {
    const body = renderFields(field.item_fields, item, (path, v) => set(v, [i, ...path]), ctx);
    body.classList.add('list-item-fields');
    wrap.append(h('div', { class: 'list-item' },
      h('div', { class: 'list-item-head' },
        h('span', { class: 'list-item-index' }, `${i + 1}`),
        h('div', { class: 'row gap-0' },
          button({ icon: 'arrow-up', title: 'Mover para cima', size: 'sm', variant: 'ghost', disabled: i === 0,
            onClick: () => { const n = [...items]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; update(n); } }),
          button({ icon: 'arrow-down', title: 'Mover para baixo', size: 'sm', variant: 'ghost', disabled: i === items.length - 1,
            onClick: () => { const n = [...items]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; update(n); } }),
          button({ icon: 'trash', title: 'Remover', size: 'sm', variant: 'ghost',
            onClick: () => update(items.filter((_, j) => j !== i)) }))),
      body));
  });
  wrap.append(button({ icon: 'plus', label: 'Adicionar', size: 'sm', onClick: () => update([...items, structuredClone(field.item_default)]) }));
  return wrap;
}

// ------------------------------------------------------------------ Select: tabela de colunas

/**
 * Colunas que saem no J do Join (spec 019), na mesma regra do motor: esquerda, depois direita com o prefixo
 * nas repetidas; "Só da esquerda" tira as chaves da direita e "Só da direita" tira as da esquerda (e a da
 * direita volta ao nome original).
 */
function joinColumns(ctx, values) {
  const left = ctx.columns?.('L') || [];
  const right = ctx.columns?.('R') || [];
  if (!left.length || !right.length) return [];
  const prefix = values?.right_prefix ?? 'r_';
  const leftNames = new Set(left.map((c) => c.name));
  const rename = (name) => (leftNames.has(name) ? `${prefix}${name}` : name);
  const keys = (values?.keys || []).filter((k) => k.left && k.right);
  const leftKeys = new Set(keys.map((k) => k.left));
  const rightKeys = new Set(keys.map((k) => rename(k.right)));
  const mode = values?.keys_mode || 'both';
  let out = [
    ...left.map((c) => ({ ...c, side: 'L' })),
    ...right.map((c) => ({ ...c, name: rename(c.name), side: 'R' })),
  ];
  if (mode === 'left') out = out.filter((c) => !(c.side === 'R' && rightKeys.has(c.name)));
  if (mode === 'right') {
    out = out.filter((c) => !(c.side === 'L' && leftKeys.has(c.name)));
    const taken = new Set(out.map((c) => c.name));
    for (const k of keys) {
      const r = rename(k.right);
      if (r !== k.right && !taken.has(k.right)) out = out.map((c) => (c.side === 'R' && c.name === r ? { ...c, name: k.right } : c));
    }
  }
  return out;
}

const CASTS = [['', 'Manter'], ['Int64', 'Inteiro'], ['Float64', 'Decimal'], ['String', 'Texto'], ['Boolean', 'Booleano'], ['Date', 'Data']];

function selectColumns(field, value, set, ctx, _id, values) {
  // Ordem escolhida arrastando as linhas (spec 018); colunas novas da entrada vão para o fim.
  const order = values?.order || [];
  const rank = (name) => { const i = order.indexOf(name); return i < 0 ? order.length : i; };
  const fromJoin = field.source === 'join';
  const input = fromJoin ? joinColumns(ctx, values) : ctx.columns?.() || [];
  const cols = input.map((c, i) => ({ c, i })).sort((a, b) => rank(a.c.name) - rank(b.c.name) || a.i - b.i).map(({ c }) => c);
  const reorder = (from, to) => {
    if (from === to || to < 0 || to >= cols.length) return;
    const names = cols.map((c) => c.name);
    const [moved] = names.splice(from, 1);
    names.splice(to, 0, moved);
    ctx.update?.('order', names);
  };
  if (!cols.length) {
    return h('p', { class: 'field-help' }, fromJoin
      ? 'Execute o fluxo até as entradas [L] e [R] para listar as colunas do J.'
      : 'Execute o fluxo até o nó anterior para listar as colunas de entrada.');
  }
  const rules = new Map((value || []).map((r) => [r.name, r]));
  const current = (name) => ({ name, keep: true, rename: '', cast: '', ...rules.get(name) });
  // Só guarda o que difere do padrão (manter, sem renomear, sem converter).
  const store = (rows) => set(rows.filter((r) => !r.keep || r.rename || r.cast));
  const save = (name, patch) => store(cols.map((c) => (c.name === name ? { ...current(c.name), ...patch } : current(c.name))));
  const setAll = (keep) => store(cols.map((c) => ({ ...current(c.name), keep: typeof keep === 'function' ? keep(current(c.name)) : keep })));

  const kept = cols.filter((c) => current(c.name).keep).length;
  const master = h('input', {
    type: 'checkbox', checked: kept === cols.length, 'aria-label': 'Marcar ou desmarcar todas as colunas',
    title: kept === cols.length ? 'Desmarcar todas' : 'Selecionar todas',
    onchange: () => setAll(kept !== cols.length),
  });
  master.indeterminate = kept > 0 && kept < cols.length;
  return h('div', { class: 'stack-xs' },
    // Selecionar tudo / desmarcar tudo / inverter (spec 013).
    h('div', { class: 'select-tools' },
      h('span', { class: 'select-count' }, `${kept} de ${cols.length} colunas mantidas`),
      h('div', { class: 'row gap-0' },
        button({ label: 'Todas', size: 'sm', variant: 'ghost', title: 'Selecionar todas as colunas', disabled: kept === cols.length, onClick: () => setAll(true) }),
        button({ label: 'Nenhuma', size: 'sm', variant: 'ghost', title: 'Desmarcar todas as colunas', disabled: kept === 0, onClick: () => setAll(false) }),
        button({ label: 'Inverter', size: 'sm', variant: 'ghost', title: 'Inverter a seleção', onClick: () => setAll((r) => !r.keep) }),
        order.length ? button({ label: 'Ordem original', size: 'sm', variant: 'ghost', title: 'Voltar à ordem das colunas de entrada', onClick: () => ctx.update?.('order', []) }) : null)),
    h('p', { class: 'field-help' }, 'Arraste pela alça ⠿ (ou use as setas nela) para mudar a ordem das colunas.'),
    h('div', { class: 'select-table' },
      h('div', { class: 'select-row head' }, h('span', {}), master, h('span', {}, 'Coluna'), h('span', {}, 'Renomear'), h('span', {}, 'Tipo')),
      cols.map((c, index) => {
        const r = current(c.name);
        const row = h('div', {
          class: ['select-row', !r.keep && 'dropped'], draggable: 'true',
          ondragstart: (e) => { e.dataTransfer.setData('text/x-prodata-col', String(index)); e.dataTransfer.effectAllowed = 'move'; },
          ondragover: (e) => { if (e.dataTransfer.types.includes('text/x-prodata-col')) { e.preventDefault(); row.classList.add('drop-over'); } },
          ondragleave: () => row.classList.remove('drop-over'),
          ondrop: (e) => { e.preventDefault(); row.classList.remove('drop-over'); reorder(Number(e.dataTransfer.getData('text/x-prodata-col')), index); },
        },
        h('button', {
          type: 'button', class: 'select-grip', title: 'Arraste para mudar a ordem · ↑ ↓ movem', 'aria-label': `Mover ${c.name}`,
          onkeydown: (e) => {
            if (e.key === 'ArrowUp') { e.preventDefault(); reorder(index, index - 1); }
            if (e.key === 'ArrowDown') { e.preventDefault(); reorder(index, index + 1); }
          },
        }, icon('grip', 12)),
        h('input', { type: 'checkbox', checked: r.keep, 'aria-label': `Manter ${c.name}`, onchange: (e) => save(c.name, { keep: e.target.checked }) }),
        h('span', { class: 'mono ellipsis', title: `${c.name} (${c.type})${c.side ? ` · vem de [${c.side}]` : ''}` },
          c.side ? h('b', { class: `side-tag side-${c.side}` }, c.side) : null, c.name, h('small', { class: 'type-tag' }, TYPE_LABEL[c.type] || c.type)),
        h('input', { class: 'input input-sm mono', value: r.rename, placeholder: '—', onchange: (e) => save(c.name, { rename: e.target.value.trim() }) }),
        h('select', { class: 'input input-sm', onchange: (e) => save(c.name, { cast: e.target.value }) },
          CASTS.map(([v, l]) => h('option', { value: v, selected: v === r.cast }, l))));
        return row;
      })));
}

// ------------------------------------------------------------------ Text Input: grade editável

function grid(field, value, set) {
  const table = structuredClone(value || { columns: ['coluna_1'], rows: [['']] });
  const commit = () => set(structuredClone(table));
  const rerender = () => wrap.replaceChildren(build());

  const onPaste = (e, r0, c0) => {
    const textData = e.clipboardData.getData('text/plain');
    if (!textData.includes('\t') && !textData.includes('\n')) return;
    e.preventDefault();
    const lines = textData.replace(/\r/g, '').replace(/\n$/, '').split('\n').map((l) => l.split('\t'));
    lines.forEach((cells, dr) => {
      const r = r0 + dr;
      while (table.rows.length <= r) table.rows.push(table.columns.map(() => ''));
      cells.forEach((v, dc) => {
        const c = c0 + dc;
        while (table.columns.length <= c) {
          table.columns.push(`coluna_${table.columns.length + 1}`);
          table.rows.forEach((row) => row.push(''));
        }
        table.rows[r][c] = v;
      });
    });
    commit();
    rerender();
  };

  const build = () => h('div', { class: 'grid-editor' },
    h('table', {},
      h('thead', {}, h('tr', {},
        h('th', { class: 'grid-corner' }),
        table.columns.map((name, c) => h('th', {},
          h('div', { class: 'row gap-0' },
            h('input', { class: 'grid-cell head', value: name, 'aria-label': `Nome da coluna ${c + 1}`,
              onchange: (e) => { table.columns[c] = e.target.value; commit(); } }),
            table.columns.length > 1 ? h('button', { type: 'button', class: 'grid-x', title: 'Remover coluna',
              onclick: () => { table.columns.splice(c, 1); table.rows.forEach((r) => r.splice(c, 1)); commit(); rerender(); } }, icon('x', 11)) : null))),
        h('th', {}, h('button', { type: 'button', class: 'grid-add', title: 'Adicionar coluna',
          onclick: () => { table.columns.push(`coluna_${table.columns.length + 1}`); table.rows.forEach((r) => r.push('')); commit(); rerender(); } }, icon('plus', 13))))),
      h('tbody', {}, table.rows.map((row, r) => h('tr', {},
        h('td', { class: 'grid-rownum' }, h('span', {}, r + 1),
          h('button', { type: 'button', class: 'grid-x', title: 'Remover linha',
            onclick: () => { table.rows.splice(r, 1); commit(); rerender(); } }, icon('x', 11))),
        table.columns.map((_, c) => h('td', {}, h('input', {
          class: 'grid-cell', value: row[c] ?? '', 'aria-label': `Linha ${r + 1}, ${table.columns[c]}`,
          onchange: (e) => { table.rows[r][c] = e.target.value; commit(); },
          onpaste: (e) => onPaste(e, r, c),
        }))),
        h('td', {}))))),
    h('div', { class: 'row space-between' },
      button({ icon: 'plus', label: 'Linha', size: 'sm', onClick: () => { table.rows.push(table.columns.map(() => '')); commit(); rerender(); } }),
      h('span', { class: 'field-help' }, 'Dica: cole células copiadas do Excel.')));

  const wrap = h('div', {}, build());
  return wrap;
}

function object(field, value, set, _ctx, id) {
  return h('textarea', {
    id, class: 'input code', rows: 6,
    onchange: (e) => { try { set(JSON.parse(e.target.value)); } catch { /* mantém valor anterior */ } },
  }, JSON.stringify(value ?? field.default, null, 2));
}

// ------------------------------------------------------------------ formato do dashboard (spec 014)

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/** Contraste WCAG entre duas cores #rrggbb. */
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Aviso quando a cor some no fundo: 3:1 para marcas, 4,5:1 para texto (ctx.contrastFor). */
function contrastNote(value, check) {
  if (!value || !check?.against) return null;
  const ratio = contrast(value, check.against);
  if (ratio >= check.min) return null;
  return h('p', { class: 'field-warn' }, icon('alert', 13),
    ` Contraste baixo com ${check.what} (${ratio.toFixed(1).replace('.', ',')}:1). ${check.min > 3 ? 'O texto pode ficar ilegível.' : 'Mantenha rótulos ou a tabela para não depender só da cor.'}`);
}

function color(field, value, set, ctx, id) {
  const note = h('div', {}, contrastNote(value, ctx.contrastFor?.(field.name)));
  const input = h('input', {
    id, type: 'color', class: 'color-input', value: value || ctx.defaultColor?.(field.name) || '#888888',
    oninput: (e) => { set(e.target.value); note.replaceChildren(contrastNote(e.target.value, ctx.contrastFor?.(field.name)) || ''); },
  });
  return h('div', { class: 'stack-xs' },
    h('div', { class: 'color-row' }, input,
      h('span', { class: 'mono muted' }, value || 'padrão do tema'),
      value ? button({ label: 'Padrão', size: 'sm', variant: 'ghost', onClick: () => set('') }) : null),
    note);
}

function optionalNumber(field, value, set, _ctx, id) {
  return h('input', {
    id, class: 'input', type: 'number', step: 'any', value: value ?? '', placeholder: 'Automático',
    onchange: (e) => set(e.target.value === '' ? null : Number(e.target.value)),
  });
}

/** Cor por categoria: uma linha por valor do eixo X do visual (ctx.categories). */
function categoryColors(field, value, set, ctx) {
  const map = { ...(value || {}) };
  const cats = ctx.categories || [];
  if (!cats.length) return h('p', { class: 'field-help' }, 'Execute o fluxo para listar as categorias.');
  return h('div', { class: 'category-colors' }, cats.map((cat, i) => {
    const note = h('div', {}, contrastNote(map[cat], ctx.contrastFor?.(field.name)));
    return h('div', { class: 'category-color' },
      h('input', {
        type: 'color', class: 'color-input', value: map[cat] || ctx.defaultColor?.(field.name, i) || '#888888', 'aria-label': `Cor de ${cat}`,
        oninput: (e) => { map[cat] = e.target.value; set({ ...map }); note.replaceChildren(contrastNote(e.target.value, ctx.contrastFor?.(field.name)) || ''); },
      }),
      h('span', { class: 'ellipsis', title: cat }, cat),
      map[cat] ? button({ icon: 'x', title: 'Voltar à cor da paleta', size: 'sm', variant: 'ghost', onClick: () => { delete map[cat]; set({ ...map }); } }) : null,
      note);
  }));
}

// ------------------------------------------------------------------ valores de uma coluna (spec 015)

/**
 * Marca valores que existem numa coluna da entrada (ex.: grupos do Venn), até `max_items`.
 * A coluna vem do campo `field.source`; sem execução, cai para digitação livre.
 */
function columnValues(field, value, set, ctx, id, values) {
  const selected = Array.isArray(value) ? [...value] : [];
  const max = field.max_items || Infinity;
  const column = values?.[field.source];
  if (!column) return h('p', { class: 'field-help' }, 'Escolha antes a coluna do grupo.');
  const wrap = h('div', { class: 'value-picker' }, h('p', { class: 'field-help' }, 'Carregando os valores…'));
  const toggle = (v) => set(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  const full = () => selected.length >= max;
  const chip = (v) => {
    const on = selected.includes(v.value);
    return h('button', {
      type: 'button', class: ['value-chip', on && 'on'], 'aria-pressed': String(on), disabled: !on && full(),
      title: !on && full() ? `Máximo de ${max}: desmarque um para trocar` : null,
      onclick: () => toggle(v.value),
    }, icon(on ? 'check' : 'plus', 12), h('span', { class: 'ellipsis' }, v.value), h('span', { class: 'muted' }, fmt.int(v.count)));
  };
  const draw = (data) => {
    const known = new Set(data.values.map((v) => v.value));
    // Coluna com muitos valores (spec 017): provavelmente um identificador. Mostra só os mais frequentes
    // e busca no servidor, para não despejar milhares de opções na tela.
    const many = data.distinct > MANY_VALUES;
    const list = h('div', { class: 'value-list', role: 'group', 'aria-label': field.title });
    const note = h('p', { class: 'field-help' });
    const fill = (rows, label) => { list.replaceChildren(...rows.map(chip)); note.textContent = label; };
    const top = () => fill(data.values.slice(0, many ? TOP_WHEN_MANY : 200),
      many ? `Mostrando os ${TOP_WHEN_MANY} mais frequentes. Busque para achar outros.` : '');
    top();
    const search = (needle) => {
      if (!needle) { top(); return; }
      if (!many && !data.truncated) {
        const found = data.values.filter((v) => v.value.toLowerCase().includes(needle.toLowerCase()));
        fill(found.slice(0, 200), found.length ? '' : 'Nenhum valor encontrado.');
        return;
      }
      ctx.values(column, null, needle)
        .then((res) => fill(res.values.slice(0, 50), res.matches > 50
          ? `${fmt.int(res.matches)} valores encontrados; mostrando 50. Refine a busca.`
          : res.matches ? '' : 'Nenhum valor encontrado.'))
        .catch(() => fill([], 'Não foi possível buscar agora.'));
    };
    const lost = selected.filter((v) => !known.has(v) && !many);
    wrap.replaceChildren(...[ // replaceChildren() nativo escreveria "null" para os itens ausentes
      h('div', { class: 'value-head' },
        h('span', {}, `${selected.length} de ${max === Infinity ? data.distinct : max} marcados`),
        h('span', { class: 'muted' }, `${fmt.int(data.distinct)} valores em [${column}]`)),
      many ? h('p', { class: 'field-warn' }, icon('alert', 13),
        ` [${column}] tem ${fmt.int(data.distinct)} valores diferentes: parece um identificador, não um grupo. `
        + 'O Venn compara 2 ou 3 grupos — prefira uma coluna com poucos valores (produto, segmento). Se for esta mesmo, busque o valor.') : null,
      selected.length ? h('div', { class: 'chips' }, selected.map((v) => h('span', { class: ['chip', lost.includes(v) && 'invalid'], title: lost.includes(v) ? 'Não existe mais nesta coluna' : null },
        lost.includes(v) ? `${v} (não encontrado)` : v,
        h('button', { type: 'button', class: 'chip-x', 'aria-label': `Remover ${v}`, onclick: () => toggle(v) }, icon('x', 12))))) : null,
      many || data.values.length > 12
        ? h('input', { id, class: 'input', type: 'search', placeholder: 'Buscar valor…', oninput: debounce((e) => search(e.target.value.trim()), 250) })
        : null,
      list,
      note,
    ].filter(Boolean));
  };
  const manual = () => wrap.replaceChildren(
    h('p', { class: 'field-help' }, 'Execute o fluxo para escolher os valores numa lista. Enquanto isso, digite:'),
    tags(field, value, set, ctx, id));
  (ctx.values ? ctx.values(column) : Promise.reject()).then(draw).catch(manual);
  return wrap;
}

const MANY_VALUES = 50;
const TOP_WHEN_MANY = 15;

/** Nomes exibidos: uma linha por série, categoria ou conjunto do visual (ctx.categories). Vazio = original. */
function renameLabels(field, value, set, ctx) {
  const map = { ...(value || {}) };
  const cats = ctx.categories || [];
  if (!cats.length) return h('p', { class: 'field-help' }, 'Execute o fluxo para listar os nomes.');
  return h('div', { class: 'rename-labels' }, cats.slice(0, 60).map((cat) => h('label', { class: 'rename-row' },
    h('span', { class: 'ellipsis muted', title: cat }, cat),
    h('input', {
      class: 'input', value: map[cat] || '', placeholder: cat, 'aria-label': `Nome exibido para ${cat}`,
      oninput: (e) => {
        if (e.target.value.trim()) map[cat] = e.target.value; else delete map[cat];
        set({ ...map });
      },
    }))));
}

const WIDGETS = {
  color, optional_number: optionalNumber, category_colors: categoryColors, column_values: columnValues,
  rename_labels: renameLabels,
  text, textarea, number, toggle, select, column, columns, tags, expression, sql, template, dataset, sheet, folder,
  list, select_columns: selectColumns, grid, object, connection: connectionField, db_table: dbTable, db_query: dbQuery,
};
