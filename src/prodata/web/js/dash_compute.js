// Cálculo dos visuais no HTML exportado (spec 021), que não tem servidor: espelho de prodata/nodes/bi.py e
// prodata/dashboard/filters.py. O motor continua sendo a referência: um teste compara os dois número a número.

const MAX_SERIES = 8;
const MAX_POINTS = 2000;
const RANKED = ['pareto', 'race'];
const MAX_LINKS = 40;
const SERIES_CHARTS = ['stacked', 'grouped', 'stacked100', 'line', 'area', 'area_stacked'];
const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const TRUE = new Set(['true', '1', 'sim', 's', 'yes', 'y', 'verdadeiro', 'x']);
const NUMBER_TEXT = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;
const compareText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

const round = (v, places = 4) => {
  const k = 10 ** places;
  return Math.round((v + Number.EPSILON * Math.sign(v)) * k) / k;
};

export function toNumber(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'boolean') return v ? 1 : 0;
  return NUMBER_TEXT.test(String(v)) ? Number(v) : null;
}

/** Mesmo texto que o motor mostra para uma categoria. */
export function labelOf(v, type) {
  if (v === null || v === undefined) return '(vazio)';
  if (type === 'float' && Number.isInteger(v)) return `${v}.0`;
  return String(v);
}

// ------------------------------------------------------------------ tabela

/** Tabela vinda do arquivo: colunas por nome, com o tipo de cada uma. */
/** A data em AAAA-MM-DD, também quando a coluna é texto (2026-05 ou 29/10/2026). */
export function dayText(v) {
  const text = String(v).trim();
  if (/^\d{4}-\d{2}$/.test(text)) return `${text}-01`;
  const br = text.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  return br ? `${br[3]}-${br[2]}-${br[1]}` : text.slice(0, 10);
}

export function makeTable(columns, types, height) {
  return { columns, types, height };
}

function subset(table, keep) {
  const columns = {};
  for (const [name, values] of Object.entries(table.columns)) columns[name] = keep.map((i) => values[i]);
  return { columns, types: table.types, height: keep.length };
}

const has = (t, name) => Object.prototype.hasOwnProperty.call(t.columns, name);
const need = (t, name, message) => { if (!name || !has(t, name)) throw new Error(message); };

export function isActive(f) {
  return f.kind === 'list' ? Boolean(f.selected?.length) : f.min !== null && f.min !== undefined ? true : f.max !== null && f.max !== undefined;
}

/** Linhas que passam nos filtros, e as colunas de filtros ativos que a tabela não tem. */
export function applyFilters(table, filters) {
  let current = table;
  const missing = [];
  for (const f of filters) {
    if (!isActive(f)) continue;
    if (!has(current, f.column)) { missing.push(f.column); continue; }
    const values = current.columns[f.column];
    const keep = [];
    if (f.kind === 'list') {
      const wanted = new Set(f.selected);
      const type = current.types[f.column];
      values.forEach((v, i) => { if (wanted.has(labelOf(v, type))) keep.push(i); });
    } else if (f.kind === 'number') {
      values.forEach((v, i) => {
        const n = toNumber(v);
        if (n !== null && (f.min === null || f.min === undefined || n >= f.min) && (f.max === null || f.max === undefined || n <= f.max)) keep.push(i);
      });
    } else {
      values.forEach((v, i) => {
        if (v === null || v === undefined) return;
        const d = dayText(v);
        if ((!f.min || d >= f.min) && (!f.max || d <= f.max)) keep.push(i);
      });
    }
    current = subset(current, keep);
  }
  return { table: current, missing };
}

// ------------------------------------------------------------------ gráfico

function aggregate(values, agg) {
  if (agg === 'count') return values.length;
  const nums = values.map(toNumber).filter((n) => n !== null);
  if (agg === 'sum') return nums.reduce((a, b) => a + b, 0);
  if (!nums.length) return null;
  if (agg === 'mean') return nums.reduce((a, b) => a + b, 0) / nums.length;
  return agg === 'min' ? Math.min(...nums) : Math.max(...nums);
}

