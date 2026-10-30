// Esquemas visuais no Configurar (spec 015, RF-1504): mostram o que Cross Tab, Transpose e Join fazem com a
// tabela, usando as colunas configuradas e, depois de executar, uma amostra da entrada. Só ilustram: o
// resultado de verdade é o do motor. Passar o mouse num valor destaca para onde ele vai.

import { api } from './api.js';
import { fmt, h } from './dom.js';
import { icon } from './icons.js';
import { inspect, nodeResult, on, store } from './store.js';

const SAMPLE_ROWS = 200;
const samples = new Map(); // "nó|saída" → Promise<linhas>
on('execution', () => samples.clear());

/** Primeiras linhas que chegam na porta (ou null se o fluxo ainda não rodou até ali). */
function sampleOf(nodeId, port = null) {
  const edge = store.workflow.edges.find((e) => e.target === nodeId && (!port || e.targetHandle === port));
  if (!edge || !nodeResult(edge.source)?.anchors?.[edge.sourceHandle]) return Promise.resolve(null);
  const key = `${edge.source}|${edge.sourceHandle}`;
  if (!samples.has(key)) {
    samples.set(key, api.results(store.workflow.id, edge.source, edge.sourceHandle, { limit: SAMPLE_ROWS })
      .then((page) => page.rows)
      .catch(() => { samples.delete(key); return null; }));
  }
  return samples.get(key);
}

const show = (v) => (v === null || v === undefined ? '—' : typeof v === 'number' ? fmt.number(v) : String(v));
const distinct = (rows, col, n) => [...new Set(rows.map((r) => show(r[col])))].slice(0, n);

/** Tabela pequena; cada célula pode ter `link` (destaque compartilhado) e `kind` (cor). */
function mini(title, head, rows) {
  const cell = (tag, c) => h(tag, {
    class: [c.kind && `x-${c.kind}`], dataset: c.link ? { link: c.link } : undefined, title: c.title || null,
  }, c.text);
  return h('div', { class: 'x-table' }, h('div', { class: 'x-title' }, title),
    h('table', {}, h('thead', {}, h('tr', {}, head.map((c) => cell('th', c)))),
      h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => cell('td', c)))))));
}

const arrow = (label) => h('div', { class: 'x-arrow' }, icon('chevron-right', 18), h('span', {}, label));

/** Destaque ao passar o mouse: todas as células com o mesmo data-link acendem juntas. */
function linkHover(root) {
  const lit = (link, on_) => root.querySelectorAll(`[data-link="${CSS.escape(link)}"]`).forEach((el) => el.classList.toggle('x-lit', on_));
  root.addEventListener('mouseover', (e) => { const el = e.target.closest('[data-link]'); if (el) lit(el.dataset.link, true); });
  root.addEventListener('mouseout', (e) => { const el = e.target.closest('[data-link]'); if (el) lit(el.dataset.link, false); });
  return root;
}

const AGG = {
  sum: (v) => v.reduce((a, b) => a + (Number(b) || 0), 0),
  mean: (v) => v.reduce((a, b) => a + (Number(b) || 0), 0) / v.length,
  count: (v) => v.length,
  min: (v) => Math.min(...v.map(Number)),
  max: (v) => Math.max(...v.map(Number)),
  first: (v) => v[0],
  concat: (v) => v.join(', '),
};
const AGG_TEXT = { sum: 'somados', mean: 'pela média', count: 'contados', min: 'pelo mínimo', max: 'pelo máximo', first: 'pelo primeiro', concat: 'juntando os textos' };

// ------------------------------------------------------------------ Cross Tab

