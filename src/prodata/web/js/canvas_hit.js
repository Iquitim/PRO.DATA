// O que está sob o cursor ou sob uma caixa: qual ligação passa por ali e se o espaço está livre.

import { NODE_MIN_H, NODE_W, edgeBend, nodeHeight, portPoint } from './canvas_geometry.js';
import { els, view } from './canvas_state.js';
import { h } from './dom.js';
import { store, toolOf } from './store.js';

/**
 * Pontos de cada fio calculados pela fórmula da curva (mesma de `curve`), sem consultar o SVG.
 * getTotalLength/getPointAtLength forçavam layout a cada evento: arrastar uma caixa solta custava
 * ~6 ms por movimento (38 ms numa CPU 4x mais lenta) e a caixa ficava para trás do cursor.
 */
function edgeSamples(steps) {
  const byId = new Map(store.workflow.nodes.map((n) => [n.id, n]));
  const out = [];
  for (const e of store.workflow.edges) {
    const s = byId.get(e.source);
    const t = byId.get(e.target);
    if (!s || !t) continue;
    const a = portPoint(s, e.sourceHandle, true);
    const b = portPoint(t, e.targetHandle, false);
    const dx = edgeBend(a, b);
    const c1 = { x: a.x + dx, y: a.y };
    const c2 = { x: b.x - dx, y: b.y };
    const points = [];
    for (let i = 1; i < steps; i += 1) {
      const u = i / steps;
      const v = 1 - u;
      const k0 = v * v * v; const k1 = 3 * v * v * u; const k2 = 3 * v * u * u; const k3 = u * u * u;
      points.push({ x: k0 * a.x + k1 * c1.x + k2 * c2.x + k3 * b.x, y: k0 * a.y + k1 * c1.y + k2 * c2.y + k3 * b.y });
    }
    out.push({ edge: e, points });
  }
  return out;
}

export function edgeNear(world, tolerance = 16) {
  let best = null;
  for (const { edge, points } of edgeSamples(24)) {
    for (const p of points) {
      const d = Math.hypot(p.x - world.x, p.y - world.y);
      if (d < tolerance / view.zoom && (!best || d < best.d)) best = { id: edge.id, d };
    }
  }
  return best?.id || null;
}

/**
 * Fio que atravessa o retângulo de um nó (inserção entre duas caixas).
 * Ignora fios ligados ao próprio nó; vence o fio com mais pontos dentro do retângulo.
 */
export function edgeThroughRect(rect, ignoreNodeId = null, pad = 12) {
  let best = null;
  for (const { edge, points } of edgeSamples(40)) {
    if (edge.source === ignoreNodeId || edge.target === ignoreNodeId) continue;
    let hits = 0;
    for (const p of points) {
      if (p.x >= rect.x - pad && p.x <= rect.x + rect.w + pad && p.y >= rect.y - pad && p.y <= rect.y + rect.h + pad) hits += 1;
    }
    if (hits && (!best || hits > best.hits)) best = { id: edge.id, hits };
  }
  return best?.id || null;
}

/** Área sem nós nem fios por baixo (para posicionar nós criados automaticamente). */
export function isAreaFree(x, y, w = NODE_W, hgt = NODE_MIN_H) {
  const pad = 20;
  const overlapsNode = store.workflow.nodes.some((n) => n.x < x + w + pad && n.x + NODE_W + pad > x
    && n.y < y + hgt + pad && n.y + nodeHeight(n) + pad > y);
  return !overlapsNode && !edgeThroughRect({ x, y, w, h: hgt });
}

/** Só nós soltos (sem conexões) e com entrada e saída de dados podem ser inseridos num fio. */
export function canSplice(n) {
  const spec = toolOf(n);
  return Boolean(spec?.inputs.some((p) => p.kind !== 'model') && spec?.outputs.some((p) => p.kind !== 'model'))
    && !store.workflow.edges.some((e) => e.source === n.id || e.target === n.id);
}

export function highlightEdge(id) {
  for (const g of els.svg.querySelectorAll('g.edge')) g.classList.toggle('drop-target', g.dataset.edge === id);
}
