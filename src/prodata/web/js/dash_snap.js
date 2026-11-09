// Encaixe e guias do modo Editar: só contas sobre retângulos, mais o desenho das guias e das medidas iguais.

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

const SAME = 0.5;
const AXES = { x: ['x', 'w', 'y', 'h'], y: ['y', 'h', 'x', 'w'] };

/** Itens na mesma linha (ou coluna) do retângulo, em ordem no eixo. */
function lane(box, others, axis) {
  const [pos, , cross, span] = AXES[axis];
  return others.filter((o) => !overlaps(box, o) && box[cross] < o[cross] + o[span] && o[cross] < box[cross] + box[span])
    .sort((a, b) => a[pos] - b[pos]);
}

/** Posições em que o retângulo repete um espaço já usado na faixa, ou fica no meio de dois vizinhos. */
function gapStops(box, others, axis) {
  const [pos, size] = AXES[axis];
  const row = lane(box, others, axis);
  const stops = [];
  const gaps = row.slice(1).map((o, i) => o[pos] - row[i][pos] - row[i][size]).filter((g) => g > 0);
  for (const o of row) for (const g of gaps) stops.push(o[pos] + o[size] + g, o[pos] - g - box[size]);
  row.slice(1).forEach((o, i) => {
    const room = o[pos] - row[i][pos] - row[i][size];
    if (room > box[size]) stops.push(row[i][pos] + row[i][size] + (room - box[size]) / 2);
  });
  return stops;
}

/** Marca os espaços iguais ao do retângulo na faixa dele. */
function gapMarks(box, others, axis) {
  const [pos, size, cross, span] = AXES[axis];
  const row = [box, ...lane(box, others, axis)].sort((a, b) => a[pos] - b[pos]);
  const pairs = row.slice(1).map((b, i) => ({ a: row[i], b, gap: b[pos] - row[i][pos] - row[i][size] })).filter((p) => p.gap > 0);
  const same = (g) => pairs.filter((p) => Math.abs(p.gap - g) <= SAME);
  const match = pairs.filter((p) => p.a === box || p.b === box).map((p) => p.gap).find((g) => same(g).length > 1);
  if (match === undefined) return [];
  return same(match).map(({ a, b }) => ({
    measure: 'gap', axis, from: a[pos] + a[size], to: b[pos], value: Math.round(match),
    at: (Math.max(a[cross], b[cross]) + Math.min(a[cross] + a[span], b[cross] + b[span])) / 2,
  }));
}

/** O encaixe mais perto, entre borda ou centro de outro item e espaço igual. */
function closest(line, gap) {
  return line && (!gap || Math.abs(line.offset) <= Math.abs(gap.offset)) ? line : gap;
}

export function snapBox(box, others, free) {
  if (free) return { dx: 0, dy: 0, guides: [] };
  const t = targets(others);
  const threshold = 6 / ui.scale;
  const gapX = nearest([box.x], gapStops(box, others, 'x'), threshold);
  const gapY = nearest([box.y], gapStops(box, others, 'y'), threshold);
  const lineX = nearest([box.x, box.x + box.w / 2, box.x + box.w], t.xs, threshold);
  const lineY = nearest([box.y, box.y + box.h / 2, box.y + box.h], t.ys, threshold);
  const sx = closest(lineX, gapX);
  const sy = closest(lineY, gapY);
  const dx = sx ? sx.offset : toGrid(box.x) - box.x;
  const dy = sy ? sy.offset : toGrid(box.y) - box.y;
  const placed = { ...box, x: box.x + dx, y: box.y + dy };
  const guides = [...gapMarks(placed, others, 'x'), ...gapMarks(placed, others, 'y')];
  if (sx && sx === lineX) guides.push({ axis: 'x', at: sx.at });
  if (sy && sy === lineY) guides.push({ axis: 'y', at: sy.at });
  return { dx, dy, guides };
}

const MIN_W = 48;

const MIN_H = 16;

/** Marca o item e todos os que têm a mesma largura (x) ou altura (y). */
function sizeMarks(rect, others, axis) {
  const [pos, size, cross] = AXES[axis];
  const same = others.filter((o) => Math.abs(o[size] - rect[size]) <= SAME);
  if (!same.length) return [];
  return [rect, ...same].map((o) => ({ measure: 'size', axis, from: o[pos], to: o[pos] + o[size], at: o[cross] + 14, value: Math.round(rect[size]) }));
}

export function resizeRect(r, dir, dx, dy, others, free) {
  const t = targets(others);
  const threshold = 6 / ui.scale;
  let guides = [];
  const edge = { x: null, y: null }; // distância do encaixe por borda em cada eixo
  const snap = (v, list, axis) => {
    if (free) return v;
    const s = nearest([v], list, threshold);
    if (s) { guides.push({ axis, at: s.at }); edge[axis] = Math.abs(s.offset); return s.at; }
    return toGrid(v);
  };
  /** Medida de outro item, se ficar mais perto do que o encaixe por borda. */
  const sizeOf = (raw, axis) => {
    if (free) return null;
    const hit = nearest([raw], others.map((o) => o[AXES[axis][1]]), threshold);
    if (!hit || (edge[axis] !== null && Math.abs(hit.offset) >= edge[axis])) return null;
    guides = guides.filter((g) => g.axis !== axis);
    return hit.at;
  };
  let { x, y } = r;
  let right = r.x + r.w;
  let bottom = r.y + r.h;
  if (dir.includes('e')) {
    right = Math.max(x + MIN_W, snap(right + dx, t.xs, 'x'));
    const w = sizeOf(r.w + dx, 'x');
    if (w !== null) right = x + w;
  }
  if (dir.includes('w')) {
    x = Math.min(right - MIN_W, Math.max(0, snap(r.x + dx, t.xs, 'x')));
    const w = sizeOf(r.w - dx, 'x');
    if (w !== null) x = Math.max(0, right - w);
  }
  if (dir.includes('s')) {
    bottom = Math.max(y + MIN_H, snap(bottom + dy, t.ys, 'y'));
    const size = sizeOf(r.h + dy, 'y');
    if (size !== null) bottom = y + size;
  }
  if (dir.includes('n')) {
    y = Math.min(bottom - MIN_H, Math.max(0, snap(r.y + dy, t.ys, 'y')));
    const size = sizeOf(r.h - dy, 'y');
    if (size !== null) y = Math.max(0, bottom - size);
  }
  right = Math.min(right, PAGE_W);
  const rect = { x: Math.round(x), y: Math.round(y), w: Math.round(right - x), h: Math.round(bottom - y) };
  if (!free && (dir.includes('e') || dir.includes('w'))) guides.push(...sizeMarks(rect, others, 'x'));
  if (!free && (dir.includes('n') || dir.includes('s'))) guides.push(...sizeMarks(rect, others, 'y'));
  return { rect, guides };
}

function measureEl(g) {
  const across = g.axis === 'x';
  return h('div', {
    class: ['dash-measure', g.measure, g.axis],
    style: across
      ? { left: `${g.from}px`, top: `${g.at}px`, width: `${g.to - g.from}px` }
      : { top: `${g.from}px`, left: `${g.at}px`, height: `${g.to - g.from}px` },
  }, h('b', {}, String(g.value)));
}

export function drawGuides(guides) {
  for (const g of els.guides || []) g.remove();
  els.guides = guides.map((g) => (g.measure ? measureEl(g) : h('div', {
    class: ['dash-guide', g.axis === 'x' ? 'v' : 'h'],
    style: g.axis === 'x' ? { left: `${g.at}px` } : { top: `${g.at}px` },
  })));
  els.page?.append(...els.guides);
}