function ordered(pairs, cfg) {
  const rows = [...pairs];
  if (cfg.sort === 'label' && !RANKED.includes(cfg.chart_type)) rows.sort((a, b) => compareText(a[0], b[0]));
  else {
    const desc = cfg.sort !== 'value_asc' || RANKED.includes(cfg.chart_type);
    rows.sort((a, b) => {
      if (a[1] === null) return b[1] === null ? 0 : 1;
      if (b[1] === null) return -1;
      return desc ? b[1] - a[1] : a[1] - b[1];
    });
  }
  return rows.map(([label, v]) => [label, v || 0]);
}

function groupValues(table, cfg) {
  const type = table.types[cfg.x_column];
  const xs = table.columns[cfg.x_column];
  const ys = cfg.agg === 'count' ? null : table.columns[cfg.y_column];
  const groups = new Map();
  xs.forEach((x, i) => {
    const label = labelOf(x, type);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(ys ? ys[i] : 1);
  });
  return [...groups].map(([label, values]) => [label, aggregate(values, cfg.agg)]);
}

function limited(rows, cfg) {
  const series = rows.slice(0, cfg.max_items).map(([label, v]) => ({ label, value: round(v) }));
  if (rows.length > cfg.max_items && ['sum', 'count'].includes(cfg.agg) && cfg.chart_type !== 'race') {
    series.push({ label: 'Outros', value: round(rows.slice(cfg.max_items).reduce((acc, [, v]) => acc + v, 0)) });
  }
  return series;
}

function paretoOf(series, threshold) {
  const total = series.reduce((acc, s) => acc + Math.max(0, s.value), 0) || 1;
  let acc = 0;
  return series.map((s) => {
    const before = acc;
    acc += Math.max(0, s.value);
    return { ...s, cum_pct: round((acc / total) * 100, 2), highlight: (before / total) * 100 < threshold };
  });
}

function multiSeries(table, cfg) {
  const xType = table.types[cfg.x_column];
  const sType = table.types[cfg.series_column];
  const cells = new Map();
  table.columns[cfg.x_column].forEach((x, i) => {
    const key = JSON.stringify([labelOf(x, xType), labelOf(table.columns[cfg.series_column][i], sType)]);
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(cfg.agg === 'count' ? 1 : table.columns[cfg.y_column][i]);
  });
  const flat = [...cells].map(([key, values]) => { const [label, serie] = JSON.parse(key); return { label, serie, value: aggregate(values, cfg.agg) }; });
  const totals = new Map();
  for (const c of flat) totals.set(c.serie, (totals.get(c.serie) || 0) + (c.value ?? 0));
  const names = [...totals].sort((a, b) => b[1] - a[1]).map(([n]) => n);
  const keep = names.length <= MAX_SERIES ? names : names.slice(0, MAX_SERIES - 1);
  const folds = names.length > keep.length && ['sum', 'count'].includes(cfg.agg);
  const merged = new Map();
  for (const c of flat) {
    const serie = keep.includes(c.serie) ? c.serie : 'Outras';
    if (serie === 'Outras' && !folds) continue;
    const key = JSON.stringify([c.label, serie]);
    merged.set(key, (merged.get(key) || 0) + (c.value ?? 0));
  }
  const byLabel = new Map();
  const values = {};
  for (const [key, v] of merged) {
    const [label, serie] = JSON.parse(key);
    byLabel.set(label, (byLabel.get(label) || 0) + v);
    (values[label] ||= {})[serie] = round(v);
  }
  const order = ordered([...byLabel], cfg).slice(0, cfg.max_items);
  return {
    series: order.map(([label, total]) => ({ label, value: round(total), values: values[label] || {} })),
    series_names: [...keep, ...(folds ? ['Outras'] : [])],
  };
}

