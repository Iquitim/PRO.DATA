// Copiar, recortar e colar caixas e etapas (spec 009, RF-902/RF-903).
// A área de transferência fica no localStorage: sobrevive à troca de fluxo e ao reinício,
// mas nunca entra no arquivo do fluxo.

import { nodesInside, removeContainerWithNodes, removeNodes } from './actions.js';
import { persist, storage, uid } from './dom.js';
import { mutate, node, select, selectedIds, selectMany, store } from './store.js';
import { toast } from './ui.js';

const KEY = 'prodata.clipboard';
const KIND = 'prodata/clip';
const clone = (v) => JSON.parse(JSON.stringify(v));
let pasteCount = 0;

export function clipboard() {
  const clip = storage(KEY, null);
  return clip?.kind === KIND && clip.nodes?.length ? clip : null;
}

export const hasClipboard = () => Boolean(clipboard());

/** O que está selecionado vira um recorte: um nó, ou uma etapa com os nós de dentro e as ligações entre eles. */
function selectionClip(nodeWidth) {
  const wf = store.workflow;
  const { nodeId, containerId } = store.selection;
  let nodes = [];
  let containers = [];
  if (selectedIds().length > 1) {
    nodes = selectedIds().map(node).filter(Boolean);
  } else if (nodeId) {
    nodes = [node(nodeId)];
  } else if (containerId) {
    const c = wf.containers.find((x) => x.id === containerId);
    nodes = nodesInside(c, nodeWidth);
    containers = [c];
  }
  if (!nodes.length && !containers.length) return null;
  const ids = new Set(nodes.map((n) => n.id));
  const edges = wf.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const xs = [...nodes.map((n) => n.x), ...containers.map((c) => c.x)];
  const ys = [...nodes.map((n) => n.y), ...containers.map((c) => c.y)];
  return { kind: KIND, nodes: clone(nodes), edges: clone(edges), containers: clone(containers), origin: { x: Math.min(...xs), y: Math.min(...ys) } };
}

export function copySelection({ nodeWidth = 188 } = {}) {
  const clip = selectionClip(nodeWidth);
  if (!clip) return false;
  persist(KEY, clip);
  pasteCount = 0;
  const what = clip.containers.length ? `Etapa com ${clip.nodes.length} caixa(s)` : `${clip.nodes.length} caixa(s)`;
  toast(`${what} copiada`, { detail: 'Ctrl+V para colar, inclusive em outro fluxo.' });
  return true;
}

export function cutSelection({ nodeWidth = 188 } = {}) {
  const clip = selectionClip(nodeWidth);
  if (!clip) return false;
  persist(KEY, clip);
  pasteCount = 0;
  if (clip.containers.length) removeContainerWithNodes(clip.containers[0].id, nodeWidth);
  else removeNodes(clip.nodes.map((n) => n.id));
  return true;
}

/** Cola com IDs novos. `at` (coordenadas do canvas) posiciona o canto superior esquerdo; sem ele, desloca do original. */
export function paste(at = null) {
  const clip = clipboard();
  if (!clip) return false;
  pasteCount += 1;
  const dx = at ? at.x - clip.origin.x : 40 * pasteCount;
  const dy = at ? at.y - clip.origin.y : 60 * pasteCount;
  const snap = (v) => Math.round(v / 10) * 10;
  const ids = new Map(clip.nodes.map((n) => [n.id, uid('n')]));
  const nodes = clip.nodes
    .filter((n) => store.tools[n.type])
    .map((n) => ({ ...clone(n), id: ids.get(n.id), x: snap(n.x + dx), y: snap(n.y + dy) }));
  const edges = clip.edges.map((e) => ({ ...clone(e), id: uid('e'), source: ids.get(e.source), target: ids.get(e.target) }));
  const containers = clip.containers.map((c) => ({ ...clone(c), id: uid('c'), x: snap(c.x + dx), y: snap(c.y + dy) }));
  mutate((wf) => {
    wf.nodes.push(...nodes);
    wf.edges.push(...edges);
    wf.containers = [...(wf.containers || []), ...containers];
  }, { affects: nodes.map((n) => n.id), structural: true });
  if (containers.length) select(null, null, containers[0].id);
  else selectMany(nodes.map((n) => n.id));
  return true;
}
