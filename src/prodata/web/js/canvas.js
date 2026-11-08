// Canvas do workflow: render incremental de nós e fios + interações por pointer events.

import {
  addNode,
  connect,
  connectionError,
  duplicateNode,
  removeEdge,
  removeNodes,
  spliceIntoEdge,
  toggleDisabled,
  addContainer,
  disabledContainerAt,
  nodesInside,
  setDisabled,
} from './actions.js';
import { copySelection, cutSelection, hasClipboard, paste } from './clipboard.js';
import { $, debounce, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { openResultsOnClick, revealPanel } from './layout.js';
import {
  checkpoint,
  commit,
  emit,
  inspect,
  isSelected,
  node,
  on,
  select,
  selectedIds,
  selectMany,
  sourceLabel,
  store,
  toggleSelected,
} from './store.js';
import { closeMenu, showMenu, toast } from './ui.js';
import { els, nodeEls, state, toWorld, view } from './canvas_state.js';
import { NODE_MIN_H, NODE_W, nodeHeight, portPoint } from './canvas_geometry.js';
import { canSplice, edgeNear, edgeThroughRect, highlightEdge } from './canvas_hit.js';
import { openQuickAdd } from './canvas_quickadd.js';
import { renderEdges } from './canvas_edges.js';
import { containerMenu, dropContainer, placeContainerEl, renameContainer, renderContainers } from './canvas_containers.js';
import { cacheActions, selectionActions } from './canvas_actions.js';
import { renderNodes } from './canvas_nodes.js';
export { heldBy, showProgress } from './canvas_nodes.js';
export { cacheActions, selectionActions } from './canvas_actions.js';
export { addContainerAtCenter } from './canvas_containers.js';
export { isAreaFree } from './canvas_hit.js';
export { NODE_W, nodeHeight } from './canvas_geometry.js';
export { toWorld, viewportCenter } from './canvas_state.js';

const MIN_ZOOM = 0.25;
const FIT_MIN_ZOOM = 1; // ao abrir, legibilidade vale mais que ver tudo (RF-407)
const MAX_ZOOM = 2;
const DRAG_THRESHOLD = 4;

let gesture = null;
let lastTitleClick = { id: null, at: 0 };
let lastPointer = null; // posição do cursor sobre o canvas (para colar no lugar certo)

// ------------------------------------------------------------------ geometria

// ------------------------------------------------------------------ view

function applyView() {
  els.world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
  const grid = 20 * view.zoom;
  els.viewport.style.backgroundSize = `${grid}px ${grid}px`;
  els.viewport.style.backgroundPosition = `${view.x}px ${view.y}px`;
  emit('zoom', view.zoom);
}

/** Traz a caixa para o meio do canvas, sem mudar o zoom. */
export function revealNode(id) {
  const n = node(id);
  if (!n) return;
  const r = els.viewport.getBoundingClientRect();
  view.x = r.width / 2 - (n.x + NODE_W / 2) * view.zoom;
  view.y = r.height / 2 - (n.y + nodeHeight(n) / 2) * view.zoom;
  applyView();
}

export function zoomBy(factor, clientX, clientY) {
  const r = els.viewport.getBoundingClientRect();
  const cx = clientX ?? r.left + r.width / 2;
  const cy = clientY ?? r.top + r.height / 2;
  const before = toWorld(cx, cy);
  view.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom * factor));
  view.x = cx - r.left - before.x * view.zoom;
  view.y = cy - r.top - before.y * view.zoom;
  applyView();
}