function scatter(table, cfg) {
  const xs = table.columns[cfg.x_column];
  const ys = table.columns[cfg.y_column];
  const sType = table.types[cfg.series_column];
  let points = [];
  xs.forEach((raw, i) => {
    const x = toNumber(raw);
    const y = toNumber(ys[i]);
    if (x === null || y === null) return;
    const p = { x, y };
    if (cfg.series_column) p.s = labelOf(table.columns[cfg.series_column][i], sType);
    points.push(p);
  });
  const total = points.length;
  if (total > MAX_POINTS) {
    const step = total / MAX_POINTS;
    points = Array.from({ length: MAX_POINTS }, (_, i) => points[Math.floor(i * step)]);
  }
  return { points, point_count: total, sampled: total > MAX_POINTS };
}

function checkMotion(table, cfg) {
  if (cfg.chart_type === 'bubble') {
    if (cfg.agg === 'count') throw new Error('As bolhas usam Soma, Média, Mínimo ou Máximo. Troque a agregação.');
    need(table, cfg.x_value_column, 'Escolha o valor do eixo X da bolha.');
    if (cfg.size_column) need(table, cfg.size_column, `Coluna de tamanho não encontrada: ${cfg.size_column}`);
  }
  if (cfg.chart_type === 'sankey' && !cfg.series_column) throw new Error('No Sankey, escolha a coluna de destino em Série.');
}

function indexGroups(labels) {
  const groups = new Map();
  labels.forEach((label, i) => {
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(i);
  });
  return groups;
}

const pick = (values, indices) => indices.map((i) => values[i]);

function bubble(table, cfg) {
  const type = table.types[cfg.x_column];
  const groups = indexGroups(table.columns[cfg.x_column].map((v) => labelOf(v, type)));
  const valueOf = (column, indices) => (column ? aggregate(pick(table.columns[column], indices), cfg.agg) : indices.length);
  const rows = [];
  for (const [label, indices] of groups) {
    const x = valueOf(cfg.x_value_column, indices);
    const y = valueOf(cfg.y_column, indices);
    if (x === null || y === null) continue;
    rows.push({ label, x, y, size: valueOf(cfg.size_column, indices) ?? 0 });
  }
  rows.sort((a, b) => b.size - a.size || compareText(a.label, b.label));
  return {
    points: rows.slice(0, cfg.max_items).map((r) => ({ label: r.label, x: round(r.x), y: round(r.y), size: round(r.size) })),
    point_count: rows.length, sampled: false,
  };
}

function sankey(table, cfg) {
  const sType = table.types[cfg.x_column];
  const tType = table.types[cfg.series_column];
  const targets = table.columns[cfg.series_column];
  const groups = indexGroups(table.columns[cfg.x_column].map((v, i) => JSON.stringify([labelOf(v, sType), labelOf(targets[i], tType)])));
  const rows = [];
  for (const [key, indices] of groups) {
    const value = cfg.agg === 'count' ? indices.length : aggregate(pick(table.columns[cfg.y_column], indices), cfg.agg);
    if (value === null || !(value > 0)) continue;
    const [source, target] = JSON.parse(key);
    rows.push({ source, target, value });
  }
  rows.sort((a, b) => b.value - a.value || compareText(a.source, b.source) || compareText(a.target, b.target));
  return { links: rows.slice(0, MAX_LINKS).map((r) => ({ ...r, value: round(r.value) })), link_count: rows.length };
}

function chart(table, cfg) {
  need(table, cfg.x_column, 'Escolha a coluna de categoria (eixo X).');
  if (cfg.agg !== 'count' || ['scatter', 'bubble'].includes(cfg.chart_type)) need(table, cfg.y_column, 'Escolha a coluna de valor (eixo Y).');
  checkMotion(table, cfg);
  const w = {
    widget_type: 'chart', title: cfg.title, chart_type: cfg.chart_type, x_column: cfg.x_column,
    y_column: cfg.agg !== 'count' ? cfg.y_column : '', series_column: cfg.series_column, agg: cfg.agg,
    row_count: table.height, series: [],
  };
  if (cfg.chart_type === 'scatter') return { ...w, ...scatter(table, cfg), agg: 'none', y_column: cfg.y_column };
  if (cfg.chart_type === 'bubble') return { ...w, ...bubble(table, cfg), x_value: cfg.x_value_column, size_column: cfg.size_column };
  if (cfg.chart_type === 'sankey') return { ...w, ...sankey(table, cfg) };
  if (cfg.series_column && SERIES_CHARTS.includes(cfg.chart_type)) return { ...w, ...multiSeries(table, cfg) };
  let series = limited(ordered(groupValues(table, cfg), cfg), cfg);
  if (cfg.chart_type === 'pareto') {
    series = paretoOf(series, cfg.pareto_threshold);
    w.threshold = cfg.pareto_threshold;
  }
  return { ...w, series };
}

