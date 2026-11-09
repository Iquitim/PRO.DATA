// Linha do tempo do dashboard (spec 030): cada momento é um filtro de data sobre as tabelas guardadas.
// Roda igual no programa e no HTML exportado, sem servidor e sem executar o fluxo (RF-3043, RF-3092).

import { applyFilters, computeWidget, dayText, makeTable } from './dash_compute.js';
import { filtersFor } from './dash_filters.js';
import { findHighlights } from './dash_highlights.js';

export const MAX_MOMENTS = 400;
const STEP_MS = 1100;
const MOVE_SHARE = 0.72; // o resto do passo fica parado, para dar tempo de ler
const HIGHLIGHT_ROWS = 100000;
const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

const utc = (text) => new Date(`${text}T00:00:00Z`);
const iso = (date) => date.toISOString().slice(0, 10);

function plusDays(text, days) {
  const d = utc(text);
  d.setUTCDate(d.getUTCDate() + days);
  return iso(d);
}

function startOf(text, step) {
  if (step === 'month') return `${text.slice(0, 7)}-01`;
  if (step === 'week') return plusDays(text, -((utc(text).getUTCDay() + 6) % 7));
  return text;
}

function nextStart(text, step) {
  if (step === 'day') return plusDays(text, 1);
  if (step === 'week') return plusDays(text, 7);
  const d = utc(text);
  d.setUTCMonth(d.getUTCMonth() + 1);
  return iso(d);
}

/** Tabelas do HTML/da linha do tempo: as colunas repetidas entram uma vez só nos dados. */
export function makeTables(data) {
  const out = {};
  for (const [id, node] of Object.entries(data.nodes || {})) {
    const columns = {};
    for (const [name, key] of Object.entries(node.columns)) columns[name] = data.columns[key];
    out[id] = makeTable(columns, node.types, node.rows);
  }
  return out;
}

/** Todos os momentos entre a primeira e a última data, sem pular os períodos vazios. */
export function momentsOf(tables, column, step) {
  let first = null;
  let last = null;
  for (const table of Object.values(tables)) {
    for (const v of table.columns[column] || []) {
      if (v === null || v === undefined) continue;
      const day = dayText(v);
      if (first === null || day < first) first = day;
      if (last === null || day > last) last = day;
    }
  }
  if (first === null) return { moments: [], tooMany: false };
  const moments = [];
  const end = startOf(last, step);
  for (let cur = startOf(first, step); cur <= end; cur = nextStart(cur, step)) {
    if (moments.length >= MAX_MOMENTS) return { moments: [], tooMany: true };
    moments.push(cur);
  }
  return { moments, tooMany: false };
}

export function momentLabel(moment, step) {
  if (!moment) return '';
  const [y, m, d] = moment.split('-');
  if (step === 'month') return `${MONTHS[Number(m) - 1]}/${y}`;
  return `${step === 'week' ? 'semana de ' : ''}${d}/${m}/${y}`;
}

export function momentFilter(timeline, moment) {
  const end = plusDays(nextStart(moment, timeline.step), -1);
  return { id: 'linha_do_tempo', kind: 'date', column: timeline.column, min: timeline.mode === 'period' ? moment : null, max: end };
}

/** Num momento só pode não haver período anterior: o KPI mostra o valor, sem a comparação, em vez de um erro. */
function computeMoment(node, table) {
  try {
    return computeWidget(node.tool, node.config, table);
  } catch (err) {
    if (node.tool !== 'bi.kpi_card' || node.config.compare !== 'previous') throw err;
    return computeWidget(node.tool, { ...node.config, compare: 'none', sparkline: false }, table);
  }
}

/** Os visuais de um momento. Quem não tem a coluna fica de fora: continua como está, e a página avisa. */
export function widgetsAt(data, tables, filters, timeline, moment) {
  const active = [...filters, momentFilter(timeline, moment)];
  const out = {};
  for (const [id, node] of Object.entries(data.nodes || {})) {
    if (!(timeline.column in tables[id].columns)) continue;
    const { table } = applyFilters(tables[id], filtersFor(node.config, active));
    try {
      out[id] = { ...computeMoment(node, table), node_id: id };
    } catch (err) {
      out[id] = { widget_type: 'message', title: node.title, message: err.message, node_id: id };
    }
  }
  return out;
}

