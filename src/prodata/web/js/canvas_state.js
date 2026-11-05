// Estado compartilhado pelas partes do canvas: posição da tela, elementos e o que muda a cada desenho.

export const view = { x: 40, y: 30, zoom: 1 };
export const els = {};
export const nodeEls = new Map(); // id -> { el, key }
export const state = {
  handlers: {},
  held: new Map(), // recalculado a cada desenho
  render: () => {},
  connecting: () => null, // o fio sendo puxado, enquanto o gesto durar
};

export function toWorld(clientX, clientY) {
  const r = els.viewport.getBoundingClientRect();
  return { x: (clientX - r.left - view.x) / view.zoom, y: (clientY - r.top - view.y) / view.zoom };
}

export function viewportCenter() {
  const r = els.viewport.getBoundingClientRect();
  return toWorld(r.left + r.width / 2, r.top + r.height / 2);
}