// ------------------------------------------------------------------ KPI

function metricOf(values, metric) {
  if (metric === 'count') return values.length;
  if (metric === 'n_unique') return new Set(values).size;
  const nums = values.map(toNumber).filter((n) => n !== null);
  if (!nums.length) return 0;
  if (metric === 'sum') return nums.reduce((a, b) => a + b, 0);
  if (metric === 'mean') return nums.reduce((a, b) => a + b, 0) / nums.length;
  return metric === 'min' ? Math.min(...nums) : Math.max(...nums);
}

const validDate = (y, m, d) => {
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d ? t : null;
};
const DATE_FORMS = [
  (s) => { const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s); return m && validDate(+m[1], +m[2], +m[3]); },
  (s) => { const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(s); return m && validDate(+m[3], +m[2], +m[1]); },
  (s) => { const m = /^(\d{4})-(\d{1,2})$/.exec(s); return m && validDate(+m[1], +m[2], 1); },
  (s) => { const m = /^(\d{4})-(\d{1,2})-(\d{1,2}) \d{1,2}:\d{2}:\d{2}$/.exec(s); return m && validDate(+m[1], +m[2], +m[3]); },
];

function asDates(values, type) {
  if (type === 'date') return values.map((v) => (v === null || v === undefined ? null : validDate(+String(v).slice(0, 4), +String(v).slice(5, 7), +String(v).slice(8, 10))));
  const texts = values.map((v) => (v === null || v === undefined ? null : String(v).trim()));
  for (const parse of DATE_FORMS) {
    const parsed = texts.map((t) => (t === null ? null : parse(t)));
    if (parsed.every((d, i) => d || texts[i] === null)) return parsed;
  }
  throw new Error('A coluna de data tem valores que não são datas (use 2026-10-29, 2026-10 ou 29/10/2026).');
}

function truncate(d, period) {
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  if (period === 'day') return d;
  if (period === 'week') return new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * 86400000);
  if (period === 'month') return new Date(Date.UTC(y, m, 1));
  if (period === 'quarter') return new Date(Date.UTC(y, Math.floor(m / 3) * 3, 1));
  return new Date(Date.UTC(y, 0, 1));
}

const two = (n) => String(n).padStart(2, '0');

function periodLabel(d, period) {
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  if (period === 'day') return `${two(d.getUTCDate())}/${two(m + 1)}/${y}`;
  if (period === 'week') return `sem. ${two(d.getUTCDate())}/${two(m + 1)}`;
  if (period === 'month') return `${MONTHS[m]}/${y}`;
  if (period === 'quarter') return `${Math.floor(m / 3) + 1}º tri/${y}`;
  return String(y);
}

function byPeriod(table, cfg) {
  if (!cfg.date_column || !has(table, cfg.date_column)) throw new Error('Escolha a coluna de data para comparar períodos ou desenhar a tendência.');
  const dates = asDates(table.columns[cfg.date_column], table.types[cfg.date_column]);
  const groups = new Map();
  dates.forEach((d, i) => {
    if (!d) return;
    const start = truncate(d, cfg.period).getTime();
    if (!groups.has(start)) groups.set(start, []);
    groups.get(start).push(cfg.metric === 'count' ? 1 : table.columns[cfg.column][i]);
  });
  return [...groups].sort((a, b) => a[0] - b[0]).map(([start, values]) => [new Date(start), metricOf(values, cfg.metric)]);
}

