// Gráficos SVG compartilhados pelo Dashboard e pelo painel de insights.
// Série única usa --series-1; a rosca usa a paleta categórica em ordem fixa (máx. 8).

import { fmt, h } from './dom.js';

const SVG = 'http://www.w3.org/2000/svg';
const MAX_SLICES = 8;

export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  el.append(...children.flat(Infinity).filter(Boolean));
  return el;
}

function niceStep(max, ticks = 4) {
  if (max <= 0) return 1;
  const raw = max / ticks;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const n = raw / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * pow;
}

function truncate(text, maxChars) {
  return text.length > maxChars ? `${text.slice(0, Math.max(1, maxChars - 1))}…` : text;
}

const tipHtml = (label, value) => `<span>${String(label).replace(/</g, '&lt;')}</span><b>${fmt.number(value)}</b>`;

/** Tooltip compartilhado por um cartão; as marcas declaram data-tip. */
export function withTooltip(card, chart) {
  const tip = h('div', { class: 'chart-tip', role: 'tooltip', hidden: true });
  chart.addEventListener('pointermove', (e) => {
    const mark = e.target.closest('[data-tip]');
    if (!mark) { tip.hidden = true; return; }
    tip.hidden = false;
    tip.innerHTML = mark.dataset.tip;
    // O cartão pode estar dentro de uma página escalada (dashboard, spec 014): converte para px do cartão.
    const r = card.getBoundingClientRect();
    const k = card.offsetWidth ? r.width / card.offsetWidth : 1;
    const x = Math.max(4, Math.min((e.clientX - r.left) / k + 12, card.offsetWidth - tip.offsetWidth - 8));
    tip.style.transform = `translate(${x}px, ${Math.max(4, (e.clientY - r.top) / k - tip.offsetHeight - 10)}px)`;
  });
  chart.addEventListener('pointerleave', () => { tip.hidden = true; });
  card.append(tip);
}

function roundedBar(x, y, w, hgt, vertical) {
  if (hgt <= 0 || w <= 0) return '';
  const r = Math.min(4, (vertical ? w : hgt) / 2, vertical ? hgt : w);
  return vertical
    ? `M${x},${y + hgt} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + hgt} Z`
    : `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + hgt - r} Q${x + w},${y + hgt} ${x + w - r},${y + hgt} H${x} Z`;
}

function yGrid(lo, hi, step, y, m, width) {
  const out = [];
  for (let v = lo; v <= hi + 1e-9; v += step) {
    out.push(svg('line', { class: 'grid', x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }),
      svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, fmt.compact(v)));
  }
  return out;
}

export function columnChart(series, width, height = 260) {
  const m = { top: 20, right: 12, bottom: 28, left: 44 };
  const w = width - m.left - m.right;
  const ht = height - m.top - m.bottom;
  const max = Math.max(0, ...series.map((s) => s.value));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step || 1;
  const y = (v) => m.top + ht - (v / top) * ht;
  const band = w / series.length;
  const barW = Math.min(24, band * 0.7);
  const maxChars = Math.max(3, Math.floor(band / 6.5));
  const peak = series.reduce((best, s, i) => (s.value > series[best].value ? i : best), 0);
  const bars = series.map((s, i) => {
    const x = m.left + band * i + (band - barW) / 2;
    const top0 = y(Math.max(0, s.value));
    return [
      svg('rect', { class: 'hit', x: m.left + band * i, y: m.top, width: band, height: ht, 'data-tip': tipHtml(s.label, s.value) }),
      svg('path', { class: 'bar', d: roundedBar(x, top0, barW, m.top + ht - top0, true) }),
      svg('text', { class: 'tick', x: x + barW / 2, y: height - 9, 'text-anchor': 'middle' }, truncate(s.label, maxChars)),
      i === peak ? svg('text', { class: 'value', x: x + barW / 2, y: top0 - 6, 'text-anchor': 'middle' }, fmt.compact(s.value)) : null,
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    yGrid(0, top, step, y, m, width),
    svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: m.top + ht, y2: m.top + ht }), bars);
}

