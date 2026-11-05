// Desenho das ligações: curvas, cores, setas, animação do fluxo e rótulos com a contagem de linhas.

import { curve, curveMid, edgeArrow, portPoint } from './canvas_geometry.js';
import { els, state } from './canvas_state.js';
import { fmt, h } from './dom.js';
import { on, store, toolOf } from './store.js';

/** Texto que vai dentro de um atributo do desenho: o id vem do arquivo do fluxo, que pode ser de outra pessoa. */
const attr = (text) => String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Cor do fio: a família da caixa, um pouco suavizada para não competir com as caixas (spec 025).
const edgeColor = (n) => `color-mix(in srgb, var(--cat-${toolOf(n)?.category || 'prep'}) 72%, var(--border-strong))`;

const MAX_FLOW_EDGES = 300;

export const MAX_ANIMATED_NEW = 3;

let flowTarget = null;

let knownEdges = { workflow: null, ids: new Set() };

/** O dado correndo pelos fios que chegam à caixa em execução. Fora da execução, nada se move. */
export function applyFlow() {
  for (const old of els.svg.querySelectorAll('.edge-flow')) old.remove();
  const wf = store.workflow;
  if (!flowTarget || !wf || wf.edges.length > MAX_FLOW_EDGES) return;
  for (const e of wf.edges) {
    if (e.target !== flowTarget) continue;
    const group = els.svg.querySelector(`g[data-edge="${CSS.escape(e.id)}"]`);
    const line = group?.querySelector('.edge-line');
    if (!line) continue;
    const flow = line.cloneNode();
    flow.setAttribute('class', 'edge-flow');
    flow.removeAttribute('stroke');
    flow.removeAttribute('pathLength');
    group.append(flow);
  }
}

/** Passar o mouse num fio acende as portas das duas pontas. */
function litPorts(edgeId, on) {
  const e = store.workflow?.edges.find((x) => x.id === edgeId);
  if (!e) return;
  for (const [node_, port, side] of [[e.source, e.sourceHandle, 'out'], [e.target, e.targetHandle, 'in']]) {
    els.nodes.querySelector(`.port.${side}[data-node="${CSS.escape(node_)}"][data-port="${CSS.escape(port)}"]`)?.classList.toggle('port-lit', on);
  }
}

function watchEdgeHover() {
  if (els.svg.dataset.watching) return;
  els.svg.dataset.watching = '1';
  const handler = (on) => (ev) => {
    const id = ev.target.closest?.('g.edge')?.dataset.edge;
    if (id) litPorts(id, on);
  };
  els.svg.addEventListener('mouseover', handler(true));
  els.svg.addEventListener('mouseout', handler(false));
}

export function renderEdges() {
  const wf = store.workflow;
  const byId = new Map(wf.nodes.map((n) => [n.id, n]));
  const paths = [];
  const defs = [];
  const pills = [];
  watchEdgeHover();
  // Um fio acabou de ser criado: ele se desenha. Abrir um fluxo não anima nada.
  const unseen = knownEdges.workflow === wf.id ? wf.edges.filter((e) => !knownEdges.ids.has(e.id)) : [];
  const drawIn = new Set(unseen.length <= MAX_ANIMATED_NEW ? unseen.map((e) => e.id) : []);
  knownEdges = { workflow: wf.id, ids: new Set(wf.edges.map((e) => e.id)) };
  let index = -1;
  for (const e of wf.edges) {
    index += 1;
    const s = byId.get(e.source);
    const t = byId.get(e.target);
    if (!s || !t) continue;
    const a = portPoint(s, e.sourceHandle, true);
    const b = portPoint(t, e.targetHandle, false);
    const d = curve(a, b);
    const tele = store.execution?.edge_telemetry?.[e.id];
    const fresh = tele && !store.pending.has(e.source);
    const model = toolOf(s)?.outputs.find((p) => p.id === e.sourceHandle)?.kind === 'model';
    // Ligação entre caixas puladas pelo cache (ou chegando no ponto de cache): tracejada em dourado.
    const skipped = state.held.has(e.source) && (state.held.has(e.target) || state.held.get(e.source).id === e.target);
    const fromColor = edgeColor(s);
    const toColor = edgeColor(t);
    defs.push(`<linearGradient id="edge-grad-${index}" gradientUnits="userSpaceOnUse" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"><stop offset="0" style="stop-color:${fromColor}"/><stop offset="1" style="stop-color:${toColor}"/></linearGradient>`);
    const isNew = drawIn.has(e.id) && !model;
    paths.push(`<g class="edge${store.selection.edgeId === e.id ? ' selected' : ''}${model ? ' model' : ''}${fresh ? ' live' : ''}${skipped ? ' state.held' : ''}${isNew ? ' edge-new' : ''}" data-edge="${attr(e.id)}">
      <path class="edge-hit" d="${d}"/><path class="edge-line" d="${d}" stroke="url(#edge-grad-${index})"${isNew ? ' pathLength="1"' : ''}/><path class="edge-arrow" style="stroke:${toColor}" d="${edgeArrow(a, b)}"/></g>`);
    const touchesSelection = [e.source, e.target].includes(store.selection.nodeId);
    if (fresh && tele.kind === 'data' && touchesSelection) {
      const m = curveMid(a, b);
      pills.push(h('button', {
        type: 'button',
        class: 'edge-pill',
        style: { left: `${m.x}px`, top: `${m.y}px` },
        dataset: { edge: e.id },
        title: `${fmt.int(tele.row_count)} linha(s) · clique para ver os dados`,
      }, fmt.compact(tele.row_count)));
    }
  }
  const draft = state.connecting();
  if (draft) paths.push(`<path class="edge-draft" d="${curve(draft.from, draft.to)}"/>`);
  els.svg.innerHTML = `<defs>${defs.join('')}</defs>${paths.join('')}`;
  els.pills.replaceChildren(...pills);
  applyFlow();
}

/** Muda a caixa em execução: o fluxo animado passa a correr nos fios que chegam nela. */
export function setFlowTarget(id) {
  if (id === flowTarget) return;
  flowTarget = id;
  applyFlow();
}
