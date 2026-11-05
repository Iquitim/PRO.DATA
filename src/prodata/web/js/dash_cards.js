// Cartões do dashboard (spec 014): gráfico, KPI, Venn, tabela e elementos livres.
// Sem dependência do fluxo aberto: os mesmos cartões desenham a página do programa e a do HTML exportado (spec 021).

import { gaugeChart, renderChart, sparkline, withTooltip } from './charts.js';
import { isClickChart, isCrossChart } from './dash_filters.js';
import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';

export const AGG_LABELS = {
  sum: 'Soma', mean: 'Média', count: 'Contagem', min: 'Mínimo', max: 'Máximo', n_unique: 'Distintos',
};

// Quem desenha decide o que acontece ao clicar: no HTML exportado não há fluxo para abrir.
// `cross` no cartão liga o filtro por clique: só na página do dashboard, não no painel de insights.
const env = { open: null, clickable: () => true, canFilter: () => false, selectedFor: () => null, onCategory: null };
export function setCardEnv(next) { Object.assign(env, next); }

const tableMode = new Set();

/** Fundo, borda, cantos e sombra do cartão. */
function cardStyle(f = {}) {
  return {
    background: f.background || null,
    border: f.border === false ? '0' : null,
    borderColor: f.border !== false && f.border_color ? f.border_color : null,
    borderRadius: f.radius !== undefined ? `${f.radius}px` : null,
    boxShadow: f.shadow ? 'var(--shadow-md)' : null,
  };
}

const titleStyle = (f) => ({ fontSize: f.title_size ? `${f.title_size}px` : null, textAlign: f.title_align === 'center' ? 'center' : null });

const STATUS_ICON = { good: 'check-circle', warning: 'alert', critical: 'alert' };
const OPS = { lt: (a, b) => a < b, le: (a, b) => a <= b, gt: (a, b) => a > b, ge: (a, b) => a >= b, eq: (a, b) => a === b };

/** Primeira regra de cor por faixa que vale para o valor (RF-1414). */
function ruleFor(rules, value, column = null) {
  if (typeof value !== 'number') return null;
  for (const raw of rules || []) {
    const r = { op: 'lt', value: 0, status: 'critical', column: '', ...raw };
    if (column !== null && r.column !== column) continue;
    if (OPS[r.op]?.(value, r.value)) return r.status;
  }
  return null;
}

/** Número do KPI no formato escolhido na caixa (automático, compacto, completo ou percentual). */
function kpiNumber(w, v = w.value) {
  const nf = w.number_format || 'auto';
  const pct = nf === 'percent';
  const n = pct ? v * 100 : v;
  const affix = (s) => `${w.prefix || ''}${s}${pct ? '%' : ''}${w.suffix || ''}`;
  const exact = affix(fmt.number(n, w.decimals ?? 0));
  const compact = nf === 'compact' || (nf === 'auto' && Math.abs(n) >= 1e6);
  return { exact, shown: compact ? affix(fmt.compact(n)) : exact };
}

/** Variação contra a meta ou o período anterior: seta + número + texto, com cor de status. */
function deltaBadge(w) {
  const c = w.compare;
  if (!c) return null;
  const up = c.delta > 0;
  const text = c.delta_pct === null ? kpiNumber(w, Math.abs(c.delta)).shown : `${fmt.number(Math.abs(c.delta_pct), 1)}%`;
  const state = c.good === null ? 'neutral' : c.good ? 'good' : 'critical';
  return h('div', { class: ['kpi-delta', `status-${state}`], title: `Referência: ${kpiNumber(w, c.reference).exact}` },
    c.delta === 0 ? h('span', {}, '=') : icon(up ? 'arrow-up' : 'arrow-down', 13),
    h('b', {}, c.delta === 0 ? 'igual' : text),
    h('span', {}, c.label));
}

