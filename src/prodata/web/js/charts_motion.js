// Gráficos feitos para acompanhar o tempo (spec 030): corrida de barras, bolhas e Sankey.
// A cor segue o nome da categoria: ela não muda quando a categoria troca de posição.

import { axisTitles, esc, margins, options, paint, svg, tone, truncate, yGrid, yScale } from './chart_kit.js';
import { fmt } from './dom.js';

const SLOTS = 8;
const CHAR = 6.6;

function slotOf(label) {
  let hash = 0;
  for (const ch of String(label)) hash = (hash * 31 + ch.codePointAt(0)) % 9973;
  return hash % SLOTS;
}

/** `_rank` (fração) vem da transição; sem ela, a posição é a ordem da lista. */
export function raceChart(series, width, height, opts) {
  const o = options(opts);
  const rows = series.map((s, i) => ({ ...s, rank: s._rank ?? i }));
  const count = Math.max(1, Math.round(Math.max(...rows.map((s) => s.rank))) + 1, series.filter((s) => s._rank === undefined).length);
  const row = Math.min(52, Math.max(16, (height - 8) / count));
  const barH = Math.max(10, row - 8);
  const labelW = Math.min(170, Math.max(40, ...rows.map((s) => String(s.label).length * CHAR)));
  const space = Math.max(20, width - labelW - 76);
  const max = o.yMax ?? Math.max(1e-9, ...rows.map((s) => s.value));
  const bars = rows.map((s) => {
    const y = 4 + s.rank * row;
    const w = (Math.min(max, Math.max(0, s.value)) / max) * space;
    const color = paint(o, slotOf(s.label), s.label, true);
    return [
      svg('rect', { class: 'hit', x: 0, y, width, height: row, 'data-tip': `<span>${esc(s.label)}</span><b>${esc(o.full(s.value))}</b>` }),
      svg('text', { class: 'tick', x: labelW, y: y + row / 2 + 4, 'text-anchor': 'end' }, truncate(s.label, Math.round(labelW / CHAR))),
      svg('rect', { x: labelW + 8, y: y + (row - barH) / 2, width: w, height: barH, rx: 3, ...color, class: ['race-bar', color.class].filter(Boolean).join(' ') }),
      svg('text', { class: 'value', x: labelW + 14 + w, y: y + row / 2 + 4 }, o.short(s.value)),
    ];
  });
  const svgH = Math.ceil(4 + count * row + 4);
  return svg('svg', { class: 'chart', width, height: svgH, viewBox: `0 0 ${width} ${svgH}` }, bars);
}