function crosstab(cfg, rows) {
  const g = cfg.group_by?.[0] || null;
  const hd = cfg.header || 'mês';
  const val = cfg.value || 'valor';
  let data = rows;
  if (!data || !cfg.header || !cfg.value) {
    // Exemplo fixo com os nomes configurados, enquanto falta configuração ou execução.
    const gn = g || 'uf';
    data = [[gn, 'SP', 'jan', 10], [gn, 'SP', 'fev', 20], [gn, 'RJ', 'jan', 5], [gn, 'SP', 'jan', 4], [gn, 'RJ', 'fev', 7]]
      .map(([k, a, b, c]) => ({ [k]: a, [hd]: b, [val]: c }));
  }
  const gKey = g || (rows ? null : 'uf');
  const groups = gKey ? distinct(data, gKey, 3) : ['(tudo)'];
  const heads = distinct(data, hd, 3);
  const used = data.filter((r) => (!gKey || groups.includes(show(r[gKey]))) && heads.includes(show(r[hd]))).slice(0, 6);
  const long = mini('Antes: uma linha por registro',
    [...(gKey ? [{ text: gKey }] : []), { text: hd, kind: 'from' }, { text: val }],
    used.map((r) => {
      const gv = gKey ? show(r[gKey]) : '(tudo)';
      return [
        ...(gKey ? [{ text: gv, link: `g:${gv}` }] : []),
        { text: show(r[hd]), link: `h:${show(r[hd])}`, kind: 'from' },
        { text: show(r[val]), link: `c:${gv}|${show(r[hd])}` },
      ];
    }));
  const agg = AGG[cfg.agg || 'sum'];
  const wide = mini('Depois: uma coluna por valor',
    [...(gKey ? [{ text: gKey }] : []), ...heads.map((x) => ({ text: x, link: `h:${x}`, kind: 'to' }))],
    groups.map((gv) => [
      ...(gKey ? [{ text: gv, link: `g:${gv}` }] : []),
      ...heads.map((x) => {
        const vals = used.filter((r) => (!gKey || show(r[gKey]) === gv) && show(r[hd]) === x).map((r) => r[val]);
        return { text: vals.length ? show(agg(vals)) : '—', link: `c:${gv}|${x}` };
      }),
    ]));
  return {
    body: [long, arrow('Cross Tab'), wide],
    caption: `Cada valor de [${hd}] vira uma coluna; os valores de [${val}] que caem na mesma célula são ${AGG_TEXT[cfg.agg || 'sum']}.`
      + (gKey ? ` Uma linha por [${gKey}].` : ' Sem "agrupar por", sai uma linha só.'),
  };
}

// ------------------------------------------------------------------ Transpose

function transpose(cfg, rows) {
  const name = cfg.name_column || 'nome';
  const value = cfg.value_column || 'valor';
  let data = rows;
  let keys = cfg.keys || [];
  let cols = cfg.columns?.length ? cfg.columns : null;
  if (!data) {
    keys = keys.length ? keys : ['uf'];
    cols = cols || ['jan', 'fev'];
    data = [{ [keys[0]]: 'SP', [cols[0]]: 10, [cols[1] || 'fev']: 20 }, { [keys[0]]: 'RJ', [cols[0]]: 5, [cols[1] || 'fev']: 7 }];
  }
  const all = Object.keys(data[0] || {});
  cols = (cols || all.filter((c) => !keys.includes(c))).slice(0, 3);
  const sample = data.slice(0, 2);
  const wide = mini('Antes: uma coluna por item',
    [...keys.map((k) => ({ text: k })), ...cols.map((c) => ({ text: c, link: `h:${c}`, kind: 'from' }))],
    sample.map((r, i) => [
      ...keys.map((k) => ({ text: show(r[k]), link: `k:${i}` })),
      ...cols.map((c) => ({ text: show(r[c]), link: `v:${i}|${c}` })),
    ]));
  const long = mini('Depois: uma linha por item',
    [...keys.map((k) => ({ text: k })), { text: name, kind: 'to' }, { text: value, kind: 'to' }],
    sample.flatMap((r, i) => cols.map((c) => [
      ...keys.map((k) => ({ text: show(r[k]), link: `k:${i}` })),
      { text: c, link: `h:${c}`, kind: 'to' },
      { text: show(r[c]), link: `v:${i}|${c}` },
    ])));
  return {
    body: [wide, arrow('Transpose'), long],
    caption: `As colunas ${cols.map((c) => `[${c}]`).join(', ')}${cols.length < (cfg.columns?.length || 0) ? '…' : ''} viram linhas: `
      + `o nome vai para [${name}] e o conteúdo para [${value}]. `
      + (keys.length ? `${keys.map((k) => `[${k}]`).join(', ')} se repete em cada linha.` : 'Escolha colunas-chave para identificar de onde veio cada linha.'),
  };
}

