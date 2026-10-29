// Dashboard em tela cheia e cartões de visual (reutilizados pelo painel de insights).

import { renderChart, withTooltip } from './charts.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { inspect, liveWidgets, on, select, store } from './store.js';

export const AGG_LABELS = {
  sum: 'Soma', mean: 'Média', count: 'Contagem', min: 'Mínimo', max: 'Máximo', n_unique: 'Distintos',
};

let root;
let handlers = {};
const tableMode = new Set();

export function initDashboard(el, opts) {
  root = el;
  handlers = opts;
  on('execution', () => store.view === 'dashboard' && render());
  on('workflow:loaded', () => store.view === 'dashboard' && render());
  new ResizeObserver(debounce(() => store.view === 'dashboard' && render(), 120)).observe(root);
}

export function goToNode(id) {
  handlers.showDesigner?.();
  select(id);
  inspect(id);
}

export function kpiTile(w, { compact = false } = {}) {
  const exact = `${w.prefix || ''}${fmt.number(w.value, w.decimals ?? 0)}${w.suffix || ''}`;
  const shown = Math.abs(w.value) >= 1e6 ? `${w.prefix || ''}${fmt.compact(w.value)}${w.suffix || ''}` : exact;
  return h('article', { class: ['kpi', compact && 'compact'], tabindex: 0, onclick: () => goToNode(w.node_id) },
    h('div', { class: 'kpi-label' }, w.title),
    h('div', { class: 'kpi-value', title: exact }, shown),
    h('div', { class: 'kpi-foot' },
      `${AGG_LABELS[w.metric] || w.metric}${w.column && w.metric !== 'count' ? ` de ${w.column}` : ''} · ${fmt.int(w.row_count)} linhas`));
}

/**
 * Cartão de gráfico. `w`: {node_id, title, subtitle?, chart_type, series, x_column, y_column, agg}.
 * Clicar no título leva ao nó de origem.
 */
export function chartCard(w, { width, height = 260, className = '' } = {}) {
  const card = h('article', { class: ['chart-card', className] });
  const asTable = tableMode.has(w.node_id);
  const subtitle = w.subtitle || (w.agg === 'count'
    ? `Contagem por ${w.x_column}` : `${AGG_LABELS[w.agg] || w.agg} de ${w.y_column} por ${w.x_column}`);
  const redraw = () => card.replaceWith(chartCard(w, { width, height, className }));
  card.append(h('header', { class: 'chart-head' },
    h('button', { type: 'button', class: 'chart-title', title: 'Ir para o nó', onclick: () => goToNode(w.node_id) },
      h('h3', {}, w.title), h('p', { class: 'muted' }, subtitle)),
    button({ icon: asTable ? 'chart' : 'table', title: asTable ? 'Ver gráfico' : 'Ver tabela', size: 'sm', variant: 'ghost',
      onClick: () => { if (asTable) tableMode.delete(w.node_id); else tableMode.add(w.node_id); redraw(); } })));

  if (!w.series.length) {
    card.append(h('div', { class: 'empty' }, 'Sem dados para exibir.'));
  } else if (asTable) {
    card.append(h('div', { class: 'chart-body table-wrap' }, h('table', { class: 'data-table compact' },
      h('thead', {}, h('tr', {}, h('th', {}, w.x_column), h('th', { class: 'num' }, w.y_column || 'contagem'))),
      h('tbody', {}, w.series.map((s) => h('tr', {}, h('td', {}, s.label), h('td', { class: 'num' }, fmt.number(s.value))))))));
  } else {
    const body = h('div', { class: 'chart-body' }, renderChart(w.chart_type, w.series, Math.max(220, width - 34), height));
    card.append(body);
    withTooltip(card, body);
  }
  return card;
}

export function render() {
  if (!root) return;
  const widgets = liveWidgets();
  const kpis = widgets.filter((w) => w.widget_type === 'kpi');
  const charts = widgets.filter((w) => w.widget_type === 'chart');
  const head = h('header', { class: 'dash-head' },
    h('div', { class: 'dash-brand' },
      h('img', { class: 'dash-logo', src: '/static/brand/protege-escudo.svg', alt: 'Grupo Protege' }),
      h('div', {}, h('div', { class: 'dash-org' }, 'Grupo Protege'), h('h1', {}, store.workflow?.name || 'Dashboard'),
      h('p', { class: 'muted' }, store.execution
        ? `${widgets.length} visual(is) publicados pelos nós de BI · execução em ${fmt.ms(store.execution.total_elapsed_ms)}`
        : 'Execute o fluxo para gerar os visuais.'))),
    button({ icon: 'refresh', label: 'Atualizar dados', variant: 'primary', onClick: () => handlers.run() }));

  if (!widgets.length) {
    root.replaceChildren(head, h('div', { class: 'empty big' }, icon('dashboard', 28),
      h('strong', {}, 'Nenhum visual publicado'),
      h('span', {}, 'Adicione nós Chart ou KPI Card (categoria BI e indicadores) ao fluxo e execute.')));
    return;
  }
  const gridWidth = root.clientWidth - 48;
  const cols = gridWidth > 1100 ? 2 : 1;
  const cardWidth = (gridWidth - (cols - 1) * 16) / cols;
  root.replaceChildren(head,
    kpis.length ? h('section', { class: 'kpi-row' }, kpis.map((w) => kpiTile(w))) : null,
    h('section', { class: 'chart-grid', style: { gridTemplateColumns: `repeat(${cols}, 1fr)` } },
      charts.map((w) => chartCard(w, { width: cardWidth }))));
}