/** `scale` (0 a 1) faz a bolha nascer e sumir na transição. */
export function bubbleChart(w, width, height, opts) {
  const o = options(opts);
  const pts = w.points || [];
  const m = margins({ top: 14, right: 18, bottom: 28, left: 52 }, o);
  const pw = width - m.left - m.right;
  const ph = height - m.top - m.bottom;
  const xs = yScale(pts.map((p) => p.x), { yMin: null, yMax: null }, false);
  const ys = yScale(pts.map((p) => p.y), o, false);
  const x = (v) => m.left + ((v - xs.lo) / (xs.hi - xs.lo)) * pw;
  const y = (v) => m.top + ph - ((Math.min(ys.hi, Math.max(ys.lo, v)) - ys.lo) / (ys.hi - ys.lo)) * ph;
  const biggest = Math.max(1e-9, ...pts.map((p) => p.size));
  const maxR = Math.min(34, Math.max(14, Math.min(pw, ph) / 8));
  const radius = (p) => Math.max(0, Math.sqrt(Math.max(0, p.size) / biggest) * maxR * (p.scale ?? 1));
  const xTicks = [];
  for (let v = xs.lo; v <= xs.hi + 1e-9; v += xs.step) {
    xTicks.push(svg('text', { class: 'tick', x: x(v), y: height - 9 - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' }, fmt.compact(v)));
  }
  const ordered = [...pts].sort((a, b) => b.size - a.size); // as menores por cima, para dar para apontar
  const dots = ordered.map((p) => {
    const r = radius(p);
    return [
      svg('circle', {
        class: 'bubble-dot', cx: x(p.x), cy: y(p.y), r, style: `fill:${tone(o, slotOf(p.label), p.label)}`,
        'data-tip': `<span>${esc(p.label)}</span><span>${esc(w.x_value)}: <b>${fmt.number(p.x)}</b></span><span>${esc(w.y_column)}: <b>${fmt.number(p.y)}</b></span><span>${esc(w.size_column || 'linhas')}: <b>${fmt.number(p.size)}</b></span>`,
      }),
      r >= 12 ? svg('text', { class: 'bubble-label', x: x(p.x), y: y(p.y) + 4, 'text-anchor': 'middle' }, truncate(p.label, Math.floor((r * 2) / CHAR))) : null,
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    yGrid(ys.lo, ys.hi, ys.step, y, m, width, o), xTicks,
    svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: m.top + ph, y2: m.top + ph }), dots,
    axisTitles({ ...o, xTitle: o.xTitle || w.x_value, yTitle: o.yTitle || w.y_column }, m, width, height));
}

/** Soma por nome, em ordem alfabética: a ordem fica parada enquanto os valores mudam. */
function sideTotals(links, key) {
  const totals = new Map();
  for (const l of links) totals.set(l[key], (totals.get(l[key]) || 0) + l.value);
  return [...totals].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([name, total]) => ({ name, total }));
}

/** Duas colunas (de → para): com estados que vão e voltam, uma coluna só viraria um emaranhado. */
export function sankeyChart(w, width, height, opts) {
  const o = options(opts);
  const links = (w.links || []).filter((l) => l.value > 0);
  const left = sideTotals(links, 'source');
  const right = sideTotals(links, 'target');
  const names = [...left, ...right].map((n) => String(n.name).length);
  const labelW = Math.min(150, Math.max(40, ...names) * CHAR);
  const gap = 8;
  const nodeW = 12;
  const inner = height - 8;
  const longest = Math.max(left.length, right.length, 1);
  const scale = Math.max(0.001, (inner - gap * (longest - 1))) / Math.max(1e-9, sideSum(left), sideSum(right));
  const place = (list) => {
    let y = 4;
    return new Map(list.map((n) => {
      const out = [n.name, { y, h: Math.max(1, n.total * scale), used: 0 }];
      y += out[1].h + gap;
      return out;
    }));
  };
  const from = place(left);
  const to = place(right);
  const x1 = labelW + 8 + nodeW;
  const x2 = width - labelW - 8 - nodeW;
  const middle = (x1 + x2) / 2;
  const sorted = [...links].sort((a, b) => (a.source < b.source ? -1 : a.source > b.source ? 1 : a.target < b.target ? -1 : 1));
  const paths = sorted.map((l) => {
    const a = from.get(l.source);
    const b = to.get(l.target);
    const thick = Math.max(1, l.value * scale);
    const y1 = a.y + a.used + thick / 2;
    const y2 = b.y + b.used + thick / 2;
    a.used += thick;
    b.used += thick;
    return svg('path', {
      class: 'sankey-link', d: `M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}`, 'stroke-width': thick,
      style: `stroke:${tone(o, slotOf(l.source), l.source)}`,
      'data-tip': `<span>${esc(l.source)} → ${esc(l.target)}</span><b>${esc(o.full(l.value))}</b>`,
    });
  });
  const blocks = (list, spots, x, anchor, textX) => list.map((n) => {
    const spot = spots.get(n.name);
    return [
      svg('rect', { class: 'sankey-node', x, y: spot.y, width: nodeW, height: spot.h, rx: 2, style: `fill:${tone(o, slotOf(n.name), n.name)}` }),
      svg('text', { class: 'tick', x: textX, y: spot.y + spot.h / 2 + 4, 'text-anchor': anchor }, truncate(n.name, Math.floor(labelW / CHAR))),
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` }, paths,
    blocks(left, from, labelW + 8, 'end', labelW + 2), blocks(right, to, x2, 'start', x2 + nodeW + 6));
}

function sideSum(list) {
  return list.reduce((acc, n) => acc + n.total, 0);
}