export function barChart(series, width) {
  const row = 26;
  const height = series.length * row + 8;
  const labelW = Math.min(150, Math.max(40, ...series.map((s) => s.label.length * 6.6)));
  const valueW = 52;
  const w = Math.max(20, width - labelW - valueW - 16);
  const max = Math.max(1e-9, ...series.map((s) => s.value));
  const bars = series.map((s, i) => {
    const y = 4 + i * row;
    const bw = (Math.max(0, s.value) / max) * w;
    return [
      svg('rect', { class: 'hit', x: 0, y, width, height: row, 'data-tip': tipHtml(s.label, s.value) }),
      svg('text', { class: 'tick', x: labelW, y: y + row / 2 + 4, 'text-anchor': 'end' }, truncate(s.label, Math.floor(labelW / 6.6))),
      svg('path', { class: 'bar', d: roundedBar(labelW + 8, y + (row - 16) / 2, bw, 16, false) }),
      svg('text', { class: 'value', x: labelW + 14 + bw, y: y + row / 2 + 4 }, fmt.compact(s.value)),
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    svg('line', { class: 'axis', x1: labelW + 8, x2: labelW + 8, y1: 2, y2: height - 2 }), bars);
}

export function lineChart(series, width, height = 260) {
  const m = { top: 20, right: 40, bottom: 28, left: 44 };
  const w = width - m.left - m.right;
  const ht = height - m.top - m.bottom;
  const min = Math.min(0, ...series.map((s) => s.value));
  const max = Math.max(...series.map((s) => s.value));
  const step = niceStep(max - min);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step || 1;
  const x = (i) => m.left + (series.length === 1 ? w / 2 : (i / (series.length - 1)) * w);
  const y = (v) => m.top + ht - ((v - lo) / (hi - lo)) * ht;
  const every = Math.ceil(series.length / Math.max(1, Math.floor(w / 70)));
  const labels = series.map((s, i) => (i % every === 0
    ? svg('text', { class: 'tick', x: x(i), y: height - 9, 'text-anchor': 'middle' }, truncate(s.label, 10)) : null));
  const d = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.value)}`).join(' ');
  const last = series.at(-1);
  const hits = series.map((s, i) => svg('rect', {
    class: 'hit', x: x(i) - w / series.length / 2, y: m.top, width: w / Math.max(1, series.length), height: ht,
    'data-tip': tipHtml(s.label, s.value),
  }));
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    yGrid(lo, hi, step, y, m, width), labels,
    svg('path', { class: 'area', d: `${d} L${x(series.length - 1)},${y(lo)} L${x(0)},${y(lo)} Z` }),
    svg('path', { class: 'line', d }), hits,
    svg('circle', { class: 'dot', cx: x(series.length - 1), cy: y(last.value), r: 4 }),
    svg('text', { class: 'value', x: x(series.length - 1) + 8, y: y(last.value) + 4 }, fmt.compact(last.value)));
}

export function donutChart(series, width, height = 200) {
  let slices = series.filter((s) => s.value > 0);
  if (slices.length > MAX_SLICES) {
    const rest = slices.slice(MAX_SLICES - 1).reduce((acc, s) => acc + s.value, 0);
    slices = [...slices.slice(0, MAX_SLICES - 1), { label: 'Outros', value: rest }];
  }
  const total = slices.reduce((acc, s) => acc + s.value, 0) || 1;
  // Acompanha o cartão (dashboard redimensionável, spec 014), deixando metade da largura para a legenda.
  const size = Math.max(120, Math.min(height, width * 0.45, 360));
  const r = size * 0.43;
  const inner = size * 0.27;
  const cx = size / 2;
  let angle = -Math.PI / 2;
  const p = (rad, a) => `${cx + rad * Math.cos(a)},${cx + rad * Math.sin(a)}`;
  const arcs = slices.map((s, i) => {
    const sweep = (s.value / total) * Math.PI * 2;
    const a0 = angle;
    const a1 = angle + sweep;
    angle = a1;
    const large = sweep > Math.PI ? 1 : 0;
    const d = sweep >= Math.PI * 2 - 1e-6
      ? `M${p(r, 0)} A${r},${r} 0 1 1 ${p(r, Math.PI)} A${r},${r} 0 1 1 ${p(r, 0)} M${p(inner, 0)} A${inner},${inner} 0 1 0 ${p(inner, Math.PI)} A${inner},${inner} 0 1 0 ${p(inner, 0)}`
      : `M${p(r, a0)} A${r},${r} 0 ${large} 1 ${p(r, a1)} L${p(inner, a1)} A${inner},${inner} 0 ${large} 0 ${p(inner, a0)} Z`;
    return svg('path', {
      class: `slice s${i + 1}`, d, 'fill-rule': 'evenodd',
      'data-tip': `${tipHtml(s.label, s.value)}<span>${fmt.number((s.value / total) * 100, 1)}%</span>`,
    });
  });
  const chart = svg('svg', { class: 'chart donut', width: size, height: size, viewBox: `0 0 ${size} ${size}` }, arcs,
    svg('text', { class: 'donut-total', x: cx, y: cx + 2, 'text-anchor': 'middle' }, fmt.compact(total)),
    svg('text', { class: 'tick', x: cx, y: cx + 18, 'text-anchor': 'middle' }, 'total'));
  const legend = h('ul', { class: 'legend' }, slices.map((s, i) => h('li', {},
    h('i', { class: `swatch s${i + 1}` }), h('span', { class: 'ellipsis' }, s.label),
    h('b', {}, fmt.compact(s.value)), h('span', { class: 'muted' }, `${fmt.number((s.value / total) * 100, 1)}%`))));
  return h('div', { class: 'donut-wrap', style: { maxWidth: `${width}px` } }, chart, legend);
}

export const CHARTS = { bar: columnChart, hbar: barChart, line: lineChart, donut: donutChart };

/** Escolhe o gráfico e devolve o elemento pronto. */
export function renderChart(type, series, width, height) {
  return (CHARTS[type] || columnChart)(series, width, height);
}