/** Ajusta à tela. `minZoom` evita que fluxos grandes abram ilegíveis (RF-407). */
export function fitView({ minZoom = MIN_ZOOM } = {}) {
  const wf = store.workflow;
  if (!wf?.nodes.length) {
    Object.assign(view, { x: 40, y: 30, zoom: 1 });
    applyView();
    return;
  }
  const boxes = [
    ...wf.nodes.map((n) => ({ x1: n.x - 20, y1: n.y - 10, x2: n.x + NODE_W + 20, y2: n.y + nodeHeight(n) + 10 })),
    ...(wf.containers || []).map((c) => ({ x1: c.x, y1: c.y, x2: c.x + c.width, y2: c.y + c.height })),
  ];
  const x1 = Math.min(...boxes.map((b) => b.x1));
  const y1 = Math.min(...boxes.map((b) => b.y1));
  const x2 = Math.max(...boxes.map((b) => b.x2));
  const y2 = Math.max(...boxes.map((b) => b.y2));
  const r = els.viewport.getBoundingClientRect();
  const pad = 40;
  view.zoom = Math.min(1.1, Math.max(minZoom, Math.min((r.width - pad * 2) / (x2 - x1), (r.height - pad * 2) / (y2 - y1))));
  // Se não couber inteiro, ancora no canto superior esquerdo (início do fluxo).
  const fitsX = (x2 - x1) * view.zoom <= r.width - pad;
  const fitsY = (y2 - y1) * view.zoom <= r.height - pad;
  view.x = fitsX ? (r.width - (x2 - x1) * view.zoom) / 2 - x1 * view.zoom : pad / 2 - x1 * view.zoom;
  view.y = fitsY ? (r.height - (y2 - y1) * view.zoom) / 2 - y1 * view.zoom : pad / 2 - y1 * view.zoom;
  applyView();
}

// ------------------------------------------------------------------ render

export function render({ containers = false } = {}) {
  if (!store.workflow) return;
  if (containers) renderContainers();
  renderNodes();
  renderEdges();
  els.empty.hidden = store.workflow.nodes.length > 0;
}

function moveNodeEl(n) {
  const entry = nodeEls.get(n.id);
  if (entry) entry.el.style.transform = `translate(${n.x}px, ${n.y}px)`;
}

// ------------------------------------------------------------------ hit testing

// ------------------------------------------------------------------ seleção múltipla, cache e entradas (spec 012)

function drawMarquee(x1, y1, x2, y2) {
  const r = els.viewport.getBoundingClientRect();
  Object.assign(els.marquee.style, {
    left: `${Math.min(x1, x2) - r.left}px`, top: `${Math.min(y1, y2) - r.top}px`,
    width: `${Math.abs(x2 - x1)}px`, height: `${Math.abs(y2 - y1)}px`,
  });
  els.marquee.hidden = false;
}

/** Mostra na tabela o que chega pela entrada `port` de `nodeId` (a saída da caixa ligada nela). */
export function inspectInput(nodeId, port) {
  const edge = store.workflow.edges.find((e) => e.target === nodeId && e.targetHandle === port);
  select(nodeId);
  if (!edge) {
    toast('Esta entrada não está ligada a nada', { kind: 'info', detail: 'Ligue uma saída nela para ver os dados que chegam.' });
    return;
  }
  inspect(edge.source, edge.sourceHandle, { nodeId, port });
  openResultsOnClick();
}

// ------------------------------------------------------------------ gestos

