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

// ------------------------------------------------------------------ fase 3 da spec 014: visuais novos

/** Cor (CSS) da série i: a mesma regra de paint(), em forma de valor para fill/stroke. */
function tone(o, i, name) {
  if (o.palette === 'custom' && o.categoryColors[name]) return o.categoryColors[name];
  if (o.palette === 'single' && o.color) return o.color;
  return `var(--${o.palette === 'alt' ? 'alt' : 'series'}-${(i % MAX_SLICES) + 1})`;
}

/** Legenda em linha acima do gráfico: obrigatória com 2 ou mais séries (a cor nunca identifica sozinha). */
function legendRow(names, colors) {
  return h('ul', { class: 'legend-row' }, names.map((n, i) => h('li', {},
    h('i', { class: 'swatch', style: { background: colors[i], opacity: colors[i] === colors[0] && i ? Math.max(0.35, 1 - i * 0.12) : null } }),
    h('span', {}, n))));
}

function multiTip(label, rows, o, total) {
  return `<span>${esc(label)}</span>${rows.map(([n, v]) => `<span>${esc(n)}: <b>${esc(o.full(v))}</b></span>`).join('')}`
    + (total === undefined ? '' : `<span>Total: <b>${esc(o.full(total))}</b></span>`);
}

/** Colunas empilhadas, agrupadas ou 100%; linhas e áreas com uma série por valor da 2ª dimensão. */
function multiChart(w, width, height, opts, mode) {
  const o = options(opts);
  const names = w.series_names || [];
  const colors = names.map((n, i) => tone(o, i, n));
  // Uma cor só: as séries se diferenciam pela opacidade, então a legenda acompanha.
  const alpha = (i) => (o.palette === 'single' && o.color ? Math.max(0.35, 1 - i * 0.12) : 1);
  const cats = w.series;
  const pct = mode === 'stacked100';
  const cell = (c, n) => {
    const v = c.values[n] || 0;
    return pct ? (c.value ? (v / c.value) * 100 : 0) : v;
  };
  const stacked = ['stacked', 'stacked100', 'area_stacked'].includes(mode);
  const svgH = height - 30;
  const m = margins({ top: 16, right: mode.startsWith('line') || mode.startsWith('area') ? 56 : 12, bottom: 28, left: 48 }, o);
  const pw = width - m.left - m.right;
  const ph = svgH - m.top - m.bottom;
  const peaks = cats.map((c) => (stacked ? names.reduce((acc, n) => acc + cell(c, n), 0) : Math.max(0, ...names.map((n) => cell(c, n)))));
  const { lo, hi, step } = pct ? { lo: 0, hi: 100, step: 25 } : yScale(peaks, o, true);
  const y = (v) => m.top + ph - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * ph;
  const band = pw / Math.max(1, cats.length);
  const maxChars = Math.max(3, Math.floor(band / 6.5));
  const ticks = cats.map((c, i) => svg('text', { class: 'tick', x: m.left + band * i + band / 2, y: svgH - 9 - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' },
    truncate(c.label, maxChars)));
  const tip = (c) => multiTip(c.label, names.map((n) => [n, c.values[n] || 0]), o, c.value);
  const marks = [];
  if (mode === 'stacked' || mode === 'stacked100' || mode === 'grouped') {
    const barW = mode === 'grouped' ? Math.min(18, (band * 0.8) / names.length) : Math.min(28, band * 0.7);
    cats.forEach((c, i) => {
      let base = 0;
      const x0 = m.left + band * i + (band - (mode === 'grouped' ? barW * names.length : barW)) / 2;
      names.forEach((n, k) => {
        const v = cell(c, n);
        if (v <= 0) return;
        if (mode === 'grouped') {
          const top0 = y(v);
          marks.push(svg('path', { class: 'bar', d: roundedBar(x0 + k * barW, top0, barW - 1, y(0) - top0, true), style: `fill:${colors[k]};fill-opacity:${alpha(k)}` }));
        } else {
          const yTop = y(base + v);
          // 1 px de respiro entre segmentos (cor da superfície), sem arredondar o meio da pilha.
          marks.push(svg('rect', { class: 'seg', x: x0, y: yTop, width: barW, height: Math.max(0, y(base) - yTop - 1), style: `fill:${colors[k]};fill-opacity:${alpha(k)}` }));
          base += v;
        }
      });
      marks.push(svg('rect', { class: 'hit', x: m.left + band * i, y: m.top, width: band, height: ph, 'data-tip': tip(c) }));
    });
    if (!pct) {
      const shown = labelled(cats, o.labels, 'max');
      for (const i of shown) {
        marks.push(svg('text', { class: 'value', x: m.left + band * i + band / 2, y: y(peaks[i]) - 6, 'text-anchor': 'middle' }, o.short(peaks[i])));
      }
    }
  } else {
    const x = (i) => m.left + (cats.length === 1 ? pw / 2 : (i / (cats.length - 1)) * pw);
    const cum = cats.map(() => 0);
    names.forEach((n, k) => {
      const pts = cats.map((c, i) => {
        const v = cell(c, n);
        const yy = stacked ? (cum[i] += v) : v;
        return [x(i), y(yy), stacked ? yy - v : 0];
      });
      const d = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px},${py}`).join(' ');
      if (mode === 'area_stacked') {
        const back = [...pts].reverse().map(([px, , b]) => `L${px},${y(b)}`).join(' ');
        marks.push(svg('path', { class: 'seg', d: `${d} ${back} Z`, style: `fill:${colors[k]};fill-opacity:${0.85 * alpha(k)}` }));
      } else {
        if (mode === 'area') marks.push(svg('path', { d: `${d} L${x(cats.length - 1)},${y(lo)} L${x(0)},${y(lo)} Z`, style: `fill:${colors[k]};fill-opacity:0.12` }));
        marks.push(svg('path', { class: 'line', d, style: `stroke:${colors[k]};stroke-opacity:${alpha(k)}` }));
      }
      // Rótulo direto no fim de cada linha quando são até 4 séries.
      if (names.length <= 4 && cats.length) {
        const [lx, ly] = pts.at(-1);
        marks.push(svg('text', { class: 'value', x: lx + 6, y: ly + 4 }, truncate(n, 9)));
      }
    });
    cats.forEach((c, i) => marks.push(svg('rect', { class: 'hit', x: x(i) - pw / Math.max(1, cats.length) / 2, y: m.top, width: pw / Math.max(1, cats.length), height: ph, 'data-tip': tip(c) })));
  }
  const yTicks = [];
  for (let v = lo; v <= hi + 1e-9; v += step) {
    if (o.grid) yTicks.push(svg('line', { class: 'grid', x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
    yTicks.push(svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, pct ? `${v}%` : fmt.compact(v)));
  }
  return h('div', { class: 'multi-chart' }, legendRow(names, colors),
    svg('svg', { class: 'chart', width, height: svgH, viewBox: `0 0 ${width} ${svgH}` }, yTicks,
      svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: y(lo), y2: y(lo) }), ticks, marks, axisTitles(o, m, width, svgH)));
}

/**
 * Pareto num eixo só (0–100%): cada coluna é a participação da categoria no total e a linha é o
 * acumulado. Dois eixos Y com escalas diferentes enganam a leitura, então não há segundo eixo.
 */
function paretoChart(series, width, height, opts, w) {
  const o = options(opts);
  const total = series.reduce((acc, s) => acc + Math.max(0, s.value), 0) || 1;
  const svgH = height - 30;
  const m = margins({ top: 18, right: 40, bottom: 28, left: 44 }, o);
  const pw = width - m.left - m.right;
  const ph = svgH - m.top - m.bottom;
  const y = (v) => m.top + ph - (Math.min(100, Math.max(0, v)) / 100) * ph;
  const band = pw / Math.max(1, series.length);
  const barW = Math.min(28, band * 0.7);
  const color = tone(o, 0, series[0]?.label);
  const lineColor = 'var(--text-2)';
  const cx = (i) => m.left + band * i + band / 2;
  const cut = series.reduce((last, s, i) => (s.highlight ? i : last), -1);
  const threshold = w.threshold ?? 80;
  const marks = series.map((s, i) => {
    const share = (Math.max(0, s.value) / total) * 100;
    const top0 = y(share);
    return [
      svg('rect', { class: 'hit', x: m.left + band * i, y: m.top, width: band, height: ph,
        'data-tip': `<span>${esc(s.label)}</span><b>${esc(o.full(s.value))}</b><span>${fmt.number(share, 1)}% do total · acumulado ${fmt.number(s.cum_pct, 1)}%</span>` }),
      svg('path', { class: 'bar', d: roundedBar(cx(i) - barW / 2, top0, barW, y(0) - top0, true), style: `fill:${color};fill-opacity:${s.highlight ? 1 : 0.35}` }),
      svg('text', { class: 'tick', x: cx(i), y: svgH - 9 - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' }, truncate(s.label, Math.max(3, Math.floor(band / 6.5)))),
    ];
  });
  const d = series.map((s, i) => `${i ? 'L' : 'M'}${cx(i)},${y(s.cum_pct)}`).join(' ');
  const grid = [0, 25, 50, 75, 100].map((v) => [
    o.grid ? svg('line', { class: 'grid', x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }) : null,
    svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, `${v}%`),
  ]);
  const label = cut >= 0 ? [
    svg('circle', { class: 'dot', cx: cx(cut), cy: y(series[cut].cum_pct), r: 4, style: `fill:${lineColor}` }),
    svg('text', { class: 'value', x: cx(cut), y: y(series[cut].cum_pct) - 9, 'text-anchor': 'middle' }, `${fmt.number(series[cut].cum_pct, 0)}%`),
  ] : null;
  return h('div', { class: 'multi-chart' },
    h('ul', { class: 'legend-row' },
      h('li', {}, h('i', { class: 'swatch', style: { background: color } }), h('span', {}, `Participação no total · ${cut + 1} de ${series.length} somam ${fmt.number(threshold, 0)}%`)),
      h('li', {}, h('i', { class: 'swatch line-swatch', style: { background: lineColor } }), h('span', {}, 'Acumulado'))),
    svg('svg', { class: 'chart', width, height: svgH, viewBox: `0 0 ${width} ${svgH}` }, grid,
      svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: y(0), y2: y(0) }), marks,
      svg('line', { class: 'threshold', x1: m.left, x2: width - m.right, y1: y(threshold), y2: y(threshold) }),
      svg('text', { class: 'tick', x: width - m.right + 4, y: y(threshold) + 4 }, `${fmt.number(threshold, 0)}%`),
      svg('path', { class: 'line', d, style: `stroke:${lineColor}` }), label, axisTitles(o, m, width, svgH)));
}

/** Funil: etapas na ordem da série, largura proporcional ao valor e % da primeira etapa. */
function funnelChart(series, width, height, opts) {
  const o = options(opts);
  const rows = series.slice(0, 12);
  const first = rows[0]?.value || 1;
  const max = Math.max(1e-9, ...rows.map((s) => s.value));
  const rowH = Math.max(22, Math.min(48, (height - 8) / Math.max(1, rows.length)));
  const labelW = Math.min(160, width * 0.28);
  const valueW = 120;
  const area = Math.max(40, width - labelW - valueW - 16);
  const color = tone(o, 0, rows[0]?.label);
  const marks = rows.map((s, i) => {
    const bw = Math.max(2, (Math.max(0, s.value) / max) * area);
    const yy = 4 + i * rowH;
    const x0 = labelW + 8 + (area - bw) / 2;
    return [
      svg('rect', { class: 'hit', x: 0, y: yy, width, height: rowH, 'data-tip': tipHtml(s.label, s.value, o) }),
      svg('text', { class: 'tick', x: labelW, y: yy + rowH / 2 + 4, 'text-anchor': 'end' }, truncate(s.label, Math.floor(labelW / 6.6))),
      svg('rect', { class: 'seg', x: x0, y: yy + 3, width: bw, height: rowH - 6, rx: 4, style: `fill:${color};fill-opacity:${Math.max(0.4, 1 - i * 0.08)}` }),
      svg('text', { class: 'value', x: labelW + 16 + area, y: yy + rowH / 2 + 4 }, `${o.short(s.value)} · ${fmt.number((s.value / first) * 100, 0)}%`),
    ];
  });
  return svg('svg', { class: 'chart', width, height: rows.length * rowH + 8, viewBox: `0 0 ${width} ${rows.length * rowH + 8}` }, marks);
}

/** Dispersão: X e Y numéricos, cor opcional por categoria (até 8; o resto vira "Outros"). */
function scatterChart(w, width, height, opts) {
  const o = options(opts);
  const pts = w.points || [];
  const counts = new Map();
  for (const p of pts) if (p.s !== undefined) counts.set(p.s, (counts.get(p.s) || 0) + 1);
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const names = ranked.length > MAX_SLICES ? [...ranked.slice(0, MAX_SLICES - 1), 'Outros'] : ranked;
  const colors = names.map((n, i) => tone(o, i, n));
  const idx = (s) => { const k = names.indexOf(s); return k >= 0 ? k : names.length - 1; };
  const svgH = height - (names.length ? 30 : 0);
  const m = margins({ top: 14, right: 16, bottom: 28 + (w.sampled ? 14 : 0), left: 52 }, o);
  const pw = width - m.left - m.right;
  const ph = svgH - m.top - m.bottom;
  const xs = yScale(pts.map((p) => p.x), { yMin: null, yMax: null }, false);
  const ys = yScale(pts.map((p) => p.y), o, false);
  const x = (v) => m.left + ((v - xs.lo) / (xs.hi - xs.lo)) * pw;
  const y = (v) => m.top + ph - ((Math.min(ys.hi, Math.max(ys.lo, v)) - ys.lo) / (ys.hi - ys.lo)) * ph;
  const grid = [];
  for (let v = ys.lo; v <= ys.hi + 1e-9; v += ys.step) {
    if (o.grid) grid.push(svg('line', { class: 'grid', x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
    grid.push(svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, fmt.compact(v)));
  }
  for (let v = xs.lo; v <= xs.hi + 1e-9; v += xs.step) {
    grid.push(svg('text', { class: 'tick', x: x(v), y: svgH - 9 - (w.sampled ? 14 : 0) - (o.xTitle ? 18 : 0), 'text-anchor': 'middle' }, fmt.compact(v)));
  }
  const dots = pts.map((p) => svg('circle', {
    class: 'scatter-dot', cx: x(p.x), cy: y(p.y), r: 4,
    style: `fill:${names.length ? colors[idx(p.s)] : tone(o, 0, '')}`,
    'data-tip': `${p.s !== undefined ? `<span>${esc(p.s)}</span>` : ''}<span>${esc(w.x_column)}: <b>${fmt.number(p.x)}</b></span><span>${esc(w.y_column)}: <b>${fmt.number(p.y)}</b></span>`,
  }));
  const note = w.sampled ? svg('text', { class: 'tick', x: width - m.right, y: svgH - 4, 'text-anchor': 'end' },
    `Amostra de ${fmt.int(pts.length)} de ${fmt.int(w.point_count)} pontos`) : null;
  const chart = svg('svg', { class: 'chart', width, height: svgH, viewBox: `0 0 ${width} ${svgH}` }, grid,
    svg('line', { class: 'axis', x1: m.left, x2: width - m.right, y1: m.top + ph, y2: m.top + ph }), dots, note,
    axisTitles({ ...o, xTitle: o.xTitle || w.x_column, yTitle: o.yTitle || w.y_column }, m, width, svgH));
  return names.length ? h('div', { class: 'multi-chart' }, legendRow(names, colors), chart) : chart;
}

/**
 * Venn. Com 2 conjuntos as áreas são proporcionais (geometria calculada no motor); com 3, os círculos
 * são ilustrativos e os números carregam a proporção, o que o rodapé diz (constituição VI).
 */
export function vennChart(w, width, height, opts) {
  const o = options(opts);
  const n = w.sets.length;
  const colors = w.sets.map((s, i) => tone(o, i, s.name));
  const svgH = height - 22;
  const R = (k) => w.regions.find((r) => r.sets.join() === k.join());
  const regionLabel = (k, px, py) => {
    const r = R(k);
    if (!r) return null;
    return svg('g', { class: 'venn-region', 'data-tip': `<span>${esc(k.map((i) => w.sets[i].name).join(' e '))}${k.length < n ? ' (só)' : ''}</span><b>${fmt.int(r.count)}</b><span>${fmt.number(r.pct, 1)}% de ${fmt.int(w.union)}</span>` },
      svg('circle', { class: 'hit', cx: px, cy: py, r: 22 }),
      svg('text', { class: 'venn-count', x: px, y: py + 2, 'text-anchor': 'middle' }, fmt.compact(r.count)),
      svg('text', { class: 'tick', x: px, y: py + 16, 'text-anchor': 'middle' }, `${fmt.number(r.pct, 0)}%`));
  };
  let circles = [];
  let labels = [];
  if (n === 2 && w.geometry) {
    const { r1, r2, d } = w.geometry;
    const span = r1 + d + r2;
    const k = Math.min((width * 0.86) / span, (svgH - 36) / (2 * Math.max(r1, r2)));
    const cy = svgH / 2 + 10;
    const c1 = width / 2 - (span * k) / 2 + r1 * k;
    const c2 = c1 + d * k;
    circles = [[c1, r1 * k], [c2, r2 * k]];
    const lensMid = (c1 + r1 * k + (c2 - r2 * k)) / 2;
    labels = [
      regionLabel([0], Math.min(c1, (c1 - r1 * k + c2 - r2 * k) / 2), cy),
      regionLabel([1], Math.max(c2, (c1 + r1 * k + c2 + r2 * k) / 2), cy),
      regionLabel([0, 1], lensMid, cy),
    ];
    circles = circles.map(([cx, r]) => [cx, cy, r]);
  } else {
    const r = Math.min(width / 3.4, (svgH - 30) / 3.1);
    const cx = width / 2;
    const cy = svgH / 2 + 12;
    const off = r * 0.62;
    const centers = [[cx - off, cy - off * 0.55], [cx + off, cy - off * 0.55], [cx, cy + off * 0.75]];
    circles = centers.map(([x, y]) => [x, y, r]);
    const out = (i, f) => [cx + (centers[i][0] - cx) * f, cy + (centers[i][1] - cy) * f];
    const mid = (i, j, f) => [cx + ((centers[i][0] + centers[j][0]) / 2 - cx) * f, cy + ((centers[i][1] + centers[j][1]) / 2 - cy) * f];
    labels = [
      regionLabel([0], ...out(0, 1.75)), regionLabel([1], ...out(1, 1.75)), regionLabel([2], ...out(2, 1.75)),
      regionLabel([0, 1], ...mid(0, 1, 2.2)), regionLabel([0, 2], ...mid(0, 2, 2.2)), regionLabel([1, 2], ...mid(1, 2, 2.2)),
      regionLabel([0, 1, 2], cx, cy),
    ];
  }
  const shapes = circles.map(([cx, cy, r], i) => svg('circle', { class: 'venn-set', cx, cy, r, style: `fill:${colors[i]};stroke:${colors[i]}` }));
  const foot = [
    w.proportional ? 'Áreas proporcionais' : 'Círculos ilustrativos: os números indicam a proporção',
    w.outside ? `${fmt.int(w.outside)} fora de todos` : null,
  ].filter(Boolean).join(' · ');
  return h('div', { class: 'multi-chart' },
    h('ul', { class: 'legend-row' }, w.sets.map((s, i) => h('li', {}, h('i', { class: 'swatch', style: { background: colors[i] } }), h('span', {}, `${s.name} · ${fmt.int(s.size)}`)))),
    svg('svg', { class: 'chart venn', width, height: svgH, viewBox: `0 0 ${width} ${svgH}` }, shapes, labels),
    h('p', { class: 'chart-foot muted' }, foot));
}

/** Medidor semicircular: valor contra o máximo, com marca da meta. */
export function gaugeChart(w, width, height, valueText) {
  const size = Math.max(120, Math.min(width, height * 1.7));
  const r = size * 0.42;
  const cx = size / 2;
  const cy = r + 12;
  const max = w.gauge_max || 1;
  const frac = Math.max(0, Math.min(1, w.value / max));
  const pt = (f, rad) => [cx - rad * Math.cos(Math.PI * f), cy - rad * Math.sin(Math.PI * f)];
  const arc = (f0, f1, rad) => {
    const [x0, y0] = pt(f0, rad);
    const [x1, y1] = pt(f1, rad);
    return `M${x0},${y0} A${rad},${rad} 0 ${f1 - f0 > 0.5 ? 1 : 0} 1 ${x1},${y1}`;
  };
  const target = w.target ? Math.max(0, Math.min(1, w.target / max)) : null;
  const tk = target === null ? null : [pt(target, r - 14), pt(target, r + 14)];
  return svg('svg', { class: 'chart gauge', width: size, height: cy + 30, viewBox: `0 0 ${size} ${cy + 30}` },
    svg('path', { class: 'gauge-track', d: arc(0, 1, r) }),
    frac > 0 ? svg('path', { class: 'gauge-value', d: arc(0, Math.max(frac, 0.002), r) }) : null,
    tk ? svg('line', { class: 'gauge-target', x1: tk[0][0], y1: tk[0][1], x2: tk[1][0], y2: tk[1][1] }) : null,
    svg('text', { class: 'gauge-text', x: cx, y: cy - 4, 'text-anchor': 'middle' }, valueText),
    svg('text', { class: 'tick', x: cx - r, y: cy + 20, 'text-anchor': 'middle' }, '0'),
    svg('text', { class: 'tick', x: cx + r, y: cy + 20, 'text-anchor': 'middle' }, fmt.compact(max)));
}

/** Minigráfico de tendência do big number (sem eixos; o último ponto em destaque). */
export function sparkline(trend, width, height) {
  if (!trend?.length) return null;
  const vals = trend.map((t) => t.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const x = (i) => 3 + (trend.length === 1 ? (width - 6) / 2 : (i / (trend.length - 1)) * (width - 6));
  const y = (v) => 3 + (hi === lo ? (height - 6) / 2 : (1 - (v - lo) / (hi - lo)) * (height - 6));
  const d = trend.map((t, i) => `${i ? 'L' : 'M'}${x(i)},${y(t.value)}`).join(' ');
  return svg('svg', { class: 'chart sparkline', width, height, viewBox: `0 0 ${width} ${height}` },
    trend.map((t, i) => svg('rect', { class: 'hit', x: x(i) - width / trend.length / 2, y: 0, width: width / trend.length, height, 'data-tip': tipHtml(t.label, t.value, options()) })),
    svg('path', { class: 'line', d }),
    svg('circle', { class: 'dot', cx: x(trend.length - 1), cy: y(vals.at(-1)), r: 3 }));
}

function areaChart(series, width, height, opts) {
  const el = lineChart(series, width, height, opts);
  el.querySelector('.area')?.classList.add('strong');
  return el;
}

export const CHARTS = {
  bar: columnChart, hbar: barChart, line: lineChart, donut: donutChart, area: areaChart, area_stacked: areaChart,
  stacked: columnChart, grouped: columnChart, stacked100: columnChart, funnel: funnelChart,
};
const MULTI = ['stacked', 'grouped', 'stacked100', 'line', 'area', 'area_stacked'];

/** Escolhe o gráfico e devolve o elemento pronto. `w` é o widget inteiro (séries, pontos, Venn...). */
export function renderChart(type, series, width, height, opts, w = {}) {
  if (w.widget_type === 'venn') return vennChart(w, width, height, opts);
  if (type === 'scatter') return scatterChart(w, width, height, opts);
  if (type === 'pareto') return paretoChart(series, width, height, opts, w);
  if (w.series_names?.length && MULTI.includes(type)) return multiChart(w, width, height, opts, type);
  return (CHARTS[type] || columnChart)(series, width, height, opts);
}