// ------------------------------------------------------------------ transição (RF-3051)

const lerp = (a, b, t) => a + (b - a) * t;
export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function mixValues(a = {}, b = {}, t) {
  const out = {};
  for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) out[key] = lerp(a[key] || 0, b[key] || 0, t);
  return out;
}

function mixSeries(a, b, t, ranked) {
  const before = new Map(a.map((s, i) => [s.label, { s, i }]));
  const after = new Map(b.map((s, i) => [s.label, { s, i }]));
  const labels = [...b.map((s) => s.label), ...a.map((s) => s.label).filter((label) => !after.has(label))];
  return labels.map((label) => {
    const p = before.get(label);
    const n = after.get(label);
    const out = { ...(n?.s || p.s), value: lerp(p?.s.value || 0, n?.s.value || 0, t) };
    if (p?.s.values || n?.s.values) out.values = mixValues(p?.s.values, n?.s.values, t);
    if (ranked) out._rank = lerp(p ? p.i : b.length, n ? n.i : b.length, t);
    return out;
  });
}

function mixKeyed(a, b, t, keyOf, mix) {
  const before = new Map(a.map((v) => [keyOf(v), v]));
  const after = new Map(b.map((v) => [keyOf(v), v]));
  return [...new Set([...before.keys(), ...after.keys()])].map((key) => mix(before.get(key), after.get(key), t));
}

const mixPoint = (p, n, t) => ({ ...(n || p), scale: p && n ? 1 : p ? 1 - t : t });
const mixBubble = (p, n, t) => {
  const from = p || { ...n, size: 0 };
  const to = n || { ...p, size: 0 };
  return { ...to, x: lerp(from.x, to.x, t), y: lerp(from.y, to.y, t), size: lerp(from.size, to.size, t) };
};
const mixLink = (p, n, t) => ({ ...(n || p), value: lerp(p?.value || 0, n?.value || 0, t) });
const pointKey = (p) => `${p.x}|${p.y}|${p.s ?? ''}`;

/** Estado intermediário entre dois widgets. KPI, tabela e mensagem trocam de uma vez. */
export function mixWidgets(a, b, t) {
  if (!a || !b || t >= 1 || a.widget_type !== 'chart' || b.widget_type !== 'chart' || a.chart_type !== b.chart_type) return b;
  if (b.chart_type === 'scatter') return { ...b, points: mixKeyed(a.points || [], b.points || [], t, pointKey, mixPoint) };
  if (b.chart_type === 'bubble') return { ...b, points: mixKeyed(a.points || [], b.points || [], t, (p) => p.label, mixBubble) };
  if (b.chart_type === 'sankey') return { ...b, links: mixKeyed(a.links || [], b.links || [], t, (l) => `${l.source}→${l.target}`, mixLink) };
  return { ...b, series: mixSeries(a.series || [], b.series || [], t, b.chart_type === 'race') };
}

// ------------------------------------------------------------------ reprodução

function reduceMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Controla o momento atual. `draw(widgets)` recebe os visuais que mudaram, já com a transição;
 * `changed()` avisa a barra. `animates(nodeId)` respeita a opção de cada visual (RF-3055).
 */