function comparison(value, reference, higher) {
  const delta = value - reference;
  return {
    reference, delta,
    delta_pct: reference === 0 ? null : round((delta / Math.abs(reference)) * 100, 2),
    good: delta === 0 ? null : (delta > 0) === higher,
  };
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * p).find((x) => x >= v);
}

function kpi(table, cfg) {
  if (cfg.metric !== 'count') need(table, cfg.column, 'Escolha a coluna do indicador.');
  const source = cfg.metric === 'count' ? new Array(table.height).fill(0) : table.columns[cfg.column];
  const w = {
    widget_type: 'kpi', title: cfg.title, column: cfg.column, metric: cfg.metric, value: metricOf(source, cfg.metric),
    prefix: cfg.prefix, suffix: cfg.suffix, decimals: cfg.decimals, number_format: cfg.number_format,
    row_count: table.height, display: cfg.display,
  };
  const periods = cfg.compare === 'previous' || cfg.sparkline ? byPeriod(table, cfg) : [];
  if (cfg.compare === 'target') {
    w.compare = { mode: 'target', label: 'da meta', ...comparison(w.value, cfg.target, cfg.higher_is_better) };
  } else if (cfg.compare === 'previous') {
    if (periods.length < 2) throw new Error('A comparação com o período anterior precisa de dados em pelo menos dois períodos.');
    const [prevD, prev] = periods.at(-2);
    const [curD, cur] = periods.at(-1);
    w.value = cur;
    w.period_label = periodLabel(curD, cfg.period);
    w.compare = { mode: 'previous', label: `vs ${periodLabel(prevD, cfg.period)}`, ...comparison(cur, prev, cfg.higher_is_better) };
  }
  if (cfg.sparkline) w.trend = periods.slice(-cfg.sparkline_periods).map(([d, v]) => ({ label: periodLabel(d, cfg.period), value: round(v) }));
  if (cfg.display === 'gauge') {
    const target = cfg.compare === 'target' ? cfg.target : 0;
    w.gauge_max = cfg.gauge_max || niceMax(Math.max(w.value, target) * 1.15);
    w.target = target || null;
  }
  return w;
}

// ------------------------------------------------------------------ Venn

function truthy(values, type) {
  if (type === 'bool') return values.map((v) => v === true);
  if (type === 'int' || type === 'float') return values.map((v) => (v ?? 0) !== 0);
  return values.map((v) => v !== null && v !== undefined && TRUE.has(String(v).trim().toLowerCase()));
}

function lensArea(r1, r2, d) {
  if (d >= r1 + r2) return 0;
  if (d <= Math.abs(r1 - r2)) return Math.PI * Math.min(r1, r2) ** 2;
  const a1 = r1 ** 2 * Math.acos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1));
  const a2 = r2 ** 2 * Math.acos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2));
  const k = 0.5 * Math.sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2));
  return a1 + a2 - k;
}

function geometry(a, b, both) {
  const r1 = Math.sqrt(a / Math.PI);
  const r2 = Math.sqrt(b / Math.PI);
  const target = Math.min(both, a, b);
  let lo = Math.abs(r1 - r2);
  let hi = r1 + r2;
  for (let i = 0; i < 80; i += 1) {
    const mid = (lo + hi) / 2;
    if (lensArea(r1, r2, mid) > target) lo = mid; else hi = mid;
  }
  return { r1, r2, d: (lo + hi) / 2 };
}