// ------------------------------------------------------------------ Join

function join(n, cfg, left, right) {
  const key = cfg.keys?.[0] || {};
  const lk = key.left || 'id';
  const rk = key.right || 'id';
  const res = nodeResult(n.id);
  const counts = ['L', 'J', 'R'].map((p) => res?.anchors?.[p]?.row_count);
  const parts = [
    ['L', 'Só na esquerda', 'Chaves sem par na direita'],
    ['J', 'Casaram', 'Colunas dos dois lados, lado a lado'],
    ['R', 'Só na direita', 'Chaves sem par na esquerda'],
  ];
  const bar = h('div', { class: 'x-join-bar' }, parts.map(([p, label, help], i) => h('button', {
    type: 'button', class: ['x-join-part', `x-${p}`], disabled: counts[i] === undefined,
    title: counts[i] === undefined ? 'Execute o fluxo para ver as linhas' : `Ver as linhas da saída ${p}`,
    onclick: () => inspect(n.id, p),
  }, h('b', {}, p), h('span', {}, label), h('strong', {}, counts[i] === undefined ? '—' : fmt.int(counts[i])), h('small', {}, help))));
  let lv = ['1', '2', '3'];
  let rv = ['2', '3', '4'];
  if (left && right) {
    // Na amostra, mostra 2 chaves que casam e 2 sem par de cada lado, para o exemplo fazer sentido.
    const la = distinct(left, lk, SAMPLE_ROWS);
    const ra = distinct(right, rk, SAMPLE_ROWS);
    const both = la.filter((v) => ra.includes(v));
    lv = [...both.slice(0, 2), ...la.filter((v) => !ra.includes(v)).slice(0, 2)];
    rv = [...both.slice(0, 2), ...ra.filter((v) => !la.includes(v)).slice(0, 2)];
  }
  const side = (title, col, vals, other) => mini(title, [{ text: col }], vals.map((v) => [{
    text: v, link: `k:${v}`, kind: other.includes(v) ? 'match' : 'alone',
  }]));
  return {
    body: [bar, h('div', { class: 'x-pair' }, side('Esquerda [L]', lk, lv, rv), arrow('casa pela chave'), side('Direita [R]', rk, rv, lv))],
    caption: `Linhas com o mesmo valor em [${lk}] e [${rk}] saem juntas em J. As demais saem em L ou R, para você ver o que não encontrou par.`
      + ((cfg.keys?.length || 0) > 1 ? ` Com ${cfg.keys.length} chaves, todas precisam ser iguais.` : ''),
  };
}

// ------------------------------------------------------------------ montagem

/** Bloco do esquema para a caixa; `refresh()` redesenha após mudar a configuração. */
export function explainerEl(n, spec) {
  const root = linkHover(h('section', { class: 'explainer', 'aria-label': 'Como funciona' }));
  const draw = async () => {
    const cfg = store.workflow.nodes.find((k) => k.id === n.id)?.config || n.config || {};
    let out;
    if (spec.explainer === 'join') {
      const [l, r] = await Promise.all([sampleOf(n.id, 'L'), sampleOf(n.id, 'R')]);
      out = join(n, cfg, l, r);
    } else {
      const rows = await sampleOf(n.id);
      out = (spec.explainer === 'crosstab' ? crosstab : transpose)(cfg, rows?.length ? rows : null);
      out.sample = Boolean(rows?.length);
    }
    root.replaceChildren(
      h('header', { class: 'x-head' }, icon('info', 14), h('strong', {}, 'Como funciona'),
        spec.explainer !== 'join' ? h('span', { class: 'muted' }, out.sample ? 'com uma amostra dos seus dados' : 'exemplo (execute para ver seus dados)') : null),
      h('div', { class: spec.explainer === 'join' ? 'x-stack' : 'x-row' }, out.body),
      h('p', { class: 'x-caption' }, out.caption));
  };
  root.refresh = () => draw().catch(() => {});
  root.append(h('p', { class: 'muted' }, 'Montando o esquema…'));
  root.refresh();
  return root;
}

