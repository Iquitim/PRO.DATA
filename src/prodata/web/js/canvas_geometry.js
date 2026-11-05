// Medidas das caixas e curvas das ligações: só contas, sem tocar na tela.

import { toolOf, visibleInputs } from './store.js';

export const NODE_W = 188;

export const NODE_MIN_H = 56;

const PORT_GAP = 18;

/** Altura do cartão: cresce com o número de portas para que nenhuma se sobreponha. */
export function nodeHeight(n) {
  const spec = toolOf(n);
  const ports = Math.max(n ? visibleInputs(n).length : 0, spec?.outputs.length || 0);
  return Math.max(NODE_MIN_H, (ports + 1) * PORT_GAP);
}

export function portPoint(n, portId, output) {
  const ports = (output ? toolOf(n)?.outputs : visibleInputs(n)) || [];
  const idx = Math.max(0, ports.findIndex((p) => p.id === portId));
  return { x: n.x + (output ? NODE_W : 0), y: n.y + (nodeHeight(n) * (idx + 1)) / (ports.length + 1) };
}

/** Quanto o fio sai reto das portas. Fios muito verticais ganham mais, para chegarem de frente na porta. */
const ARROW_GAP = 9; // distância até o centro da porta, para a ponta não entrar nela

const ARROW_LENGTH = 5;

const ARROW_WIDTH = 4;

export const edgeBend = (a, b) => Math.max(40, Math.abs(b.x - a.x) * 0.5, Math.min(Math.abs(b.y - a.y) * 0.35, 110));

export function curve(a, b) {
  const dx = edgeBend(a, b);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

/** Seta na chegada: fica sobre o próprio fio e aponta para onde ele está indo, de qualquer ângulo. */
export function edgeArrow(a, b) {
  const dx = edgeBend(a, b);
  const at = (u) => {
    const v = 1 - u;
    const k1 = 3 * v * v * u; const k2 = 3 * v * u * u; const k3 = u * u * u; const k0 = v * v * v;
    return {
      x: k0 * a.x + k1 * (a.x + dx) + k2 * (b.x - dx) + k3 * b.x,
      y: k0 * a.y + k1 * a.y + k2 * b.y + k3 * b.y,
    };
  };
  const gap = (p, q) => Math.hypot(p.x - q.x, p.y - q.y);
  const walk = (from, distance, start) => {
    const STEP = 0.002;
    for (let u = start - STEP; u > 0; u -= STEP) {
      if (gap(at(u), from) < distance) continue;
      // Em fios longos, um passo anda vários pixels: refina até a distância certa.
      let far = u;
      let near = Math.min(start, u + STEP);
      for (let i = 0; i < 8; i += 1) {
        const mid = (far + near) / 2;
        if (gap(at(mid), from) >= distance) far = mid; else near = mid;
      }
      return { p: at(far), u: far };
    }
    return { p: at(0), u: 0 };
  };
  const tip = walk(b, ARROW_GAP, 1);
  const back = walk(tip.p, ARROW_LENGTH, tip.u).p;
  const size = gap(tip.p, back) || 1;
  const ux = (tip.p.x - back.x) / size;
  const uy = (tip.p.y - back.y) / size;
  const wing = (side) => `${(back.x - uy * side * ARROW_WIDTH).toFixed(1)} ${(back.y + ux * side * ARROW_WIDTH).toFixed(1)}`;
  return `M ${wing(1)} L ${tip.p.x.toFixed(1)} ${tip.p.y.toFixed(1)} L ${wing(-1)}`;
}

export function curveMid(a, b) {
  const dx = edgeBend(a, b);
  // Ponto t=0.5 da Bézier cúbica: (P0 + 3P1 + 3P2 + P3) / 8
  return {
    x: (a.x + 3 * (a.x + dx) + 3 * (b.x - dx) + b.x) / 8,
    y: (a.y + 3 * a.y + 3 * b.y + b.y) / 8,
  };
}
