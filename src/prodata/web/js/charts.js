// Gráficos SVG compartilhados pelo Dashboard e pelo painel de insights.
// Série única usa --series-1; a rosca usa a paleta categórica em ordem fixa (máx. 8).
// `opts` (formato do visual, spec 014) é opcional: sem ele, cada gráfico mantém o visual de sempre.

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

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const tipHtml = (label, value, o) => `<span>${esc(label)}</span><b>${esc(o.full(value))}</b>`;

/** Opções completas a partir do formato salvo no item (ou dos padrões de antes). */
function options(opts = {}) {
  const affix = (s) => `${opts.prefix || ''}${s}${opts.suffix || ''}`;
  const decimals = opts.decimals ?? 1;
  return {
    palette: opts.palette || 'brand',
    color: opts.color || '',
    categoryColors: opts.category_colors || {},
    labels: opts.data_labels, // undefined = comportamento original de cada gráfico
    grid: opts.grid ?? true,
    legend: opts.show_legend ?? true,
    xTitle: opts.x_title || '',
    yTitle: opts.y_title || '',
    yMin: opts.y_min ?? null,
    yMax: opts.y_max ?? null,
    short: (v) => affix(opts.label_format === 'full' ? fmt.number(v, decimals) : fmt.compact(v)),
    full: (v) => affix(fmt.number(v, opts.label_format === 'full' ? decimals : undefined)),
  };
}

/**
 * Cor de uma marca. `multi`: cada categoria tem a sua cor (rosca); senão é uma série só (--series-1).
 * Devolve atributos SVG: classe da paleta ou estilo com a cor escolhida.
 */
function paint(o, i, label, multi) {
  const slot = (i % MAX_SLICES) + 1;
  const custom = o.palette === 'custom' && o.categoryColors[label];
  if (custom) return { style: `fill:${custom}` };
  if (o.palette === 'single' && o.color) return { style: `fill:${o.color}${multi ? `;fill-opacity:${Math.max(0.35, 1 - i * 0.12)}` : ''}` };
  if (o.palette === 'alt') return multi ? { class: `a${slot}` } : { style: 'fill:var(--alt-1)' };
  return multi ? { class: `s${slot}` } : {};
}

/** Quais índices recebem número em destaque (nunca todos: o resto fica no tooltip). */
function labelled(series, mode, fallback) {
  const pick = mode ?? fallback;
  if (pick === 'all') return new Set(series.map((_, i) => i));
  if (pick === 'none' || !series.length) return new Set();
  const max = series.reduce((best, s, i) => (s.value > series[best].value ? i : best), 0);
  const min = series.reduce((best, s, i) => (s.value < series[best].value ? i : best), 0);
  return new Set(pick === 'max_min' ? [max, min] : pick === 'last' ? [series.length - 1] : [max]);
}

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

