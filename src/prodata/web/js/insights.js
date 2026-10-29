// Painel de insights (abaixo do canvas): KPIs e gráficos dos nós de BI e um
// gráfico automático para cada Summarize executado.

import { api } from './api.js';
import { AGG_LABELS, goToNode, kpiTile, visualCard } from './dashboard.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { panelControls } from './layout.js';
import { liveWidgets, nodeResult, on, store } from './store.js';

const CARD_WIDTH = 380;
const SUMMARY_ROWS = 30;
const NUMERIC = new Set(['Int64', 'Float64']);

let root;
let body;
let count;
let seq = 0;

export function initInsights(el, opts) {
  root = el;
  count = h('span', { class: 'count', hidden: true });
  body = h('div', { class: 'insights-body' });
  root.replaceChildren(
    h('header', { class: 'insights-head' },
      h('div', { class: 'insights-title' }, icon('chart', 15), 'Gráficos e resumos', count),
      h('div', { class: 'row gap-0' },
        button({ icon: 'dashboard', title: 'Abrir Dashboard', size: 'sm', variant: 'ghost', onClick: opts.openDashboard }),
        panelControls('insights'))),
    body);
  on('execution', render);
  // Caixa de BI excluída ou desativada: o visual some na hora (spec 010, RF-1005).
  on('workflow:changed', ({ structural }) => structural && render());
  on('workflow:loaded', render);
  on('layout', render);
  new ResizeObserver(debounce(() => render(), 150)).observe(root);
}

function isFresh(id) {
  const res = nodeResult(id);
  return res && ['executed', 'cached'].includes(res.status);
}

/** Converte a saída de um Summarize em widget de gráfico (ou de indicadores, sem agrupamento). */
async function summaryWidget(n) {
  const columns = nodeResult(n.id).anchors.out?.columns || [];
  const groups = (n.config.group_by || []).filter((g) => columns.some((c) => c.name === g));
  const numeric = columns.filter((c) => NUMERIC.has(c.type) && !groups.includes(c.name));
  if (!numeric.length) return null;
  const value = numeric[0].name;
  const page = await api.results(store.workflow.id, n.id, 'out', {
    limit: groups.length ? SUMMARY_ROWS : 1, sort_col: value, sort_desc: true,
  });

  if (!groups.length) {
    const row = page.rows[0] || {};
    return { kind: 'totals', node_id: n.id, title: n.label, values: numeric.map((c) => [c.name, row[c.name]]) };
  }
  const series = page.rows.map((r) => ({
    label: groups.map((g) => r[g] ?? '(vazio)').join(' · '),
    value: Number(r[value]) || 0,
  }));
  const agg = (n.config.aggregations || []).find((a) => (a.alias || `${a.agg}_${a.column}`) === value);
  return {
    kind: 'chart',
    node_id: n.id,
    title: n.label || 'Resumo',
    subtitle: `${agg ? `${AGG_LABELS[agg.agg] || agg.agg} · ` : ''}${value} por ${groups.join(', ')}`
      + (page.filtered_count > SUMMARY_ROWS ? ` · top ${SUMMARY_ROWS} de ${fmt.int(page.filtered_count)}` : ''),
    chart_type: series.length > 8 ? 'hbar' : 'bar',
    x_column: groups.join(' · '),
    y_column: value,
    series,
  };
}

function totalsCard(w) {
  return h('article', { class: 'kpi compact totals', tabindex: 0, onclick: () => goToNode(w.node_id) },
    h('div', { class: 'kpi-label' }, w.title),
    h('dl', { class: 'totals-list' }, w.values.map(([k, v]) => h('div', {},
      h('dt', {}, k), h('dd', {}, typeof v === 'number' ? fmt.compact(v) : String(v ?? '—'))))));
}

export async function render() {
  if (!root || !store.workflow || !root.isConnected || root.closest('#panelStore')) return;
  const mine = ++seq;
  const widgets = new Map(liveWidgets().map((w) => [w.node_id, w]));
  const summaries = store.workflow.nodes.filter((n) => n.type === 'transform.summarize' && isFresh(n.id));
  const built = await Promise.all(summaries.map((n) => summaryWidget(n).catch(() => null)));
  if (mine !== seq) return; // uma execução mais nova já está desenhando
  const bySummary = new Map(summaries.map((n, i) => [n.id, built[i]]));

  // Embaixo: faixa horizontal, altura do painel. Nas laterais: pilha vertical, largura do painel.
  const vertical = Boolean(root.closest('.slot-side'));
  const width = vertical ? Math.max(240, root.clientWidth - 24) : CARD_WIDTH;
  const chartHeight = vertical ? 220 : Math.max(130, root.clientHeight - 128);
  const cards = [];
  for (const n of store.workflow.nodes) {
    const w = widgets.get(n.id) || bySummary.get(n.id);
    if (!w) continue;
    if (w.widget_type === 'kpi') cards.push(kpiTile(w, { compact: true }));
    else if (w.kind === 'totals') cards.push(totalsCard(w));
    else cards.push(visualCard(w, { width, height: chartHeight, className: 'insight' }));
  }

  count.hidden = !cards.length;
  count.textContent = cards.length;
  body.replaceChildren(cards.length
    ? h('div', { class: 'insights-strip' }, cards)
    : h('div', { class: 'empty' }, icon('chart', 20),
      h('strong', {}, store.execution ? 'Nenhum gráfico ou resumo' : 'Execute o fluxo'),
      h('span', {}, 'Nós Chart, KPI Card e Summarize aparecem aqui após a execução.')));
}