function onPointerDown(e) {
  // A barra flutuante fica dentro do canvas: sem isto o pan capturaria o ponteiro e o clique não chegaria aos botões.
  if (e.button === 2 || e.target.closest('.canvas-toolbar, .trust-host')) return;
  closeMenu();
  const target = e.target;
  const world = toWorld(e.clientX, e.clientY);

  if (target.closest('.container-toggle, .node-delete')) {
    return; // botões dentro de caixas tratam o próprio clique; não iniciam arraste
  }
  if (e.button !== 1 && target.closest('.container-resize')) {
    const c = store.workflow.containers.find((k) => k.id === target.closest('.container-box').dataset.container);
    gesture = { type: 'container-resize', id: c.id, w: c.width, h: c.height, start: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (e.button !== 1 && target.closest('.container-title')) {
    const c = store.workflow.containers.find((k) => k.id === target.closest('.container-box').dataset.container);
    // Os nós de dentro são definidos no início do gesto e acompanham o contêiner.
    const members = nodesInside(c, NODE_W).map((n) => ({ id: n.id, x: n.x, y: n.y }));
    gesture = { type: 'container-move', id: c.id, x: c.x, y: c.y, members, start: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (e.button !== 1 && (e.shiftKey || e.ctrlKey || e.metaKey) && !target.closest('.node, .edge-pill, g.edge')) {
    // Shift/Ctrl + arrastar no vazio: retângulo de seleção (spec 012). Ctrl soma à seleção atual.
    gesture = { type: 'marquee', start: world, startX: e.clientX, startY: e.clientY, moved: false,
      additive: e.ctrlKey || e.metaKey };
  } else if (e.button === 1 || (!target.closest('.node, .edge-pill, g.edge'))) {
    gesture = { type: 'pan', startX: e.clientX, startY: e.clientY, vx: view.x, vy: view.y, moved: false };
  } else if ((e.shiftKey || e.ctrlKey || e.metaKey) && target.closest('.node') && !target.closest('.port')) {
    gesture = { type: 'toggle', id: target.closest('.node').dataset.id, startX: e.clientX, startY: e.clientY, moved: false };
  } else if (target.closest('.port.out')) {
    const { node: nodeId, port } = target.closest('.port').dataset;
    gesture = { type: 'connect', nodeId, port, from: portPoint(node(nodeId), port, true), to: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (target.closest('.node')) {
    const id = target.closest('.node').dataset.id;
    const n = node(id);
    const inPort = target.closest('.port.in')?.dataset.port || null;
    if (selectedIds().length > 1 && isSelected(id) && !inPort) {
      // Arrastar uma das selecionadas move o grupo inteiro.
      const members = selectedIds().map(node).filter(Boolean).map((m) => ({ id: m.id, x: m.x, y: m.y }));
      gesture = { type: 'group-drag', id, members, start: world, startX: e.clientX, startY: e.clientY, moved: false };
    } else {
      gesture = { type: 'drag', id, dx: world.x - n.x, dy: world.y - n.y, startX: e.clientX, startY: e.clientY,
        moved: false, inPort };
    }
  } else if (target.closest('.edge-pill')) {
    gesture = { type: 'pill', edge: target.closest('.edge-pill').dataset.edge };
  } else if (target.closest('g.edge')) {
    gesture = { type: 'edge', edge: target.closest('g.edge').dataset.edge };
  }
  try {
    els.viewport.setPointerCapture(e.pointerId);
  } catch {
    /* ponteiro já liberado (ex.: evento sintético); o gesto segue sem captura */
  }
}

// Mouses e canetas mandam 120–1000 movimentos por segundo, mais do que a tela desenha:
// guarda só o último e processa uma vez por quadro.
let pendingMove = null;
let moveFrame = 0;

function onPointerMove(e) {
  lastPointer = { x: e.clientX, y: e.clientY };
  if (!gesture) return;
  pendingMove = e;
  if (!moveFrame) moveFrame = requestAnimationFrame(flushMove);
}

function flushMove() {
  if (moveFrame) cancelAnimationFrame(moveFrame);
  moveFrame = 0;
  const e = pendingMove;
  pendingMove = null;
  if (e && gesture) handleMove(e);
}

// ------------------------------------------------------------------ andar a tela ao arrastar até a borda

const AUTO_PAN_GESTURES = new Set(['connect', 'drag', 'group-drag', 'container-move']);
const AUTO_PAN_EDGE = 56; // faixa da borda, em px, onde a tela começa a andar
const AUTO_PAN_SPEED = 16; // px por quadro, com o cursor na borda ou fora dela
const AUTO_PAN_ROOM = 200; // ao puxar uma ligação, espaço livre depois da última caixa
let autoPanFrame = 0;
let autoPanEvent = null;

const edgeSpeed = (pos, low, high) => {
  if (pos < low + AUTO_PAN_EDGE) return AUTO_PAN_SPEED * Math.min(1, (low + AUTO_PAN_EDGE - pos) / AUTO_PAN_EDGE);
  if (pos > high - AUTO_PAN_EDGE) return -AUTO_PAN_SPEED * Math.min(1, (pos - high + AUTO_PAN_EDGE) / AUTO_PAN_EDGE);
  return 0;
};

/** Quem puxa uma ligação procura uma caixa: a tela não anda além do fim delas. Quem arrasta uma caixa leva ela junto. */
function limitToContent(vx, vy, r) {
  if (gesture.type !== 'connect' || !store.workflow.nodes.length) return [vx, vy];
  const xs = store.workflow.nodes.map((n) => n.x);
  const ys = store.workflow.nodes.map((n) => n.y);
  const left = Math.min(...xs) * view.zoom + view.x + r.left;
  const top = Math.min(...ys) * view.zoom + view.y + r.top;
  const right = (Math.max(...xs) + NODE_W) * view.zoom + view.x + r.left;
  const bottom = (Math.max(...ys) + NODE_MIN_H) * view.zoom + view.y + r.top;
  return [
    (vx > 0 && left > r.left + AUTO_PAN_ROOM) || (vx < 0 && right < r.right - AUTO_PAN_ROOM) ? 0 : vx,
    (vy > 0 && top > r.top + AUTO_PAN_ROOM) || (vy < 0 && bottom < r.bottom - AUTO_PAN_ROOM) ? 0 : vy,
  ];
}

function autoPanTick() {
  autoPanFrame = 0;
  if (!gesture?.moved || !AUTO_PAN_GESTURES.has(gesture.type) || !autoPanEvent) return;
  const r = els.viewport.getBoundingClientRect();
  const [vx, vy] = limitToContent(
    edgeSpeed(autoPanEvent.clientX, r.left, r.right), edgeSpeed(autoPanEvent.clientY, r.top, r.bottom), r);
  if (vx || vy) {
    view.x += vx;
    view.y += vy;
    applyView();
    handleMove(autoPanEvent); // o cursor ficou parado, mas o mundo andou embaixo dele
  }
  autoPanFrame = requestAnimationFrame(autoPanTick);
}

function handleMove(e) {
  const far = Math.hypot(e.clientX - gesture.startX, e.clientY - gesture.startY) > DRAG_THRESHOLD;
  if (!gesture.moved && !far) return;
  autoPanEvent = e;
  if (!autoPanFrame && AUTO_PAN_GESTURES.has(gesture.type)) autoPanFrame = requestAnimationFrame(autoPanTick);
  const world = toWorld(e.clientX, e.clientY);

  if (gesture.type === 'pan') {
    gesture.moved = true;
    view.x = gesture.vx + (e.clientX - gesture.startX);
    view.y = gesture.vy + (e.clientY - gesture.startY);
    applyView();
    els.viewport.classList.add('panning');
  } else if (gesture.type === 'container-move' || gesture.type === 'container-resize') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const c = store.workflow.containers.find((k) => k.id === gesture.id);
    const dx = Math.round((world.x - gesture.start.x) / 10) * 10;
    const dy = Math.round((world.y - gesture.start.y) / 10) * 10;
    if (gesture.type === 'container-resize') {
      c.width = Math.max(200, gesture.w + dx);
      c.height = Math.max(120, gesture.h + dy);
    } else {
      c.x = gesture.x + dx;
      c.y = gesture.y + dy;
      for (const m of gesture.members) {
        const n = node(m.id);
        n.x = m.x + dx;
        n.y = m.y + dy;
        moveNodeEl(n);
      }
      renderEdges();
    }
    placeContainerEl(c);
  } else if (gesture.type === 'marquee') {
    gesture.moved = true;
    gesture.end = world;
    drawMarquee(gesture.startX, gesture.startY, e.clientX, e.clientY);
  } else if (gesture.type === 'group-drag') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const dx = Math.round((world.x - gesture.start.x) / 10) * 10;
    const dy = Math.round((world.y - gesture.start.y) / 10) * 10;
    for (const m of gesture.members) {
      const n = node(m.id);
      n.x = m.x + dx;
      n.y = m.y + dy;
      moveNodeEl(n);
    }
    renderEdges();
  } else if (gesture.type === 'drag') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const n = node(gesture.id);
    n.x = Math.round((world.x - gesture.dx) / 10) * 10;
    n.y = Math.round((world.y - gesture.dy) / 10) * 10;
    moveNodeEl(n);
    renderEdges();
    gesture.spliceEdge = canSplice(n)
      ? edgeThroughRect({ x: n.x, y: n.y, w: NODE_W, h: nodeHeight(n) }, n.id) : null;
    highlightEdge(gesture.spliceEdge);
  } else if (gesture.type === 'connect') {
    gesture.moved = true;
    gesture.to = world;
    renderEdges();
    const hover = document.elementFromPoint(e.clientX, e.clientY)?.closest('.port.in');
    for (const p of els.nodes.querySelectorAll('.port.in.can-drop, .port.in.cannot-drop')) {
      p.classList.remove('can-drop', 'cannot-drop');
    }
    if (hover) {
      const ok = !connectionError(gesture.nodeId, gesture.port, hover.dataset.node, hover.dataset.port);
      hover.classList.add(ok ? 'can-drop' : 'cannot-drop');
    }
  }
}

function onPointerUp(e) {
  if (pendingMove) flushMove(); // o último movimento antes de soltar não pode se perder
  const g = gesture;
  gesture = null;
  els.viewport.classList.remove('panning');
  if (!g) return;

  if (g.type === 'pan' && !g.moved) {
    select(null);
  } else if (g.type === 'marquee') {
    els.marquee.hidden = true;
    if (g.moved) {
      const box = { x1: Math.min(g.start.x, g.end.x), y1: Math.min(g.start.y, g.end.y),
        x2: Math.max(g.start.x, g.end.x), y2: Math.max(g.start.y, g.end.y) };
      const hits = store.workflow.nodes.filter((n) => n.x < box.x2 && n.x + NODE_W > box.x1
        && n.y < box.y2 && n.y + nodeHeight(n) > box.y1).map((n) => n.id);
      selectMany(g.additive ? [...selectedIds(), ...hits] : hits);
    } else if (!g.additive) {
      select(null);
    }
  } else if (g.type === 'toggle') {
    toggleSelected(g.id);
  } else if (g.type === 'group-drag') {
    if (g.moved) {
      commit();
      // Caixas levadas para dentro de uma etapa desligada também ficam desativadas.
      const toDisable = g.members.map((m) => node(m.id))
        .filter((n) => n && !n.disabled && disabledContainerAt(n, NODE_W, nodeHeight(n))).map((n) => n.id);
      if (toDisable.length) setDisabled(toDisable, true);
    } else {
      select(g.id);
      inspect(g.id);
    }
  } else if (g.type === 'container-move' || g.type === 'container-resize') {
    if (g.moved) {
      commit({ affects: [], structural: true });
    } else {
      // Duplo clique detectado aqui: o redesenho da seleção troca o elemento entre os cliques.
      const now = Date.now();
      const isDouble = lastTitleClick.id === g.id && now - lastTitleClick.at < 400;
      lastTitleClick = { id: g.id, at: now };
      if (isDouble) renameContainer(g.id);
      else if (store.selection.containerId !== g.id) select(null, null, g.id);
    }
  } else if (g.type === 'drag') {
    if (g.moved) {
      commit();
      highlightEdge(null);
      if (g.spliceEdge) spliceIntoEdge(g.spliceEdge, g.id, { nodeWidth: NODE_W });
      // Nó levado para dentro de uma caixa desligada também fica desativado.
      const moved = node(g.id);
      if (moved && !moved.disabled && disabledContainerAt(moved, NODE_W, nodeHeight(moved))) toggleDisabled(g.id);
    } else if (g.inPort) {
      inspectInput(g.id, g.inPort);
    } else {
      select(g.id);
      inspect(g.id, store.inspect.nodeId === g.id && !store.inspect.via ? store.inspect.anchor : null);
      openResultsOnClick();
    }
  } else if (g.type === 'connect') {
    if (!g.moved) {
      select(g.nodeId);
      inspect(g.nodeId, g.port);
      openResultsOnClick();
    } else {
      const hover = document.elementFromPoint(e.clientX, e.clientY)?.closest('.port.in');
      if (hover) connect(g.nodeId, g.port, hover.dataset.node, hover.dataset.port);
      else if (els.viewport.contains(document.elementFromPoint(e.clientX, e.clientY))
        && !document.elementFromPoint(e.clientX, e.clientY)?.closest('.node')) {
        // Soltar fora do canvas (a tela anda quando o cursor passa da borda) só cancela.
        openQuickAdd(e.clientX, e.clientY, g);
      }
      renderEdges();
    }
  } else if (g.type === 'pill') {
    const edge = store.workflow.edges.find((x) => x.id === g.edge);
    if (edge) {
      select(edge.source);
      inspect(edge.source, edge.sourceHandle);
    }
  } else if (g.type === 'edge') {
    select(null, g.edge);
  }
}

function onWheel(e) {
  if (e.target.closest('.trust-host')) return; // a lista da faixa rola sozinha, sem mexer no zoom
  e.preventDefault();
  if (e.ctrlKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
    zoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY);
  } else {
    view.x -= e.deltaX;
    applyView();
  }
}

/** Seleciona a caixa e põe o foco no nome dela no Inspector. */
function renameNodeInInspector(id) {
  select(id);
  requestAnimationFrame(() => {
    const input = document.querySelector('.inspector-title-input');
    input?.focus();
    input?.select();
  });
}

function onContextMenu(e) {
  e.preventDefault();
  if (e.target.closest('.canvas-toolbar, .trust-host')) return;
  const world = toWorld(e.clientX, e.clientY);
  const pasteItem = (label = 'Colar aqui') => ({
    label, icon: 'clipboard', shortcut: 'Ctrl+V', disabled: !hasClipboard(), onSelect: () => paste(world),
  });
  const containerEl = e.target.closest('.container-title, .container-resize');
  if (containerEl) {
    containerMenu(containerEl.closest('.container-box').dataset.container, e.clientX, e.clientY, pasteItem());
    return;
  }
  const nodeEl = e.target.closest('.node');
  const edgeEl = e.target.closest('g.edge');
  if (nodeEl && selectedIds().length > 1 && isSelected(nodeEl.dataset.id)) {
    showMenu(e.clientX, e.clientY, [
      ...selectionActions(selectedIds()),
      'separator',
      { label: 'Copiar', icon: 'copy', shortcut: 'Ctrl+C', onSelect: () => copySelection({ nodeWidth: NODE_W }) },
      { label: 'Recortar', icon: 'scissors', shortcut: 'Ctrl+X', onSelect: () => cutSelection({ nodeWidth: NODE_W }) },
    ]);
  } else if (nodeEl) {
    const id = nodeEl.dataset.id;
    const n = node(id);
    select(id);
    showMenu(e.clientX, e.clientY, [
      { label: 'Configurar', icon: 'settings', onSelect: () => { revealPanel('explorer'); select(id); } },
      { label: 'Executar até aqui', icon: 'target', shortcut: 'Ctrl+Shift+Enter', onSelect: () => state.handlers.runTo?.(id) },
      { label: 'Ver resultados', icon: 'table', onSelect: () => { revealPanel('results'); inspect(id); } },
      { label: 'Ver SQL', icon: 'terminal', onSelect: () => state.handlers.viewSql?.(id) },
      ...cacheActions(n),
      'separator',
      { label: 'Copiar', icon: 'copy', shortcut: 'Ctrl+C', onSelect: () => copySelection({ nodeWidth: NODE_W }) },
      { label: 'Recortar', icon: 'scissors', shortcut: 'Ctrl+X', onSelect: () => cutSelection({ nodeWidth: NODE_W }) },
      pasteItem('Colar'),
      { label: 'Duplicar', icon: 'copy', shortcut: 'Ctrl+D', onSelect: () => duplicateNode(id) },
      'separator',
      { label: 'Renomear', icon: 'edit', onSelect: () => renameNodeInInspector(id) },
      { label: n.disabled ? 'Habilitar' : 'Desabilitar', icon: 'power', onSelect: () => toggleDisabled(id) },
      'separator',
      { label: 'Excluir', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeNodes([id]) },
    ]);
  } else if (edgeEl) {
    const edge = store.workflow.edges.find((x) => x.id === edgeEl.dataset.edge);
    select(null, edge.id);
    showMenu(e.clientX, e.clientY, [
      { label: 'Ver dados deste fio', icon: 'table', onSelect: () => inspect(edge.source, edge.sourceHandle) },
      { label: 'Inserir ferramenta no meio…', icon: 'plus', onSelect: () => openQuickAdd(e.clientX, e.clientY, { to: world, splice: edge.id }) },
      { label: 'Excluir conexão', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeEdge(edge.id) },
    ]);
  } else {
    showMenu(e.clientX, e.clientY, [
      pasteItem(),
      { label: 'Selecionar todas as caixas', icon: 'check', shortcut: 'Ctrl+A', onSelect: () => selectMany(store.workflow.nodes.map((n) => n.id)) },
      'separator',
      { label: 'Adicionar ferramenta aqui…', icon: 'plus', onSelect: () => openQuickAdd(e.clientX, e.clientY, { to: world }) },
      {
        label: 'Nova etapa aqui', icon: 'group', shortcut: 'G',
        onSelect: () => { const c = addContainer(world.x, world.y); requestAnimationFrame(() => renameContainer(c.id)); },
      },
      'separator',
      { label: 'Ajustar à tela', icon: 'fit', shortcut: 'F', onSelect: fitView },
    ]);
  }
}

// ------------------------------------------------------------------ arrastar da paleta / painel de dados

export const DND_TOOL = 'application/x-prodata-tool';
export const DND_DATASET = 'application/x-prodata-dataset';
export const DND_CONTAINER = 'application/x-prodata-container';

function onDragOver(e) {
  const types = e.dataTransfer.types;
  if (!types.includes(DND_TOOL) && !types.includes(DND_DATASET) && !types.includes(DND_CONTAINER)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
  highlightEdge(types.includes(DND_TOOL) ? dropEdge(toWorld(e.clientX, e.clientY)) : null);
}

/** Fio sob a caixa que seria criada no ponto do cursor (ou bem perto da linha). */
function dropEdge(world) {
  const rect = { x: world.x - NODE_W / 2, y: world.y - NODE_MIN_H / 2, w: NODE_W, h: NODE_MIN_H };
  return edgeThroughRect(rect) || edgeNear(world);
}

function onDrop(e) {
  const tool = e.dataTransfer.getData(DND_TOOL);
  const dataset = e.dataTransfer.getData(DND_DATASET);
  if (e.dataTransfer.types.includes(DND_CONTAINER)) {
    e.preventDefault();
    dropContainer(toWorld(e.clientX, e.clientY));
    return;
  }
  if (!tool && !dataset) return;
  e.preventDefault();
  highlightEdge(null);
  const world = toWorld(e.clientX, e.clientY);
  const x = world.x - NODE_W / 2;
  const y = world.y - NODE_MIN_H / 2;
  if (dataset) {
    addNode('io.input_data', x, y, { dataset, __label: sourceLabel(dataset) });
    return;
  }
  const edgeId = dropEdge(world);
  const created = addNode(tool, x, y);
  if (created && edgeId && canSplice(created)) spliceIntoEdge(edgeId, created.id, { nodeWidth: NODE_W });
}

// ------------------------------------------------------------------ adicionar rápido (puxar fio para o vazio)

// ------------------------------------------------------------------ init

export function initCanvas(root, opts = {}) {
  state.render = render;
  state.connecting = () => (gesture?.type === 'connect' && gesture.moved ? gesture : null);
  state.handlers = opts;
  els.viewport = root;
  els.world = $('.canvas-world', root);
  els.containers = $('.canvas-containers', root);
  els.svg = $('.canvas-edges', root);
  els.pills = $('.canvas-pills', root);
  els.nodes = $('.canvas-nodes', root);
  els.empty = $('.canvas-empty', root);
  els.marquee = h('div', { class: 'canvas-marquee', hidden: true });
  root.append(els.marquee);

  root.addEventListener('pointerdown', onPointerDown);
  root.addEventListener('pointermove', onPointerMove);
  root.addEventListener('pointerup', onPointerUp);
  root.addEventListener('pointercancel', () => { gesture = null; pendingMove = null; els.marquee.hidden = true; });
  // Arrastar a partir do canvas, mesmo saindo dele, não pode selecionar o texto da tela.
  root.addEventListener('selectstart', (e) => {
    if (!e.target.closest?.('input, textarea, [contenteditable]')) e.preventDefault();
  });
  root.addEventListener('pointerleave', () => { lastPointer = null; });
  root.addEventListener('wheel', onWheel, { passive: false });
  root.addEventListener('contextmenu', onContextMenu);
  root.addEventListener('dragover', onDragOver);
  root.addEventListener('dragleave', () => highlightEdge(null));
  root.addEventListener('drop', onDrop);
  root.addEventListener('dblclick', (e) => {
    if (!e.target.closest('.node, .container-box, .canvas-toolbar, .trust-host')) openQuickAdd(e.clientX, e.clientY, { to: toWorld(e.clientX, e.clientY) });
  });

  on('workflow:loaded', (payload) => {
    nodeEls.forEach(({ el }) => el.remove());
    nodeEls.clear();
    render({ containers: true });
    // Trocar de aba volta para a posição em que o fluxo estava; abrir um fluxo ajusta à tela.
    if (payload?.view) {
      Object.assign(view, payload.view);
      applyView();
    } else {
      requestAnimationFrame(() => fitView({ minZoom: FIT_MIN_ZOOM }));
    }
  });
  // Caixas são poucas: redesenhar sempre mantém título/descrição/cor em dia durante a edição.
  on('workflow:changed', () => render({ containers: true }));
  on('selection', () => render({ containers: true }));
  on('inspect', () => render());
  on('execution', () => render());

  const saved = storage('prodata.view', null);
  if (saved) Object.assign(view, saved);
  applyView();
  // Salva a posição só quando o movimento para (antes: a cada evento de arrastar a tela).
  on('zoom', debounce(() => persist('prodata.view', view), 400));
}

export const currentZoom = () => view.zoom;
export const getView = () => ({ ...view });

/** Ponto do canvas sob o cursor, se ele estiver sobre o canvas; senão null. */
export function pointerWorld() {
  if (!lastPointer || !els.viewport) return null;
  const r = els.viewport.getBoundingClientRect();
  const inside = lastPointer.x >= r.left && lastPointer.x <= r.right && lastPointer.y >= r.top && lastPointer.y <= r.bottom;
  return inside ? toWorld(lastPointer.x, lastPointer.y) : null;
}