function yGrid(lo, hi, step, y, m, width, o) {
  const out = [];
  for (let v = lo; v <= hi + 1e-9; v += step) {
    if (o.grid) out.push(svg('line', { class: 'grid', x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
    out.push(svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, fmt.compact(v)));
  }
  return out;
}

/** Margens com espaço para os títulos dos eixos, quando houver. */
function margins(base, o) {
  return { ...base, left: base.left + (o.yTitle ? 16 : 0), bottom: base.bottom + (o.xTitle ? 18 : 0) };
}

function axisTitles(o, m, width, height) {
  return [
    o.xTitle ? svg('text', { class: 'axis-title', x: m.left + (width - m.left - m.right) / 2, y: height - 4, 'text-anchor': 'middle' }, o.xTitle) : null,
    o.yTitle ? svg('text', { class: 'axis-title', x: 0, y: 0, 'text-anchor': 'middle',
      transform: `translate(12 ${m.top + (height - m.top - m.bottom) / 2}) rotate(-90)` }, o.yTitle) : null,
  ];
}

/** Escala do eixo Y: automática a partir de zero, ou com mínimo/máximo escolhidos no formato. */
function yScale(values, o, fromZero) {
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  let lo = o.yMin ?? (fromZero ? Math.min(0, dataMin) : Math.min(0, dataMin));
  let hi = o.yMax ?? dataMax;
  if (hi <= lo) hi = lo + 1;
  const step = niceStep(hi - lo);
  if (o.yMin === null) lo = Math.floor(lo / step) * step;
  if (o.yMax === null) hi = Math.ceil(hi / step) * step || 1;
  return { lo, hi, step };
}

export function columnChart(series, width, height = 260, opts) {
  const o = options(opts);
  const m = margins({ top: 20, right: 12, bottom: 28, left: 44 }, o);
  const w = width - m.left - m.right;
  const ht = height - m.top - m.bottom;
  const { lo, hi, step } = yScale(series.map((s) => s.value), o, true);
  const y = (v) => m.top + ht - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * ht;
  const band = w / series.length;
  const barW = Math.min(24, band * 0.7);
  const maxChars = Math.max(3, Math.floor(band / 6.5));
  const shown = labelled(series, o.labels, 'max');
  const base = y(Math.max(lo, 0));
  const bars = series.map((s, i) => {
    const x = m.left + band * i + (band - barW) / 2;
    const top0 = y(Math.max(lo, s.value));
    return [
      svg('rect', { class: 'hit', x: m.left + band * i, y: m.top, width: band, height: ht, 'data-tip': tipHtml(s.label, s.value, o) }),
      svg('path', { class: 'bar', d: roundedBar(x, top0, barW, base - top0, true), ...paint(o, i, s.label, false) }),
      svg('text', { class: 'tick', x: x + barW / 2, y: height - 9 - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' }, truncate(s.label, maxChars)),
      shown.has(i) ? svg('text', { class: 'value', x: x + barW / 2, y: top0 - 6, 'text-anchor': 'middle' }, o.short(s.value)) : null,
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    yGrid(lo, hi, step, y, m, width, o),
    svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: base, y2: base }), bars, axisTitles(o, m, width, height));
}

export function barChart(series, width, _height, opts) {
  const o = options(opts);
  const row = 26;
  const height = series.length * row + 8 + (o.xTitle ? 18 : 0);
  const labelW = Math.min(150, Math.max(40, ...series.map((s) => s.label.length * 6.6)));
  const valueW = 52;
  const w = Math.max(20, width - labelW - valueW - 16);
  const max = o.yMax ?? Math.max(1e-9, ...series.map((s) => s.value));
  const shown = labelled(series, o.labels, 'all');
  const bars = series.map((s, i) => {
    const y = 4 + i * row;
    const bw = (Math.min(max, Math.max(0, s.value)) / max) * w;
    return [
      svg('rect', { class: 'hit', x: 0, y, width, height: row, 'data-tip': tipHtml(s.label, s.value, o) }),
      svg('text', { class: 'tick', x: labelW, y: y + row / 2 + 4, 'text-anchor': 'end' }, truncate(s.label, Math.floor(labelW / 6.6))),
      svg('path', { class: 'bar', d: roundedBar(labelW + 8, y + (row - 16) / 2, bw, 16, false), ...paint(o, i, s.label, false) }),
      shown.has(i) ? svg('text', { class: 'value', x: labelW + 14 + bw, y: y + row / 2 + 4 }, o.short(s.value)) : null,
    ];
  });
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    svg('line', { class: 'axis', x1: labelW + 8, x2: labelW + 8, y1: 2, y2: height - 2 - (o.xTitle ? 18 : 0) }), bars,
    o.xTitle ? svg('text', { class: 'axis-title', x: labelW + 8 + w / 2, y: height - 4, 'text-anchor': 'middle' }, o.xTitle) : null);
}

export function lineChart(series, width, height = 260, opts) {
  const o = options(opts);
  const m = margins({ top: 20, right: 40, bottom: 28, left: 44 }, o);
  const w = width - m.left - m.right;
  const ht = height - m.top - m.bottom;
  const { lo, hi, step } = yScale(series.map((s) => s.value), o, true);
  const x = (i) => m.left + (series.length === 1 ? w / 2 : (i / (series.length - 1)) * w);
  const y = (v) => m.top + ht - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * ht;
  const every = Math.ceil(series.length / Math.max(1, Math.floor(w / 70)));
  const labels = series.map((s, i) => (i % every === 0
    ? svg('text', { class: 'tick', x: x(i), y: height - 9 - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' }, truncate(s.label, 10)) : null));
  const d = series.map((s, i) => `${i ? 'L' : 'M'}${x(i)},${y(s.value)}`).join(' ');
  const hits = series.map((s, i) => svg('rect', {
    class: 'hit', x: x(i) - w / series.length / 2, y: m.top, width: w / Math.max(1, series.length), height: ht,
    'data-tip': tipHtml(s.label, s.value, o),
  }));
  // A linha usa a cor como traço; paint() devolve preenchimento, então converte.
  const tone = paint(o, 0, series[0]?.label, false);
  const stroke = tone.style ? { style: tone.style.replace('fill:', 'stroke:') } : {};
  const shown = labelled(series, o.labels, 'last');
  return svg('svg', { class: 'chart', width, height, viewBox: `0 0 ${width} ${height}` },
    yGrid(lo, hi, step, y, m, width, o), labels,
    svg('path', { class: 'area', d: `${d} L${x(series.length - 1)},${y(lo)} L${x(0)},${y(lo)} Z`, ...tone }),
    svg('path', { class: 'line', d, ...stroke }), hits,
    [...shown].map((i) => [
      svg('circle', { class: 'dot', cx: x(i), cy: y(series[i].value), r: 4, ...tone }),
      svg('text', { class: 'value', x: x(i) + (i === series.length - 1 ? 8 : 0), y: y(series[i].value) - (i === series.length - 1 ? -4 : 8),
        'text-anchor': i === series.length - 1 ? 'start' : 'middle' }, o.short(series[i].value)),
    ]),
    axisTitles(o, m, width, height));
}

export function donutChart(series, width, height = 200, opts) {
  const o = options(opts);
  let slices = series.filter((s) => s.value > 0);
  if (slices.length > MAX_SLICES) {
    const rest = slices.slice(MAX_SLICES - 1).reduce((acc, s) => acc + s.value, 0);
    slices = [...slices.slice(0, MAX_SLICES - 1), { label: 'Outros', value: rest }];
  }
  const total = slices.reduce((acc, s) => acc + s.value, 0) || 1;
  // Acompanha o cartão (dashboard redimensionável, spec 014), deixando metade da largura para a legenda.
  const size = Math.max(120, Math.min(height, width * (o.legend ? 0.45 : 1), 360));
  const r = size * 0.43;
  const inner = size * 0.27;
  const cx = size / 2;
  let angle = -Math.PI / 2;
  const p = (rad, a) => `${cx + rad * Math.cos(a)},${cx + rad * Math.sin(a)}`;
  const tones = slices.map((s, i) => paint(o, i, s.label, true));
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
      class: ['slice', tones[i].class].filter(Boolean).join(' '), style: tones[i].style, d, 'fill-rule': 'evenodd',
      'data-tip': `${tipHtml(s.label, s.value, o)}<span>${fmt.number((s.value / total) * 100, 1)}%</span>`,
    });
  });
  const chart = svg('svg', { class: 'chart donut', width: size, height: size, viewBox: `0 0 ${size} ${size}` }, arcs,
    svg('text', { class: 'donut-total', x: cx, y: cx + 2, 'text-anchor': 'middle' }, o.short(total)),
    svg('text', { class: 'tick', x: cx, y: cx + 18, 'text-anchor': 'middle' }, 'total'));
  // A amostra da legenda usa a mesma cor da fatia (classe da paleta ou cor escolhida).
  const swatch = (t) => h('i', { class: ['swatch', t.class], style: t.style ? { background: t.style.split(';')[0].replace('fill:', ''), opacity: (t.style.match(/fill-opacity:([\d.]+)/) || [])[1] || null } : null });
  const legend = o.legend ? h('ul', { class: 'legend' }, slices.map((s, i) => h('li', {},
    swatch(tones[i]), h('span', { class: 'ellipsis' }, s.label),
    h('b', {}, o.short(s.value)), h('span', { class: 'muted' }, `${fmt.number((s.value / total) * 100, 1)}%`)))) : null;
  return h('div', { class: 'donut-wrap', style: { maxWidth: `${width}px` } }, chart, legend);
}

export const CHARTS = { bar: columnChart, hbar: barChart, line: lineChart, donut: donutChart };

/** Escolhe o gráfico e devolve o elemento pronto. */
export function renderChart(type, series, width, height, opts) {
  return (CHARTS[type] || columnChart)(series, width, height, opts);
}