function membership(table, cfg) {
  if (cfg.mode === 'flags') {
    const names = cfg.flag_columns;
    const missing = names.filter((c) => !has(table, c));
    if (missing.length) throw new Error(`Colunas não encontradas: ${missing.join(', ')}`);
    return { names, rows: names.map((c) => truthy(table.columns[c], table.types[c])), total: table.height };
  }
  const names = cfg.groups.map((g) => g.trim()).filter(Boolean);
  for (const c of [cfg.key_column, cfg.group_column]) need(table, c, 'Escolha a coluna da chave e a do grupo.');
  const groupType = table.types[cfg.group_column];
  const byKey = new Map();
  const present = new Set();
  table.columns[cfg.key_column].forEach((k, i) => {
    if (k === null || k === undefined) return;
    const raw = table.columns[cfg.group_column][i];
    const g = raw === null || raw === undefined ? null : labelOf(raw, groupType);
    if (g !== null) present.add(g);
    if (!byKey.has(k)) byKey.set(k, new Set());
    byKey.get(k).add(g);
  });
  const absent = names.filter((n) => !present.has(n));
  if (absent.length && [2, 3].includes(names.length)) throw new Error(`Grupo sem nenhuma linha: ${absent.join(', ')} (confira maiúsculas e acentos).`);
  const keys = [...byKey.values()];
  return { names, rows: names.map((n) => keys.map((set) => set.has(n))), total: keys.length };
}

function combos(n) {
  const out = [];
  const walk = (start, picked, size) => {
    if (picked.length === size) { out.push([...picked]); return; }
    for (let i = start; i < n; i += 1) walk(i + 1, [...picked, i], size);
  };
  for (let size = 1; size <= n; size += 1) walk(0, [], size);
  return out;
}

function venn(table, cfg) {
  const { names, rows, total } = membership(table, cfg);
  if (![2, 3].includes(names.length)) throw new Error('Escolha 2 ou 3 conjuntos.');
  const inAny = (i) => rows.some((r) => r[i]);
  let union = 0;
  for (let i = 0; i < total; i += 1) if (inAny(i)) union += 1;
  const regions = combos(names.length).map((sets) => {
    let count = 0;
    for (let i = 0; i < total; i += 1) if (rows.every((r, j) => r[i] === sets.includes(j))) count += 1;
    return { sets, count, pct: union ? round((count / union) * 100, 2) : 0 };
  });
  const sizes = rows.map((r) => r.filter(Boolean).length);
  const w = {
    widget_type: 'venn', title: cfg.title, sets: names.map((name, i) => ({ name, size: sizes[i] })), regions, union,
    outside: total - union, row_count: table.height, proportional: names.length === 2,
  };
  if (names.length === 2 && sizes[0] && sizes[1]) w.geometry = geometry(sizes[0], sizes[1], regions.find((r) => r.sets.length === 2).count);
  return w;
}

// ------------------------------------------------------------------ tabela

function tableWidget(table, cfg) {
  const cols = cfg.columns?.length ? cfg.columns : Object.keys(table.columns);
  const missing = cols.filter((c) => !has(table, c));
  if (missing.length) throw new Error(`Colunas não encontradas: ${missing.join(', ')}`);
  const numeric = cols.filter((c) => ['int', 'float'].includes(table.types[c]));
  let order = Array.from({ length: table.height }, (_, i) => i);
  if (cfg.sort_column) {
    const values = table.columns[cfg.sort_column];
    if (!values) throw new Error(`Coluna de ordenação não encontrada: ${cfg.sort_column}`);
    order = order.sort((a, b) => {
      const x = values[a];
      const y = values[b];
      if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1;
      if (y === null || y === undefined) return -1;
      const c = typeof x === 'number' ? x - y : compareText(x, y);
      return cfg.sort_desc ? -c : c;
    });
  }
  const w = {
    widget_type: 'table', title: cfg.title,
    columns: cols.map((name) => ({ name, numeric: numeric.includes(name) })),
    rows: order.slice(0, cfg.max_rows).map((i) => cols.map((c) => table.columns[c][i] ?? null)),
    row_count: table.height, truncated: table.height > cfg.max_rows,
  };
  if (cfg.totals && numeric.length) {
    w.totals = Object.fromEntries(numeric.map((c) => [c, table.columns[c].map(toNumber).filter((n) => n !== null).reduce((a, b) => a + b, 0)]));
  }
  return w;
}

const TOOLS = { 'bi.chart': chart, 'bi.kpi_card': kpi, 'bi.venn': venn, 'bi.table': tableWidget };

export function computeWidget(tool, cfg, table) {
  return TOOLS[tool](table, cfg);
}