export function kpiTile(w, { compact = false, className = '', fmt: f = {}, width = 260 } = {}) {
  const { exact, shown } = kpiNumber(w);
  const status = ruleFor(f.value_rules, w.value);
  const label = f.show_title === false ? null : h('div', { class: 'kpi-label', style: titleStyle(f) },
    status ? icon(STATUS_ICON[status], 13) : null, f.title || w.title, w.period_label ? h('span', { class: 'muted' }, ` · ${w.period_label}`) : null);
  const foot = f.show_footer === false ? null : h('div', { class: 'kpi-foot' },
    f.subtitle || `${AGG_LABELS[w.metric] || w.metric}${w.column && w.metric !== 'count' ? ` de ${w.column}` : ''} · ${fmt.int(w.row_count)} linhas`);
  const card = h('article', {
    class: ['kpi', compact && 'compact', className, f.align === 'center' && 'centered', status && `rule-${status}`], tabindex: 0, style: cardStyle(f),
    onclick: () => env.clickable() && env.open?.(w.node_id),
  });
  if (w.display === 'gauge' && !compact) {
    const body = h('div', { class: 'kpi-gauge' }, gaugeChart(w, Math.max(160, width - 36), 200, shown));
    card.append(...[label, body, deltaBadge(w), foot].filter(Boolean)); // append() nativo escreveria "null"
    withTooltip(card, body);
    return card;
  }
  const spark = !compact && w.trend?.length ? h('div', { class: 'kpi-spark' }, sparkline(w.trend, Math.max(80, width - 40), 32)) : null;
  card.append(...[label,
    h('div', { class: 'kpi-row' },
      h('div', { class: 'kpi-value', title: exact, style: { fontSize: f.value_size ? `${f.value_size}px` : null, color: f.value_color || null } }, shown),
      deltaBadge(w)),
    spark, foot].filter(Boolean));
  if (spark) withTooltip(card, spark);
  return card;
}

const SUBTITLES = {
  pareto: (w) => `Participação de cada ${w.x_column} e acumulado`,
  scatter: (w) => `${w.y_column} × ${w.x_column}`,
  funnel: (w) => `Etapas de ${w.x_column}`,
};

/** Linhas da tabela equivalente a cada visual (modo tabela: o dado nunca depende só do gráfico). */
function tableData(w) {
  if (w.widget_type === 'venn') {
    return {
      head: ['Região', 'Quantidade', '%'],
      rows: w.regions.map((r) => [r.sets.map((i) => w.sets[i].name).join(' e ') + (r.sets.length < w.sets.length ? ' (só)' : ''), fmt.int(r.count), `${fmt.number(r.pct, 1)}%`]),
    };
  }
  if (w.chart_type === 'scatter') {
    const s = w.points?.[0]?.s !== undefined;
    return { head: [...(s ? [w.series_column] : []), w.x_column, w.y_column], rows: (w.points || []).slice(0, 300).map((p) => [...(s ? [p.s] : []), fmt.number(p.x), fmt.number(p.y)]) };
  }
  if (w.series_names?.length) {
    return { head: [w.x_column, ...w.series_names, 'Total'], rows: w.series.map((c) => [c.label, ...w.series_names.map((n) => fmt.number(c.values[n] || 0)), fmt.number(c.value)]) };
  }
  if (w.chart_type === 'pareto') {
    return { head: [w.x_column, w.y_column || 'contagem', 'Acumulado'], rows: w.series.map((s) => [s.label, fmt.number(s.value), `${fmt.number(s.cum_pct, 1)}%`]) };
  }
  return { head: [w.x_column, w.y_column || 'contagem'], rows: w.series.map((s) => [s.label, fmt.number(s.value)]) };
}

/**
 * Nomes trocados no painel Formato (spec 015, RF-1502): muda só o texto exibido (eixo, legenda, tooltip e
 * modo tabela). `_keyOf` devolve o nome original, que é o que as cores por categoria usam.
 */
function relabel(w, labels) {
  if (!labels || !Object.keys(labels).length) return w;
  const rename = (name) => labels[name] ?? name;
  const back = new Map(Object.entries(labels).map(([from, to]) => [to, from]));
  const out = { ...w, _keyOf: (name) => back.get(name) ?? name };
  if (w.series) {
    out.series = w.series.map((s) => ({
      ...s,
      label: rename(s.label),
      values: s.values && Object.fromEntries(Object.entries(s.values).map(([k, v]) => [rename(k), v])),
    }));
  }
  if (w.series_names) out.series_names = w.series_names.map(rename);
  if (w.sets) out.sets = w.sets.map((set) => ({ ...set, name: rename(set.name) }));
  if (w.points) out.points = w.points.map((pt) => (pt.s === undefined ? pt : { ...pt, s: rename(pt.s) }));
  return out;
}

/**
 * Cartão de gráfico. `w`: widget publicado pela caixa (Chart ou Venn). Clicar no título leva ao nó de
 * origem. `actions`: botões extras no cabeçalho; `fmt`: formato do visual.
 */