export function createReplay({ data, tables, timeline, moments, getFilters, draw, changed, animates = () => true }) {
  const state = { index: moments.length - 1, playing: false, frame: 0, last: 0, phase: 0, highlights: null };
  let cache = new Map();
  const at = (i) => {
    if (!cache.has(i)) cache.set(i, widgetsAt(data, tables, getFilters(), timeline, moments[i]));
    return cache.get(i);
  };
  const paint = (from, to, t) => {
    const a = at(from);
    const b = at(to);
    const out = {};
    for (const id of Object.keys(b)) out[id] = animates(id) && t < 1 ? mixWidgets(a[id], b[id], t) : b[id];
    draw(out);
  };
  const stop = () => {
    cancelAnimationFrame(state.frame);
    state.playing = false;
    state.phase = 0;
    changed?.();
  };
  const seek = (i) => {
    const index = Math.max(0, Math.min(moments.length - 1, i));
    state.index = index;
    state.phase = 0;
    paint(index, index, 1);
    changed?.();
  };
  const tick = (time) => {
    if (!state.playing) return;
    const elapsed = state.last ? time - state.last : 0;
    state.last = time;
    state.phase += elapsed / (STEP_MS / timeline.speed);
    if (state.phase >= 1) {
      if (state.index >= moments.length - 1) { stop(); return; }
      state.index += 1;
      state.phase = 0;
      state.held = false;
      changed?.();
    }
    if (state.phase < MOVE_SHARE && !reduceMotion()) {
      paint(state.index - 1, state.index, ease(state.phase / MOVE_SHARE));
    } else if (!state.held) {
      paint(state.index, state.index, 1);
      state.held = true;
    }
    state.frame = requestAnimationFrame(tick);
  };
  const play = () => {
    if (moments.length < 2) return;
    if (state.index >= moments.length - 1) state.index = 0;
    state.playing = true;
    state.last = 0;
    state.phase = MOVE_SHARE;
    state.held = true;
    paint(state.index, state.index, 1);
    changed?.();
    state.frame = requestAnimationFrame(tick);
  };
  return {
    moments,
    timeline,
    get index() { return state.index; },
    get playing() { return state.playing; },
    get moment() { return moments[state.index]; },
    widgets: () => at(state.index),
    between: (i, t) => {
      const from = at(i);
      const to = at(Math.min(moments.length - 1, i + 1));
      return Object.fromEntries(Object.keys(to).map((id) => [id, animates(id) && t > 0 ? mixWidgets(from[id], to[id], ease(t)) : from[id]]));
    },
    still: () => Object.keys(data.nodes || {}).filter((id) => !(timeline.column in tables[id].columns)),
    play,
    pause: stop,
    toggle: () => (state.playing ? stop() : play()),
    seek,
    /** Filtros ou modo mudaram: o que foi calculado não vale mais. */
    invalidate: () => { cache = new Map(); state.highlights = null; },
    redraw: () => paint(state.index, state.index, 1),
    /** Marcas do primeiro visual que acompanha o tempo, sempre por período: acumulado só sobe. */
    highlights: () => {
      if (state.highlights) return state.highlights;
      const id = Object.keys(data.nodes || {}).find((k) => tables[k].height <= HIGHLIGHT_ROWS
        && timeline.column in tables[k].columns && ['bi.chart', 'bi.kpi_card'].includes(data.nodes[k].tool));
      if (!id || moments.length < 5) { state.highlights = { title: '', marks: [] }; return state.highlights; }
      const node = data.nodes[id];
      const byPeriod = { ...timeline, mode: 'period' };
      const values = moments.map((m) => totalOf(computeWithin(tables[id], node, [...getFilters(), momentFilter(byPeriod, m)])));
      state.highlights = { title: node.title, marks: findHighlights(values) };
      return state.highlights;
    },
    rows: (id, limit) => {
      const { table } = applyFilters(tables[id], [...getFilters(), momentFilter(timeline, moments[state.index])]);
      const names = Object.keys(table.columns);
      const rows = [];
      for (let i = 0; i < Math.min(limit, table.height); i += 1) rows.push(Object.fromEntries(names.map((n) => [n, table.columns[n][i]])));
      return { columns: names, rows, total: table.height };
    },
    snapshot: (filters, moment) => widgetsAt(data, tables, filters, timeline, moment),
  };
}

function computeWithin(table, node, active) {
  const filtered = applyFilters(table, filtersFor(node.config, active)).table;
  try {
    return computeMoment(node, filtered);
  } catch {
    return null;
  }
}

function totalOf(w) {
  if (!w) return 0;
  if (w.widget_type === 'kpi') return w.value || 0;
  if (w.links) return w.links.reduce((acc, l) => acc + l.value, 0);
  if (w.points) return w.points.length;
  return (w.series || []).reduce((acc, s) => acc + (s.value || 0), 0);
}
