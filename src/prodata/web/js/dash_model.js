// Layout do dashboard gravado no fluxo (spec 014): página, itens e visuais fora da página.

import { api } from './api.js';
import { liveWidgets, silently, store } from './store.js';

export const PAGE_W = 1600;
export const GRID = 8;
const PAGE_HEIGHTS = { '16:9': 900, 'a4-landscape': 1131, 'a4-portrait': 2263 };
export const PAGE_SIZES = [
  ['16:9', 'Tela 16:9'], ['a4-landscape', 'A4 paisagem'], ['a4-portrait', 'A4 retrato'], ['free', 'Altura livre'],
];

export const pageHeight = (page) => (page.size === 'free' ? page.height : PAGE_HEIGHTS[page.size] || 900);

/** Caixas de BI do fluxo: cada uma publica um visual. */
export const biNodes = () => (store.workflow?.nodes || []).filter((n) => store.tools[n.type]?.category === 'bi');

export const widgetsByNode = () => Object.fromEntries(liveWidgets().map((w) => [w.node_id, w]));

/** O que a organização automática precisa saber de um visual (tipo, gráfico, nº de categorias). */
export function hintFor(nodeId, widgets = widgetsByNode()) {
  const n = store.workflow.nodes.find((k) => k.id === nodeId);
  const w = widgets[nodeId];
  if (n?.type === 'bi.kpi_card' || w?.widget_type === 'kpi') return { kind: 'kpi' };
  if (w?.widget_type === 'table') return { kind: 'table' };
  return { kind: 'chart', chart_type: w?.chart_type || n?.config?.chart_type || 'bar', categories: w?.series?.length || 0 };
}

export const rectOf = (item) => ({ x: item.x, y: item.y, w: item.w, h: item.h });
const newId = () => `d_${Math.random().toString(36).slice(2, 8)}`;

/**
 * Garante o layout: fluxos antigos ganham "KPIs no topo + 2 colunas" (RF-1408); caixas de BI novas vão
 * para o primeiro espaço livre (RF-1406); visuais de caixas excluídas saem. Não entra no desfazer.
 */
export async function ensureLayout() {
  const wf = store.workflow;
  if (!wf) return false;
  const ids = new Set(biNodes().map((n) => n.id));
  const widgets = widgetsByNode();
  if (!wf.dashboard) {
    const visuals = biNodes().map((n, i) => ({ id: newId(), node_id: n.id, order: i }));
    const page = { size: '16:9', height: 900, background: '' };
    const items = visuals.map((v) => ({ id: v.node_id, hint: hintFor(v.node_id, widgets), rect: { x: 0, y: v.order, w: 0, h: 0 } }));
    const result = items.length ? (await api.arrangeDashboard({ page, items }))['kpis-top-2'] : { positions: {}, page };
    if (store.workflow !== wf || wf.dashboard) return false;
    silently(() => {
      wf.dashboard = {
        page: result.page,
        items: visuals.map((v) => ({ id: v.id, kind: 'visual', node_id: v.node_id, ...result.positions[v.node_id], format: {}, content: '' })),
        hidden: [],
      };
    });
    return true;
  }
  const dash = wf.dashboard;
  const stale = dash.items.some((i) => i.kind === 'visual' && !ids.has(i.node_id)) || dash.hidden.some((id) => !ids.has(id));
  const placed = new Set([...dash.items.map((i) => i.node_id), ...dash.hidden]);
  const missing = [...ids].filter((id) => !placed.has(id));
  if (!stale && !missing.length) return false;
  const positions = missing.length
    ? await api.placeDashboard({ items: missing.map((id) => ({ id, hint: hintFor(id, widgets) })), occupied: dash.items.map(rectOf) })
    : {};
  if (store.workflow !== wf) return false;
  silently(() => {
    dash.items = dash.items.filter((i) => i.kind !== 'visual' || ids.has(i.node_id));
    dash.hidden = dash.hidden.filter((id) => ids.has(id));
    for (const id of missing) {
      if (positions[id]) dash.items.push({ id: newId(), kind: 'visual', node_id: id, ...positions[id], format: {}, content: '' });
    }
    growToFit(dash);
  });
  return true;
}

/** Itens além do fim da página fixa fazem a altura virar livre (RF-1463). Devolve true se cresceu. */
export function growToFit(dash) {
  const bottom = Math.max(0, ...dash.items.map((i) => i.y + i.h)) + 40;
  if (bottom <= pageHeight(dash.page)) return false;
  dash.page = { ...dash.page, size: 'free', height: Math.ceil(bottom / GRID) * GRID };
  return true;
}

/** Devolve um visual escondido para a página, no primeiro espaço livre (RF-1407). */
export async function restoreVisual(nodeId, mutate) {
  const dash = store.workflow.dashboard;
  const positions = await api.placeDashboard({ items: [{ id: nodeId, hint: hintFor(nodeId) }], occupied: dash.items.map(rectOf) });
  let grew = false;
  mutate((wf) => {
    wf.dashboard.hidden = wf.dashboard.hidden.filter((id) => id !== nodeId);
    wf.dashboard.items.push({ id: newId(), kind: 'visual', node_id: nodeId, ...positions[nodeId], format: {}, content: '' });
    grew = growToFit(wf.dashboard);
  });
  return grew;
}