export function chartCard(original, { width, height = 260, className = '', actions = [], fmt: f = {}, cross = false } = {}) {
  const w = relabel(original, f.labels);
  const card = h('article', { class: ['chart-card', className], style: cardStyle(f) });
  const asTable = tableMode.has(w.node_id);
  const subtitle = f.subtitle || w.subtitle || (w.widget_type === 'venn' ? `${fmt.int(w.union)} em pelo menos um conjunto`
    : SUBTITLES[w.chart_type]?.(w)
      || (w.agg === 'count' ? `Contagem por ${w.x_column}` : `${AGG_LABELS[w.agg] || w.agg} de ${w.y_column} por ${w.x_column}`)
      + (w.series_column ? ` e ${w.series_column}` : ''));
  const redraw = () => card.replaceWith(chartCard(original, { width, height, className, actions, fmt: f, cross }));
  const showTitle = f.show_title !== false;
  const showSub = f.show_subtitle !== false;
  card.append(h('header', { class: ['chart-head', !showTitle && !showSub && 'bare'] },
    showTitle || showSub ? h('button', { type: 'button', class: 'chart-title', title: env.open ? 'Ir para o nó' : null, style: titleStyle(f), onclick: () => env.open?.(w.node_id) },
      showTitle ? h('h3', { style: { fontSize: f.title_size ? `${f.title_size}px` : null } }, f.title || w.title) : null,
      showSub ? h('p', { class: 'muted' }, subtitle) : null) : h('span', { class: 'grow' }),
    h('div', { class: 'chart-actions' }, actions,
      button({ icon: asTable ? 'chart' : 'table', title: asTable ? 'Ver gráfico' : 'Ver tabela', size: 'sm', variant: 'ghost',
        onClick: () => { if (asTable) tableMode.delete(w.node_id); else tableMode.add(w.node_id); redraw(); } }))));

  const empty = w.widget_type === 'venn' ? !w.union : !(w.series?.length || w.points?.length);
  if (empty) {
    card.append(h('div', { class: 'empty' }, 'Sem dados para exibir.'));
  } else if (asTable) {
    const t = tableData(w);
    card.append(h('div', { class: 'chart-body table-wrap' }, h('table', { class: 'data-table compact' },
      h('thead', {}, h('tr', {}, t.head.map((c, i) => h('th', { class: i ? 'num' : null }, c)))),
      h('tbody', {}, t.rows.map((r) => h('tr', {}, r.map((v, i) => h('td', { class: i ? 'num' : null }, v))))))));
  } else {
    const canCross = cross && isCrossChart(w);
    const filterable = cross && isClickChart(w) && env.canFilter(original);
    const body = h('div', { class: 'chart-body' }, renderChart(w.chart_type, w.series || [], Math.max(220, width - 34), height, {
      ...f, _keyOf: w._keyOf, _filterable: filterable, _selected: canCross ? env.selectedFor(original) : null,
    }, w));
    if (filterable) {
      body.addEventListener('click', (e) => {
        const mark = e.target.closest('[data-cat]');
        if (mark) env.onCategory(original, mark.dataset.cat, e.ctrlKey || e.metaKey);
      });
    }
    card.append(body);
    withTooltip(card, body);
  }
  return card;
}

/** Tabela formatada (ferramenta Table): totais, linhas alternadas e cores por faixa com ícone. */
export function tableCard(w, { className = '', fmt: f = {}, actions = [] } = {}) {
  const card = h('article', { class: ['chart-card', 'table-card', className, f.compact && 'dense', f.zebra === false && 'plain'], style: cardStyle(f) });
  const showTitle = f.show_title !== false;
  const showSub = f.show_subtitle !== false;
  card.append(h('header', { class: ['chart-head', !showTitle && !showSub && 'bare'] },
    showTitle || showSub ? h('button', { type: 'button', class: 'chart-title', title: env.open ? 'Ir para o nó' : null, style: titleStyle(f), onclick: () => env.open?.(w.node_id) },
      showTitle ? h('h3', { style: { fontSize: f.title_size ? `${f.title_size}px` : null } }, f.title || w.title) : null,
      showSub ? h('p', { class: 'muted' }, f.subtitle || `${fmt.int(Math.min(w.rows.length, w.row_count))} de ${fmt.int(w.row_count)} linhas`) : null) : h('span', { class: 'grow' }),
    h('div', { class: 'chart-actions' }, actions)));
  const cellOf = (col, v) => {
    const status = col.numeric ? ruleFor(f.rules, v, col.name) : null;
    return h('td', { class: [col.numeric && 'num', status && `cell-${status}`] },
      status ? icon(STATUS_ICON[status], 12) : null, col.numeric && typeof v === 'number' ? fmt.number(v) : (v ?? '—'));
  };
  card.append(h('div', { class: 'chart-body table-wrap' }, h('table', { class: 'data-table compact dash-table' },
    h('thead', {}, h('tr', {}, w.columns.map((c) => h('th', { class: c.numeric ? 'num' : null }, c.name)))),
    h('tbody', {}, w.rows.map((r) => h('tr', {}, r.map((v, i) => cellOf(w.columns[i], v))))),
    w.totals ? h('tfoot', {}, h('tr', {}, w.columns.map((c, i) => h('td', { class: c.numeric ? 'num' : null },
      c.numeric ? fmt.number(w.totals[c.name]) : i === 0 ? 'Total' : '')))) : null)));
  return card;
}

