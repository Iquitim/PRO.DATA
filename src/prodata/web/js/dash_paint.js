// Pincel do dashboard (spec 032): leva o formato de uma caixa para outras.

import { formatFields, formatKind } from './dash_panel.js';
import { commitLayout, els, itemById, page, ui } from './dash_state.js';

/** O que descreve o próprio visual e por isso fica nele. */
const OWN = new Set(['title', 'subtitle', 'labels', 'x_title', 'y_title', 'y_min', 'y_max']);

const copyable = (kind) => formatFields(kind).map((f) => f.name).filter((name) => !OWN.has(name));

function redraw() {
  els.panelKey = null; // o botão do painel troca de texto
  page.render();
}

export function startPaint(item) {
  ui.paint = { id: item.id, kind: formatKind(item), format: structuredClone(item.format || {}) };
  redraw();
}

/** Devolve true se o pincel estava ligado. */
export function stopPaint() {
  if (!ui.paint) return false;
  ui.paint = null;
  redraw();
  return true;
}

/** Campo que a origem deixou no padrão volta ao padrão no destino; o que só existe num dos dois não muda. */
export function applyPaint(id) {
  const target = itemById(id);
  if (!target || id === ui.paint.id) return;
  const { kind, format } = ui.paint;
  const allowed = new Set(copyable(kind));
  const shared = copyable(formatKind(target)).filter((name) => allowed.has(name));
  commitLayout((d) => {
    const it = d.items.find((i) => i.id === id);
    const next = { ...it.format };
    for (const name of shared) {
      if (name in format) next[name] = structuredClone(format[name]);
      else delete next[name];
    }
    it.format = next;
  });
}
