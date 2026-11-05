// Encaixe e guias do modo Editar: só contas sobre retângulos, mais o desenho das guias.

import { GRID, PAGE_W, pageHeight } from './dash_model.js';
import { dash, els, ui } from './dash_state.js';
import { h } from './dom.js';

export const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function bbox(rects) {
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  return { x, y, w: Math.max(...rects.map((r) => r.x + r.w)) - x, h: Math.max(...rects.map((r) => r.y + r.h)) - y };
}

/** Linhas de referência: bordas e centro da página, margens e bordas/centros dos outros itens. */
function targets(others) {
  const ph = pageHeight(dash().page);
  const xs = [0, 40, PAGE_W / 2, PAGE_W - 40, PAGE_W];
  const ys = [0, 40, ph / 2, ph - 40, ph];
  for (const o of others) {
    xs.push(o.x, o.x + o.w / 2, o.x + o.w);
    ys.push(o.y, o.y + o.h / 2, o.y + o.h);
  }
  return { xs, ys };
}

/** Melhor encaixe de um conjunto de arestas numa lista de alvos: { offset, at } ou null. */
function nearest(edges, values, threshold) {
  let best = null;
  for (const edge of edges) {
    for (const v of values) {
      const d = v - edge;
      if (Math.abs(d) <= threshold && (!best || Math.abs(d) < Math.abs(best.offset))) best = { offset: d, at: v };
    }
  }
  return best;
}

const toGrid = (v) => Math.round(v / GRID) * GRID;

export function snapBox(box, others, free) {
  if (free) return { dx: 0, dy: 0, guides: [] };
  const t = targets(others);
  const threshold = 6 / ui.scale;
  const sx = nearest([box.x, box.x + box.w / 2, box.x + box.w], t.xs, threshold);
  const sy = nearest([box.y, box.y + box.h / 2, box.y + box.h], t.ys, threshold);
  const guides = [];
  if (sx) guides.push({ axis: 'x', at: sx.at });
  if (sy) guides.push({ axis: 'y', at: sy.at });
  return {
    dx: sx ? sx.offset : toGrid(box.x) - box.x,
    dy: sy ? sy.offset : toGrid(box.y) - box.y,
    guides,
  };
}

const MIN_W = 48;

const MIN_H = 16;

export function resizeRect(r, dir, dx, dy, others, free) {
  const t = targets(others);
  const threshold = 6 / ui.scale;
  const guides = [];
  const snap = (v, list, axis) => {
    if (free) return v;
    const s = nearest([v], list, threshold);
    if (s) { guides.push({ axis, at: s.at }); return s.at; }
    return toGrid(v);
  };
  let { x, y } = r;
  let right = r.x + r.w;
  let bottom = r.y + r.h;
  if (dir.includes('e')) right = Math.max(x + MIN_W, snap(right + dx, t.xs, 'x'));
  if (dir.includes('w')) x = Math.min(right - MIN_W, Math.max(0, snap(r.x + dx, t.xs, 'x')));
  if (dir.includes('s')) bottom = Math.max(y + MIN_H, snap(bottom + dy, t.ys, 'y'));
  if (dir.includes('n')) y = Math.min(bottom - MIN_H, Math.max(0, snap(r.y + dy, t.ys, 'y')));
  right = Math.min(right, PAGE_W);
  return { rect: { x: Math.round(x), y: Math.round(y), w: Math.round(right - x), h: Math.round(bottom - y) }, guides };
}

export function drawGuides(guides) {
  for (const g of els.guides || []) g.remove();
  els.guides = guides.map((g) => h('div', {
    class: ['dash-guide', g.axis === 'x' ? 'v' : 'h'],
    style: g.axis === 'x' ? { left: `${g.at}px` } : { top: `${g.at}px` },
  }));
  els.page?.append(...els.guides);
}