/** Cartão certo para cada widget publicado (dashboard e painel de insights). */
export function visualCard(w, opts = {}) {
  if (w.widget_type === 'message') return messageCard(w);
  if (w.widget_type === 'kpi') return kpiTile(w, opts);
  if (w.widget_type === 'table') return tableCard(w, opts);
  return chartCard(w, opts);
}

/** Texto, imagem e forma (RF-1440..RF-1442). O texto entra como texto puro, nunca como HTML. */
export function freeEl(item, { editing }) {
  const f = item.format || {};
  if (item.kind === 'text') {
    return h('div', {
      class: 'dash-text',
      style: {
        fontSize: `${f.size || 16}px`, fontWeight: f.bold ? '700' : null, fontStyle: f.italic ? 'italic' : null,
        color: f.color || null, textAlign: f.align || null, background: f.background || null,
        justifyContent: { middle: 'center', bottom: 'flex-end' }[f.vertical] || null,
      },
    }, h('span', {}, item.content || (editing ? 'Texto vazio' : '')));
  }
  if (item.kind === 'image') {
    if (!item.content) return editing ? h('div', { class: 'dash-placeholder' }, icon('file', 22), h('span', {}, 'Escolha uma imagem no painel Formato')) : null;
    return h('img', {
      class: 'dash-image', src: item.content, alt: '', draggable: false,
      style: { objectFit: f.fit || 'contain', opacity: f.opacity !== undefined ? f.opacity / 100 : null, borderRadius: f.radius ? `${f.radius}px` : null },
    });
  }
  if (item.kind === 'shape') {
    const opacity = f.opacity !== undefined ? f.opacity / 100 : null;
    if (f.shape === 'line') {
      const horizontal = item.w >= item.h;
      return h('div', { class: ['dash-line', horizontal ? 'h' : 'v'], style: { opacity } },
        h('span', { style: { [horizontal ? 'borderTopWidth' : 'borderLeftWidth']: `${f.stroke_width ?? 1}px`, borderColor: f.stroke || null } }));
    }
    return h('div', {
      class: 'dash-shape',
      style: {
        background: f.fill || null, opacity, borderRadius: `${f.radius ?? 12}px`,
        borderWidth: `${f.stroke_width ?? 1}px`, borderColor: f.stroke || null,
      },
    });
  }
  return null;
}

/** Visual que não pôde ser calculado com os filtros de agora (ex.: um só período para comparar). */
function messageCard(w) {
  return h('article', { class: 'chart-card fill' },
    h('header', { class: 'chart-head' }, h('h3', {}, w.title)),
    h('div', { class: 'empty' }, w.message));
}

/** Altura do cabeçalho do cartão: o resto da altura do item é do gráfico. */
export function chartChrome(f) {
  const title = f.show_title === false ? 0 : Math.round((f.title_size || 14) * 1.45);
  const sub = f.show_subtitle === false ? 0 : 18;
  return 30 + (title || sub ? title + sub + 12 : 24);
}

/** Posiciona um conteúdo na página. */
export function placeItem(item, content, extra = null, attrs = {}) {
  return h('div', {
    ...attrs,
    class: ['dash-item', `kind-${item.kind}`, attrs.class],
    dataset: { id: item.id },
    style: { left: `${item.x}px`, top: `${item.y}px`, width: `${item.w}px`, height: `${item.h}px` },
  }, content, extra);
}
